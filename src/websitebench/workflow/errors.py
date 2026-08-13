"""Workflow-specific diagnostics."""


class WorkflowError(ValueError):
    """A fail-closed corpus workflow validation or transition error."""

    def __init__(self, problems: str | list[str]) -> None:
        if isinstance(problems, list):
            message = "\n".join(f"- {problem}" for problem in problems)
        else:
            message = problems
        super().__init__(message)
