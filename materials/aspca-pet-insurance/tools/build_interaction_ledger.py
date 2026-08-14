#!/usr/bin/env python3
"""Build the aspca-pet-insurance interaction ledger from walk evidence.

Reads the source-side trajectory recordings (``artifacts/trajectory/tc-001``
and ``tc-002``) to inventory every control the recorded walk activated, then
proves each control against the *running clone* DOM: one visible-text proof
and one raw-markup proof per control, extracted from the served document that
hosts it. Selectors come only from attributes the recorder captured
(tag/id/name/input_type); the recorder omits element text and input values,
so all copy is taken from the clone DOM, never inferred from selectors.

Diagnostic authority only: this ledger describes what the clone serves; it is
not an acceptance, rights, or deployment decision.

Usage:
    python tools/build_interaction_ledger.py --base-url http://127.0.0.1:8093
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

SITE_ID = "aspca-pet-insurance"
SITE_ROOT = Path(__file__).resolve().parents[1]
TRAJECTORIES = ("tc-001", "tc-002")
LEDGER_SCHEMA = "aspca-pet-insurance.interaction-ledger.v1"

# Documents that can host walk-activated controls, in lookup order.
# (interactive_url, dom_source_path)
DOCUMENTS = [
    ("/quote/#/start", "/quote/views/start"),
    ("/quote/#/plans", "/quote/views/rates"),
    ("/quote/#/plans", "/quote/views/plan-customize"),
    ("/portal/#/login", "/portal/views/login"),
    ("/portal/", "/portal/"),
    ("/quote/", "/quote/"),
]

# JS-driven mutation endpoints per control, from clone/static/site/*.js.
# The funnel and portal are fetch-driven: no <form method="post"> exists, so
# "form action" is recorded as the JS submission endpoint of the hosting form.
MUTATION_BY_CONTROL = {
    "form:form": {
        "kind": "js-fetch-submit",
        "endpoint": "POST /api/quotes",
        "note": (
            "Angular-style funnel start form; quote-app.js posts JSON to "
            "/api/quotes, then rates load via POST /api/quotes/{quote_id}/rate."
        ),
    },
    "input:250l2": {
        "kind": "js-fetch-submit",
        "endpoint": "POST /api/quotes/{quote_id}/rate",
        "note": "Customize radio triggers a re-rate via quote-app.js.",
    },
    "input:90l2": {
        "kind": "js-fetch-submit",
        "endpoint": "POST /api/quotes/{quote_id}/rate",
        "note": "Customize radio triggers a re-rate via quote-app.js.",
    },
    "input:5000l2": {
        "kind": "js-fetch-submit",
        "endpoint": "POST /api/quotes/{quote_id}/rate",
        "note": "Customize radio triggers a re-rate via quote-app.js.",
    },
    "button:registerBtn": {
        "kind": "navigation",
        "endpoint": None,
        "note": (
            "Reveals the registration panel (hidden-attribute toggle); the "
            "eventual registration posts to /portal/api/register."
        ),
    },
}

# Journey / state / checkpoint mapping keyed by the control's hosting view.
CONTEXT_BY_VIEW = {
    "/quote/views/start": {
        "journey_id": "quote.get-rates.success",
        "state": "quote-start",
        "checkpoint_id": "quote-start.desktop",
    },
    "/quote/views/rates": {
        "journey_id": "quote.select-plan.customize",
        "state": "quote-rates",
        "checkpoint_id": "quote-rates.desktop",
    },
    "/quote/views/plan-customize": {
        "journey_id": "quote.select-plan.customize",
        "state": "quote-plan-customize",
        "checkpoint_id": "quote-plan-customize.desktop",
    },
    "/portal/views/login": {
        "journey_id": "auth.register.unavailable",
        "state": "portal-login",
        "checkpoint_id": "portal-register.desktop",
    },
    "/portal/": {
        "journey_id": "auth.login.invalid",
        "state": "portal-login",
        "checkpoint_id": "portal-login.desktop",
    },
    "/quote/": {
        "journey_id": "quote.get-rates.success",
        "state": "quote-start",
        "checkpoint_id": "quote-start.desktop",
    },
}

_CSS_SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def fetch(base_url: str, path: str) -> str:
    with urllib.request.urlopen(base_url + path) as resp:
        return resp.read().decode("utf-8", "replace")


def visible_text(markup: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markup)
    text = re.sub(r"&#x27;|&#39;", "'", text)
    text = re.sub(r"&amp;", "&", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_selector(tag: str, elem_id: str | None, name: str | None,
                    input_type: str | None) -> str:
    if elem_id:
        if _CSS_SAFE_ID.match(elem_id):
            return f"#{elem_id}"
        return f"[id='{elem_id}']"
    if name and input_type == "submit":
        return f"form[name='{name}'] button[type='submit']"
    if name:
        return f"{tag.lower()}[name='{name}']"
    if input_type:
        return f"{tag.lower()}[type='{input_type}']"
    return tag.lower()


def element_snippet(body: str, elem_id: str | None, name: str | None,
                    tag: str) -> str | None:
    """Raw-markup proof: the element's opening tag, verbatim from the clone."""
    patterns = []
    if elem_id:
        patterns.append(re.escape(f'id="{elem_id}"'))
    if name:
        patterns.append(re.escape(f'name="{name}"'))
    for pattern in patterns:
        match = re.search(pattern, body)
        if not match:
            continue
        start = body.rfind("<", 0, match.start())
        end = body.find(">", match.end())
        if start >= 0 and end >= 0:
            return body[start:end + 1][:400]
    return None


