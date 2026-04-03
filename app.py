from __future__ import annotations

import csv
import json
import math
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlparse

import psycopg2
from flask import Flask, abort, redirect, render_template, request, url_for


DATA_DIR = Path("data")
CATEGORY_DB_DIR = DATA_DIR / "category_db"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_SSLMODE = os.environ.get("DB_SSLMODE", "prefer").strip()
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", "3rdtrail"),
    "dbname": os.environ.get("DB_NAME", "WebApp"),
}
DB_ENABLED = os.environ.get("DB_ENABLED", "1") not in {"0", "false", "False"}
SUBMISSION_PERSISTENCE_ENABLED = False
MULTIPLE_CHOICE_CHOICES = ("A", "B", "C", "D")


def _database_url_has_sslmode(database_url: str) -> bool:
    parsed = urlparse(database_url)
    return "sslmode" in dict(parse_qsl(parsed.query, keep_blank_values=True))


def connect_to_database():
    if DATABASE_URL:
        if _database_url_has_sslmode(DATABASE_URL):
            return psycopg2.connect(DATABASE_URL)
        return psycopg2.connect(DATABASE_URL, sslmode=DB_SSLMODE)

    return psycopg2.connect(**DB_CONFIG, sslmode=DB_SSLMODE)


@dataclass
class Question:
    number: int
    correct_answers: List[str]
    category: str
    expects_numeric_response: bool
    db_question_id: Optional[int] = None
    category_video_url: Optional[str] = None

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


_TEST_NUMBER_PATTERN = re.compile(r"(?:test|t)\s*[_\-\s]?(\d+)", re.IGNORECASE)
_MODULE_NUMBER_PATTERN = re.compile(r"(?:module|m)\s*[_\-\s]?(\d+)", re.IGNORECASE)
def _extract_test_module_numbers(test: TestDefinition) -> Tuple[Optional[str], Optional[str]]:
    test_number: Optional[str] = None
    module_number: Optional[str] = None
    for source in (test.name, test.identifier):
        if not source:
            continue
        if test_number is None:
            match = _TEST_NUMBER_PATTERN.search(source)
            if match:
                test_number = match.group(1)
        if module_number is None:
            match = _MODULE_NUMBER_PATTERN.search(source)
            if match:
                module_number = match.group(1)
    return test_number, module_number


def _build_question_link_prefix(test: TestDefinition) -> Optional[str]:
    test_number, module_number = _extract_test_module_numbers(test)
    if not test_number or not module_number:
        return None
    return f"https://www.hasantutoring.com/math-test-{test_number}-module-{module_number}/v/question"


