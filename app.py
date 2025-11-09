from __future__ import annotations

import csv
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psycopg2
from flask import Flask, abort, redirect, render_template, request, url_for


DATA_DIR = Path("data")
CATEGORY_DB_DIR = DATA_DIR / "category_db"
RESULTS_DIR = Path("results")
DB_CONFIG = {
    "host": os.environ.get("SAT_DB_HOST", "localhost"),
    "port": int(os.environ.get("SAT_DB_PORT", "5432")),
    "user": os.environ.get("SAT_DB_USER", "postgres"),
    "password": os.environ.get("SAT_DB_PASSWORD", "3rdtrail"),
    "dbname": os.environ.get("SAT_DB_NAME", "SAT_Database"),
}
DB_ENABLED = os.environ.get("SAT_DB_ENABLED", "1") not in {"0", "false", "False"}


@dataclass
class Question:
    number: int
    correct_answers: List[str]
    category: str
    expects_numeric_response: bool

    @property
    def display_correct_answer(self) -> str:
        if not self.correct_answers:
            return ""
        if len(self.correct_answers) == 1:
            return self.correct_answers[0]
        return " or ".join(self.correct_answers)


app = Flask(__name__)


@dataclass(frozen=True)
class DatabaseTestMetadata:
    test_id: int
    section_id: int
    module_id: int


@dataclass(frozen=True)
class TestDefinition:
    identifier: str
    name: str
    source: str
    path: Optional[Path] = None
    db_metadata: Optional[DatabaseTestMetadata] = None


