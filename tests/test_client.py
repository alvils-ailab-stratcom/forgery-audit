import json

import httpx
import pytest

from forgery_audit.client import DetectionError, ResembleClient


def test_polling_preserves_raw_bodies_and_waits_for_intelligence(tmp_path):
    source = tmp_path / "media.mp4"
    source.write_bytes(b"test fixture")
    calls = []
    raw = b'{ "success": true, "item": {"uuid":"abc", "status":"completed", "intelligence":{"status":"completed"}}}'

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert b'name="max_video_secs"' in request.content
            return httpx.Response(200, json={"success": True, "item": {"uuid": "abc", "status": "processing"}})
        if len(calls) == 2:
            return httpx.Response(200, json={"item": {"status": "completed", "intelligence": {"status": "processing"}}})
        return httpx.Response(200, content=raw)

    client = ResembleClient("secret-token", transport=httpx.MockTransport(handler))
    directory = tmp_path / "result"
    result = client.detect(source, directory, "video", interval=0, duration=22)
    client.close()
    assert result["item"]["intelligence"]["status"] == "completed"
    assert len(calls) == 3
    assert (directory / "http/0003.response.json").read_bytes() == raw
    assert len(list((directory / "http").glob("*.response.txt"))) == 3
    assert "secret-token" not in "".join(p.read_text() for p in directory.rglob("*.json"))


def test_confirmed_rejection_drops_addons_then_allows_resubmission(tmp_path):
    source = tmp_path / "media.jpg"
    source.write_bytes(b"fixture")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, content=b'{"error":"plan lacks Detect"}')

    client = ResembleClient("secret", transport=httpx.MockTransport(handler))
    directory = tmp_path / "result"
    with pytest.raises(DetectionError, match="403"):
        client.detect(source, directory, "image")
    # signal, use_reverse_search and detect_watermark were dropped one by one before giving up.
    assert [r.method for r in calls] == ["POST"] * 4
    assert b'name="detect_watermark"' in calls[0].content and b'name="detect_watermark"' not in calls[3].content
    assert json.loads((directory / "http/0001.response.txt").read_text())["error"] == "plan lacks Detect"
    with pytest.raises(DetectionError, match="403"):
        client.detect(source, directory, "image")  # A confirmed rejection may be corrected and resubmitted.
    client.close()
    assert len(calls) == 8


def test_unresolved_submission_is_never_retried(tmp_path):
    source = tmp_path / "media.jpg"
    source.write_bytes(b"fixture")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("boom")

    client = ResembleClient("secret", transport=httpx.MockTransport(handler))
    directory = tmp_path / "result"
    with pytest.raises(DetectionError, match="Transport failure"):
        client.detect(source, directory, "image")
    with pytest.raises(DetectionError, match="Previous submission"):
        client.detect(source, directory, "image")
    client.close()
    assert len(calls) == 1


def test_new_options_supersede_a_finished_job_and_keep_its_history(tmp_path):
    source = tmp_path / "media.jpg"
    source.write_bytes(b"fixture")
    directory = tmp_path / "result"
    directory.mkdir()
    (directory / "job.json").write_text('{"uuid":"old","fields":{"visualize":"true","intelligence":"true"}}')
    (directory / "latest.json").write_text('{"item":{"uuid":"old","status":"completed"}}')
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "item": {"uuid": "new", "status": "processing"}})
        return httpx.Response(
            200,
            json={
                "item": {
                    "uuid": "new",
                    "status": "completed",
                    "intelligence": {"status": "completed"},
                    "watermark": {"status": "completed", "metrics": {"overall_status": "absent"}},
                }
            },
        )

    client = ResembleClient("secret", transport=httpx.MockTransport(handler))
    result = client.detect(source, directory, "image", interval=0)
    client.close()
    assert result["item"]["uuid"] == "new"
    assert calls[0].method == "POST"
    assert json.loads((directory / "job.superseded-01.json").read_text())["uuid"] == "old"
    assert json.loads((directory / "latest.superseded-01.json").read_text())["item"]["uuid"] == "old"
    assert json.loads((directory / "job.json").read_text())["fields"]["detect_watermark"] == "true"


def test_resume_uses_saved_uuid_without_upload(tmp_path):
    directory = tmp_path / "result"
    directory.mkdir()
    (directory / "job.json").write_text('{"uuid":"saved-job"}')

    def handler(request):
        assert request.method == "GET"
        assert request.url.path.endswith("/saved-job")
        return httpx.Response(200, json={"item": {"status": "completed", "intelligence": {"status": "failed"}}})

    client = ResembleClient("secret", transport=httpx.MockTransport(handler))
    client.detect(tmp_path / "unused.jpg", directory, "image")
    client.close()


def test_corrected_validation_rejection_is_safe_to_resubmit(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"fixture")
    rejected = True

    def handler(request):
        nonlocal rejected
        if rejected:
            rejected = False
            return httpx.Response(422, json={"success": False, "error": "Validation failed"})
        if request.method == "POST":
            assert b"\r\n23\r\n" in request.content
        return httpx.Response(
            200, json={"item": {"uuid": "new", "status": "completed", "intelligence": {"status": "completed"}}}
        )

    client = ResembleClient("secret", transport=httpx.MockTransport(handler))
    client.detect(source, tmp_path / "result", "video", duration=22.01)
    client.close()
    job = json.loads((tmp_path / "result/job.json").read_text())
    assert job["rejected_attempts"] == [{"status_code": 422, "dropped_option": "signal"}]
    assert "signal" not in job["fields"] and job["fields"]["detect_watermark"] == "true"
    assert (tmp_path / "result/http/0001.response.txt").exists()
    assert (tmp_path / "result/http/0002.response.json").exists()
