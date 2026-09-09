"""Folder inventory, immutable source copies, local metadata and derived evidence."""

import base64
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PIL import ExifTags, Image

from forgery_audit.analysis import analyze
from forgery_audit.client import DetectionError, ResembleClient, load_json, save_json
from forgery_audit.markdown import write_markdown
from forgery_audit.report import write_report

EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".3gpp"},
    "audio": {".wav", ".mp3", ".m4a", ".ogg", ".aac", ".flac", ".amr"},
}
# Asked through Detect Intelligence so the provider answers with the full report context. The answers are
# provider hypotheses; the Latvian report attributes them and never presents them as verified facts.
QUESTIONS = [
    "Was this content created using deepfake or generative AI technology? State the evidence for and against.",
    "Which parts of the content (regions, persons, time ranges, visual versus audio) show signs of manipulation "
    "or synthesis, and which parts do not?",
    "Is the content more likely manipulated from real recordings or generated entirely? Explain the basis.",
    "Which deepfake or generative technology, model family or vendor was likely used, and what supports that?",
    "What task, instruction or prompt was the technology most likely given to produce this content?",
    "What source materials (original photographs, videos, voice recordings, identities) were likely used?",
    "When, where and with what device or software was this file most likely created? Use any platform "
    "watermark, on-screen caption, container metadata, EXIF or encoder evidence, and say what cannot be "
    "determined.",
    "Were any AI watermarks (Resemble Perth, Google SynthID), C2PA content credentials or platform "
    "'AI-generated' labels found, and what do they imply?",
]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def media_type(path: Path) -> str:
    return next((kind for kind, extensions in EXTENSIONS.items() if path.suffix.lower() in extensions), "unsupported")


def metadata_for(path: Path, relative: str) -> dict:
    result = {
        "relative_path": relative,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "media_type": media_type(path),
        "inventoried_at_utc": datetime.now(UTC).isoformat(),
    }
    if result["media_type"] == "image":
        try:
            with Image.open(path) as image:
                result["image"] = {
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "frames": getattr(image, "n_frames", 1),
                    "exif_unverified": {ExifTags.TAGS.get(k, str(k)): str(v) for k, v in image.getexif().items()},
                }
        except (OSError, ValueError) as exc:
            result["metadata_error"] = type(exc).__name__
    elif result["media_type"] in {"video", "audio"}:
        if shutil.which("ffprobe"):
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path.resolve())],
                    capture_output=True,
                    timeout=60,
                )
                result["ffprobe"] = json.loads(probe.stdout) if probe.returncode == 0 else {}
                result["ffprobe_stderr"] = probe.stderr.decode(errors="replace")
                result["ffprobe_returncode"] = probe.returncode
            except (subprocess.TimeoutExpired, ValueError):
                result["metadata_error"] = "ffprobe failed or timed out"
        else:
            result["metadata_error"] = "ffprobe is not installed; duration and stream coverage cannot be verified"
    return result


def extract_visualizations(payload: dict, directory: Path) -> None:
    """Decode embedded evidence without altering the raw payload or fetching arbitrary URLs."""
    entries = []

    def visit(node, pointer=""):
        if isinstance(node, dict):
            for key, value in node.items():
                location = pointer + "/" + key
                if key in {"image", "heatmap", "mask"} and isinstance(value, str):
                    entry = {"pointer": location}
                    if value.startswith("https://"):
                        entry.update({"status": "remote_reference_only", "url": value})
                    else:
                        try:
                            data = base64.b64decode(value.split(",", 1)[-1], validate=True)
                            suffix = (
                                ".png"
                                if data.startswith(b"\x89PNG")
                                else ".jpg"
                                if data.startswith(b"\xff\xd8")
                                else ".bin"
                            )
                            if value.startswith("data:video/mp4;"):
                                suffix = ".mp4"
                            target = directory / f"{len(entries):04d}{suffix}"
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(data)
                            entry.update({"status": "decoded", "file": target.name, "sha256": sha256(target)})
                        except ValueError:
                            entry["status"] = "unrecognized_encoding"
                    entries.append(entry)
                elif isinstance(value, (dict, list)):
                    visit(value, location)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, pointer + f"/{index}")

    visit(payload)
    save_json(directory / "index.json", entries)