def label_text(body: str, elem_id: str | None) -> str | None:
    if not elem_id:
        return None
    match = re.search(
        r'<label[^>]*for="%s"[^>]*>(.*?)</label>' % re.escape(elem_id),
        body, re.S)
    if match:
        text = visible_text(match.group(1))
        if text:
            return text[:160]
    return None


def inner_text(body: str, elem_id: str | None, tag: str) -> str | None:
    if not elem_id:
        return None
    match = re.search(
        r'<%s[^>]*id="%s"[^>]*>(.*?)</%s>'
        % (tag.lower(), re.escape(elem_id), tag.lower()),
        body, re.S)
    if match:
        text = visible_text(match.group(1))
        if text:
            return text[:160]
    return None


def aria_label(snippet: str | None) -> str | None:
    if not snippet:
        return None
    match = re.search(r'aria-label="([^"]+)"', snippet)
    return match.group(1)[:160] if match else None


def nearest_legend(body: str, position: int) -> str | None:
    head = body[:position]
    matches = list(re.finditer(r"<legend[^>]*>(.*?)</legend>", head, re.S))
    if matches:
        text = visible_text(matches[-1].group(1))
        if text:
            return text[:160]
    # A container (e.g. a form) opens before its own legend: look forward.
    match = re.search(r"<legend[^>]*>(.*?)</legend>", body[position:], re.S)
    if match:
        text = visible_text(match.group(1))
        if text:
            return text[:160]
    return None


def collect_controls() -> list[dict]:
    """Distinct activated controls across both trajectories, with event refs."""
    controls: dict[tuple, dict] = {}
    for trace_id in TRAJECTORIES:
        actions = SITE_ROOT / "artifacts" / "trajectory" / trace_id / "actions.jsonl"
        for line in actions.open():
            event = json.loads(line)
            if event.get("type") not in {"click", "input", "change", "submit"}:
                continue
            target = event.get("target") or {}
            tag = target.get("tag")
            if not tag:
                continue
            key = (tag, target.get("id"), target.get("name"),
                   target.get("input_type"))
            entry = controls.setdefault(key, {
                "tag": tag,
                "id": target.get("id"),
                "name": target.get("name"),
                "input_type": target.get("input_type"),
                "event_types": set(),
                "evidence": {},
            })
            entry["event_types"].add(event["type"])
            entry["evidence"].setdefault(trace_id, []).append(event["event_id"])
    ordered = []
    for entry in controls.values():
        entry["event_types"] = sorted(entry["event_types"])
        # Keep only first and last event id per trajectory: bounded evidence.
        entry["evidence"] = {
            trace: ([ids[0]] if len(ids) == 1 else [ids[0], ids[-1]])
            for trace, ids in entry["evidence"].items()
        }
        ordered.append(entry)
    ordered.sort(key=lambda e: (str(e["id"] or ""), str(e["name"] or ""), e["tag"]))
    return ordered


