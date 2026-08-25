#!/usr/bin/env python3
"""High-confidence privacy scan with redacted-only findings.

The scanner deliberately reports structural locations and sanitized context. It
never echoes the matched value, which keeps a failing regression run from
turning a sensitive value into a second artifact.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEXT_SUFFIXES = {
    ".csv", ".css", ".html", ".js", ".json", ".jsonl", ".log", ".md",
    ".mjs", ".py", ".trace", ".txt", ".yaml", ".yml",
}
RESERVED_EMAIL_DOMAINS = {
    "example.com", "example.invalid", "example.test", "localhost",
    "offline.invalid",
}
IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache"}
IGNORED_FILES = {Path(__file__).resolve()}

EMAIL = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@(?P<domain>[A-Z0-9.-]+\.[A-Z]{2,})\b"
)


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]


RULES = (
    Rule(
        "authorization-value",
        re.compile(
            r"(?i)\b(?:authorization|proxy-authorization)\s*[:=]\s*"
            r"(?:bearer|basic)\s+[A-Za-z0-9._~+/-]{8,}={0,2}"
        ),
    ),
    Rule(
        "cookie-value",
        re.compile(
            r"(?i)\b(?:set-cookie|cookie)\s*[:=]\s*"
            r"[A-Za-z0-9_.-]{2,}=[A-Za-z0-9._~+/%-]{8,}"
        ),
    ),
    Rule(
        "assigned-secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|client[_-]?secret|secret|token|"
            r"access[_-]?token|refresh[_-]?token)\b[\"']?\s*[:=]\s*[\"']"
            r"(?![^\"']*(?:example|fixture|local|synthetic|test))"
            r"[A-Za-z0-9._~+/-]{16,}[\"']"
        ),
    ),
    Rule(
        "password-value",
        re.compile(
            r"(?i)(?<![A-Za-z0-9_-])(?:password|passwd|pwd)\b"
            r"[\"']?\s*[:=]\s*[\"']"
            r"(?![^\"']*(?:example|fixture|local|synthetic|test|decoy|offline))"
            r"[^\"'\r\n]{8,}[\"']"
        ),
    ),
    Rule(
        "cloudflare-api-token",
        re.compile(
            r"(?i)\b(?:cf|cloudflare)[A-Za-z0-9_-]*api[_-]?token\b"
            r"[\"']?\s*[:=]\s*[\"']"
            r"(?![^\"']*(?:example|fixture|local|synthetic|test))"
            r"[A-Za-z0-9._~+/-]{20,}[\"']"
        ),
    ),
    Rule(
        "private-key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    Rule(
        "live-provider-key",
        re.compile(
            r"\b(?:sk_live_[A-Za-z0-9]{12,}|rk_live_[A-Za-z0-9]{12,}|"
            r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|re_[A-Za-z0-9_-]{20,})\b"
        ),
    ),
    Rule(
        "plaintext-otp",
        re.compile(
            r"(?i)\b(?:verification[_ -]?code|one[_ -]?time[_ -]?code|otp)"
            r"\b[\"']?\s*[:=]\s*[\"']?\d{4,8}\b"
        ),
    ),
    Rule(
        "payment-card-data",
        re.compile(
            r"(?i)\b(?:card[_ -]?(?:number|pan)|primary[_ -]?account[_ -]?number)"
            r"\b[\"']?\s*[:=]\s*[\"']?(?:\d[ -]*?){13,19}(?!\d)"
        ),
    ),
    Rule(
        "international-phone",
        re.compile(r"(?<!\w)\+[1-9]\d{7,14}(?!\d)"),
    ),
    Rule(
        "postal-address",
        re.compile(
            r"(?i)\b(?:postal[_ -]?address|street[_ -]?address|address)\b"
            r"[\"']?\s*[:=]\s*[\"']"
            r"(?![^\"']*(?:example|fixture|local|synthetic|test|offline))"
            r"\d{1,6}\s+(?:[A-Z0-9][A-Z0-9.'-]*\s+){0,5}"
            r"(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr|"
            r"boulevard|blvd|way|court|ct)\b[^\"'\r\n]{0,32}[\"']"
        ),
    ),
    Rule(
        "url-query-identifier",
        re.compile(
            r"(?i)(?:https?://|//)[^\s\"'<>]*"
            r"(?:[?&]|&amp;)(?:mid|msclkid|sid|vid)="
            r"[^\s\"'<>&]+(?:&amp;[^\s\"'<>]*)?"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    category: str
    context: str

    def render(self, root: Path) -> str:
        try:
            label = self.path.relative_to(root)
        except ValueError:
            label = self.path
        return f"{label}:{self.line}:{self.category}:{self.context}"


def _reserved_email(match: re.Match[str]) -> bool:
    domain = match.group("domain").casefold()
    return domain in RESERVED_EMAIL_DOMAINS or domain.endswith(".example.invalid")


def _sanitize(line: str, start: int, end: int) -> str:
    bounded = line[max(0, start - 48):min(len(line), end + 48)]
    for rule in RULES:
        bounded = rule.pattern.sub("[REDACTED]", bounded)
    bounded = EMAIL.sub("[REDACTED_EMAIL]", bounded)
    bounded = re.sub(r"[A-Za-z0-9_~+/-]{24,}", "[REDACTED_VALUE]", bounded)
    return " ".join(bounded.split())[:160]


def _text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        resolved = path.resolve()
        if (
            path.is_file()
            and path.suffix.casefold() in TEXT_SUFFIXES
            and not IGNORED_PARTS.intersection(path.parts)
            and resolved not in IGNORED_FILES
        ):
            yield path


def scan_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in _text_files(root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, 1):
            for match in EMAIL.finditer(line):
                if not _reserved_email(match):
                    findings.append(
                        Finding(
                            path,
                            line_number,
                            "non-reserved-email",
                            _sanitize(line, match.start(), match.end()),
                        )
                    )
            for rule in RULES:
                for match in rule.pattern.finditer(line):
                    findings.append(
                        Finding(
                            path,
                            line_number,
                            rule.category,
                            _sanitize(line, match.start(), match.end()),
                        )
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan_tree(root)
    for finding in findings:
        print(finding.render(root))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
