"""Conservative interpretation of documented labels; scores never become invented thresholds."""

import math

LABELS = {
    "fake": "synthetic_indicators",
    "likely fake": "synthetic_indicators",
    "real": "no_synthetic_indicators",
    "likely real": "no_synthetic_indicators",
}
COMPONENTS = {"image": ["image_metrics"], "audio": ["metrics"], "video": ["video_metrics", "metrics"]}
KNOWN_ITEM_KEYS = {
    "uuid",
    "name",
    "filename",
    "status",
    "media_type",
    "modality",
    "face_only",
    "duration",
    "url",
    "audio_url",
    "created_at",
    "updated_at",
    "visualize",
    "zero_retention_mode",
    "file_deleted_at",
    "extra_params",
    "metrics",
    "image_metrics",
    "video_metrics",
    "intelligence",
    "audio_source_tracing",
    "audio_source_tracing_enabled",
    "c2pa_manifest",
    "watermark",
    "signal",
    "signal_enabled",
    "use_ood_detector",
}
# Container tags that hint at a distribution platform or an encoder rather than a camera.
PROVENANCE_TAGS = {"aigc_info", "comment", "encoder", "vid_md5", "creation_time", "make", "model", "software"}


def normalize(label: object) -> str:
    return LABELS.get(str(label).strip().lower(), "inconclusive")


def findings(node: object, pointer: str):
    if isinstance(node, dict):
        if "label" in node or "conclusion" in node:
            label = node.get("label", node.get("conclusion"))
            result = {"pointer": pointer, "provider_label": label, "assessment": normalize(label)}
            stamp = node.get("timestamp")
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and math.isfinite(stamp) and stamp >= 0:
                result["timestamp_seconds"] = stamp
            yield result
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                yield from findings(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from findings(value, f"{pointer}/{index}")


def watermark_summary(item: dict) -> dict:
    """Resemble Perth and Google SynthID watermark detection, when it was requested."""
    value = item.get("watermark")
    if not isinstance(value, dict):
        return {"requested": False, "status": "not_requested"}
    metrics = value.get("metrics") if isinstance(value.get("metrics"), dict) else {}
    return {
        "requested": True,
        "status": value.get("status", "unknown"),
        "overall_status": metrics.get("overall_status"),
        "detected_model_versions": metrics.get("detected_model_versions"),
        "synthid": metrics.get("synthid"),  # None means SynthID verification was unavailable
        "verdict": metrics.get("verdict"),
        "error_message": value.get("error_message"),
    }


def provenance_from_metadata(metadata: dict) -> dict:
    """Editable embedded metadata; a hint about the last encoder or platform, never a capture record."""
    result: dict = {"exif_present": False, "container_tags": {}}
    exif = (metadata.get("image") or {}).get("exif_unverified") or {}
    result["exif_present"] = bool(exif)
    result["exif_selected"] = {k: v for k, v in exif.items() if k in {"Make", "Model", "Software", "DateTime"}}
    tags = ((metadata.get("ffprobe") or {}).get("format") or {}).get("tags") or {}
    result["container_tags"] = {k: v for k, v in tags.items() if k.lower() in PROVENANCE_TAGS}
    comment = str(tags.get("comment", ""))
    result["platform_hint"] = "tiktok" if comment.startswith("vid:v") or "aigc_info" in tags else None
    return result


def analyze(payload: dict, kind: str, metadata: dict | None = None, questions: list[dict] | None = None) -> dict:
    item = payload.get("item", {})
    complete = item.get("status") == "completed" and payload.get("success") is not False
    components = []
    evidence = []
    for field in COMPONENTS.get(kind, []):
        node = item.get(field)
        label = node.get("label") if isinstance(node, dict) else None
        components.append(
            {"field": field, "provider_label": label, "assessment": normalize(label) if complete else "inconclusive"}
        )
        if complete:
            evidence.extend(findings(node, f"/item/{field}"))
    assessments = [entry["assessment"] for entry in components]
    if "synthetic_indicators" in assessments:
        verdict = "synthetic_indicators"
    elif assessments and all(value == "no_synthetic_indicators" for value in assessments):
        verdict = "no_synthetic_indicators"
    else:
        verdict = "inconclusive"
    intelligence = item.get("intelligence")
    return {
        "language": "en",
        "method": "Resemble Detect; provider categorical labels, without local score thresholds",
        "assessment": verdict,
        "provider_status": item.get("status", "unavailable"),
        "detect_uuid": item.get("uuid"),
        "media_type": kind,
        "components": components,
        "findings": evidence,
        "intelligence": intelligence,
        "intelligence_complete": isinstance(intelligence, dict) and intelligence.get("status") == "completed",
        "audio_source_tracing": item.get("audio_source_tracing"),
        "c2pa_manifest": item.get("c2pa_manifest"),
        "watermark": watermark_summary(item),
        "signal": item.get("signal"),
        "requested_options": item.get("extra_params"),
        "undocumented_fields": {k: item[k] for k in sorted(set(item) - KNOWN_ITEM_KEYS)},
        "provenance": provenance_from_metadata(metadata or {}),
        "questions": questions or [],
        "limitations": [
            "A detector label is evidence of synthetic indicators, not proof of authenticity or fabrication.",
            "Missing, unrecognized and incomplete results are inconclusive, never real.",
            "A fake label does not distinguish generation from manipulation.",
            "Frame timestamps identify sampled findings, not continuous manipulated intervals or pixel masks.",
            "Scores alone cannot establish the exact generator, prompt, source material, date, location or device.",
            "Local filesystem timestamps are not capture dates. Embedded metadata is unverified.",
            "Intelligence descriptions and question answers are provider-generated hypotheses, not verification.",
            "An absent watermark or C2PA manifest is not evidence of authenticity; most generators embed neither.",
        ],
    }