def locate(base_url: str, control: dict,
           documents: list[tuple[str, str, str]]) -> tuple[str, str, int] | None:
    """Find the served clone document containing this control."""
    for interactive, source, body in documents:
        if control["id"]:
            match = re.search(re.escape(f'id="{control["id"]}"'), body)
            if match:
                return interactive, source, match.start()
        elif control["name"]:
            match = re.search(re.escape(f'name="{control["name"]}"'), body)
            if match:
                return interactive, source, match.start()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8093")
    parser.add_argument(
        "--output",
        default=str(SITE_ROOT / "artifacts" / "offline-clone"
                    / "interaction-ledger.json"))
    args = parser.parse_args()

    documents = [
        (interactive, source, fetch(args.base_url, source))
        for interactive, source in DOCUMENTS
    ]

    entries = []
    unlocated = []
    for control in collect_controls():
        located = locate(args.base_url, control, documents)
        if located is None:
            unlocated.append(control)
            continue
        interactive, source, position = located
        body = next(b for i, s, b in documents if s == source)
        selector = stable_selector(control["tag"], control["id"],
                                   control["name"], control["input_type"])
        snippet = element_snippet(body, control["id"], control["name"],
                                  control["tag"])
        visible = (
            label_text(body, control["id"])
            or inner_text(body, control["id"], control["tag"])
            or aria_label(snippet)
            or nearest_legend(body, position)
        )
        mutation_key = f"{control['tag'].lower()}:{control['id'] or control['name']}"
        mutation = MUTATION_BY_CONTROL.get(mutation_key)
        context = CONTEXT_BY_VIEW[source]
        entries.append({
            "control": {
                "tag": control["tag"],
                "id": control["id"],
                "name": control["name"],
                "input_type": control["input_type"],
            },
            "selector": selector,
            "clone_url": interactive,
            "dom_source_url": source,
            "visible_text_proof": visible,
            "raw_markup_proof": snippet,
            "form_action": mutation,
            "journey_id": context["journey_id"],
            "role": "anonymous",
            "state": context["state"],
            "evidence": {
                "checkpoint_id": context["checkpoint_id"],
                "trajectory_events": control["evidence"],
            },
            "activated_by": control["event_types"],
        })

    ledger = {
        "schema_version": LEDGER_SCHEMA,
        "site_id": SITE_ID,
        "authority": "diagnostic-only",
        "clone_base_url": args.base_url,
        "generated_by": "tools/build_interaction_ledger.py",
        "sources": {
            "trajectories": [
                f"artifacts/trajectory/{trace_id}/actions.jsonl"
                for trace_id in TRAJECTORIES
            ],
            "note": (
                "Selectors use only recorder-captured attributes "
                "(tag/id/name/input_type); the recorder omits element text "
                "and input values, so every proof string is extracted from "
                "the running clone DOM."
            ),
        },
        "mutation_boundary": {
            "note": (
                "The funnel and portal are fetch-driven; no <form "
                "method=\"post\"> exists in the clone. The API accepts zero "
                "payment fields (422 errors.payment); checkout submission and "
                "portal member mutations were not activated by the recorded "
                "walk and are not synthesized here."
            ),
            "unexercised_endpoints": [
                "POST /api/quotes/{quote_id}/enroll",
                "POST /api/quotes/{quote_id}/pets",
                "GET /api/quotes/search",
                "POST /portal/api/login",
                "POST /portal/api/forgot-password",
                "POST /portal/api/register",
            ],
        },
        "controls": entries,
        "unlocated_controls": [
            {
                "tag": c["tag"], "id": c["id"], "name": c["name"],
                "input_type": c["input_type"],
                "activated_by": c["event_types"],
                "evidence": c["evidence"],
                "note": (
                    "No id/name attribute captured by the recorder (or the "
                    "element is generated at runtime); not locatable in a "
                    "served document without inferring, so recorded without "
                    "proofs rather than guessed."
                ),
            }
            for c in unlocated
        ],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
    located_ids = [e["selector"] for e in entries]
    print(f"ledger: {output}")
    print(f"controls located: {len(entries)}; unlocated: {len(unlocated)}")
    print("selectors:", ", ".join(located_ids))
    missing_proofs = [e["selector"] for e in entries
                      if not e["visible_text_proof"] or not e["raw_markup_proof"]]
    if missing_proofs:
        print("MISSING PROOFS:", ", ".join(missing_proofs))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
