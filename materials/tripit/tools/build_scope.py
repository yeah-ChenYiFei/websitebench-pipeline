#!/usr/bin/env python3
"""Build the frozen tripit scope artifacts from capture evidence.

Generates, deterministically from source-current capture artifacts plus the
hand-frozen semantic files (purpose/invariants/journeys/deterministic-seed):

  scope/routes.json                 observed + declared-unavailable route table
  scope/visual-calibration-spec.json  3-frame flicker measurements per region
  scope/checkpoints.json            frozen visual contracts (threshold derived
                                    from pre-candidate source flicker floors)
  scope/claims.jsonl                directly-observed / structural / unavailable
  scope/coverage.json               dimensions incl. seed cross-references
  source-current/<id>/capture-metadata.json  status: captured

Thresholds and ignore regions are derived ONLY from source-side 3-frame
calibration; no candidate render exists at build time (clone/app.py raises).
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from PIL import Image, ImageChops, ImageStat

SITE = pathlib.Path(__file__).resolve().parents[1]
REPO = SITE.parents[1]
CAPTURE_ID = "2026-08-03.tripit-r1"
CAP_ROOT = SITE / "source-current" / CAPTURE_ID
METRIC = "pixel-mae-similarity-v1"
BASE_THRESHOLD = 0.995
SAFETY_MARGIN = 0.002
# Below this full-region source flicker floor the page animates too much for
# a meaningful pixel contract; the checkpoint stays in scope as reference
# evidence but is not acceptance-eligible.
STABILITY_FLOOR = 0.98

VIEWPORTS = {
    "desktop": (1440, 900),
    "tablet": (1024, 768),
    "mobile": (390, 844),
}

# checkpoint id -> route id
ROUTE_OF = {
    "home": "web-home", "free": "web-free", "pro": "web-pro",
    "how-it-works": "how-it-works", "pricing": "pricing",
    "sap-concur": "sap-concur", "download": "download", "security": "security",
    "blog-index": "blog-index",
    "traveler-resource-center": "traveler-resource-center",
    "login": "account-login", "create": "account-create",
    "forgot-password": "account-forgot-password",
    "legal-user-agreement": "uhp-user-agreement",
    "legal-privacy": "uhp-privacy", "legal-do-not-share": "uhp-do-not-share",
    "home-lang-menu-open": "web-home", "home-mobile-menu-open": "web-home",
    "login-client-validation": "account-login",
}

STATE_OF = {
    "home-lang-menu-open": "lang-menu-open",
    "home-mobile-menu-open": "mobile-menu-open",
    "login-client-validation": "client-validation-error",
}

OBSERVED_ROUTES = [
    ("root-redirect", "/", "p0", "entry-redirect",
     "GET / responds by landing the browser on /web (observed final_url)."),
    ("web-home", "/web", "p0", "marketing-home", None),
    ("web-free", "/web/free", "p1", "product-free", None),
    ("web-pro", "/web/pro", "p1", "product-pro", None),
    ("how-it-works", "/web/free/how-it-works", "p1", "product-explainer", None),
    ("pricing", "/web/pro/pricing", "p1", "pro-pricing", None),
    ("sap-concur", "/web/pro/sap-concur", "p2", "partner-page", None),
    ("download", "/web/free/download", "p2", "app-download", None),
    ("security", "/web/security", "p2", "security-statement", None),
    ("blog-index", "/web/blog", "p2", "editorial-index", None),
    ("traveler-resource-center", "/web/traveler-resource-center", "p2",
     "editorial-index", None),
    ("account-login", "/account/login", "p0", "auth-sign-in", None),
    ("account-create", "/account/create", "p0", "auth-registration", None),
    ("account-forgot-password", "/account/forgotPassword", "p0",
     "auth-password-reset", None),
    ("uhp-user-agreement", "/uhp/userAgreement", "p2", "legal", None),
    ("uhp-privacy", "/uhp/privacyPolicy", "p2", "legal", None),
    ("uhp-do-not-share", "/uhp/doNotShare", "p2", "legal", None),
]

UNAVAILABLE_FAMILIES = [
    ("app-trips-list", "Upcoming/Past/Unfiled trips list"),
    ("app-trip-itinerary", "Trip detail timeline with expanded plan rows"),
    ("app-plan-forms", "Add/edit forms and detail views for the 12 plan types"),
    ("app-import-surface", "Email-import surfaces: forward copy, Unfiled, history"),
    ("app-share-dialogs", "Share invite/role/revoke dialogs"),
    ("app-documents", "Document upload/preview/download surfaces"),
    ("app-account-settings", "Profile, traveler profile, notifications, settings"),
    ("app-pro-surfaces", "Pro upgrade, status, cancel, and Pro feature surfaces"),
]


def normalize(img: Image.Image, width: int, height: int) -> Image.Image:
    """Reduce a full-page frame to the frozen viewport box: crop wider frames
    (horizontal overflow beyond the viewport is scrolled-out content) and pad
    shorter ones with white. Narrower frames indicate a broken capture."""
    img = img.convert("RGB")
    if img.width < width:
        raise SystemExit(f"frame width {img.width} < viewport width {width}")
    if img.width > width:
        img = img.crop((0, 0, width, img.height))
    if img.height >= height:
        return img.crop((0, 0, width, height))
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    canvas.paste(img, (0, 0))
    return canvas


def similarity(a: Image.Image, b: Image.Image, box: tuple[int, int, int, int]) -> float:
    diff = ImageChops.difference(a.crop(box), b.crop(box))
    return 1.0 - sum(ImageStat.Stat(diff).mean) / (255 * len(diff.getbands()))


def clip_region(reg: dict | None, width: int, height: int) -> dict | None:
    if not reg:
        return None
    x = max(0, min(reg["x"], width))
    y = max(0, min(reg["y"], height))
    x2 = max(0, min(reg["x"] + reg["width"], width))
    y2 = max(0, min(reg["y"] + reg["height"], height))
    if x2 - x < 8 or y2 - y < 8:
        return None
    return {"x": x, "y": y, "width": x2 - x, "height": y2 - y}


def main() -> int:
    index = json.loads((CAP_ROOT / "capture-index.json").read_text())["captures"]
    state_path = CAP_ROOT / "state-capture-index.json"
    if state_path.is_file():
        index += json.loads(state_path.read_text())["captures"]
    captures = [c for c in index if "error" not in c]

    seed = json.loads((SITE / "scope" / "deterministic-seed.json").read_text())
    journeys = json.loads((SITE / "scope" / "journeys.json").read_text())["journeys"]

    calibration_rows: list[dict] = []
    report_rows: list[dict] = []
    checkpoints: list[dict] = []
    claims: list[dict] = []
    direct_state_items: list[str] = []

    for cap in captures:
        cp, vp = cap["checkpoint"], cap["viewport"]
        width, height = VIEWPORTS[vp]
        dest = CAP_ROOT / cp / vp
        frames = [normalize(Image.open(dest / f"frame-{n}.png"), width, height)
                  for n in (1, 2, 3)]
        site_rel = f"source-current/{CAPTURE_ID}/{cp}/{vp}"
        repo_rel = f"materials/tripit/{site_rel}"
        # The frozen contract artifact must be exactly viewport-sized (repo
        # manifest validation); persist the normalized frame-1 crop.
        viewport_png = dest / "frame-1.viewport.png"
        frames[0].save(viewport_png, format="PNG")
        viewport_sha = hashlib.sha256(viewport_png.read_bytes()).hexdigest()

        # Calibration-spec region enum is header/main/action/overlay/footer;
        # the DOM "form" landmark maps to "action". The full-viewport box is
        # measured in the report and bound on the checkpoint contract itself.
        regions = {"full": {"x": 0, "y": 0, "width": width, "height": height}}
        for name, enum_name in (("header", "header"), ("main", "main"),
                                 ("footer", "footer"), ("form", "action")):
            clipped = clip_region((cap.get("regions") or {}).get(name), width, height)
            if clipped and enum_name not in regions:
                regions[enum_name] = clipped

        region_contracts = []
        for rname, reg in regions.items():
            box = (reg["x"], reg["y"], reg["x"] + reg["width"],
                   reg["y"] + reg["height"])
            sims = [round(similarity(frames[i], frames[j], box), 6)
                    for i, j in ((0, 1), (0, 2), (1, 2))]
            floor = min(sims)
            threshold = round(min(BASE_THRESHOLD, floor - SAFETY_MARGIN), 4)
            report_rows.append({
                "id": f"{cp}.{vp}.{rname}",
                "checkpoint_id": f"{cp}.{vp}",
                "region": rname,
                "region_box": reg,
                "pairwise_similarity": sims,
                "flicker_floor": floor,
                "derived_threshold": threshold,
            })
            if rname != "full":
                calibration_rows.append({
                    "id": f"{cp}.{vp}.{rname}",
                    "region": rname,
                    "source_samples": [
                        {"path": f"{repo_rel}/frame-{n}.png"}
                        for n in (1, 2, 3)
                    ],
                    "ignore_regions": [],
                })
            region_contracts.append({
                "region": rname, "box": reg, "threshold": threshold,
                "flicker_floor": floor,
            })

        full = next(r for r in region_contracts if r["region"] == "full")
        priority = cap["priority"].lower()
        state = STATE_OF.get(cp, "loaded")
        eligible = full["flicker_floor"] >= STABILITY_FLOOR
        checkpoints.append({
            "id": f"{cp}.{vp}",
            "route_id": ROUTE_OF[cp],
            "state": state,
            "role": "visitor.anonymous",
            "viewport": vp,
            "priority": priority,
            "evidence_kind": "direct",
            "capture_id": CAPTURE_ID,
            "requested_url": cap["requested_url"],
            "final_url": cap["final_url"],
            "title": cap["title"],
            "acceptance_eligible": eligible,
            **({} if eligible else {"acceptance_exclusion_reason": (
                f"full-region source flicker floor {full['flicker_floor']} is "
                f"below the {STABILITY_FLOOR} stability minimum (continuous "
                "source-side animation); frames retained as reference "
                "evidence, no pixel acceptance claimed")}),
            "visual_contract": {
                "source_artifact_path": f"{site_rel}/frame-1.viewport.png",
                "source_artifact_sha256": viewport_sha,
                "viewport": {"width": width, "height": height},
                "comparison_region": {"x": 0, "y": 0, "width": width,
                                       "height": height},
                "metric": METRIC,
                "threshold": full["threshold"],
            },
            "region_contracts": [r for r in region_contracts
                                  if r["region"] != "full"],
        })
        direct_state_items.append(f"{cp}.{vp}")
        claims.append({
            "id": f"claim.capture.{cp}.{vp}",
            "kind": "directly-observed",
            "statement": (
                f"Checkpoint {cp} ({state}) at {vp} {width}x{height} was "
                f"captured from {cap['final_url']} with 3 full-page frames, "
                f"DOM html, link census, and region geometry; title "
                f"{cap['title']!r}, body length {cap['body_text_len']}."),
            "evidence_refs": [
                f"{site_rel}/frame-1.png", f"{site_rel}/frame-2.png",
                f"{site_rel}/frame-3.png", f"{site_rel}/meta.json",
                f"{site_rel}/page.html", f"{site_rel}/links.json",
            ],
        })

    structural_claims = [
        {
            "id": "claim.structural.root-redirect",
            "kind": "directly-observed",
            "statement": "GET https://www.tripit.com/ lands the browser on /web (final_url observed for the home checkpoint at every viewport).",
            "evidence_refs": [f"source-current/{CAPTURE_ID}/home/desktop/meta.json"],
        },
        {
            "id": "claim.structural.login-form-contract",
            "kind": "directly-observed",
            "statement": "The login form posts fields csrf_token, errors, toc, redirect_url (hidden), login_email_address (email), login_password (password), remember_me (checkbox id remember-me-checkbox); links to /account/forgotPassword, /account/signInGoogle, /account/create.",
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/login/desktop/page.html",
                f"source-current/{CAPTURE_ID}/login/desktop/links.json",
            ],
        },
        {
            "id": "claim.structural.create-form-contract",
            "kind": "directly-observed",
            "statement": "The registration form has csrf_token/errors/toc/redirect_url hidden fields, email_address, password (helper: 'At least 15 characters. Cannot be an email.'), place (Home City), user-agreement-and-privacy checkbox, and /account/signUpGoogle SSO.",
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/create/desktop/page.html",
            ],
        },
        {
            "id": "claim.structural.login-client-validation",
            "kind": "directly-observed",
            "statement": "Typing an invalid email and blurring shows the red floating label and 'Please use a valid email address.' with no network request; captured as state client-validation-error.",
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/login-client-validation/desktop/frame-1.png",
                f"source-current/{CAPTURE_ID}/login-client-validation/desktop/meta.json",
            ],
        },
        {
            "id": "claim.structural.trustarc-consent-gate",
            "kind": "directly-observed",
            "statement": "tripit.com is gated by a TrustArc consent manager; without stored consent the EU-expressed flow blocks content behind 'Please wait while we attempt to load your cookie preferences.' The capture baseline presets expressed-consent cookies; the consent modal itself ('About cookies on this site' / Accept All Cookies / Reject All) was observed from the lax-region session.",
            "evidence_refs": [f"source-current/{CAPTURE_ID}/home/desktop/page.html"],
        },
        {
            "id": "claim.structural.language-menu",
            "kind": "directly-observed",
            "statement": "The EN control opens a language menu adding locale destinations English (UK) /en-uk/web, Francais /fr/web, Deutsch /de/web, Espanol (Latinoamerica) /es-co/web, Espanol (Espana) /es/web; captured as home-lang-menu-open.",
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/home-lang-menu-open/desktop/frame-1.png",
                f"source-current/{CAPTURE_ID}/home-lang-menu-open/desktop/links.json",
            ],
        },
        {
            "id": "claim.structural.mobile-menu",
            "kind": "directly-observed",
            "statement": "At 390x844 the header collapses to a hamburger button whose open state exposes the primary nav; captured as home-mobile-menu-open.",
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/home-mobile-menu-open/mobile/frame-1.png",
            ],
        },
        {
            "id": "claim.structural.http2-quirk",
            "kind": "structural-only",
            "statement": "Direct Chromium HTTP/2 navigation to /account/create intermittently fails with ERR_HTTP2_PROTOCOL_ERROR while the same URL serves over the request API; capture used retry plus HTTP/1.1 fallback. Recorded as a source-infrastructure observation, not a product behavior.",
            "evidence_refs": [],
        },
    ]
    unavailable_claims = [
        {
            "id": f"claim.unavailable.{route_id}",
            "kind": "unavailable",
            "statement": (
                f"{label} was not captured: authenticated source access requires "
                "the user-driven Steel Live View sign-in (Browserbase retired, "
                "402). No inference is credited; the clone implements this "
                "family as a declared local contract pending an authenticated "
                "capture round."),
            "evidence_refs": [],
        }
        for route_id, label in UNAVAILABLE_FAMILIES
    ]
    claims = structural_claims + unavailable_claims + claims

    routes = {
        "schema_version": "offline-clone.routes.v1",
        "status": "frozen",
        "site_id": "tripit",
        "routes": [
            {
                "id": rid, "route_pattern": pattern, "priority": prio,
                "purpose_edge": edge, "evidence_kind": "direct",
                "local_destination": True,
                "roles": ["visitor.anonymous"],
                **({"note": note} if note else {}),
            }
            for rid, pattern, prio, edge, note in OBSERVED_ROUTES
        ] + [
            {
                "id": rid,
                "route_pattern": f"unavailable-pending-authenticated-capture:{rid}",
                "priority": "p0", "purpose_edge": "authenticated-app",
                "evidence_kind": "unavailable", "local_destination": True,
                "roles": ["traveler.free-local", "traveler.pro-local"],
                "note": label,
            }
            for rid, label in UNAVAILABLE_FAMILIES
        ],
    }

    calibration = {
        "schema_version": "offline-clone.visual-stability-calibration-spec.v1",
        "site_id": "tripit",
        "rows": calibration_rows,
    }

    calibration_report = {
        "schema_version": "tripit.visual-calibration-report.v1",
        "status": "frozen",
        "site_id": "tripit",
        "capture_id": CAPTURE_ID,
        "frames_per_checkpoint": 3,
        "metric": METRIC,
        "threshold_rule": (
            "threshold = min(0.995, flicker_floor - 0.002) per region, where "
            "flicker_floor is the minimum pairwise pixel-mae-similarity-v1 "
            "across the three pre-candidate source frames normalized to the "
            "frozen viewport box. Derived before any candidate render existed."),
        "rows": report_rows,
    }

    checkpoints_doc = {
        "schema_version": "offline-clone.checkpoints.v1",
        "status": "frozen",
        "site_id": "tripit",
        "capture_id": CAPTURE_ID,
        "viewports": {k: {"width": w, "height": h}
                       for k, (w, h) in VIEWPORTS.items()},
        "metric": METRIC,
        "calibration_spec": "scope/visual-calibration-spec.json",
        "freeze_decision": {
            "named_supervisor": "claude-fable-5-offline-clone-run",
            "decided_at": "2026-08-04T14:30:00Z",
            "rationale": (
                "Anonymous marketing, auth-shell, legal, and interaction-state "
                "contracts freeze against the 2026-08-03.tripit-r1 three-frame "
                "capture before any candidate exists (clone/app.py raises "
                "NotImplementedError). Thresholds derive only from source-side "
                "flicker floors (threshold = min(0.995, floor - 0.002)); no "
                "ignore regions exist. Checkpoints whose full-region flicker "
                "floor falls below the 0.98 stability minimum (continuously "
                "animated source surfaces) are acceptance_eligible=false and "
                "retained as reference evidence only. Authenticated surfaces "
                "are excluded as evidence_kind=unavailable and a later "
                "authenticated round may add checkpoints without altering "
                "these contracts."),
        },
        "checkpoints": checkpoints,
    }

    p0_auth = [j["id"] for j in journeys
               if j["id"].startswith(("auth.", "anon.auth"))
               and j["priority"] == "p0"]
    p0_travel = [j["id"] for j in journeys
                 if j["id"].startswith(("trips.", "anchor.", "plans.",
                                        "documents.", "share.", "import."))
                 and j["priority"] == "p0"]
    seed_rows = [
        f"{row['entity_name']}::{row['storage_name']}::"
        f"count={row['expected_row_count']}"
        for row in seed["entities"]
    ]
    reset_probes = [row["id"] for row in seed["reset_probes"]]
    coverage = {
        "schema_version": "offline-clone.coverage.v1",
        "status": "frozen",
        "dimensions": [
            {
                "id": "source-direct-states",
                "label": "Anonymous states captured directly from tripit.com",
                "unit": "state",
                "category": "source",
                "required_evidence_kinds": ["browser", "visual"],
                "required_items": sorted(direct_state_items),
                "satisfied_items": [],
                "rationale": "Every captured checkpoint x viewport carries a frozen three-frame visual contract.",
            },
            {
                "id": "source-unavailable-states",
                "label": "Authenticated families declared unavailable this round",
                "unit": "family",
                "category": "source",
                "required_evidence_kinds": ["full-suite"],
                "required_items": [rid for rid, _ in UNAVAILABLE_FAMILIES],
                "satisfied_items": [],
                "rationale": "Authenticated/Pro source pixels await a user-driven Steel Live View session; families ship as declared local contracts with no visual acceptance claimed.",
            },
            {
                "id": "p0-auth-journeys",
                "label": "P0 auth journeys",
                "unit": "journey",
                "category": "functional",
                "required_evidence_kinds": ["full-suite"],
                "required_items": sorted(p0_auth),
                "satisfied_items": [],
                "rationale": "Registration, sign-in, reset, and session lifecycle with success/failure/retry outcomes.",
            },
            {
                "id": "p0-travel-journeys",
                "label": "P0 travel-domain journeys",
                "unit": "journey",
                "category": "functional",
                "required_evidence_kinds": ["full-suite"],
                "required_items": sorted(p0_travel),
                "satisfied_items": [],
                "rationale": "Trips, anchor hotel add, twelve plan types, import, sharing, and documents with success/failure/retry outcomes.",
            },
            {
                "id": "plan-type-rows",
                "label": "The twelve plan types",
                "unit": "plan-type",
                "category": "functional",
                "required_evidence_kinds": ["full-suite"],
                "required_items": ["air", "lodging", "car", "rail", "transport",
                                    "cruise", "restaurant", "meeting",
                                    "activity", "map", "directions", "note"],
                "satisfied_items": [],
                "rationale": "Each type must add/view/edit/delete/reorder/move with its registered field set.",
            },
            {
                "id": "import-fixture-rows",
                "label": "Deterministic import fixture library",
                "unit": "fixture",
                "category": "functional",
                "required_evidence_kinds": ["full-suite"],
                "required_items": [f["id"] for f in seed["import_fixtures"]],
                "satisfied_items": [],
                "rationale": "Parsed/updated/canceled/duplicate/unparseable outcomes plus trip-overlap and Unfiled routing.",
            },
            {
                "id": "payment-scenarios",
                "label": "Payment adapter scenarios",
                "unit": "scenario",
                "category": "functional",
                "required_evidence_kinds": ["full-suite"],
                "required_items": ["sandbox-pro-approved", "sandbox-pro-declined",
                                    "sandbox-pro-retryable",
                                    "stripe-test-checkout-verified-webhook"],
                "satisfied_items": [],
                "rationale": "Local sandbox tiers plus verified Stripe-test checkout; duplicate webhooks never double-activate.",
            },
            {
                "id": "share-role-rows",
                "label": "Share role matrix",
                "unit": "role",
                "category": "functional",
                "required_evidence_kinds": ["full-suite"],
                "required_items": ["viewer", "editor", "traveler",
                                    "show-sensitive-flag", "revoked"],
                "satisfied_items": [],
                "rationale": "Role-scoped visibility incl. sensitive-field masking and immediate revocation.",
            },
            {
                "id": "p0-network-invariants",
                "label": "Runtime network closure",
                "unit": "assertion",
                "category": "network",
                "required_evidence_kinds": ["network"],
                "required_items": ["zero-requests-to-tripit.com",
                                    "zero-requests-to-trustarc",
                                    "zero-requests-to-google-or-cdns",
                                    "same-origin-only-asset-graph"],
                "satisfied_items": [],
                "rationale": "The deployed clone must have zero TripIt runtime dependencies.",
            },
            {
                "id": "deterministic-seed-rows",
                "label": "Deterministic seed entities",
                "unit": "entity",
                "category": "backend",
                "required_evidence_kinds": ["migration", "full-suite"],
                "required_items": seed_rows,
                "satisfied_items": [],
                "rationale": "Physical SQLite rows after reset must match the frozen manifest exactly.",
            },
            {
                "id": "deterministic-reset-probes",
                "label": "Reset/restart probes",
                "unit": "probe",
                "category": "backend",
                "required_evidence_kinds": ["migration", "full-suite"],
                "required_items": reset_probes,
                "satisfied_items": [],
                "rationale": "Exact reseed, idempotent repeat, and restart round-trip.",
            },
        ],
    }

    metadata = {
        "schema_version": "tripit.capture-metadata.v1",
        "status": "captured",
        "capture_id": CAPTURE_ID,
        "captured_at_utc": "2026-08-04",
        "source_origins": ["https://www.tripit.com/"],
        "engine": {
            "primary": "steel-cloud-cdp",
            "region": "lax",
            "browser": "Chromium 151 headless via Playwright connect_over_cdp",
            "notes": "tripit.com blocks Steel's default egress region (nginx 500) and intermittently 500s lax; navigation used retry. TrustArc expressed-consent cookies preset. Local venv Playwright renders identically and served as cross-check.",
        },
        "baseline": {
            "locale": "en-US",
            "timezone": "America/New_York",
            "consent": "trustarc-expressed-eu-preset",
        },
        "viewports": [
            {"name": k, "width": w, "height": h}
            for k, (w, h) in VIEWPORTS.items()
        ],
        "roles_captured": ["anonymous"],
        "roles_unavailable": {
            "free-user": "pending user-driven Steel Live View sign-in",
            "pro-user": "pending user-driven Steel Live View sign-in",
        },
        "frames_per_checkpoint": 3,
        "captures": [
            {k: c[k] for k in ("checkpoint", "viewport", "requested_url",
                                "final_url", "title", "frames", "frame_sha256",
                                "frames_identical", "engine")}
            for c in captures
        ],
    }

    (SITE / "scope" / "routes.json").write_text(
        json.dumps(routes, indent=2) + "\n")
    (SITE / "scope" / "visual-calibration-spec.json").write_text(
        json.dumps(calibration, indent=2) + "\n")
    (SITE / "scope" / "visual-calibration-report.json").write_text(
        json.dumps(calibration_report, indent=2) + "\n")
    (SITE / "scope" / "checkpoints.json").write_text(
        json.dumps(checkpoints_doc, indent=2) + "\n")
    (SITE / "scope" / "coverage.json").write_text(
        json.dumps(coverage, indent=2) + "\n")
    with (SITE / "scope" / "claims.jsonl").open("w") as fh:
        for claim in claims:
            fh.write(json.dumps(claim) + "\n")
    (CAP_ROOT / "capture-metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n")

    floors = sorted(
        (row["flicker_floor"], row["id"])
        for row in report_rows if row["region"] == "full")
    print(f"checkpoints: {len(checkpoints)}  calibration rows: "
          f"{len(calibration_rows)}  report rows: {len(report_rows)}  "
          f"claims: {len(claims)}")
    print("lowest full-region flicker floors:")
    for floor, rid in floors[:8]:
        print(f"  {floor:.6f}  {rid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
