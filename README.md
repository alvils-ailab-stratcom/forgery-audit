# Forgery Audit

Folder-based Resemble AI deepfake analysis. Deliverable: one concise Latvian Markdown report per image, video or audio file (`results/<case>/reports/<file>.lv.md`) plus a half-page cover `atzinums.lv.md`. English technical analysis, provider answers and complete raw API response bodies remain beside them. Each report has three sections: material (file, SHA-256, format, date, analysis id), checks performed with their results and Resemble's own scores (detector per modality, watermark Perth/SynthID, C2PA, reverse image search, audio source tracing, Intelligence assessments, abnormalities, transcription, question count, EXIF or container metadata), a half-page conclusion, numbered references (reverse-image-search articles with resolved URLs and the provider's reason, the Resemble analysis id, documentation of each method) and a score legend. No images or limitations section.

## One prompt in Claude Code or Codex

Open the repository in Claude Code (`/forgery-audit data`) or Codex and ask, for example, "audit the data folder". Both tools load `.agents/skills/forgery-audit/SKILL.md` (Claude Code through the `.claude/skills` symlink) and run the whole flow: `make analyze`, evidence review, a reviewed `conclusion.lv.txt` per artifact, `make reports`, verification, and the report paths in the answer. `CLAUDE.md` and `AGENTS.md` point both agents at the skill.

## Run

Install `uv`, Python 3.12, `ffmpeg` (for ffprobe) and `fonts-dejavu-core`. On other systems set `FORGERY_AUDIT_FONT` to a Unicode TrueType font supporting Latvian.

```bash
make install
# Set RESEMBLE_AI_API_KEY in .env (the existing file is supported).
make analyze DATA=data OUTPUT=results/audit
make reports DATA=data OUTPUT=results/audit  # offline regeneration of Markdown and PDF, no upload
make check
```

`uv run forgery-audit FOLDER --output RESULTS --timeout 900` is also available. If your shell exports `UV_PROJECT_ENVIRONMENT` for a different project, unset it first; Make pins this project's environment.

Analysis submits each supported artifact to Resemble and can incur API charges. Images, video and audio use `/api/v2/detect`; video requests both modalities and passes the locally measured duration. Every applicable option is requested: Intelligence, visualizations, watermark detection (Resemble Perth and Google SynthID, `detect_watermark`), C2PA validation, reverse image search (images), audio source tracing and the out-of-distribution detector (audio), and Signal fraud classification. Plan-gated add-ons rejected with HTTP 402/403/422 are dropped one at a time and listed in `job.json`; on this account Signal is refused, Detect Agents are unavailable and the Identity API has no enrolled identities. After detection, eight Detect Intelligence questions (the seven MIC questions plus watermark/label evidence) are asked through `/detects/{uuid}/intelligence` and stored in `questions.en.json`. A finished job whose options predate newly available ones is superseded by a new submission; the old job and payload stay as `job.superseded-NN.json` and `latest.superseded-NN.json`. No local score thresholds or Intelligence-based verdict escalation are used. Files over 150 MB are recorded as errors; secure-token uploads are not implemented yet. Text, PDF and other unsupported formats get a Latvian inconclusive report and are not uploaded. Documents are not silently treated as media or AI-generated text.

Supported extensions: JPG/JPEG, PNG, GIF, WEBP; MP4, MOV, AVI, MKV, WEBM, 3GP/3GPP; WAV, MP3, M4A, OGG, AAC, FLAC, AMR. Resemble may reject an individual codec. Hidden files and symlinks are skipped. The output folder is excluded from recursive intake.

## Evidence files

`manifest.json` maps original relative filenames to stable directories keyed by path and SHA-256. Each contains:

