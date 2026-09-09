"""Persist requests before sending and responses before interpreting them."""

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://app.resemble.ai/api/v2"
# Paid or plan-gated add-ons, dropped one at a time when the server confirms it rejected the submission.
OPTIONAL_ADDONS = ("signal", "use_reverse_search", "use_ood_detector", "detect_watermark")
REJECTION_STATUSES = {402, 403, 422}


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class DetectionError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def detection_fields(kind: str, duration: float | None = None) -> dict[str, str]:
    """Every documented Detect option that applies to this media type."""
    fields = {
        "visualize": "true",
        "intelligence": "true",
        "infer_from_intelligence": "false",
        "detect_watermark": "true",  # Resemble Perth v1/v2 and Google SynthID
        "signal": "true",  # fraud/abuse classification, plan-gated
    }
    if kind == "image":
        fields["use_reverse_search"] = "true"
    if kind == "video":
        fields["modality"] = "all"
        if duration:
            # Live API rejects fractional values although the published schema says double.
            fields["max_video_secs"] = str(math.ceil(duration))
    if kind in {"video", "audio"}:
        fields["audio_source_tracing"] = "true"
    if kind == "audio":
        fields["use_ood_detector"] = "true"
    return fields


def auxiliary_done(item: dict) -> bool:
    """Intelligence and watermark analysis may finish after the detector itself."""
    for key in ("intelligence", "watermark"):
        value = item.get(key)
        if isinstance(value, dict) and value.get("status") not in {"completed", "failed", None}:
            return False
    return True