class QuestionBank:
    """Utility responsible for loading and caching questions for each test."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._questions_cache: Dict[str, List[Question]] = {}
        self._category_lookup = self._load_category_lookup()

    def available_tests(self) -> List[TestDefinition]:
        tests: List[TestDefinition] = []
        tests.extend(self._available_csv_tests())
        tests.extend(self._available_database_tests())
        return tests

    def _available_csv_tests(self) -> List[TestDefinition]:
        tests: List[TestDefinition] = []

        if not self._data_dir.exists():
            return tests

        for csv_path in sorted(self._data_dir.glob("*.csv")):
            identifier = csv_path.stem
            name = csv_path.stem.replace("_", " ").title()
            tests.append(
                TestDefinition(
                    identifier=identifier,
                    name=name,
                    source="csv",
                    path=csv_path,
                )
            )

        return tests

    def _available_database_tests(self) -> List[TestDefinition]:
        tests: List[TestDefinition] = []

        if not DB_ENABLED:
            return tests

        try:
            with psycopg2.connect(**DB_CONFIG) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT DISTINCT
                            q.test_id,
                            t.name,
                            q.section_id,
                            s.name,
                            q.module_id,
                            m.name
                        FROM questions q
                        JOIN tests t ON q.test_id = t.id
                        JOIN sections s ON q.section_id = s.id
                        JOIN modules m ON q.module_id = m.id
                        ORDER BY t.name, s.name, m.name, q.test_id, q.section_id, q.module_id
                        """
                    )
                    for row in cursor.fetchall():
                        test_id, test_name, section_id, section_name, module_id, module_name = row
                        identifier = f"db_{test_id}_{section_id}_{module_id}"
                        display_name = f"{test_name} {section_name} {module_name}"
                        tests.append(
                            TestDefinition(
                                identifier=identifier,
                                name=display_name,
                                source="database",
                                db_metadata=DatabaseTestMetadata(
                                    test_id=test_id,
                                    section_id=section_id,
                                    module_id=module_id,
                                ),
                            )
                        )
        except psycopg2.Error as exc:
            app.logger.warning("Failed to load database tests: %s", exc)

        return tests

    def get_test(self, test_id: str) -> TestDefinition:
        for test in self.available_tests():
            if test.identifier == test_id:
                return test
        raise ValueError(f"Unknown test identifier: {test_id}")

    def questions_for(self, test_id: str) -> List[Question]:
        if test_id in self._questions_cache:
            return self._questions_cache[test_id]

        test = self.get_test(test_id)
        if test.source == "csv":
            if not test.path:
                raise ValueError(f"Test '{test.identifier}' is missing its CSV path.")
            questions = self._load_csv(test.path)
        elif test.source == "database":
            if not test.db_metadata:
                raise ValueError(f"Test '{test.identifier}' is missing database metadata.")
            questions = self._load_database_questions(test.db_metadata)
        else:
            raise ValueError(f"Unknown test source '{test.source}'.")
        self._questions_cache[test_id] = questions
        return questions

    def _load_csv(self, csv_path: Path) -> List[Question]:
        if not csv_path.exists():
            raise FileNotFoundError(
                "Question data file not found. Expected at '{}'".format(csv_path)
            )

        questions: List[Question] = []
        with csv_path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                try:
                    number = int(row["question_number"].strip())
                except (KeyError, ValueError) as exc:
                    raise ValueError(
                        "Each question must include a numeric 'question_number'."
                    ) from exc

                raw_answer = row.get("correct_answer", "").strip()
                answers, expects_numeric_response = _normalize_answers(raw_answer)
                if not answers:
                    raise ValueError(
                        f"Question {number} is missing a 'correct_answer' entry."
                    )

                category_id_raw = row.get("category_type_id", "").strip()
                if not category_id_raw:
                    raise ValueError(
                        f"Question {number} is missing a 'category_type_id' entry."
                    )

                category_key = _normalize_category_key(category_id_raw)
                category = self._category_lookup.get(category_key)
                if category is None:
                    raise ValueError(
                        "Question {} references an unknown category_type_id '{}'.".format(
                            number, category_id_raw
                        )
                    )

                questions.append(
                    Question(
                        number=number,
                        correct_answers=answers,
                        category=category,
                        expects_numeric_response=expects_numeric_response,
                    )
                )

        questions.sort(key=lambda q: q.number)
        return questions

    def _load_database_questions(self, metadata: DatabaseTestMetadata) -> List[Question]:
        if not DB_ENABLED:
            raise RuntimeError("Database-backed tests are disabled via configuration.")

        query = """
            SELECT
                q.test_question_number,
                q.correct_answer,
                qt.name AS category_name
            FROM questions q
            JOIN question_types qt ON q.question_type_id = qt.id
            WHERE q.test_id = %s AND q.section_id = %s AND q.module_id = %s
            ORDER BY q.test_question_number
        """

        questions: List[Question] = []
        try:
            with psycopg2.connect(**DB_CONFIG) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        query,
                        (
                            metadata.test_id,
                            metadata.section_id,
                            metadata.module_id,
                        ),
                    )
                    rows = cursor.fetchall()
        except psycopg2.Error as exc:
            raise RuntimeError(f"Failed to load questions from database: {exc}") from exc

        if not rows:
            raise ValueError("No questions were found for the selected database test.")

        for test_question_number, correct_answer, category_name in rows:
            if test_question_number is None:
                raise ValueError("Each database question must include a test_question_number.")

            answers, expects_numeric_response = _normalize_answers((correct_answer or "").strip())
            if not answers:
                raise ValueError(
                    f"Question {test_question_number} is missing a 'correct_answer' entry."
                )

            if not category_name:
                raise ValueError(
                    f"Question {test_question_number} is missing a linked question type."
                )

            questions.append(
                Question(
                    number=int(test_question_number),
                    correct_answers=answers,
                    category=category_name,
                    expects_numeric_response=expects_numeric_response,
                )
            )

        questions.sort(key=lambda q: q.number)
        return questions

    def _load_category_lookup(self) -> Dict[str, str]:
        category_file = CATEGORY_DB_DIR / "SAT_Question_Categories.csv"

        if not category_file.exists():
            raise FileNotFoundError(
                "Category database not found. Expected at '{}'".format(category_file)
            )

        lookup: Dict[str, str] = {}
        with category_file.open(newline="") as csv_file:
            reader = csv.reader(csv_file)
            for row in reader:
                if not row:
                    continue

                raw_key = row[0].strip()
                if not raw_key:
                    continue

                if raw_key.lower() == "index":
                    continue

                if len(row) < 2:
                    raise ValueError(
                        "Category mapping rows must include at least two columns."
                    )

                category_name = row[1].strip()
                if not category_name:
                    raise ValueError(
                        "Category '{}' is missing a name in the mapping file.".format(
                            raw_key
                        )
                    )

                lookup[_normalize_category_key(raw_key)] = category_name

        if not lookup:
            raise ValueError("No categories were loaded from the mapping file.")

        return lookup


