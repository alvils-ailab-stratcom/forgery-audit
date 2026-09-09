"""Latvian narrative PDFs; quantitative evidence stays in the intermediate files."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

from forgery_audit.client import save_json

CONCLUSIONS = {
    "synthetic_indicators": "Resemble AI analīzē konstatētas pazīmes, kas norāda uz iespējamu mākslīgi ģenerētu vai "
    "ar dziļviltojuma tehnoloģiju pārveidotu saturu. "
    "Šis automātiskais rezultāts pats par sevi nav galīgs viltojuma pierādījums.",
    "no_synthetic_indicators": "Resemble AI analīzē nav konstatētas dziļviltojumam raksturīgas pazīmes. "
    "Tas neapstiprina materiāla autentiskumu un neizslēdz manipulācijas, kuras izmantotā metode neatklāj.",
    "inconclusive": "Pieejamie analīzes rezultāti nav pietiekami, lai noteiktu, vai materiāls ir dziļviltojums.",
}
COMPONENT_NAMES = {"image_metrics": "Attēls", "video_metrics": "Video vizuālais saturs", "metrics": "Skaņas saturs"}
ASSESSMENTS = {
    "synthetic_indicators": "konstatētas iespējama sintētiska satura pazīmes",
    "no_synthetic_indicators": "sintētiska satura pazīmes nav konstatētas",
    "inconclusive": "rezultāts nav nosakāms vai nav pieejams",
}
QUESTIONS = [
    "Vai iesniegtais saturs ir izveidots, izmantojot dziļviltojuma tehnoloģiju?",
    "Vai viss saturs vai kāda tā daļa ir izveidota, izmantojot dziļviltojuma tehnoloģiju? Kura tieši?",
    "Vai saturs ir manipulēts vai ģenerēts ar dziļviltojuma tehnoloģiju?",
    "Ar kādu dziļviltojuma tehnoloģiju saturs izgatavots?",
    "Kāds uzdevums dots dziļviltojuma tehnoloģijai, lai izveidotu saturu?",
    "Kādus materiālus izmantoja dziļviltojuma tehnoloģija satura izveidei?",
    "Kad, kur un ar kādu ierīci saturs ir izveidots?",
]


def narrative(metadata: dict, analysis: dict) -> dict:
    conclusion = CONCLUSIONS[analysis["assessment"]]
    components = "; ".join(
        f"{COMPONENT_NAMES[c['field']]}: {ASSESSMENTS[c['assessment']]}" for c in analysis["components"]
    )
    stamps = sorted(
        {
            f["timestamp_seconds"]
            for f in analysis["findings"]
            if f["assessment"] == "synthetic_indicators" and "timestamp_seconds" in f
        }
    )
    localization = "Precīzu pārveidoto apgabalu vai nepārtrauktu laika intervālu ar pieejamajiem datiem noteikt nevar."
    if stamps and len(stamps) <= 20:
        localization = (
            "Iespējama sintētiska satura pazīmes atzīmētas analizētajos kadros šādos laikos no ieraksta sākuma "
            "(sekundēs): " + ", ".join(f"{s:g}" for s in stamps) + ". " + localization
        )
    elif stamps:
        localization = (
            f"Iespējama sintētiska satura pazīmes atzīmētas {len(stamps)} analizētajos kadros; "
            f"pirmais atzīmētais kadrs ir {stamps[0]:g} sekundē, pēdējais — {stamps[-1]:g} sekundē. "
            "Pilns kadru laiku saraksts saglabāts starprezultātos. " + localization
        )
    reasons = components or "Šim materiālam nav pieejams interpretējams detektora rezultāts."
    coverage = analysis.get("coverage", {})
    if analysis["media_type"] == "video":
        source = coverage.get("source_duration_seconds")
        visual = coverage.get("visual_duration_seconds")
        audio = coverage.get("audio_duration_seconds")
        reasons += (
            f" Faila ilgums: {source if source is not None else 'nav noteikts'} sekundes; "
            f"piegādātāja norādītais vizuālās analīzes ilgums: {visual if visual is not None else 'nav norādīts'} "
            f"sekundes; skaņas analīzes ilgums: {audio if audio is not None else 'nav norādīts'} sekundes. "
            "Secinājumi attiecas tikai uz faktiski analizēto saturu."
        )
    if analysis.get("error"):
        reasons += " Analīzi neizdevās pabeigt; tehniskais iemesls saglabāts analīzes starprezultātos."
    if analysis["media_type"] == "unsupported":
        reasons = "Šī Resemble Detect darbplūsma neatbalsta iesniegtā faila formāta dziļviltojuma noteikšanu."
    answers = [
        conclusion,
        (components + ". " if components else "") + localization,
        "Detektora klasifikācija viena pati neļauj nošķirt pilnīgu ģenerēšanu no esoša materiāla pārveidošanas.",
        "Konkrēto ģenerēšanas vai pārveidošanas tehnoloģiju ar pieejamajiem pierādījumiem noteikt nevar.",
        "Sākotnējo uzdevumu vai uzvedni no detektora rezultāta noteikt nevar.",
        "Sākotnējie attēli, ieraksti vai citi avota materiāli nav droši identificējami no detektora rezultāta.",
        "Izveides laiks, vieta un ierīce nav droši nosakāmi. Faila metadati, ja tādi ir, saglabāti starprezultātos; "
        "tie var būt mainīti, un faila sistēmas laiks nav uzņemšanas laika pierādījums.",
    ]
    watermark = analysis.get("watermark") or {}
    if watermark.get("status") == "completed":
        if watermark.get("overall_status") in {"present", "degraded"} or watermark.get("synthid") is True:
            answers[0] += " Konstatēta ģeneratora ūdenszīme (Resemble Perth vai Google SynthID)."
        else:
            answers[3] += (
                " Resemble Perth un Google SynthID ūdenszīmes nav konstatētas; to trūkums neapliecina autentiskumu."
            )
    if (analysis.get("c2pa_manifest") or {}).get("validation_state") == "NotPresent":
        answers[6] += " C2PA satura akreditācijas datu failā nav."
    tracing = analysis.get("audio_source_tracing")
    if isinstance(tracing, dict) and tracing.get("label") and not tracing.get("error_message"):
        source = str(tracing["label"])
        if source.lower() not in {"real", "unknown", "none", "unavailable"}:
            answers[3] += (
                f" Resemble skaņas avota noteikšanas modulis norāda iespējamo avotu «{source}»; "
                "tā ir piegādātāja hipotēze."
            )
    return {
        "language": "lv",
        "title": "Digitālā materiāla dziļviltojuma analīzes atzinums",
        "filename": metadata["relative_path"],
        "sha256": metadata["sha256"],
        "created_at": datetime.now(UTC).isoformat(),
        "conclusion": conclusion,
        "reasoning": reasons,
        "questions": [{"question": q, "answer": a} for q, a in zip(QUESTIONS, answers, strict=True)],
        "provider_answers_en": [
            {"question": q.get("question"), "answer": q.get("answer"), "status": q.get("status")}
            for q in analysis.get("questions", [])
            if isinstance(q, dict)
        ],
        "limitations": "Atzinums sagatavots automātiski, pamatojoties uz Resemble AI rezultātiem. "
        "Tas nav parakstīts tiesu eksperta atzinums. Detektora pazīmes neļauj apstiprināt notikuma patiesumu, "
        "satura autoru vai izgatavošanas apstākļus. "
        "Skaitliskie rādītāji un pilnie API dati glabājas atsevišķi starprezultātos.",
    }


def write_report(directory: Path, metadata: dict, analysis: dict) -> None:
    value = narrative(metadata, analysis)
    review_path = directory / "review.lv.json"
    observations = []
    if review_path.exists():
        payload = json.loads((directory / "latest.json").read_text())
        review = json.loads(review_path.read_text())
        for observation in review["observations"]:
            pointer = observation["pointer"]
            if not isinstance(pointer, str) or not pointer.startswith("/item/"):
                raise ValueError("Review evidence pointer must reference /item/ in latest.json")
            node = payload
            try:
                for token in pointer[1:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    node = node[int(token)] if isinstance(node, list) else node[token]
            except (KeyError, IndexError, ValueError, TypeError):
                raise ValueError(f"Review evidence pointer is missing: {pointer}") from None
            text = observation["text_lv"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Review text_lv must be nonempty Latvian text")
            observations.append({"text_lv": text, "pointer": pointer})
    value["observations"] = observations
    save_json(directory / "report.lv.json", value)
    font = Path(os.environ.get("FORGERY_AUDIT_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    if not font.is_file():
        raise RuntimeError("Install fonts-dejavu-core or set FORGERY_AUDIT_FONT to a Unicode TTF font")
    pdfmetrics.registerFont(TTFont("Latvian", str(font)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "LatvianBody", parent=styles["BodyText"], fontName="Latvian", fontSize=10, leading=15, spaceAfter=9
    )
    heading = ParagraphStyle(
        "LatvianHeading",
        parent=body,
        fontSize=12,
        leading=17,
        spaceBefore=12,
        textColor=colors.HexColor("#17354a"),
        keepWithNext=True,
    )
    title = ParagraphStyle("LatvianTitle", parent=heading, fontSize=18, leading=23)
    story: list[Flowable] = []

    def paragraph(text: str, style=body):
        story.append(Paragraph(escape(text), style))

    paragraph(value["title"], title)
    paragraph("Materiāls: " + value["filename"])
    paragraph("SHA-256: " + value["sha256"])
    paragraph("Analīzes dokumenta datums (UTC): " + value["created_at"])
    paragraph("Secinājums", heading)
    paragraph(value["conclusion"])
    paragraph("Pamatojums un metode", heading)
    paragraph("Analīzes metode: Resemble AI dziļviltojuma detektora kategorisko rezultātu izvērtēšana.")
    paragraph(value["reasoning"])
    if observations:
        paragraph("Piegādātāja papildu novērojumu izvērtējums", heading)
        for observation in observations:
            paragraph(observation["text_lv"])
        paragraph(
            "Šie novērojumi ir piegādātāja skaidrojuma izvērtējums; tie nav neatkarīgi apstiprināti fakti. "
            "Saistes uz sākotnējiem datiem saglabātas dokumenta strukturētajā versijā."
        )
    for index, question in enumerate(value["questions"], 1):
        paragraph(f"{index}. {question['question']}", heading)
        paragraph(question["answer"])
    paragraph("Ierobežojumi un pierādījumu uzskaite", heading)
    paragraph(value["limitations"])
    paragraph(
        "Avoti: https://docs.resemble.ai/api-reference/deepfake-detection/create-detection un "
        "https://docs.resemble.ai/api-reference/deepfake-detection/get-detection. "
        "Faila kontrolsumma, metadati, pieprasījumi, atbildes un analīze angļu valodā ir saglabāti kopā ar dokumentu."
    )
    story.append(Spacer(1, 4 * mm))
    SimpleDocTemplate(
        str(directory / "report.lv.pdf"),
        pagesize=(210 * mm, 297 * mm),
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=value["title"],
        author="Forgery Audit",
    ).build(story)
