# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run dev server
flask --app app run --debug

# Run production server
gunicorn app:app
```

No test suite exists currently.

## Architecture

Single-file Flask app (`app.py`) with Jinja2 templates. All scoring logic, data loading, and route handling live in `app.py`.

### Request flow
1. `GET /` — select a test (tests come from PostgreSQL or `data/*.csv`)
2. `GET /entry?test_id=<id>` — answer entry form
3. `POST /results` — scores answers, persists submission to DB, renders report
4. `GET /ss_homepage` — static shell mirroring the Squarespace marketing site

### Data sources (dual-mode)
The app supports two test sources, controlled by `DB_ENABLED` (default: `1`):

- **PostgreSQL** — tests are discovered by joining `tests`, `sections`, `modules`, and `questions` tables. Category names come from `question_types`; video links from `QType_Vids`.
- **CSV fallback** — each `data/*.csv` file is one test module. Category names resolve via `data/category_db/SAT_Question_Categories.csv`.

Submission persistence is temporarily disabled in this version of the app. The app reads from PostgreSQL for test/question data, but it does not write rows to `submissions`.

Test identifiers: CSV tests use the filename stem; DB tests use `db_{test_id}_{section_id}_{module_id}`.

### Key classes
- `QuestionBank` — loads and in-memory caches questions per test; handles both CSV and DB sources
- `Question` (dataclass) — one question with correct answers, category, and optional video URL
- `TestDefinition` (dataclass) — metadata for a selectable test (source, path or DB metadata)

### Scoring
`build_score_report()` computes per-question correctness, category breakdown, and a linear SAT scale estimate: `200 + floor(accuracy * 600)`. Grid-in questions support multiple correct answers separated by `;` in CSVs.

Question explanation links are constructed from the test name via regex: `https://www.hasantutoring.com/math-test-{N}-module-{M}/v/question{N}`.

### Frontend / CSS
Templates extend `templates/base.html`. Page-specific styles are embedded as `<style>` blocks inside each template rather than in external files. `static/ss_homepage/` contains copied Squarespace assets (CSS/JS) used to mirror the marketing site header/footer — do not edit these files.

### Environment variables
| Variable | Default |
|---|---|
| `DATABASE_URL` | unset; when present, overrides individual DB connection fields |
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `DB_USER` | `postgres` |
| `DB_PASSWORD` | `3rdtrail` |
| `DB_NAME` | `WebApp` |
| `DB_ENABLED` | `1` (set to `0` to disable all DB features) |
| `DB_SSLMODE` | `prefer` locally; set to `require` on Render |