def build_score_report(student_answers: Dict[int, str], questions: List[Question]):
    per_question = []
    category_totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    correct_count = 0

    for question in questions:
        student_answer = student_answers.get(question.number, "")
        is_correct = student_answer in question.correct_answers

        category_totals[question.category]["total"] += 1
        if is_correct:
            correct_count += 1
            category_totals[question.category]["correct"] += 1

        per_question.append(
            {
                "number": question.number,
                "student_answer": student_answer or "—",
                "raw_student_answer": student_answer,
                "correct_answer": question.display_correct_answer,
                "is_correct": is_correct,
                "category": question.category,
            }
        )

    # SAT math scores range from 200-800. We approximate the scale linearly based on
    # the percentage of questions answered correctly.
    total_questions = len(questions)
    if total_questions:
        accuracy = correct_count / total_questions
        scaled_score = 200 + math.floor(accuracy * 600)
    else:
        accuracy = 0
        scaled_score = 200

    category_breakdown = []
    for category, totals in sorted(category_totals.items()):
        total = totals["total"]
        correct = totals["correct"]
        accuracy_pct = (correct / total * 100) if total else 0
        category_breakdown.append(
            {
                "category": category,
                "correct": correct,
                "total": total,
                "accuracy_pct": accuracy_pct,
            }
        )

    return {
        "per_question": per_question,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "accuracy_pct": accuracy * 100 if total_questions else 0,
        "scaled_score": scaled_score,
        "category_breakdown": category_breakdown,
    }


def _normalize_answers(raw_answer: str) -> Tuple[List[str], bool]:
    tokens = [token.strip() for token in raw_answer.split(";")]
    tokens = [token for token in tokens if token]

    if not tokens:
        return [], False

    expects_numeric = all(_is_numeric_token(token) for token in tokens)

    if expects_numeric:
        normalized = [_normalize_numeric_token(token) for token in tokens]
    else:
        normalized = [token.upper() for token in tokens]

    deduped: List[str] = []
    seen = set()
    for answer in normalized:
        if answer not in seen:
            seen.add(answer)
            deduped.append(answer)

    return deduped, expects_numeric


def _normalize_numeric_token(value: str) -> str:
    return value.strip()


def _is_numeric_token(value: str) -> bool:
    if not value:
        return False

    trimmed = value.strip()
    if not trimmed:
        return False

    # Allow negative values and decimal points when determining if the answer
    # represents a numeric response. Digits remain untouched later, so we don't
    # coerce the value into a number here.
    if trimmed.count("-") > 1:
        return False
    if trimmed.startswith("-"):
        trimmed = trimmed[1:]

    if trimmed.count(".") > 1:
        return False
    trimmed = trimmed.replace(".", "")

    return trimmed.isdigit()


def _normalize_category_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return cleaned

    try:
        return str(int(cleaned))
    except ValueError:
        return cleaned


question_bank = QuestionBank(DATA_DIR)


def _sanitize_filename_segment(value: str) -> str:
    if not value:
        return "student"

    allowed = [ch for ch in value if ch.isalnum() or ch in ("-", "_")]
    sanitized = "".join(allowed).strip("-_")
    return sanitized or "student"