class QuestionBank:
    """Utility responsible for loading and caching questions for each test."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._questions_cache: Dict[str, List[Question]] = {}
        self._category_lookup = self._load_category_lookup()
        self._question_type_video_lookup = self._load_question_type_video_lookup()

    def available_tests(self) -> List[TestDefinition]:
        return self._available_database_tests()

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
            with connect_to_database() as conn:
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
                        category_video_url=self._question_type_video_lookup.get(category_key),
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
                qt.name AS category_name,
                q.id AS question_id,
                q.question_type_id
            FROM questions q
            JOIN question_types qt ON q.question_type_id = qt.id
            WHERE q.test_id = %s AND q.section_id = %s AND q.module_id = %s
            ORDER BY q.test_question_number
        """

        questions: List[Question] = []
        try:
            with connect_to_database() as conn:
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

        for test_question_number, correct_answer, category_name, question_id, question_type_id in rows:
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
                    db_question_id=question_id,
                    category_video_url=self._question_type_video_lookup.get(
                        _normalize_category_key(str(question_type_id))
                    ),
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

    def _load_question_type_video_lookup(self) -> Dict[str, str]:
        if not DB_ENABLED:
            return {}

        lookup: Dict[str, str] = {}
        try:
            with connect_to_database() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT question_types_id, video_link
                        FROM "QType_Vids"
                        WHERE video_link IS NOT NULL
                        """
                    )
                    for question_type_id, video_link in cursor.fetchall():
                        if question_type_id is None or not video_link:
                            continue
                        normalized_key = _normalize_category_key(str(question_type_id))
                        cleaned_path = str(video_link).strip().lstrip("/")
                        if cleaned_path:
                            lookup[normalized_key] = f"https://www.hasantutoring.com/{cleaned_path}"
        except psycopg2.Error as exc:
            app.logger.warning("Failed to load question type video links: %s", exc)

        return lookup


def build_score_report(student_answers: Dict[int, str], questions: List[Question]):
    per_question = []
    category_totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    category_video_urls: Dict[str, str] = {}
    missed_totals: Dict[str, int] = defaultdict(int)
    correct_count = 0

    for question in questions:
        student_answer = student_answers.get(question.number, "")
        is_correct = student_answer in question.correct_answers

        category_totals[question.category]["total"] += 1
        if question.category_video_url and question.category not in category_video_urls:
            category_video_urls[question.category] = question.category_video_url
        if is_correct:
            correct_count += 1
            category_totals[question.category]["correct"] += 1
        else:
            missed_totals[question.category] += 1

        per_question.append(
            {
                "number": question.number,
                "student_answer": student_answer or "—",
                "raw_student_answer": student_answer,
                "correct_answer": question.display_correct_answer,
                "is_correct": is_correct,
                "category": question.category,
                "category_video_url": question.category_video_url,
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
                "category_video_url": category_video_urls.get(category),
            }
        )

    total_missed = total_questions - correct_count
    missed_question_breakdown = []
    if total_missed:
        for category, missed_count in sorted(
            missed_totals.items(),
            key=lambda item: (-item[1], item[0].lower()),
        ):
            missed_question_breakdown.append(
                {
                    "category": category,
                    "missed": missed_count,
                    "share_pct": (missed_count / total_missed) * 100,
                }
            )

    return {
        "per_question": per_question,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "accuracy_pct": accuracy * 100 if total_questions else 0,
        "scaled_score": scaled_score,
        "category_breakdown": category_breakdown,
        "missed_question_breakdown": missed_question_breakdown,
        "missed_count": total_missed,
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
    if value is None:
        return False

    trimmed = str(value).strip()
    if not trimmed:
        return False

    signless = trimmed.lstrip("+-").strip()
    if not signless:
        return False

    if " " in signless:
        parts = [part for part in signless.split() if part]
        if len(parts) == 2 and _is_decimal_string(parts[0]) and _is_fraction_string(parts[1]):
            return True
        return False

    if "/" in signless:
        return _is_fraction_string(signless)

    return _is_decimal_string(signless)


def _is_decimal_string(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False

    try:
        Decimal(candidate)
    except (InvalidOperation, ValueError):
        return False

    return True


def _is_fraction_string(value: str) -> bool:
    parts = value.split("/")
    if len(parts) != 2:
        return False

    numerator, denominator = (part.strip() for part in parts)
    if not numerator or not denominator:
        return False

    if not _is_decimal_string(numerator):
        return False

    if not _is_decimal_string(denominator):
        return False

    try:
        return Decimal(denominator) != 0
    except (InvalidOperation, ValueError):
        return False


def _normalize_category_key(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return cleaned

    try:
        return str(int(cleaned))
    except ValueError:
        return cleaned


question_bank = QuestionBank(DATA_DIR)

def _persist_submission(
    *,
    test: TestDefinition,
    student_name: str,
    answers: Dict[int, str],
    report,
) -> None:
    if not DB_ENABLED or not SUBMISSION_PERSISTENCE_ENABLED:
        return

    payload_answers = json.dumps(answers)
    payload_report = json.dumps(report)
    payload_categories = json.dumps(report.get("category_breakdown", []))
    created_at = datetime.utcnow()

    try:
        with connect_to_database() as conn:
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

        try:
            question_bank.get_test(test_id)
            selected_test_id = test_id
        except ValueError:
            # Fall back to the default test if an invalid identifier is submitted.
            selected_test_id = tests[0].identifier

        return redirect(
            url_for(
                "entry",
                test_id=selected_test_id,
            )
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
        "index.html",
        tests=tests,
        selected_test_id=selected_test_id,
    )


@app.get("/entry")
def entry():
    test_id = request.args.get("test_id", "").strip()

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
        questions=questions,
        multiple_choice_choices=MULTIPLE_CHOICE_CHOICES,
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

    answers: Dict[int, str] = {}
    for question in questions:
        answer = request.form.get(f"q_{question.number}", "").strip()
        if not question.expects_numeric_response:
            answer = answer.upper()
        answers[question.number] = answer

    report = build_score_report(answers, questions)

    _persist_submission(test=test, student_name="Student", answers=answers, report=report)

    return render_template(
        "results.html",
        test_id=test.identifier,
        test_name=test.name,
        report=report,
        question_link_prefix=_build_question_link_prefix(test),
    )


@app.get("/ss_homepage")
def ss_homepage_shell():
    return render_template("ss_homepage_shell.html")


if __name__ == "__main__":
    app.run(debug=True)
@app.context_processor
def inject_globals():
    return {"current_year": datetime.utcnow().year}
