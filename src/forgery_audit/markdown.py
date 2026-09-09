"""Latvian Markdown per artifact: material, every check with its result, conclusion, references, score legend."""

from datetime import UTC, datetime
from pathlib import Path

from forgery_audit.client import load_json
from forgery_audit.pdf import write_pdf

CODECS = {"h264": "H.264", "hevc": "H.265", "h265": "H.265", "vp9": "VP9", "av1": "AV1", "aac": "AAC", "mp3": "MP3"}
LABELS_LV = {"fake": "viltots", "likely fake": "iespējams viltots", "real": "īsts", "likely real": "iespējams īsts"}
DOCS = [
    (
        "Resemble AI Detect API (detektors, Intelligence, ūdenszīmes, C2PA, atgriezeniskā meklēšana, skaņas avots)",
        "https://docs.resemble.ai/api-reference/deepfake-detection/create-detection",
    ),
    ("Resemble AI ūdenszīmju noteikšana (Perth, Google SynthID)", "https://docs.resemble.ai/detect/watermark"),
    ("Resemble AI skaņas avota noteikšana", "https://docs.resemble.ai/detect/audio-source-tracing"),
    ("Resemble AI Detect Intelligence jautājumi", "https://docs.resemble.ai/detect/detect-intelligence"),
]
SCORE_NOTES = [
    "Detektora rezultāts un kopvērtējums: piegādātāja varbūtība 0–1, ka saturs ir sintētisks.",
    "Noteiktība un konsekvence: rezultāta stabilitāte starp analizētajiem kadriem vai skaņas posmiem.",
    "Ūdenszīmes detekcijas rādītājs: piegādātāja varbūtība 0–1, ka iegulta ūdenszīme ir; vērtība ap 0,5 nozīmē, "
    "ka signāla nav. Ūdenszīmes trūkums neapliecina autentiskumu.",
    "Intelligence vērtības iekavās: piegādātāja pārliecība 0–100 par savu skaidrojumu, ne neatkarīgs apstiprinājums.",
    "Atgriezeniskās meklēšanas līdzība: piegādātāja vērtējums 0–1 par atrastā avota atbilstību.",
]
ISSUER = "Forgery Audit, automatizēta analīze ar Resemble AI Detect"
SUMMARY_CHECKS = {
    "Attēla detektors",
    "Video detektors",
    "Skaņas detektors",
    "Skaņas avota noteikšana",
    "Ūdenszīmes (Resemble Perth, Google SynthID)",
    "C2PA satura akreditācija",
}


def _lv(number: float) -> str:
    """Latvian decimal comma."""
    return f"{number:g}".replace(".", ",")


def _num(value, digits: int = 3) -> str:
    try:
        return _lv(round(float(value), digits))
    except (TypeError, ValueError):
        return "nav"


def _label(value) -> str:
    text = str(value)
    return f"{text} ({LABELS_LV[text.lower()]})" if text.lower() in LABELS_LV else text


def _codec(stream: dict) -> str:
    name = str(stream.get("codec_name", ""))
    return CODECS.get(name.lower(), name.upper())


def _size(size: int | None) -> str:
    size = size or 0
    return _lv(round(size / 1024 / 1024, 1)) + " MB" if size >= 1024 * 1024 else f"{round(size / 1024)} KB"


def describe_file(metadata: dict) -> str:
    kind = metadata.get("media_type")
    size = _size(metadata.get("bytes"))
    if kind == "image":
        image = metadata.get("image") or {}
        return f"{image.get('format', 'Attēls')} attēls, {image.get('width')} × {image.get('height')} px, {size}"
    probe = metadata.get("ffprobe") or {}
    streams = probe.get("streams") or []
    fmt = probe.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    container = Path(metadata.get("relative_path", "")).suffix.lstrip(".").upper() or "Fails"
    duration = None
    try:
        duration = f"{_lv(round(float(str(fmt.get('duration'))), 1))} s"
    except (TypeError, ValueError):
        pass
    if kind == "video":
        parts = [f"{container} video"]
        if video:
            parts.append(f"{video.get('width')} × {video.get('height')} px")
        if duration:
            parts.append(duration)
        if video:
            parts.append(f"{_codec(video)} video")
        parts.append(f"{_codec(audio)} skaņa" if audio else "bez skaņas celiņa")
        return ", ".join(parts + [size])
    if kind == "audio":
        parts = [f"{container} audio"]
        if duration:
            parts.append(duration)
        if audio:
            parts.append(f"{_codec(audio)}, {audio.get('sample_rate')} Hz")
        return ", ".join(parts + [size])
    suffix = Path(metadata.get("relative_path", "")).suffix or "nezināms formāts"
    return f"{suffix} fails, {size}; nav attēls, video vai audio"


