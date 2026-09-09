import pytest

from forgery_audit.analysis import analyze


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Fake", "synthetic_indicators"),
        ("real", "no_synthetic_indicators"),
        (None, "inconclusive"),
        ("new label", "inconclusive"),
    ],
)
def test_image_categorical_verdict(label, expected):
    result = analyze({"item": {"status": "completed", "image_metrics": {"label": label, "score": 0.99}}}, "image")
    assert result["assessment"] == expected


def test_failed_detection_cannot_produce_a_verdict_from_partial_metrics():
    result = analyze({"item": {"status": "failed", "image_metrics": {"label": "fake"}}}, "image")
    assert result["assessment"] == "inconclusive"
    assert result["findings"] == []


def test_video_preserves_opposing_modalities_and_nested_frame_evidence():
    payload = {
        "item": {
            "status": "completed",
            "metrics": {"label": "real"},
            "video_metrics": {
                "label": "Fake",
                "children": [{"type": "VideoChunkResult", "children": [{"conclusion": "Fake", "timestamp": 2.4}]}],
            },
        }
    }
    result = analyze(payload, "video")
    assert result["assessment"] == "synthetic_indicators"
    assert result["components"][1]["assessment"] == "no_synthetic_indicators"
    frame = next(f for f in result["findings"] if "timestamp_seconds" in f)
    assert frame["timestamp_seconds"] == 2.4
    assert frame["pointer"] == "/item/video_metrics/children/0/children/0"


def test_missing_video_modality_is_not_authentic():
    result = analyze({"item": {"status": "completed", "video_metrics": {"label": "real"}}}, "video")
    assert result["assessment"] == "inconclusive"
