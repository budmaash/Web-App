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
├── results/              # Generated score report CSVs (created on demand)
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

## Database logging & dynamic tests (optional)

When a local PostgreSQL instance is running, the app now does two things:

1. **Exposes database-backed tests.** Each combination of entries from the
   `tests`, `sections`, and `modules` tables produces a selectable exam—for
   example, `Digital Paper Test 1 Math Module 1` and `Digital Paper Test 1 Math
   Module 2`. Questions are pulled from the `questions` table and categories are
   resolved via `question_types`, so any updates you make in the database are
   reflected immediately in the UI alongside the CSV-based tests that live in
   `data/`.
2. **Archives submissions.** Every score report is stored in a `submissions`
   table for external analytics, along with a `students` roster (deduped by
   first/last name) plus one row per question in the `responses` table tying the
   student's answer to the appropriate test/section/module metadata.

The default connection details are:

```
host=localhost
port=5432
dbname=SAT_Database
user=postgres
password=3rdtrail
```

Override any value by exporting `SAT_DB_HOST`, `SAT_DB_PORT`, `SAT_DB_NAME`,
`SAT_DB_USER`, `SAT_DB_PASSWORD`, or disable all database features with
`SAT_DB_ENABLED=0`.

Create the destination table before running the app:

```sql
CREATE TABLE IF NOT EXISTS submissions (
  id SERIAL PRIMARY KEY,
  test_code TEXT NOT NULL,
  student_name TEXT NOT NULL,
  answers_json JSONB NOT NULL,
  results_json JSONB NOT NULL,
  category_json JSONB NOT NULL,
  raw_correct INTEGER NOT NULL,
  raw_total INTEGER NOT NULL,
  scaled_score INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_submissions_test_code ON submissions (test_code);
```

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
