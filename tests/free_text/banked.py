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


class QuestionAsker:
    """Answers by what is asked: the first key found in the prompt picks the answer.

    For tests that run the whole translation, where the number and order of questions follow
    from the library and are not the point. An entry is an answer or a function of the
    question's schema; a question no key matches fails the test.
    """

    def __init__(self, answers: Mapping[str, Answer | Callable[[Mapping[str, Any]], Answer]]):
        self._answers = dict(answers)
        self.questions: list[str] = []

    def ask(self, prompt: str, schema: Mapping[str, Any], *, max_tokens: int) -> Answer:
        self.questions.append(prompt)
        # A recorded key is written on one line; the prompt wraps where its source does.
        flat = " ".join(prompt.split())
        for key, answer in self._answers.items():
            if key in prompt or key in flat:
                return answer(schema) if callable(answer) else answer
        raise AssertionError(f"no banked answer for: {prompt[:80]}")


def recorded(answers: Mapping[str, Answer]) -> QuestionAsker:
    """A QuestionAsker over a recorded fixture's banked answers.

    A recorded single `choice` may be the start of the option it picks ("anywhere"), as the
    options are long sentences a fixture should not have to copy; it must match exactly one.
    """
    return QuestionAsker({key: _by_prefix(answer) for key, answer in answers.items()})


def _by_prefix(answer: Answer) -> Answer | Callable[[Mapping[str, Any]], Answer]:
    if answer is None or not isinstance(answer.get("choice"), str):
        return answer
    wanted = answer["choice"]

    def expand(schema: Mapping[str, Any]) -> Answer:
        options = schema["properties"]["choice"]["enum"]
        matches = [option for option in options if option.startswith(wanted)]
        if len(matches) != 1:
            raise AssertionError(f"recorded choice {wanted!r} matches {matches} of {options}")
        return {**answer, "choice": matches[0]}

    return expand
