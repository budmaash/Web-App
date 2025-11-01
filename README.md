# SAT Math Score Tool

This project provides a lightweight web application for entering student responses to SAT Math practice tests and instantly generating a detailed score report. The tool highlights correct and incorrect answers and aggregates performance by College Board skill categories.

## Features

- ✅ Enter answers for each question using a simple web form
- 📊 Instant score report with estimated scaled SAT Math score
- 🗂️ Category breakdown that mirrors the categories defined in your spreadsheet
- 🔁 Quickly rescore another student without reloading the page

## Project structure

```
.
├── app.py                # Flask application with scoring logic
├── data/
│   └── questions.csv     # Answer key with category metadata
├── static/
│   └── styles.css        # Styling for the UI
└── templates/
    ├── base.html         # Shared layout
    ├── index.html        # Answer entry form
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

## Customising the answer key

Replace the sample `data/questions.csv` file with your own spreadsheet exported to CSV format. The file must include the following columns:

- `question_number` – The numeric identifier of the question (e.g. 1, 2, …)
- `correct_answer` – The correct answer choice (A–E)
- `category` – The category label to use in the score report

Additional columns are ignored, so you can keep extra metadata in the spreadsheet without breaking the importer.

## How scoring works

- Correct answers count toward the total number of correctly answered questions.
- Accuracy is calculated as the percentage of correct responses.
- The SAT Math scaled score is estimated using a simple linear mapping between the raw score and the 200–800 scale. Replace the `build_score_report` helper in `app.py` if you have a more precise conversion chart.

## Future improvements

- Support for multiple answer keys/tests and student history
- CSV upload for importing student responses in bulk
- Authentication for instructors

Contributions and feedback are welcome!
