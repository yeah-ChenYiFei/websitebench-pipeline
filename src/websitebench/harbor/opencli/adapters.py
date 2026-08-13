"""Generate ``browser: false`` OpenCLI adapters from a Harbor site.

One adapter file per *command*, not per step: routes and selectors arrive as
arguments, so three files cover any number of contract steps.

Generated adapters are committed under
``harbor/sites/<site-id>/interactions/adapters/`` so they are reviewable and
diffable. ``interactions/`` is not one of ``site.paths``' visibility roots, so
they never enter a materialized bundle — an adapter is a tool for driving the
site, not part of the site.

Installing them copies into ``~/.opencli/clis/wb-<site-id>/``, where OpenCLI
picks them up with no build step. The ``wb-`` prefix is mandatory: OpenCLI ships
163 official site adapters including ``amazon`` and ``imdb``, and an unprefixed
directory would silently override one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .contract import LoadedContract, OpenCliContractError

TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"
COMMANDS = ("state", "click", "submit")
SHARED = "_wb.js"
NAMESPACE_PREFIX = "wb-"


def adapter_site_name(site_id: str) -> str:
    """Return the OpenCLI site namespace used for a Harbor site."""

    return f"{NAMESPACE_PREFIX}{site_id}"


def render(
    site_id: str, display_name: str, *, sample_route: str = ""
) -> dict[str, str]:
    """Render every adapter file for one site, keyed by filename."""

    rendered: dict[str, str] = {
        SHARED: (TEMPLATE_ROOT / SHARED).read_text(encoding="utf-8")
    }
    for command in COMMANDS:
        template = TEMPLATE_ROOT / f"{command}.js.tmpl"
        rendered[f"{command}.js"] = (
            template.read_text(encoding="utf-8")
            .replace("{{SITE_ID}}", site_id)
            .replace("{{DISPLAY}}", display_name)
            .replace("{{SAMPLE_ROUTE}}", sample_route or "some/route/")
        )
    return rendered


def render_for_contract(contract: LoadedContract, display_name: str) -> dict[str, str]:
    """Render adapters, using a real contract route as the help example."""

    sample = ""
    for profile in contract.profiles.values():
        if profile.steps:
            sample = profile.steps[0].route
            break
    return render(contract.site_id, display_name, sample_route=sample)


def write(rendered: dict[str, str], destination: Path) -> list[Path]:
    """Write rendered adapters, returning the paths written."""

    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, source in sorted(rendered.items()):
        path = destination / name
        path.write_text(source, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def check(rendered: dict[str, str], destination: Path) -> list[str]:
    """Return a list of drift problems between rendered and on-disk adapters."""

    problems: list[str] = []
    for name, source in sorted(rendered.items()):
        path = destination / name
        if not path.is_file():
            problems.append(f"{path}: missing; run opencli-adapters to generate it")
            continue
        if path.read_text(encoding="utf-8") != source:
            problems.append(f"{path}: differs from the generator output")
    return problems


def install(source_dir: Path, site_id: str, *, home: Path | None = None) -> Path:
    """Copy generated adapters into the user's OpenCLI adapter directory.

    This mutates the user's home directory, so it is opt-in and never called
    from a test.
    """

    if not source_dir.is_dir():
        raise OpenCliContractError(f"no generated adapters at {source_dir}")
    root = (home or Path.home()) / ".opencli" / "clis" / adapter_site_name(site_id)
    root.mkdir(parents=True, exist_ok=True)
    for name in [SHARED, *(f"{command}.js" for command in COMMANDS)]:
        candidate = source_dir / name
        if not candidate.is_file():
            raise OpenCliContractError(f"missing generated adapter: {candidate}")
        shutil.copyfile(candidate, root / name)
    return root