def process(
    source: Path, output: Path, client: ResembleClient | None, timeout: float = 900, offline: bool = False
) -> list[dict]:
    source, output = source.resolve(), output.resolve()
    if not source.is_dir():
        raise ValueError("Input must be an existing directory")
    if output == source or source.is_relative_to(output):
        raise ValueError("Output must not equal or contain the input directory")
    paths = sorted(
        p
        for p in source.rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and not p.is_relative_to(output)
        and not any(part.startswith(".") for part in p.relative_to(source).parts)
    )
    if not paths:
        raise ValueError("Input directory contains no artifacts")
    output.mkdir(parents=True, exist_ok=True)
    summary = []
    for path in paths:
        relative = path.relative_to(source).as_posix()
        digest = sha256(path)
        path_id = hashlib.sha256(relative.encode()).hexdigest()[:10]
        directory = output / f"{path_id}-{digest[:16]}"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            original = directory / ("source" + path.suffix.lower())
            if not original.exists():
                shutil.copyfile(path, original)
            if sha256(original) != digest:
                raise ValueError("Preserved source checksum differs from input")
            meta_path = directory / "metadata.json"
            if meta_path.exists():
                metadata = load_json(meta_path)
            else:
                metadata = metadata_for(original, relative)
                save_json(meta_path, metadata)
            kind = metadata["media_type"]
            payload = {}
            error = None
            questions = []
            try:
                latest = directory / "latest.json"
                payload = load_json(latest) if latest.exists() else {}
                if kind != "unsupported" and not offline:
                    if client is None:
                        raise DetectionError("RESEMBLE_AI_API_KEY is missing")
                    duration = metadata.get("ffprobe", {}).get("format", {}).get("duration")
                    # The client reuses a finished job unless newly available options justify a new one.
                    payload = client.detect(
                        original, directory, kind, timeout=timeout, duration=float(duration) if duration else None
                    )
                elif not payload and kind != "unsupported":
                    error = "No saved detection payload; offline mode does not call Resemble"
            except DetectionError as exc:
                error = str(exc)
                if (directory / "latest.json").exists():
                    payload = load_json(directory / "latest.json")
            question_file = directory / "questions.en.json"
            if question_file.exists():
                questions = load_json(question_file)
            uuid = payload.get("item", {}).get("uuid")
            if client and not offline and uuid and payload.get("item", {}).get("status") == "completed":
                try:
                    questions = client.ask(uuid, directory, QUESTIONS)
                except DetectionError as exc:
                    error = error or f"Detect Intelligence questions failed: {exc}"
                    if question_file.exists():
                        questions = load_json(question_file)
            analysis = analyze(payload, kind, metadata, questions)
            if error:
                analysis["error"] = error
            analysis["coverage"] = {
                "source_duration_seconds": metadata.get("ffprobe", {}).get("format", {}).get("duration"),
                "visual_duration_seconds": (payload.get("item", {}).get("video_metrics") or {}).get("duration"),
                "audio_duration_seconds": (payload.get("item", {}).get("metrics") or {}).get("duration"),
            }
            save_json(directory / "analysis.en.json", analysis)
            extract_visualizations(payload, directory / "visualizations")
            write_report(directory, metadata, analysis)
            entry = {
                "file": relative,
                "directory": directory.name,
                "assessment": analysis["assessment"],
                "error": error,
                "supported": kind != "unsupported",
            }
        except (OSError, ValueError, RuntimeError) as exc:
            entry = {"file": relative, "directory": directory.name, "error": str(exc), "assessment": "inconclusive"}
            save_json(directory / "error.json", entry)
        summary.append(entry)
        save_json(output / "manifest.json", summary)
    write_markdown(output, summary)
    return summary
