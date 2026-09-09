# Forgery audit

Folder-based deepfake analysis with Resemble AI; deliverable is concise Latvian Markdown per artifact.

- Any request to audit, check or write an opinion about media files: follow `.agents/skills/forgery-audit/SKILL.md`
  end to end (`make analyze` → review → `conclusion.lv.txt` → `make reports`) and hand over `results/<case>/reports/`.
- Payload questions or API changes: `.agents/skills/resemble-payload-analysis/SKILL.md`.
- Report wording rules: `.agents/skills/resemble-forgery-report/SKILL.md`.
- Code lives in `src/forgery_audit`; `make check` runs ruff, ty and pytest. Tests never call the network.
- Always use `make` targets; never run bare `uv run`/`uv sync` here. The shell exports `UV_PROJECT_ENVIRONMENT`
  for another project and a bare `uv` command rebuilds that project's venv. Ad-hoc Python: `.venv/bin/python`.
- Deliverables per artifact: `results/<case>/reports/<file>.lv.md` and `.lv.pdf` (same content), plus the cover
  `atzinums.lv.md`/`.pdf`.
- `.env` holds `RESEMBLE_AI_API_KEY`; never print it. `data/` and `results/` are private evidence, not for Git.