class ResembleClient:
    def __init__(self, key: str, transport: httpx.BaseTransport | None = None):
        self.key = key
        self.http = httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=120, transport=transport)

    def close(self) -> None:
        self.http.close()

    def request(self, directory: Path, method: str, route: str, **kwargs) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        number = len(list(directory.glob("*.request.json"))) + 1
        prefix = directory / f"{number:04d}"
        save_json(
            prefix.with_suffix(".request.json"),
            {
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "method": method,
                "url": BASE_URL + route,
                "fields": kwargs.get("data", kwargs.get("json", {})),
                "file": kwargs["files"]["file"][0] if "files" in kwargs else None,
                "authorization": "[REDACTED]",
            },
        )
        try:
            response = self.http.request(method, BASE_URL + route, **kwargs)
        except httpx.HTTPError as exc:
            save_json(prefix.with_suffix(".error.json"), {"error": type(exc).__name__})
            raise DetectionError(f"Transport failure: {type(exc).__name__}; inspect saved request") from None
        # Preserve the response body as received, except any reflected API credential.
        raw = response.content.replace(self.key.encode(), b"[REDACTED]")
        prefix.with_suffix(".response.txt").write_bytes(raw)
        save_json(prefix.with_suffix(".http.json"), {"status_code": response.status_code})
        if response.is_error:
            raise DetectionError(
                f"Resemble returned HTTP {response.status_code}; inspect saved response", response.status_code
            )
        try:
            payload = response.json()
        except ValueError:
            raise DetectionError("Resemble returned non-JSON content") from None
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise DetectionError("Resemble returned an unsuccessful or malformed payload")
        prefix.with_suffix(".response.json").write_bytes(raw)
        return payload

    def _last_submission_is_unresolved(self, directory: Path) -> bool:
        """True when a POST was sent but neither a success body nor a confirmed rejection was recorded."""
        for request_file in sorted((directory / "http").glob("*.request.json"), reverse=True):
            if load_json(request_file).get("method") != "POST":
                continue
            prefix = str(request_file).removesuffix(".request.json")
            if Path(prefix + ".response.json").exists():
                return False
            status_file = Path(prefix + ".http.json")
            if status_file.exists() and load_json(status_file).get("status_code") in REJECTION_STATUSES:
                body = Path(prefix + ".response.txt")
                try:
                    json.loads(body.read_text())
                    return False
                except (OSError, ValueError):
                    return True
            return True
        return False

    def _submit(self, path: Path, directory: Path, fields: dict[str, str]) -> tuple[str, dict[str, str]]:
        fields = dict(fields)
        attempts = []
        while True:
            with path.open("rb") as stream:
                try:
                    payload = self.request(
                        directory / "http", "POST", "/detect", data=fields, files={"file": (path.name, stream)}
                    )
                except DetectionError as exc:
                    present = [addon for addon in OPTIONAL_ADDONS if addon in fields]
                    if exc.status_code not in REJECTION_STATUSES or not present:
                        raise
                    dropped = present[0]
                    attempts.append({"status_code": exc.status_code, "dropped_option": dropped})
                    del fields[dropped]
                    continue
            item = payload.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("uuid"), str) or not item["uuid"]:
                raise DetectionError("Submission returned no detection UUID")
            save_json(
                directory / "job.json",
                {"uuid": item["uuid"], "fields": fields, "rejected_attempts": attempts},
            )
            return item["uuid"], fields

    def detect(
        self,
        path: Path,
        directory: Path,
        kind: str,
        timeout: float = 900,
        interval: float = 5,
        duration: float | None = None,
    ) -> dict:
        state_path = directory / "job.json"
        wanted = detection_fields(kind, duration)
        if state_path.exists():
            job = load_json(state_path)
            uuid = job["uuid"]
            saved = job.get("fields")
            tried = set(saved or {}) | {a["dropped_option"] for a in job.get("rejected_attempts", [])}
            if saved is not None and set(wanted) - tried:
                # New options became available; keep the earlier job and its raw history, then submit again.
                number = len(list(directory.glob("job.superseded-*.json"))) + 1
                state_path.replace(directory / f"job.superseded-{number:02d}.json")
                latest = directory / "latest.json"
                if latest.exists():
                    latest.replace(directory / f"latest.superseded-{number:02d}.json")
                uuid = None
        else:
            uuid = None
        if uuid is None:
            if path.stat().st_size > 150_000_000:
                raise DetectionError("File exceeds the implemented 150 MB direct-upload limit")
            # Never retry a submission automatically: the server may already have accepted it.
            if self._last_submission_is_unresolved(directory):
                raise DetectionError("Previous submission has no saved job ID; inspect it before starting a new run")
            uuid, _ = self._submit(path, directory, wanted)
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.request(directory / "http", "GET", f"/detect/{quote(uuid, safe='')}")
            save_json(directory / "latest.json", last)
            item = last.get("item")
            if not isinstance(item, dict):
                raise DetectionError("Detection result has no item object")
            status = item.get("status")
            if status == "failed":
                raise DetectionError("Resemble detection failed; inspect latest.json")
            if status == "completed" and auxiliary_done(item):
                return last
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        if last and last.get("item", {}).get("status") == "completed":
            return last  # Detection is usable; analysis records incomplete auxiliary results separately.
        raise DetectionError("Polling timed out; rerun with the same output directory to resume the saved job")

    def ask(
        self, uuid: str, directory: Path, questions: list[str], timeout: float = 300, interval: float = 2
    ) -> list[dict]:
        """Detect Intelligence questions about a completed detection; answers are provider text, not facts."""
        state_path = directory / "questions.en.json"
        state = load_json(state_path) if state_path.exists() else []
        by_question = {entry["question"]: entry for entry in state if isinstance(entry, dict)}
        detect = quote(uuid, safe="")
        for question in questions:
            entry = by_question.get(question)
            if entry and entry.get("status") == "completed":
                continue
            if not entry or not entry.get("uuid"):
                payload = self.request(
                    directory / "http", "POST", f"/detects/{detect}/intelligence", json={"query": question}
                )
                item = payload.get("item") or {}
                entry = {"question": question, "uuid": item.get("uuid"), "status": item.get("status"), "answer": None}
                by_question[question] = entry
            if not entry.get("uuid"):
                entry["status"] = "failed"
                entry["error"] = "No question UUID returned"
                continue
            deadline = time.monotonic() + timeout
            delay = 1.0
            while time.monotonic() < deadline:
                payload = self.request(
                    directory / "http", "GET", f"/detects/{detect}/intelligence/{quote(str(entry['uuid']), safe='')}"
                )
                item = payload.get("item") or {}
                entry["status"] = item.get("status")
                entry["answer"] = item.get("answer")
                entry["error"] = item.get("error_message")
                if entry["status"] in {"completed", "failed"}:
                    break
                time.sleep(min(delay, max(0, deadline - time.monotonic())))
                delay = min(delay * 2, 10)
        result = [by_question[q] for q in questions] + [e for q, e in by_question.items() if q not in questions]
        save_json(state_path, result)
        return result
