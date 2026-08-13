"""Structurally compare two recorded browser trajectories.

The recorder retains a redacted ledger of what a human did: event types, the
route each event happened on, and the structural identity of the element that
received it.  Recording the same journey once against a source site and once
against an offline candidate therefore yields two sequences that *should* line
up if the candidate reproduces the source's interaction structure.

What this comparison can and cannot support follows directly from what the
recorder retains:

* It compares structure and order -- event types, routes, and element identity.
* It cannot compare pixels, copy, or network behaviour, because the recorder
  omits element text, input values, and network traffic entirely.
* It cannot see cross-origin iframes, which the recorder skips.

Consequently a report from this module is ``diagnostic`` authority: it produces
findings that feed an interaction ledger and a repair loop.  It is deliberately
not a pass/fail gate, and this module intentionally offers no "fail on
divergence" mode -- a clean diff here is not evidence that a candidate is
faithful, only that the recorded structural path is reproducible.

Comparison runs over a normalized projection.  Fields that necessarily differ
between two human demonstrations -- wall-clock timestamps, pointer coordinates,
scroll offsets -- are dropped, as are the throttled ``scroll``/``input`` streams,
because keeping them manufactures divergences that mean nothing.  Origins are
dropped too: a source origin and a loopback candidate origin never match, so
only the path participates.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

DIFF_SCHEMA_VERSION = "websitebench.browser-trajectory.diff.v1"

#: Events that carry intent.  ``scroll`` and ``input`` are throttled streams
#: whose density reflects how fast a person moved, not what the site did, and
#: ``keydown``/``keyup`` are collapsed to ``"character"`` by the recorder, so
#: none of them survive normalization by default.
SIGNAL_EVENT_TYPES = ("click", "change", "submit", "pageLoad")

#: Element fields compared by default.  ``xpath`` and ``class_name`` are
#: excluded: both diverge on DOM or styling details a user cannot perceive,
#: which is the wrong bar for an offline clone.  ``--strict`` opts into them.
DEFAULT_TARGET_FIELDS = ("tag", "id", "name", "input_type", "role")
STRICT_TARGET_FIELDS = DEFAULT_TARGET_FIELDS + ("class_name", "xpath")


class TrajectoryDiffError(RuntimeError):
    """Raised when a trajectory ledger cannot be read or compared."""


@dataclass(frozen=True)
class NormalizedStep:
    """One comparable step: what happened, where, and to which element."""

    type: str
    path: str
    target: tuple[tuple[str, str], ...]
    source_event_ids: tuple[str, ...] = ()

    def key(self) -> tuple[Any, ...]:
        """The tuple actually aligned; event ids are provenance, not identity."""
        return (self.type, self.path, self.target)

    def label(self) -> str:
        fields = dict(self.target)
        ident = fields.get("id") or fields.get("name") or fields.get("role") or ""
        tag = fields.get("tag", "").lower()
        element = f"{tag}#{ident}" if tag and ident else (tag or ident or "-")
        return f"{self.type} {element} @ {self.path}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "path": self.path,
            "target": dict(self.target),
            "label": self.label(),
            "event_ids": list(self.source_event_ids),
        }


@dataclass
class Finding:
    kind: str
    detail: str
    source_step: NormalizedStep | None = None
    candidate_step: NormalizedStep | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "source": self.source_step.as_dict() if self.source_step else None,
            "candidate": (
                self.candidate_step.as_dict() if self.candidate_step else None
            ),
        }


@dataclass
class DiffReport:
    source_path: str
    candidate_path: str
    source_actions_total: int
    candidate_actions_total: int
    source_steps: list[NormalizedStep]
    candidate_steps: list[NormalizedStep]
    findings: list[Finding]
    matched: int
    normalization: dict[str, Any] = field(default_factory=dict)

    @property
    def similarity(self) -> float:
        total = len(self.source_steps) + len(self.candidate_steps)
        if total == 0:
            return 1.0
        return round(2 * self.matched / total, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIFF_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "authority": "diagnostic",
            "authority_note": (
                "Structural and ordering evidence only. Establishes nothing "
                "about pixels, copy, network closure, or cross-origin iframes, "
                "and satisfies no gate."
            ),
            "source": {
                "path": self.source_path,
                "actions_total": self.source_actions_total,
                "comparable_steps": len(self.source_steps),
            },
            "candidate": {
                "path": self.candidate_path,
                "actions_total": self.candidate_actions_total,
                "comparable_steps": len(self.candidate_steps),
            },
            "normalization": self.normalization,
            "similarity": self.similarity,
            "matched_steps": self.matched,
            "findings_total": len(self.findings),
            "findings": [finding.as_dict() for finding in self.findings],
        }


def resolve_actions_path(value: Path) -> Path:
    """Accept either a recorder output directory or an actions.jsonl directly."""

    if value.is_dir():
        candidate = value / "actions.jsonl"
        if not candidate.is_file():
            raise TrajectoryDiffError(f"no actions.jsonl inside {value}")
        return candidate
    if not value.is_file():
        raise TrajectoryDiffError(f"not a trajectory ledger: {value}")
    return value


def load_actions(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL ledger, skipping blank lines and rejecting malformed rows."""

    actions: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TrajectoryDiffError(
                    f"{path}:{number} is not valid JSON: {exc}"
                ) from exc
            if not isinstance(record, dict):
                raise TrajectoryDiffError(f"{path}:{number} is not a JSON object")
            actions.append(record)
    return actions


