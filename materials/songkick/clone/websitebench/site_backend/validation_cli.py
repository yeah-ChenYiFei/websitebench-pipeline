"""Canonical stdin/stdout validator used by non-Python deployment tooling."""

from __future__ import annotations

import json
import sys

from .errors import RuntimeContractError
from .runtime import validate_runtime


def main() -> int:
    try:
        value = json.load(sys.stdin)
        runtime = validate_runtime(value)
    except (json.JSONDecodeError, RuntimeContractError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    json.dump(
        dict(runtime.raw),
        sys.stdout,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
