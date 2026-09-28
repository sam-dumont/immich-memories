"""Banked model answers for the free-text reading and linking tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

Answer = Mapping[str, Any] | None


class BankedAsker:
    """Answers each question from a bank, in the order the questions come.

    A bank entry is an answer, None (the answer was cut off), or a function of the question's
    schema (an answer that depends on the order its options were offered in).
    """

    def __init__(self, *answers: Answer | Callable[[Mapping[str, Any]], Answer]) -> None:
        self._answers = list(answers)
        self.questions: list[tuple[str, Mapping[str, Any]]] = []

    def ask(self, prompt: str, schema: Mapping[str, Any], *, max_tokens: int) -> Answer:
        self.questions.append((prompt, schema))
        if not self._answers:
            raise AssertionError(f"no banked answer for question {len(self.questions)}")
        answer = self._answers.pop(0)
        return answer(schema) if callable(answer) else answer