def _path_of(url: Any) -> str:
    """Keep the route, drop the origin -- candidate origins never match source."""

    if not isinstance(url, str) or not url:
        return ""
    parsed = urlsplit(url)
    return parsed.path or "/"


def _target_of(record: dict[str, Any], fields: Sequence[str]) -> tuple[
    tuple[str, str], ...
]:
    raw = record.get("target")
    if not isinstance(raw, dict):
        return ()
    pairs = []
    for name in fields:
        value = raw.get(name)
        if isinstance(value, str) and value:
            pairs.append((name, value))
    return tuple(pairs)


def normalize(
    actions: Iterable[dict[str, Any]],
    *,
    signal_types: Sequence[str] = SIGNAL_EVENT_TYPES,
    target_fields: Sequence[str] = DEFAULT_TARGET_FIELDS,
    collapse_repeats: bool = False,
) -> list[NormalizedStep]:
    """Project a ledger onto comparable steps.

    Consecutive duplicate ``pageLoad`` steps are always collapsed: the capture
    script is injected per document, so every same-origin frame emits its own
    ``pageLoad`` for the same route.  That is an artifact of injection, not
    something the site did.  ``collapse_repeats`` extends the same treatment to
    every event type, which suppresses genuine repeats such as a double submit --
    so it stays off unless asked for.
    """

    allowed = set(signal_types)
    steps: list[NormalizedStep] = []
    for record in actions:
        event_type = record.get("type")
        if not isinstance(event_type, str) or event_type not in allowed:
            continue
        step = NormalizedStep(
            type=event_type,
            path=_path_of(record.get("url")),
            target=_target_of(record, target_fields),
            source_event_ids=(
                (record["event_id"],)
                if isinstance(record.get("event_id"), str)
                else ()
            ),
        )
        if steps and steps[-1].key() == step.key():
            if collapse_repeats or event_type == "pageLoad":
                previous = steps[-1]
                steps[-1] = NormalizedStep(
                    type=previous.type,
                    path=previous.path,
                    target=previous.target,
                    source_event_ids=previous.source_event_ids
                    + step.source_event_ids,
                )
                continue
        steps.append(step)
    return steps


def compare(
    source_steps: Sequence[NormalizedStep],
    candidate_steps: Sequence[NormalizedStep],
) -> tuple[list[Finding], int]:
    """Align two step sequences and describe where they diverge.

    Divergence is reported, never adjudicated.  A missing step is at least as
    likely to mean the two demonstrations differed as it is to mean the
    candidate lacks the control -- the caller decides which.
    """

    matcher = SequenceMatcher(
        a=[step.key() for step in source_steps],
        b=[step.key() for step in candidate_steps],
        autojunk=False,
    )
    findings: list[Finding] = []
    matched = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
            continue
        if tag in {"replace", "delete"}:
            for step in source_steps[i1:i2]:
                findings.append(
                    Finding(
                        kind="missing-in-candidate",
                        detail=(
                            "recorded against the source but absent from the "
                            "candidate run at this point in the sequence"
                        ),
                        source_step=step,
                    )
                )
        if tag in {"replace", "insert"}:
            for step in candidate_steps[j1:j2]:
                findings.append(
                    Finding(
                        kind="extra-in-candidate",
                        detail=(
                            "recorded against the candidate but absent from the "
                            "source run at this point in the sequence"
                        ),
                        candidate_step=step,
                    )
                )
    return findings, matched


def diff_trajectories(
    source: Path,
    candidate: Path,
    *,
    strict: bool = False,
    include_input: bool = False,
    collapse_repeats: bool = False,
) -> DiffReport:
    source_actions_path = resolve_actions_path(source)
    candidate_actions_path = resolve_actions_path(candidate)
    source_actions = load_actions(source_actions_path)
    candidate_actions = load_actions(candidate_actions_path)

    signal_types = tuple(SIGNAL_EVENT_TYPES)
    if include_input:
        signal_types += ("input",)
    target_fields = STRICT_TARGET_FIELDS if strict else DEFAULT_TARGET_FIELDS

    source_steps = normalize(
        source_actions,
        signal_types=signal_types,
        target_fields=target_fields,
        collapse_repeats=collapse_repeats,
    )
    candidate_steps = normalize(
        candidate_actions,
        signal_types=signal_types,
        target_fields=target_fields,
        collapse_repeats=collapse_repeats,
    )
    findings, matched = compare(source_steps, candidate_steps)
    return DiffReport(
        source_path=str(source_actions_path),
        candidate_path=str(candidate_actions_path),
        source_actions_total=len(source_actions),
        candidate_actions_total=len(candidate_actions),
        source_steps=source_steps,
        candidate_steps=candidate_steps,
        findings=findings,
        matched=matched,
        normalization={
            "compared_event_types": list(signal_types),
            "compared_target_fields": list(target_fields),
            "dropped_fields": [
                "timestamp_ms",
                "pointer",
                "scroll",
                "key",
                "input_value",
                "event_id",
                "url_origin",
            ],
            "dropped_event_types": [
                event
                for event in ("scroll", "input", "keydown", "keyup")
                if event not in signal_types
            ],
            "collapse_repeats": collapse_repeats,
            "always_collapsed": ["consecutive duplicate pageLoad"],
        },
    )
