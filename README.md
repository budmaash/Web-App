# SAT Math Score Tool

This project provides a lightweight web application for entering student responses to SAT Math practice tests and instantly generating a detailed score report. The tool highlights correct and incorrect answers and aggregates performance by College Board skill categories.

## Features

- ✅ Start by selecting the test and student, then enter answers using a multiple-choice or numeric-entry web form
- 🎯 Handle grid-in questions with alternate numeric answers (e.g. `5;5.0`)
- 📊 Instant score report with estimated scaled SAT Math score
- 🗂️ Category breakdown that mirrors the categories defined in your spreadsheet
- 📝 Choose from any CSV answer keys stored in the `data/` directory
- 🔁 Quickly rescore another student without reloading the page
- 📄 Automatically archive each score report as a CSV file for future reference

## Project structure

```
.
├── app.py                # Flask application with scoring logic
├── data/
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

## Customising the answer keys

Place one or more CSV files inside the `data/` directory—each file represents a different test. The filename is displayed in the UI (underscores are converted to spaces), making it easy to switch between practice sets. Every CSV must include the following columns:

- `question_number` – The numeric identifier of the question (e.g. 1, 2, …)
- `correct_answer` – The correct answer choice (A–D) or numeric value for grid-in questions. For grid-ins with multiple acceptable values, separate each option with a semicolon (e.g. `12;12.0`).
- `category` – The category label to use in the score report

Additional columns are ignored, so you can keep extra metadata in the spreadsheet without breaking the importer. Add, remove, or rename files at any time; the app will automatically list every CSV present when you reload the page.

## How scoring works

- Correct answers count toward the total number of correctly answered questions.
- Accuracy is calculated as the percentage of correct responses.
- The SAT Math scaled score is estimated using a simple linear mapping between the raw score and the 200–800 scale. Replace the `build_score_report` helper in `app.py` if you have a more precise conversion chart.

## Future improvements

- CSV upload for importing student responses in bulk
- Authentication for instructors

Contributions and feedback are welcome!
