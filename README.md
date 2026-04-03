# SAT Math Score Tool

This project provides a lightweight web application for entering student responses to SAT Math practice tests and instantly generating a detailed score report. The tool highlights correct and incorrect answers and aggregates performance by College Board skill categories.

## Features

- ✅ Start by selecting the test and entering the student's first and last name, then record answers using a multiple-choice or numeric-entry web form
- 🎯 Handle grid-in questions with alternate numeric answers (e.g. `5;5.0`)
- 📊 Instant score report with estimated scaled SAT Math score
- 🗂️ Category breakdown that mirrors the categories defined in your spreadsheet-backed category database
- 📝 Choose from any CSV answer keys stored in the `data/` directory
- 🔁 Quickly rescore another student without reloading the page
- 📄 Automatically archive each score report as a CSV file for future reference

## Project structure

```
.
├── app.py                # Flask application with scoring logic
├── data/
│   ├── category_db/
│   │   └── SAT_Question_Categories.csv  # Lookup table that maps category_type_id values to labels
│   └── *.csv             # One or more answer keys with category metadata
├── static/
│   └── styles.css        # Styling for the UI
└── templates/
    ├── base.html         # Shared layout
    ├── index.html        # Test and student selector
    ├── entry.html        # Answer entry form
    └── results.html      # Score report view
```

## Getting started

1. **Install dependencies**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Run the development server**

   ```bash
   flask --app app run --debug
   ```

3. **Open the app**

Visit <http://127.0.0.1:5000> in your browser.

## Database-backed tests

When PostgreSQL is enabled, the app does two things:

1. **Exposes database-backed tests.** Each combination of entries from the
   `tests`, `sections`, and `modules` tables produces a selectable exam—for
   example, `Digital Paper Test 1 Math Module 1` and `Digital Paper Test 1 Math
   Module 2`. Questions are pulled from the `questions` table and categories are
   resolved via `question_types`, so any updates you make in the database are
   reflected immediately in the UI alongside the CSV-based tests that live in
   `data/`.
2. **Archives submissions.** Every score report is stored in a `submissions`
   table for external analytics. Each row stores the submitted answers, the
   computed results payload, the category breakdown, and summary scoring fields.

The default connection details are:

```
host=localhost
port=5432
dbname=SAT_Database
user=postgres
password=3rdtrail
```

Local configuration defaults:

- `DB_HOST=localhost`
- `DB_PORT=5432`
- `DB_NAME=WebApp`
- `DB_USER=postgres`
- `DB_PASSWORD=3rdtrail`
- `DB_ENABLED=1`
- `DB_SSLMODE=prefer`

The app also supports a single `DATABASE_URL` environment variable. If `DATABASE_URL`
is set, it takes precedence over the individual `DB_*` variables. This is the
recommended configuration for Render Postgres.

Submission writes are currently disabled in code, so this version reads from the
database but does not insert rows into `submissions`.

## Deploying to Render

This branch includes a [render.yaml](/Users/majidhasan/Documents/WebApp/render.yaml)
blueprint that provisions:

- a Python web service named `webapp`
- a Render Postgres database named `WebApp`

The web service receives `DATABASE_URL` from the Render Postgres
`connectionString` and sets `DB_SSLMODE=require`.

To deploy:

1. Push the `webapp_db` branch to GitHub.
2. In Render, create a new Blueprint service from the repository.
3. Select the branch that contains this `render.yaml`.
4. Render will create both the web service and the `WebApp` Postgres database.

If you already created the database manually in Render, you can skip the
blueprint database creation and instead set `DATABASE_URL` on the web service to
the database's internal connection string.

## Customising the answer keys

Place one or more CSV files inside the `data/` directory—each file represents a different test. The filename is displayed in the UI (underscores are converted to spaces), making it easy to switch between practice sets. Every CSV must include the following columns:

- `question_number` – The numeric identifier of the question (e.g. 1, 2, …)
- `correct_answer` – The correct answer choice (A–D) or numeric value for grid-in questions. For grid-ins with multiple acceptable values, separate each option with a semicolon (e.g. `12;12.0`).
- `category_type_id` – A numeric identifier that maps to the `index` column inside `data/category_db/SAT_Question_Categories.csv`. The score report will display the human-readable category name from that lookup table.

Update `data/category_db/SAT_Question_Categories.csv` whenever you add or modify category labels so that each `category_type_id` continues to resolve to the desired text in the score report.

Additional columns are ignored, so you can keep extra metadata in the spreadsheet without breaking the importer. Add, remove, or rename files at any time; the app will automatically list every CSV present when you reload the page.

## How scoring works

- Correct answers count toward the total number of correctly answered questions.
- Accuracy is calculated as the percentage of correct responses.
- The SAT Math scaled score is estimated using a simple linear mapping between the raw score and the 200–800 scale. Replace the `build_score_report` helper in `app.py` if you have a more precise conversion chart.

## Future improvements

- CSV upload for importing student responses in bulk
- Authentication for instructors

Contributions and feedback are welcome!
