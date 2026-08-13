"""Fail-closed diagnostics for the declarative site compiler."""

from __future__ import annotations

from collections.abc import Iterable


class SiteCompilerError(ValueError):
    """One or more declarative compiler inputs are invalid or inconsistent."""

    def __init__(self, problems: str | Iterable[str]):
        normalized = [problems] if isinstance(problems, str) else list(problems)
        self.problems = tuple(str(problem) for problem in normalized)
        super().__init__("\n".join(self.problems))