- `source.*`: unchanged source bytes, with SHA-256 and original path in `metadata.json`.
- `http/NNNN.request.json`: request method, endpoint and multipart fields, without credentials. Source file bytes are preserved separately; multipart transport boundaries are not captured.
- `http/NNNN.response.txt`: complete response body for **every** HTTP response, including errors and polling states. Valid successful JSON bodies are also saved verbatim as `.response.json`.
- `http/NNNN.http.json`: HTTP status; `.error.json` records transport failures.
- `job.json`: persisted detection UUID and options, for resuming without another upload.
- `latest.json`: parsed most recent detection response; raw history is never replaced by this convenience file.
- `analysis.en.json`: English interpretation, modality labels, evidence JSON pointers, frame timestamps, source tracing, Intelligence, provenance and coverage.
- `visualizations/`: decoded embedded heatmaps/images/video and a pointer/checksum index. Remote visualization URLs are recorded but not downloaded automatically.
- `questions.en.json`: provider answers to the eight English questions; hypotheses, not verified facts.
- `reverse-search.json`: reverse-image-search hits with the article URL resolved behind the provider redirect (resolved during live runs, cached for offline regeneration).
- `conclusion.lv.txt`: optional reviewed Latvian prose written by the agent; replaces the automatic text in the report.
- `report.lv.json` and `report.lv.pdf`: Latvian narrative and seven requested questions (earlier PDF layout).
- `../reports/<file>.lv.md` and `../atzinums.lv.md`: the delivered Markdown, regenerated by every run.

API authorization is never logged. Any reflected API key is redacted from a response body; otherwise raw bytes are preserved. Provider signed URLs remain in payloads, so treat the results directory as private evidence. `.env`, source data and results are excluded from Git and Docker contexts.

Completed jobs are reused; processing jobs resume by UUID. A submission whose outcome is unknown is not repeated automatically. Check its saved response/account before deliberately choosing a new output directory. The CLI finishes other files after an API failure and returns nonzero for errors or unsupported artifacts. Offline mode with no cached payload produces an inconclusive report and nonzero exit.

## Interpretation

Use categorical provider labels, preserving each modality separately. A positive detector label supports possible synthetic content; a negative label does not prove authenticity. Missing and unknown labels remain inconclusive. Timestamp findings identify sampled frames, not continuous forged intervals. Compare reported coverage with local duration before claiming whole-file analysis. Absent C2PA credentials do not indicate forgery. Embedded metadata may be edited; filesystem dates are not capture dates.

The seven Latvian questions are addressed, with explicit unknowns for exact technology, prompt, sources and creation circumstances. Audio source tracing is a provider hypothesis. Intelligence descriptions, especially identities, historical context and purported fact-checks, are not independently established facts. The initial automatic PDF is a technical report, not an invented signed expert opinion.

## Tooling and delivery

Project-local skills live in `.agents/skills/`: `forgery-audit` (end-to-end flow), `resemble-payload-analysis` (API and payload handling) and `resemble-forgery-report` (Latvian wording rules). The deliverable is one Markdown report per artifact plus the cover: material table, checks-and-results table with Resemble's scores, and a half-page Latvian conclusion covering the seven MIC questions in continuous flow. No images, question-and-answer layout, links or annex. Raw evidence remains preserved separately. The PDF renderer still uses the earlier layout.

The `src/` package uses uv with a committed lockfile. Quality, tests and Docker/GHCR workflows follow the nearby ABM project's structure, adapted to this CLI and GitHub-hosted runners. ABM has no Makefile; this project adds one. PRs build without publishing; main publishes `main` and a SHA tag; stable release tags also publish `latest`. CI uses mocked API responses and never submits evidence. No GitHub repository or deployed environment has been created by this setup.

```bash
docker build -t forgery-audit .
docker run --rm --env-file .env -v "$PWD/data:/data:ro" -v "$PWD/results:/results" forgery-audit
```

## Resemble contracts

Verified against official documentation on 2026-09-09:

- [Create detection](https://docs.resemble.ai/api-reference/deepfake-detection/create-detection)
- [Get detection](https://docs.resemble.ai/api-reference/deepfake-detection/get-detection)
- [Intake limits and options](https://docs.resemble.ai/detect/create)
- [Secure uploads, for future large-file support](https://docs.resemble.ai/api-reference/secure-uploads/create-secure-upload)

Real sample payloads are preserved locally in `results/payload-probe/`; current reports and subsequent full-duration jobs are in `results/audit/`.
