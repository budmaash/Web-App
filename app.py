from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from flask import Flask, render_template, request


DATA_FILE = Path("data/questions.csv")


@dataclass
class Question:
    number: int
    correct_answer: str
    category: str


app = Flask(__name__)


class QuestionBank:
    """Utility responsible for loading and caching questions."""

    def __init__(self, data_file: Path) -> None:
        self._data_file = data_file
        self._questions: List[Question] | None = None

    def all(self) -> List[Question]:
        if self._questions is None:
            self._questions = self._load()
        return self._questions

    def _load(self) -> List[Question]:
        if not self._data_file.exists():
            raise FileNotFoundError(
                "Question data file not found. Expected at '{}'".format(self._data_file)
            )

        questions: List[Question] = []
        with self._data_file.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                try:
                    number = int(row["question_number"].strip())
                except (KeyError, ValueError) as exc:
                    raise ValueError(
                        "Each question must include a numeric 'question_number'."
                    ) from exc

                correct_answer = row.get("correct_answer", "").strip().upper()
                if not correct_answer:
                    raise ValueError(
                        f"Question {number} is missing a 'correct_answer' entry."
                    )

                category = row.get("category", "").strip()
                if not category:
                    raise ValueError(
                        f"Question {number} is missing a 'category' entry."
                    )

                questions.append(Question(number=number, correct_answer=correct_answer, category=category))

        questions.sort(key=lambda q: q.number)
        return questions


def build_score_report(student_answers: Dict[int, str], questions: List[Question]):
    per_question = []
    category_totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    correct_count = 0

    for question in questions:
        student_answer = student_answers.get(question.number, "")
        is_correct = student_answer == question.correct_answer

        category_totals[question.category]["total"] += 1
        if is_correct:
            correct_count += 1
            category_totals[question.category]["correct"] += 1

        per_question.append(
            {
                "number": question.number,
                "student_answer": student_answer or "—",
                "correct_answer": question.correct_answer,
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


question_bank = QuestionBank(DATA_FILE)


@app.get("/")
def index():
    questions = question_bank.all()
    return render_template("index.html", questions=questions)


@app.post("/results")
def results():
    questions = question_bank.all()
    student_name = request.form.get("student_name", "").strip() or "Student"

    answers: Dict[int, str] = {}
    for question in questions:
        answer = request.form.get(f"q_{question.number}", "").strip().upper()
        answers[question.number] = answer

    report = build_score_report(answers, questions)

    return render_template(
        "results.html",
        student_name=student_name,
        report=report,
    )


if __name__ == "__main__":
    app.run(debug=True)
