from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_TOKENS = (
    "human_supervisor",
    "human_gate",
    "human_decision",
    "human_acceptance",
    "decided_by",
    "named-human",
    "human-fidelity",
    "human-supervision",
    "human-scope",
    "human-semantic",
    "human-release",
    "requires-human",
    "人工监督",
    "人工门禁",
    "人工验收",
    "人工保真",
    "具名人类",
    "人类负责人",
)
FORBIDDEN_REQUIREMENTS = (
    re.compile(
        r"(?:require|required|requires|must).{0,80}"
        r"\bhuman(?:[-_ ](?:review|acceptance|approval|signature|inspection))",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?:必须|要求).{0,40}(?:人工|人类).{0,40}"
        r"(?:核验|验收|审核|复核|签字|签核|确认)",
        re.DOTALL,
    ),
)


def test_active_instructions_code_and_prompts_have_no_human_gates() -> None:
    files = [
        ROOT / "AGENTS.md",
        ROOT / "README.md",
        ROOT / "PROJECT.md",
        ROOT / "CONTRIBUTING.md",
        *sorted((ROOT / "prompts").rglob("*.md")),
        *sorted((ROOT / "skills").rglob("*.md")),
        *sorted(
            path
            for path in (ROOT / "docs").rglob("*.md")
            if "adr" not in path.parts
        ),
        *sorted(
            path
            for path in (ROOT / "src" / "websitebench").rglob("*")
            if path.suffix in {".py", ".html"}
            and "_schemas" not in path.parts
            and path.name != "contracts.py"  # explicit legacy v1 parser
        ),
        *sorted(
            path for path in (ROOT / "tools" / "offline_clone").rglob("*.py")
        ),
    ]
    problems: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8").casefold()
        for token in FORBIDDEN_TOKENS:
            if token.casefold() in text:
                problems.append(f"{path.relative_to(ROOT)}: {token}")
        for pattern in FORBIDDEN_REQUIREMENTS:
            if pattern.search(text):
                problems.append(
                    f"{path.relative_to(ROOT)}: requirement {pattern.pattern}"
                )
    assert not problems, "\n".join(problems)


def test_agent_generated_content_is_explicitly_eligible() -> None:
    policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Agent-generated code, assets, fixtures, tests, reports" in policy
    assert "author-based approval has no technical gate status" in policy
    assert not (ROOT / "docs" / "offline-clone-human-supervision.md").exists()