def _save_score_report(report, student_name: str, test: TestDefinition) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_student = _sanitize_filename_segment(student_name)
    filename = f"{test.identifier}_{safe_student}_{timestamp}.csv"
    destination = RESULTS_DIR / filename

    with destination.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["question_number", "student_answer", "category", "status"])
        for row in report["per_question"]:
            if row["is_correct"]:
                status = "Correct"
            elif not row["raw_student_answer"]:
                status = "Omitted"
            else:
                status = "Incorrect"

            writer.writerow(
                [
                    row["number"],
                    row["raw_student_answer"],
                    row["category"],
                    status,
                ]
            )

    try:
        return str(destination.relative_to(Path.cwd()))
    except ValueError:
        return str(destination)


def _persist_submission(
    *,
    test: TestDefinition,
    student_name: str,
    answers: Dict[int, str],
    report,
) -> None:
    if not DB_ENABLED:
        return

    payload_answers = json.dumps(answers)
    payload_report = json.dumps(report)
    payload_categories = json.dumps(report.get("category_breakdown", []))
    created_at = datetime.utcnow()

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO submissions (
                        test_code,
                        student_name,
                        answers_json,
                        results_json,
                        category_json,
                        raw_correct,
                        raw_total,
                        scaled_score,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        test.identifier,
                        student_name or "Student",
                        payload_answers,
                        payload_report,
                        payload_categories,
                        report.get("correct_count", 0),
                        report.get("total_questions", 0),
                        report.get("scaled_score", 200),
                        created_at,
                    ),
                )
    except psycopg2.Error as exc:
        app.logger.warning("Failed to persist submission to Postgres: %s", exc)


@app.route("/", methods=["GET", "POST"])
def index():
    tests = question_bank.available_tests()
    selected_test_id = tests[0].identifier if tests else None

    if request.method == "POST":
        if not tests:
            abort(400, description="No test files are available to score.")

        test_id = request.form.get("test_id", "").strip() or selected_test_id
        student_name = request.form.get("student_name", "").strip()

        try:
            question_bank.get_test(test_id)
            selected_test_id = test_id
        except ValueError:
            # Fall back to the default test if an invalid identifier is submitted.
            selected_test_id = tests[0].identifier

        return redirect(
            url_for("entry", test_id=selected_test_id, student_name=student_name)
        )

    if request.method == "GET" and tests:
        requested_test = request.args.get("test_id", "").strip()
        if requested_test:
            try:
                question_bank.get_test(requested_test)
                selected_test_id = requested_test
            except ValueError:
                pass

    return render_template(
        "index.html", tests=tests, selected_test_id=selected_test_id
    )


@app.get("/entry")
def entry():
    test_id = request.args.get("test_id", "").strip()
    student_name = request.args.get("student_name", "").strip()

    if not test_id:
        abort(400, description="A test must be selected before entering answers.")

    try:
        test = question_bank.get_test(test_id)
    except ValueError as exc:
        abort(400, description=str(exc))

    questions = question_bank.questions_for(test_id)

    return render_template(
        "entry.html",
        test=test,
        student_name=student_name,
        questions=questions,
    )


@app.post("/results")
def results():
    test_id = request.form.get("test_id", "").strip()
    if not test_id:
        abort(400, description="A test must be selected to score responses.")

    try:
        test = question_bank.get_test(test_id)
    except ValueError as exc:
        abort(400, description=str(exc))

    questions = question_bank.questions_for(test_id)
    student_name = request.form.get("student_name", "").strip() or "Student"

    answers: Dict[int, str] = {}
    for question in questions:
        answer = request.form.get(f"q_{question.number}", "").strip()
        if not question.expects_numeric_response:
            answer = answer.upper()
        answers[question.number] = answer

    report = build_score_report(answers, questions)

    saved_report_path = _save_score_report(report, student_name, test)
    _persist_submission(test=test, student_name=student_name, answers=answers, report=report)

    return render_template(
        "results.html",
        student_name=student_name,
        test_id=test.identifier,
        test_name=test.name,
        report=report,
        report_csv_path=saved_report_path,
    )


if __name__ == "__main__":
    app.run(debug=True)
