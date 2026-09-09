import base64
import json

import httpx
import pytest
from PIL import Image
from pypdf import PdfReader

from forgery_audit.analysis import analyze
from forgery_audit.client import ResembleClient
from forgery_audit.pipeline import extract_visualizations, process, sha256
from forgery_audit.report import write_report


def test_folder_reports_and_raw_history_survive_offline_regeneration(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    Image.new("RGB", (3, 3)).save(source / "attēls.jpg")
    (source / "document.txt").write_text("English evidence text, not a detector-supported input.")
    calls = []

    def handler(request):
        calls.append(request)
        if "/intelligence" in request.url.path:
            return httpx.Response(
                202 if request.method == "POST" else 200,
                json={"success": True, "item": {"uuid": "q1", "status": "completed", "answer": "Provider text."}},
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "item": {
                    "uuid": "test-id",
                    "status": "completed",
                    "image_metrics": {"label": "Fake", "score": 0.98123},
                    "intelligence": {"status": "completed"},
                    "watermark": {"status": "completed", "metrics": {"overall_status": "absent", "synthid": False}},
                    "c2pa_manifest": {"validation_state": "NotPresent"},
                },
            },
        )

    client = ResembleClient("not-a-live-key", transport=httpx.MockTransport(handler))
    output = source / "reports"
    first = process(source, output, client)
    client.close()
    assert len(first) == 2
    assert len([c for c in calls if c.method == "POST" and c.url.path.endswith("/detect")]) == 1
    image_result = next(r for r in first if r["file"] == "attēls.jpg")
    directory = output / image_result["directory"]
    questions = json.loads((directory / "questions.en.json").read_text())
    assert len(questions) == 8 and all(q["answer"] == "Provider text." for q in questions)
    report = (output / "reports" / "attēls.jpg.lv.md").read_text()
    assert report.startswith("# Digitālā materiāla dziļviltojuma analīzes atzinums\n\n## attēls.jpg")
    assert "| Dokuments | Atzinums Nr. ATZ-" in report and "## 1. Atzinums" in report
    assert "## 2. Veiktās pārbaudes un rezultāti" in report and "## 3. Pārbaudes uzdevums" in report
    assert report.index("## 1. Atzinums") < report.index("## 2. Veiktās")
    assert "| Attēla detektors | Fake (viltots), rezultāts 0,981 |" in report
    assert "| Ūdenszīmes (Resemble Perth, Google SynthID) | Perth nav; SynthID nav |" in report
    assert "| C2PA satura akreditācija | nav |" in report and "| EXIF metadati | nav |" in report
    assert "8 no 8 atbildēti" in report and "klasificē kā viltotu" in report
    assert "<img" not in report
    assert "## 4. Atsauces" in report and "docs.resemble.ai" in report and "## 5. Rādītāju skaidrojums" in report
    cover = (output / "atzinums.lv.md").read_text()
    assert "### attēls.jpg" in cover and "### document.txt" in cover and "nav atbalstīts" in cover
    assert sha256(directory / "source.jpg") == sha256(source / "attēls.jpg")
    pdf = PdfReader(output / "reports" / "attēls.jpg.lv.pdf")
    text = " ".join(page.extract_text() for page in pdf.pages)
    assert "Atzinums" in text and "SynthID" in text and (output / "atzinums.lv.pdf").exists()
    assert "dziļviltojuma" in text
    assert "0.98123" not in text
    assert "confidence" not in text.lower()
    assert len(json.loads((directory / "report.lv.json").read_text())["questions"]) == 7
    raw = {p: p.read_bytes() for p in directory.glob("http/*")}
    second = process(source, output, None, offline=True)
    assert len(second) == 2  # Output artifacts never become new input.
    assert all(p.read_bytes() == content for p, content in raw.items())
    unsupported = next(r for r in first if r["file"] == "document.txt")
    assert unsupported["assessment"] == "inconclusive"
    assert not (output / unsupported["directory"] / "http").exists()


def test_embedded_visualizations_are_saved_with_pointer_and_digest(tmp_path):
    png = b"\x89PNG\r\n\x1a\nfixture"
    value = "data:image/png;base64," + base64.b64encode(png).decode()
    extract_visualizations({"item": {"image_metrics": {"ifl": {"heatmap": value}}}}, tmp_path)
    entries = json.loads((tmp_path / "index.json").read_text())
    assert entries[0]["pointer"] == "/item/image_metrics/ifl/heatmap"
    assert (tmp_path / entries[0]["file"]).read_bytes() == png


def test_review_requires_existing_evidence_and_renders_attributed_latvian(tmp_path):
    payload = {
        "item": {
            "status": "completed",
            "image_metrics": {"label": "Fake"},
            "intelligence": {"description": {"abnormalities": "Blended edges"}},
        }
    }
    (tmp_path / "latest.json").write_text(json.dumps(payload))
    review = {
        "observations": [
            {
                "pointer": "/item/intelligence/description/abnormalities",
                "text_lv": "Resemble aprakstā norādītas izplūdušas savienojuma malas.",
            }
        ]
    }
    review_path = tmp_path / "review.lv.json"
    review_path.write_text(json.dumps(review))
    metadata = {"relative_path": "image.jpg", "sha256": "a" * 64}
    write_report(tmp_path, metadata, analyze(payload, "image"))
    saved = json.loads((tmp_path / "report.lv.json").read_text())
    assert saved["observations"][0]["text_lv"].startswith("Resemble aprakstā")
    review["observations"][0]["pointer"] = "/item/missing"
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="pointer is missing"):
        write_report(tmp_path, metadata, analyze(payload, "image"))
