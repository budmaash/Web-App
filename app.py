from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from flask import Flask, abort, render_template, request


DATA_DIR = Path("data")


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
class TestDefinition:
    identifier: str
    name: str
    path: Path


class QuestionBank:
    """Utility responsible for loading and caching questions for each test."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._questions_cache: Dict[str, List[Question]] = {}

    def available_tests(self) -> List[TestDefinition]:
        tests: List[TestDefinition] = []

        if not self._data_dir.exists():
            return tests

        for csv_path in sorted(self._data_dir.glob("*.csv")):
            identifier = csv_path.stem
            name = csv_path.stem.replace("_", " ").title()
            tests.append(TestDefinition(identifier=identifier, name=name, path=csv_path))

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
        questions = self._load(test.path)
        self._questions_cache[test_id] = questions
        return questions

    def _load(self, csv_path: Path) -> List[Question]:
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

                category = row.get("category", "").strip()
                if not category:
                    raise ValueError(
                        f"Question {number} is missing a 'category' entry."
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


question_bank = QuestionBank(DATA_DIR)


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


@app.get("/")
def index():
    tests = question_bank.available_tests()
    selected_test_id = request.args.get("test_id") if tests else None

    questions: List[Question] = []
    if tests:
        if selected_test_id:
            try:
                questions = question_bank.questions_for(selected_test_id)
            except ValueError:
                selected_test_id = tests[0].identifier
                questions = question_bank.questions_for(selected_test_id)
        else:
            selected_test_id = tests[0].identifier
            questions = question_bank.questions_for(selected_test_id)

    return render_template(
        "index.html",
        tests=tests,
        selected_test_id=selected_test_id,
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

    return render_template(
        "results.html",
        student_name=student_name,
        test_id=test.identifier,
        test_name=test.name,
        report=report,
    )


if __name__ == "__main__":
    app.run(debug=True)