def _item(directory: Path) -> dict:
    latest = directory / "latest.json"
    return (load_json(latest) if latest.exists() else {}).get("item") or {}


def _description(item: dict) -> dict:
    intelligence = item.get("intelligence")
    description = intelligence.get("description") if isinstance(intelligence, dict) else None
    return description if isinstance(description, dict) else {}


def _flagged_stamps(analysis: dict) -> list[float]:
    return sorted(
        {
            f["timestamp_seconds"]
            for f in analysis.get("findings", [])
            if f["assessment"] == "synthetic_indicators" and "timestamp_seconds" in f
        }
    )


def check_rows(directory: Path, metadata: dict, analysis: dict) -> list[tuple[str, str]]:
    """What was tried and what came back, one row per check, with the provider's own numbers."""
    item = _item(directory)
    kind = metadata.get("media_type")
    rows: list[tuple[str, str]] = []
    if kind == "unsupported":
        return [("Resemble AI Detect", "nav veikts: formāts nav attēls, video vai audio")]
    if not item:
        return [("Resemble AI Detect", f"nav rezultāta: {analysis.get('error') or 'atbilde nav saglabāta'}")]
    image: dict = item.get("image_metrics") or {}
    if image.get("label") is not None:
        ifl = (image.get("ifl") or {}).get("score")
        rows.append(
            (
                "Attēla detektors",
                f"{_label(image['label'])}, rezultāts {_num(image.get('score'))}"
                + (f", IFL {_num(ifl)}" if ifl is not None else ""),
            )
        )
    video: dict = item.get("video_metrics") or {}
    if video.get("label") is not None:
        stamps = _flagged_stamps(analysis)
        frames = f"; atzīmēti {len(stamps)} kadri no {_lv(stamps[0])} līdz {_lv(stamps[-1])} s" if stamps else ""
        rows.append(
            (
                "Video detektors",
                f"{_label(video['label'])}, rezultāts {_num(video.get('score'))}, noteiktība "
                f"{_num(video.get('certainty'))}, analizēts {_num(video.get('duration'), 1)} s{frames}",
            )
        )
    audio: dict = item.get("metrics") or {}
    if audio.get("label") is not None:
        rows.append(
            (
                "Skaņas detektors",
                f"{_label(audio['label'])}, kopvērtējums {_num(audio.get('aggregated_score'))}, konsekvence "
                f"{_num(audio.get('consistency'), 2)}, analizēts {_num(audio.get('duration'), 1)} s",
            )
        )
    tracing = item.get("audio_source_tracing")
    if kind in {"video", "audio"}:
        if isinstance(tracing, dict) and tracing.get("label"):
            rows.append(("Skaņas avota noteikšana", f"iespējamais avots {tracing['label']}"))
        else:
            rows.append(("Skaņas avota noteikšana", "avots nav noteikts"))
    watermark = item.get("watermark")
    if isinstance(watermark, dict):
        metrics: dict = watermark["metrics"] if isinstance(watermark.get("metrics"), dict) else {}
        models = "; ".join(
            f"{m.get('model_version')} {'ir' if m.get('detected') else 'nav'}, "
            f"detekcijas rādītājs {_num(m.get('confidence'), 2)}"
            for m in metrics.get("model_results") or []
            if isinstance(m, dict)
        )
        synthid = metrics.get("synthid")
        status = {"present": "ir", "degraded": "ir, bojāta", "absent": "nav", "inconclusive": "nenoteikts"}
        rows.append(
            (
                "Ūdenszīmes (Resemble Perth, Google SynthID)",
                f"Perth {status.get(metrics.get('overall_status'), watermark.get('status'))}"
                + (f", {models}" if models else "")
                + f"; SynthID {'ir' if synthid else 'nav' if synthid is False else 'nav pieejams'}",
            )
        )
    else:
        rows.append(("Ūdenszīmes (Resemble Perth, Google SynthID)", "nav pārbaudīts"))
    c2pa: dict = item.get("c2pa_manifest") or {}
    if c2pa.get("validation_state"):
        state = {"Valid": "derīgi dati ir", "NotPresent": "nav", "Unavailable": "nav pieejams"}
        rows.append(("C2PA satura akreditācija", state.get(c2pa["validation_state"], c2pa["validation_state"])))
    if kind == "image":
        sources = analysis.get("reverse_image_search") or image.get("reverse_image_search_sources")
        if isinstance(sources, list) and sources:
            listed = "; ".join(
                f"[{s.get('title', 'avots')}]({s.get('resolved_url') or s.get('url')}) "
                f"(līdzība {_num(s.get('similarity'), 2)})"
                for s in sources
                if isinstance(s, dict)
            )
            rows.append(("Atgriezeniskā attēlu meklēšana", listed))
        elif (item.get("extra_params") or {}).get("use_reverse_search"):
            rows.append(("Atgriezeniskā attēlu meklēšana", "atbilstoši avoti nav atrasti"))
    description = _description(item)
    altered = description.get("digitally_altered")
    if isinstance(altered, dict) and altered:
        basis = f", pamats {altered['basis']}" if altered.get("basis") else ""
        rows.append(
            (
                "Intelligence: digitāla pārveidošana",
                f"{'ir' if altered.get('detected') else 'nav'} ({_num(altered.get('confidence'), 0)}){basis}; "
                f"{altered.get('alterations', '')}".rstrip("; "),
            )
        )
    liveness = description.get("liveness")
    if isinstance(liveness, dict) and liveness:
        rows.append(
            ("Intelligence: dzīvīgums", f"{liveness.get('assessment')} ({_num(liveness.get('confidence'), 0)})")
        )
    fraud = description.get("fraud")
    if isinstance(fraud, dict) and fraud:
        rows.append(
            (
                "Intelligence: krāpšanas tips",
                f"{fraud.get('type')} ({_num(fraud.get('confidence'), 0)}); {fraud.get('reasoning', '')}".rstrip("; "),
            )
        )
    if description.get("abnormalities"):
        rows.append(("Intelligence: novirzes", str(description["abnormalities"])))
    if description.get("transcription"):
        rows.append(("Intelligence: transkripcija", str(description["transcription"])))
    intelligence = item.get("intelligence")
    if isinstance(intelligence, dict) and intelligence.get("status") != "completed":
        rows.append(("Intelligence", f"nav pabeigts ({intelligence.get('status')})"))
    questions = [q for q in analysis.get("questions", []) if isinstance(q, dict)]
    if questions:
        answered = sum(1 for q in questions if q.get("status") == "completed")
        rows.append(("Detect Intelligence jautājumi", f"{answered} no {len(questions)} atbildēti"))
    provenance = analysis.get("provenance") or {}
    if kind == "image":
        exif = provenance.get("exif_selected") or {}
        rows.append(("EXIF metadati", ", ".join(f"{k} {v}" for k, v in exif.items()) if exif else "nav"))
    else:
        tags = provenance.get("container_tags") or {}
        listed = "; ".join(f"{k} {v}" for k, v in tags.items())
        hint = "TikTok eksports; " if provenance.get("platform_hint") == "tiktok" else ""
        rows.append(("Konteinera metadati", (hint + listed) if listed else "nav"))
    return [(k, v.replace("|", "/").replace("\n", " ")) for k, v in rows]


