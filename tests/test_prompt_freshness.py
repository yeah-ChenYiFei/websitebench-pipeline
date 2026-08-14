"""The offline-clone prompt must not tell an agent to run things that are gone.

On 2026-08-11 the repository removed `websitebench.project` along with the
repository-wide plan gates.  The prompt kept instructing agents to run
`websitebench-project validate` and `websitebench-project status` for hours
afterwards; a peer session happened to sweep three files and fix it, which is
luck rather than a mechanism.  The same audit also found a reference to a
tool path that had been renamed long before.

A prompt is documentation that gets executed.  When it drifts from the codebase
the failure is silent and lands on whoever runs it next, so the binding is
asserted here instead of being re-discovered by hand.

Scope: only the things a machine can check -- declared entry points, module
importability, repository paths, and the entry/reference cross-links.  Whether a
rule is still *wise* is not testable and is deliberately out of scope.

One gap worth naming: these tests assert the *repository* contract, not the
state of any particular virtualenv.  A command can be declared here, import
cleanly, and still have no console script on PATH because the package has not
been reinstalled since the entry point was added -- which is exactly the state
`websitebench-browser-trajectory` was in when this file was written.  Asserting
the console script would make the suite fail on every fresh checkout, so run
`uv pip install -e . --no-deps` after adding an entry point and do not expect
this file to catch it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROMPT_DIR = REPO / "prompts" / "offline-clone"
ENTRY = PROMPT_DIR / "autonomous-source-to-clone.md"
REFERENCES = PROMPT_DIR / "references"
CONTEXT_HANDOFF = PROMPT_DIR / "context-handoff.md"
CLAUDE_SETTINGS = REPO / ".claude" / "settings.json"

# Paths inside fenced examples are templates, not repository paths.
PLACEHOLDER = re.compile(r"[<>*]")
REPO_PATH = re.compile(
    r"`((?:src|docs|deploy|scripts|tools|project|materials|harbor|prompts|skills|tests|\.github|\.claude)"
    r"/[A-Za-z0-9_./<>*-]+)`"
)
CLI_IN_FENCE = re.compile(r"^\s*(websitebench-[a-z-]+)\b", re.MULTILINE)
CLI_INLINE = re.compile(r"`(websitebench-[a-z-]+)")


RUNBOOK = PROMPT_DIR / "RUNBOOK.md"
HAN_TEXT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def prompt_files() -> list[Path]:
    """The executable prompts, phase references, and human-facing runbook.

    The runbook is included because it hands a person commands to type. A stale
    command there wastes someone's time just as surely as a stale one in the
    prompt wastes an agent's. The context handoff executes at every phase
    boundary, so it receives the same freshness checks.
    """
    assert ENTRY.is_file(), f"entry prompt is missing: {ENTRY}"
    assert CONTEXT_HANDOFF.is_file(), (
        f"context handoff prompt is missing: {CONTEXT_HANDOFF}"
    )
    assert RUNBOOK.is_file(), f"runbook is missing: {RUNBOOK}"
    return [ENTRY, CONTEXT_HANDOFF, RUNBOOK, *sorted(REFERENCES.glob("*.md"))]


def prompt_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in prompt_files())


def test_every_prompt_file_is_english() -> None:
    """Keep every maintained prompt readable without a Chinese-language fallback."""
    non_english: list[str] = []
    for path in sorted(PROMPT_DIR.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if HAN_TEXT.search(text):
            non_english.append(str(path.relative_to(REPO)))
    assert not non_english, (
        "all files under prompts/ must be English; found Han text in "
        f"{non_english}"
    )


def declared_entry_points() -> dict[str, str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return dict(data["project"]["scripts"])


def referenced_clis() -> set[str]:
    text = prompt_text()
    return set(CLI_IN_FENCE.findall(text)) | set(CLI_INLINE.findall(text))


def test_every_referenced_cli_is_a_declared_entry_point() -> None:
    declared = declared_entry_points()
    missing = sorted(name for name in referenced_clis() if name not in declared)
    assert not missing, (
        "the prompt instructs agents to run commands that pyproject.toml does not "
        f"declare: {missing}. Either restore the entry point or update the prompt."
    )


def test_every_referenced_cli_resolves_to_an_importable_module() -> None:
    """Catches the failure that actually happened: the entry point outlived its module."""
    declared = declared_entry_points()
    broken: list[str] = []
    for name in sorted(referenced_clis()):
        target = declared.get(name)
        if target is None:
            continue  # reported by the test above
        module = target.split(":", 1)[0]
        try:
            found = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            found = None
        if found is None:
            broken.append(f"{name} -> {module}")
    assert not broken, (
        "the prompt instructs agents to run commands whose module no longer "
        f"imports: {broken}. This is the websitebench-project failure mode."
    )


def test_every_referenced_repository_path_exists() -> None:
    missing: list[str] = []
    for path in sorted({m for f in prompt_files() for m in REPO_PATH.findall(f.read_text("utf-8"))}):
        if PLACEHOLDER.search(path):
            continue  # templated, e.g. materials/<site-id>/scope
        if not (REPO / path).exists():
            missing.append(path)
    assert not missing, (
        f"the prompt points at repository paths that do not exist: {missing}"
    )


def test_entry_indexes_every_reference_and_indexes_nothing_else() -> None:
    """A reference nobody links to is a rule that silently stops being read."""
    indexed = {
        Path(m).name
        for m in re.findall(r"`(references/[A-Za-z0-9_.-]+\.md)`", ENTRY.read_text("utf-8"))
    }
    on_disk = {path.name for path in REFERENCES.glob("*.md")}
    assert indexed == on_disk, (
        f"entry index and references/ disagree — only indexed: {sorted(indexed - on_disk)}; "
        f"only on disk: {sorted(on_disk - indexed)}"
    )


@pytest.mark.parametrize("path", sorted(REFERENCES.glob("*.md")), ids=lambda p: p.name)
def test_reference_declares_the_entry_prompt_wins(path: Path) -> None:
    """Split content must not silently reinstate a rule the entry prompt overrode.

    The references carry the original phase text, including instructions the
    operating rules deliberately supersede (per-page human approval, for one).
    Each file therefore states that precedence up front.
    """
    head = path.read_text(encoding="utf-8")[:600]
    assert "autonomous-source-to-clone.md" in head, (
        f"{path.name} does not name the entry prompt in its header"
    )
    assert "take precedence over this file" in head, (
        f"{path.name} does not declare that the entry prompt's rules take precedence"
    )


def test_entry_prompt_stays_small_enough_to_stay_resident() -> None:
    """The split exists so the always-loaded part stays small; guard the win.

    Measured before the split: 67 KB resident for the whole run. The budget is
    generous enough for real edits and tight enough that folding a phase back
    into the entry file fails here instead of quietly undoing the split.
    """
    size = ENTRY.stat().st_size
    assert size < 32_768, (
        f"entry prompt is {size} bytes; move phase detail into references/ "
        "rather than growing the always-resident file"
    )


def test_long_runs_have_a_fresh_context_rollover_contract() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    handoff = CONTEXT_HANDOFF.read_text(encoding="utf-8")
    settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))

    assert "materials/<site-id>/scope/agent-handoff.md" in entry
    assert "new standard subagent with fresh context" in entry
    assert "Use a standard subagent, not a fork" in handoff
    assert "must never claim" in handoff and "`/clear`" in handoff
    assert settings["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == "70"


def test_harbor_phase_tracks_the_current_compile_case_protocol() -> None:
    phase = (REFERENCES / "06-ledger-harbor.md").read_text(encoding="utf-8")
    build = (PROMPT_DIR / "build.md").read_text(encoding="utf-8")
    combined = phase + "\n" + build

    for requirement in (
        "websitebench-harbor init-site",
        "websitebench-harbor init-instance",
        "status: draft",
        "scorable: false",
        "compile.sh -> executable",
        "HOST",
        "PORT",
        "DATA_DIR",
        "SEED",
        "TZ",
        "/__websitebench/health",
        "playwright",
        "browser-use",
        "T1=20",
        "T2=165",
        "T3=15",
        "L1=35",
        "L2=50",
        "L3=80",
    ):
        assert requirement in combined

    assert "do not copy another site's test content" in combined.lower()
    assert "must not consume any of the 200 site cases" in phase