def reference_lines(directory: Path, metadata: dict, analysis: dict) -> list[str]:
    """Numbered references: reverse-search articles with the provider's reason, then method documentation."""
    lines = []
    sources = analysis.get("reverse_image_search") or []
    for source in sources:
        if not isinstance(source, dict) or not source.get("url"):
            continue
        url = source.get("resolved_url") or source["url"]
        reason = f" {source['reason']}" if source.get("reason") else ""
        title = source.get("title", "avots")
        lines.append(f"[{title}]({url}), līdzība {_num(source.get('similarity'), 2)}.{reason}")
    item = _item(directory)
    if item.get("uuid"):
        stamp = str(item.get("created_at", ""))[:19].replace("T", " ")
        lines.append(
            f"Resemble AI Detect analīze `{item['uuid']}`, {stamp} UTC; "
            "pilnās API atbildes saglabātas pierādījumu mapē."
        )
    if metadata.get("media_type") != "unsupported":
        lines += [f"[{title}]({url})" for title, url in DOCS]
    return [f"{i}. {line}" for i, line in enumerate(lines, 1)]


def _table(header: tuple[str, str], rows: list[tuple[str, str]]) -> str:
    lines = [f"| {header[0]} | {header[1]} |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def verdict_sentence(analysis: dict) -> str:
    components = {c["field"]: c["assessment"] for c in analysis.get("components", [])}
    if analysis.get("media_type") == "unsupported":
        return "Dziļviltojuma pārbaude šim failam nav veikta, jo formāts nav atbalstīts."
    if not components or analysis.get("provider_status") != "completed":
        return "Resemble AI analīzes rezultāts nav pieejams, tāpēc secinājums nav iespējams."
    names = {"image_metrics": "attēlu", "video_metrics": "vizuālo saturu", "metrics": "skaņu"}
    fake = [names[k] for k, v in components.items() if v == "synthetic_indicators"]
    real = [names[k] for k, v in components.items() if v == "no_synthetic_indicators"]
    parts = []
    if fake:
        parts.append(f"Resemble AI detektors {' un '.join(fake)} klasificē kā viltotu")
    if real:
        parts.append(f"{' un '.join(real)} klasificē kā īstu, kas neapliecina autentiskumu")
    if not parts:
        return "Resemble AI detektora rezultāts nav interpretējams."
    return "; ".join(parts) + "."


def auto_conclusion(directory: Path, metadata: dict, analysis: dict) -> str:
    """Automatic Latvian prose covering the seven questions; a reviewed conclusion.lv.txt replaces it."""
    if metadata.get("media_type") == "unsupported":
        return "Fails nav attēls, video vai audio, tāpēc Resemble AI to neanalizē un jautājumi paliek neatbildēti."
    text = verdict_sentence(analysis)
    stamps = _flagged_stamps(analysis)
    if stamps:
        text += (
            f" Pazīmes atzīmētas {len(stamps)} analizētajos kadros no {_lv(stamps[0])} līdz {_lv(stamps[-1])} "
            "sekundei; tas nenozīmē, ka pārveidots katrs kadrs vai viss tā laukums."
        )
    altered = _description(_item(directory)).get("digitally_altered")
    altered = altered if isinstance(altered, dict) else {}
    if altered.get("basis") == "localized_manipulation":
        text += " Piegādātāja Intelligence analīze norāda uz lokālu pārveidošanu, nevis pilnīgu ģenerēšanu."
    elif altered.get("basis") == "non_photographic":
        text += " Piegādātāja Intelligence analīze norāda uz pilnībā ģenerētu saturu."
    elif analysis.get("assessment") == "synthetic_indicators":
        text += " Detektora rezultāts viens pats neļauj nošķirt ģenerēšanu no esoša materiāla pārveidošanas."
    tracing = analysis.get("audio_source_tracing")
    if isinstance(tracing, dict) and tracing.get("label"):
        text += f" Skaņas avota noteikšana kā iespējamo balss avotu norāda {tracing['label']}."
    watermark = analysis.get("watermark") or {}
    if watermark.get("status") == "completed":
        if watermark.get("overall_status") in {"present", "degraded"} or watermark.get("synthid") is True:
            text += " Konstatēta ģeneratora ūdenszīme."
        else:
            text += " Resemble Perth un Google SynthID ūdenszīmes nav konstatētas."
    if (analysis.get("c2pa_manifest") or {}).get("validation_state") == "NotPresent":
        text += " C2PA satura akreditācijas datu nav."
    text += " Konkrēto ģenerēšanas rīku, tam doto uzdevumu un izmantotos avota materiālus no rezultātiem noteikt nevar."
    provenance = analysis.get("provenance") or {}
    if provenance.get("platform_hint") == "tiktok":
        text += " Konteinera metadati norāda uz TikTok eksportu, nevis oriģinālu ierakstu."
    if metadata.get("media_type") == "image" and not provenance.get("exif_present"):
        text += " EXIF metadatu nav."
    return text + " Izveides laiks, vieta un ierīce nav nosakāmi."


def conclusion_text(directory: Path, metadata: dict, analysis: dict) -> str:
    reviewed = directory / "conclusion.lv.txt"
    if reviewed.exists():
        text = reviewed.read_text(encoding="utf-8").strip()
        if text:
            return text
    return auto_conclusion(directory, metadata, analysis)


def report_name(relative: str) -> str:
    return relative.replace("/", "__") + ".lv.md"


def _load(root: Path, entry: dict) -> tuple[Path, dict, dict]:
    directory = root / entry["directory"]
    metadata = load_json(directory / "metadata.json") if (directory / "metadata.json").exists() else {}
    metadata.setdefault("relative_path", entry["file"])
    analysis_path = directory / "analysis.en.json"
    analysis = load_json(analysis_path) if analysis_path.exists() else {"assessment": "inconclusive"}
    if entry.get("error") and not analysis.get("error"):
        analysis["error"] = entry["error"]
    return directory, metadata, analysis


def document_number(metadata: dict, stamp: str) -> str:
    return f"ATZ-{stamp.replace('-', '')}-{str(metadata.get('sha256', ''))[:8].upper() or 'NA'}"


def write_artifact_report(root: Path, entry: dict) -> Path:
    directory, metadata, analysis = _load(root, entry)
    item = _item(directory)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    header = [
        ("Dokuments", f"Atzinums Nr. {document_number(metadata, stamp)}"),
        ("Datums", stamp),
        ("Sagatavoja", ISSUER),
        ("Pārbaudāmais materiāls", f"`{entry['file']}`"),
        ("SHA-256", f"`{metadata.get('sha256', 'nav')}`"),
        ("Formāts", describe_file(metadata)),
    ]
    if item.get("uuid"):
        header.append(("Resemble AI analīzes ID", f"`{item['uuid']}`, {str(item.get('created_at', ''))[:10]}"))
    lines = [
        "# Digitālā materiāla dziļviltojuma analīzes atzinums",
        "",
        _table(("", ""), header),
        "",
        "## 1. Atzinums",
        "",
        conclusion_text(directory, metadata, analysis),
        "",
        "## 2. Veiktās pārbaudes un rezultāti",
        "",
        _table(("Pārbaude", "Rezultāts"), check_rows(directory, metadata, analysis)),
    ]
    references = reference_lines(directory, metadata, analysis)
    if references:
        lines += ["", "## 3. Atsauces", "", *references]
    if metadata.get("media_type") != "unsupported" and item:
        lines += ["", "## 4. Rādītāju skaidrojums", "", *[f"- {note}" for note in SCORE_NOTES]]
    lines += [
        "",
        "---",
        "",
        "Atzinumu sagatavoja automatizēta analīze; pilnie Resemble AI pieprasījumi un atbildes, faila kopija un "
        "kontrolsumma glabājas pierādījumu mapē.",
        "",
        "Pārbaudīja: ____________________  Datums: ____________",
    ]
    target = root / "reports" / report_name(entry["file"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def write_summary(root: Path, entries: list[dict]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "# Digitālā materiāla dziļviltojuma analīzes atzinums",
        "",
        "## Kopsavilkums",
        "",
        _table(
            ("", ""),
            [
                ("Dokuments", f"Audita kopsavilkums, {stamp}"),
                ("Sagatavoja", ISSUER),
                ("Pārbaudīto failu skaits", str(len(entries))),
            ],
        ),
        "",
        "## 1. Atzinums",
        "",
    ]
    for entry in entries:
        _directory, metadata, analysis = _load(root, entry)
        lines += [f"**{entry['file']}.** {describe_file(metadata)}. {verdict_sentence(analysis)}", ""]
    lines += ["## 2. Veiktās pārbaudes un rezultāti", ""]
    for entry in entries:
        directory, metadata, analysis = _load(root, entry)
        rows = [(k, v) for k, v in check_rows(directory, metadata, analysis) if k in SUMMARY_CHECKS]
        lines += [f"### {entry['file']}", ""]
        if rows:
            lines += [_table(("Pārbaude", "Rezultāts"), rows), ""]
    lines += [
        "## 3. Metode",
        "",
        "Resemble AI Detect: dziļviltojuma detektors katrai modalitātei, Intelligence analīze, ūdenszīmju pārbaude "
        "(Resemble Perth, Google SynthID), C2PA satura akreditācija, atgriezeniskā attēlu meklēšana, skaņas avota "
        "noteikšana un Detect Intelligence jautājumi; papildus lokālie faila metadati un apskate. Katram failam ir "
        "atsevišķs atzinums ar pilnu pārbaužu tabulu, atsaucēm un rādītāju skaidrojumu.",
        "",
        "---",
        "",
        "Pārbaudīja: ____________________  Datums: ____________",
    ]
    target = root / "atzinums.lv.md"
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def write_markdown(root: Path, entries: list[dict]) -> list[Path]:
    """Per-artifact Markdown and PDF under reports/, plus the audit cover in both formats; entirely offline."""
    written = []
    for entry in entries:
        markdown = write_artifact_report(root, entry)
        written += [markdown, write_pdf(markdown, subject=entry["file"])]
    cover = write_summary(root, entries)
    written += [cover, write_pdf(cover, subject="kopsavilkums")]
    return written
