#!/usr/bin/env python3
"""Freeze the aspca-pet-insurance scope against the r1 capture evidence.

Modeled on materials/tripit/tools/build_scope.py, adapted to this site's
pre-declared evidence topology (scope/checkpoints.json topology_note): the
pixel-locked visual_contract oracle is exactly home.{desktop,tablet,mobile};
every other captured (checkpoint, viewport) is retained as a frozen source
raster via source_artifact_path and witnessed by browser evidence.

Deterministically, from source-current capture artifacts only (no candidate
render exists), this tool:

  * renames the quote-save.desktop draft row to quote-resume.desktop and adds
    quote-add-a-pet.desktop (capture evidence showed no save-quote affordance;
    the funnel's persistence surface is the deep-linkable #/quote-search
    resume route, and the /\\bsave\\b/i probe instead hit the 'Add a Pet
    Save 10%' upsell, honestly relabeled at capture time);
  * normalizes each captured frame set to the frozen viewport box and writes
    frame-1.viewport.png (the exact-viewport contract artifact);
  * measures 3-frame pairwise flicker per region (full + DOM landmarks) and
    derives thresholds = min(0.995, flicker_floor - 0.002);
  * binds visual_contract + region_contracts on the three home checkpoints
    only; upgrades every other captured row to evidence_kind 'direct' with a
    frozen source_artifact_path; leaves unavailable rows untouched;
  * writes scope/visual-calibration-spec.json (CLI spec schema) and
    scope/visual-calibration-report.json (per-region measurements);
  * writes source-current/<id>/capture-metadata.json (status: captured);
  * writes scope/claims.jsonl (capture + structural + unavailable claims);
  * updates the source-direct-states coverage denominator;
  * freezes scope/checkpoints.json (status frozen + freeze_decision).

Thresholds derive ONLY from source-side 3-frame calibration.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from PIL import Image, ImageChops, ImageStat

SITE = pathlib.Path(__file__).resolve().parents[1]
CAPTURE_ID = "2026-08-13.aspca-pet-insurance-r1"
CAP_ROOT = SITE / "source-current" / CAPTURE_ID
METRIC = "pixel-mae-similarity-v1"
BASE_THRESHOLD = 0.995
SAFETY_MARGIN = 0.002
# Below this full-region source flicker floor a pixel contract is
# meaningless; the row stays as reference evidence, not acceptance-eligible.
STABILITY_FLOOR = 0.98

VIEWPORTS = {
    "desktop": (1440, 900),
    "tablet": (1024, 768),
    "mobile": (390, 844),
}

# The pre-declared pixel oracle (scope/checkpoints.json topology_note).
ORACLE_IDS = {"home.desktop", "home.tablet", "home.mobile"}

PORTAL_MEMBER_IDS = {
    "portal-dashboard.desktop", "portal-policy-documents.desktop",
    "portal-claim-start.desktop", "portal-claim-status.desktop",
    "portal-billing.desktop",
}
PAYMENT_SIDE_IDS = {
    "quote-checkout-payment.desktop", "quote-checkout-review.desktop",
    "quote-confirmation.desktop", "quote-payment-retry.desktop",
}


def normalize(img: Image.Image, width: int, height: int) -> Image.Image:
    """Reduce a full-page frame to the frozen viewport box: crop wider frames
    (horizontal overflow is scrolled-out content) and pad shorter ones with
    white. Narrower frames indicate a broken capture."""
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


def similarity(a: Image.Image, b: Image.Image,
               box: tuple[int, int, int, int]) -> float:
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


def load_captures() -> list[dict]:
    index = json.loads((CAP_ROOT / "capture-index.json").read_text())["captures"]
    state_path = CAP_ROOT / "state-capture-index.json"
    if state_path.is_file():
        index += json.loads(state_path.read_text())["captures"]
    return [c for c in index if "error" not in c]


def checkpoint_surgery(rows: list[dict]) -> list[dict]:
    """quote-save.desktop -> quote-resume.desktop; insert quote-add-a-pet."""
    out: list[dict] = []
    for row in rows:
        if row["id"] == "quote-resume.desktop":
            return rows  # already applied (idempotent rerun)
    for row in rows:
        if row["id"] == "quote-save.desktop":
            resume = dict(row)
            resume["id"] = "quote-resume.desktop"
            resume["state"] = "resume-search"
            resume["note"] = (
                "Replaces the planned quote-save checkpoint: capture evidence "
                "showed no save-quote affordance on the plans view; the "
                "funnel's persistence surface is the deep-linkable "
                "#/quote-search resume route (Fetch a Previous Quote).")
            out.append(resume)
            out.append({
                "id": "quote-add-a-pet.desktop",
                "route_id": row.get("route_id", "quote"),
                "state": "add-a-pet-upsell",
                "role": row.get("role", "quote-lead"),
                "viewport": "desktop",
                "priority": "p1",
                "evidence_kind": "unavailable",
                "planned_evidence_kind": "directly-observed",
                "acceptance_eligible": False,
                "note": (
                    "Discovered during capture: the 'Add a Pet Save 10%' "
                    "upsell on the plans view navigates to #/add-a-pet. The "
                    "capture was originally aimed at a save-quote affordance "
                    "(a /\\bsave\\b/i text match) and was honestly relabeled; "
                    "see the checkpoint's meta.json relabel note."),
            })
        else:
            out.append(row)
    return out


def build() -> int:
    captures = load_captures()
    doc = json.loads((SITE / "scope" / "checkpoints.json").read_text())
    rows = checkpoint_surgery(doc["checkpoints"])
    by_id = {r["id"]: r for r in rows}

    calibration_rows: list[dict] = []
    report_rows: list[dict] = []
    claims: list[dict] = []
    direct_state_items: list[str] = []
    oracle_floors: dict[str, float] = {}

    for cap in captures:
        cp, vp = cap["checkpoint"], cap["viewport"]
        cid = f"{cp}.{vp}"
        row = by_id.get(cid)
        if row is None:
            raise SystemExit(f"captured state {cid} has no checkpoint row")
        width, height = VIEWPORTS[vp]
        dest = CAP_ROOT / cp / vp
        frames = [normalize(Image.open(dest / f"frame-{n}.png"), width, height)
                  for n in (1, 2, 3)]
        site_rel = f"source-current/{CAPTURE_ID}/{cp}/{vp}"
        repo_rel = f"materials/aspca-pet-insurance/{site_rel}"
        # The frozen contract artifact must be exactly viewport-sized.
        frames[0].save(dest / "frame-1.viewport.png", format="PNG")

        regions = {"full": {"x": 0, "y": 0, "width": width, "height": height}}
        for name, enum_name in (("header", "header"), ("main", "main"),
                                ("footer", "footer"), ("form", "action")):
            clipped = clip_region((cap.get("regions") or {}).get(name),
                                  width, height)
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
                "checkpoint_id": cid,
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
        row["evidence_kind"] = "direct"
        row.pop("planned_evidence_kind", None)
        row["capture_id"] = CAPTURE_ID
        row["requested_url"] = cap["requested_url"]
        row["final_url"] = cap["final_url"]
        row["title"] = cap["title"]
        if cid in ORACLE_IDS:
            oracle_floors[cid] = full["flicker_floor"]
            eligible = full["flicker_floor"] >= STABILITY_FLOOR
            row["acceptance_eligible"] = eligible
            if not eligible:
                row["acceptance_exclusion_reason"] = (
                    f"full-region source flicker floor "
                    f"{full['flicker_floor']} is below the {STABILITY_FLOOR} "
                    "stability minimum (continuous source-side animation); "
                    "frames retained as reference evidence, no pixel "
                    "acceptance claimed")
            row["visual_contract"] = {
                "source_artifact_path": f"{site_rel}/frame-1.viewport.png",
                "viewport": {"width": width, "height": height},
                "comparison_region": {"x": 0, "y": 0, "width": width,
                                      "height": height},
                "metric": METRIC,
                "threshold": full["threshold"],
            }
            row["region_contracts"] = [r for r in region_contracts
                                       if r["region"] != "full"]
        else:
            row["acceptance_eligible"] = False
            row["source_artifact_path"] = f"{site_rel}/frame-1.viewport.png"
        direct_state_items.append(cid)
        state = row.get("state", "loaded")
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
            "id": "claim.structural.www-canonical-origin",
            "kind": "directly-observed",
            "statement": (
                "GET https://www.aspcapetinsurance.com/ serves the marketing "
                "home directly (HTTP 200, no redirect); the quote funnel and "
                "member portal are Angular hash-routed SPAs under /quote/# "
                "and /portal/# on the same origin."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/home/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/quote-start/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/portal-login/desktop/meta.json",
            ],
        },
        {
            "id": "claim.structural.funnel-hash-routes",
            "kind": "directly-observed",
            "statement": (
                "The quote funnel's observed hash routes are #/start (quote "
                "form), #/plans (tier selector + Build Your Own Plan), "
                "#/add-a-pet (multi-pet upsell), #/quote-search (Fetch a "
                "Previous Quote resume surface), and #/checkout (contact "
                "details + billing frequency enrollment page)."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-start/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/quote-rates/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/quote-add-a-pet/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/quote-resume/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/quote-checkout/desktop/meta.json",
            ],
        },
        {
            "id": "claim.structural.quote-form-contract",
            "kind": "directly-observed",
            "statement": (
                "The #/start quote form collects species (Dog/Cat toggle), "
                "pet name, ZIP code, age (select), gender, breed (typeahead "
                "backed by GET /api/q/values/breeds/<species>), and email "
                "(#emailAddress); the submit control is the g-recaptcha "
                "'See My Rates' button. ZIP lookup calls "
                "/api/q/values/Zipcode/<zip> to resolve the state code."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-start/desktop/page.html",
                f"source-current/{CAPTURE_ID}/quote-start/desktop/resources.json",
            ],
        },
        {
            "id": "claim.structural.email-pattern-gate",
            "kind": "directly-observed",
            "statement": (
                "#emailAddress enforces ng-pattern "
                "/[a-z0-9A-Z._%+-]+@[a-z0-9A-Z.-]+\\.[a-zA-Z]{2,4}$/ — the "
                "TLD is capped at 4 characters, so .invalid addresses can "
                "never pass; submission with a failing address keeps the "
                "route on #/start and renders 'Verify that your email "
                "address is correct.' The capture therefore used a "
                "non-deliverable IANA-reserved example.com fallback address "
                "(real_email_authorized stays false; substitution recorded "
                "in the walk log)."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-start/desktop/page.html",
                f"source-current/{CAPTURE_ID}/walk-log-attempt1.json",
                f"source-current/{CAPTURE_ID}/walk-log.json",
            ],
        },
        {
            "id": "claim.structural.quote-start-validation",
            "kind": "directly-observed",
            "statement": (
                "Submitting the empty #/start form stays on #/start and "
                "renders per-field validation errors (captured as state "
                "quote-start-validation); entering ZIP 00000 renders "
                "'00000 is not a valid zip code.' (captured as state "
                "quote-ineligible)."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-start-validation/desktop/frame-1.png",
                f"source-current/{CAPTURE_ID}/quote-ineligible/desktop/frame-1.png",
                f"source-current/{CAPTURE_ID}/quote-ineligible/desktop/meta.json",
            ],
        },
        {
            "id": "claim.structural.rates-tier-contract",
            "kind": "directly-observed",
            "statement": (
                "For the frozen Willow scenario (Cat, Domestic Shorthair, "
                "2 Years, Female, ZIP 44301) #/plans offered three preset "
                "Complete Coverage tiers priced $8.48/mo ($500 deductible / "
                "$2,500 annual limit), $16.74/mo ($500 / $5,000), and "
                "$23.19/mo ($500 / $10,000), plus preventive-care add-ons "
                "Basic $9.95/mo and Prime $24.95/mo, an "
                "#accordBtn-build-your-own customization accordion, an 'Add "
                "a Pet Save 10%' upsell, and a Continue CTA "
                "(controller.submit()) into #/checkout."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-rates/desktop/page.html",
                f"source-current/{CAPTURE_ID}/rating-claims.json",
            ],
        },
        {
            "id": "claim.structural.rating-recalculation",
            "kind": "directly-observed",
            "statement": (
                "Build Your Own Plan radio changes re-rate live: from the "
                "$16.74/mo baseline, deductible $500->$250 (input 250l2, "
                "value Deductible250) re-rated to $23.65/mo; reimbursement "
                "80%->90% (90l2, Copay10) re-rated to $30.83/mo; the annual "
                "limit $5,000 click (5000l2, Limit5000) landed checked with "
                "no price change (custom layer already at $5,000); 'Add "
                "Basic' preventive care attached at $9.95/mo without "
                "changing the tier price (billed as a separate line). "
                "Radio inputs are visually hidden; the interactive surface "
                "is label[for=...], and ids start with digits so attribute "
                "selectors are required."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/rating-claims.json",
                f"source-current/{CAPTURE_ID}/quote-plan-customize/desktop/page.html",
            ],
        },
        {
            "id": "claim.structural.checkout-contract",
            "kind": "directly-observed",
            "statement": (
                "#/checkout is a contact-details enrollment page with 15 "
                "controls (firstName, lastName, address1, address2, city, "
                "stateSelect, zipcode, phone, email, marketingCodeSelect, "
                "Monthly/Annually billing-frequency radios, agreeTerms, "
                "paperless, submit) and ZERO payment-instrument fields — no "
                "card, cvc, expiry, or bank inputs exist on this route. "
                "Capture stopped here: no field on this page was focused or "
                "filled (authorization hard stop honored by construction)."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-checkout/desktop/page.html",
                f"source-current/{CAPTURE_ID}/walk-log.json",
            ],
        },
        {
            "id": "claim.structural.no-save-affordance",
            "kind": "directly-observed",
            "statement": (
                "The #/plans view exposes no save-quote affordance; the "
                "funnel's persistence surface is the deep-linkable "
                "#/quote-search 'Fetch a Previous Quote' route. The original "
                "save-probe (/\\bsave\\b/i) instead hit the 'Add a Pet Save "
                "10%' upsell and navigated to #/add-a-pet; that capture was "
                "relabeled quote-add-a-pet with the relabel reason recorded "
                "in its meta.json."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/quote-resume/desktop/meta.json",
                f"source-current/{CAPTURE_ID}/quote-add-a-pet/desktop/meta.json",
            ],
        },
        {
            "id": "claim.structural.portal-login-contract",
            "kind": "directly-observed",
            "statement": (
                "/portal/#/login is the Member Center sign-in shell with "
                "email + password fields, client-side validation on invalid "
                "email (captured as portal-login-validation), a forgot-"
                "password flow, and a registration entry; no credentials "
                "were entered beyond a one-character non-secret placeholder "
                "used to trigger validation."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/portal-login/desktop/page.html",
                f"source-current/{CAPTURE_ID}/portal-login-validation/desktop/frame-1.png",
                f"source-current/{CAPTURE_ID}/portal-forgot-password/desktop/frame-1.png",
                f"source-current/{CAPTURE_ID}/portal-register/desktop/frame-1.png",
            ],
        },
        {
            "id": "claim.structural.ab-testing-baseline",
            "kind": "structural-only",
            "statement": (
                "The source runs the Kameleoon A/B framework. Each capture "
                "round used one Browserbase session for all viewports "
                "(viewport switching instead of new sessions) so the A/B "
                "assignment stayed constant across every frame in a round."),
            "evidence_refs": [
                f"source-current/{CAPTURE_ID}/home/desktop/page.html",
                f"source-current/{CAPTURE_ID}/session-fingerprint.json",
            ],
        },
        {
            "id": "claim.structural.asset-closure",
            "kind": "structural-only",
            "statement": (
                "The source capture retains 502 asset rows. Candidate "
                "reference analysis marks 212 as required (210 P0), and all "
                "212 required files and recursive reference edges verify "
                "with required_closure=1.0 and no blocking issue. Optional "
                "historical captures remain catalogued but are not claimed "
                "as candidate runtime dependencies."),
            "evidence_refs": [
                "source-assets/manifest.json",
                "source-assets/unresolved-references.json",
            ],
        },
    ]

    unavailable_claims = [
        {
            "id": f"claim.unavailable.{cid.rsplit('.', 1)[0]}",
            "kind": "unavailable",
            "statement": (
                f"{cid.rsplit('.', 1)[0]} was not captured: member-portal "
                "surfaces require the user's read-only credential handoff, "
                "which had not been granted when capture reached them. No "
                "inference is credited and the clone does not implement the "
                "authenticated surface. Anonymous portal operations fail "
                "closed pending a separately authorized capture round."),
            "evidence_refs": [],
        }
        for cid in sorted(PORTAL_MEMBER_IDS)
    ] + [
        {
            "id": f"claim.unavailable.{cid.rsplit('.', 1)[0]}",
            "kind": "unavailable",
            "statement": (
                f"{cid.rsplit('.', 1)[0]} was not captured by policy: the "
                "authorization boundary stops the source walk before any "
                "payment field, so the real funnel's post-checkout payment, "
                "review, confirmation, and payment-retry surfaces were "
                "never reached. The clone adds an explicitly labeled local-"
                "sandbox continuation that accepts no payment credentials "
                "and carries no source-pixel or source-behavior claim."),
            "evidence_refs": [],
        }
        for cid in sorted(PAYMENT_SIDE_IDS)
    ]
    claims = structural_claims + unavailable_claims + claims

    now = dt.datetime.now(dt.timezone.utc)
    decided_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    doc["checkpoints"] = rows
    doc["status"] = "frozen"
    doc["topology_note"] = (
        "Frozen evidence topology (petfinder/edx/tripit pattern): the "
        "pixel-locked visual_contract oracle is exactly the three "
        "home.{desktop,tablet,mobile} checkpoints (threshold = min(0.995, "
        "flicker_floor - 0.002), full region, zero ignore regions); every "
        "other captured state is retained as a frozen source raster via "
        "source_artifact_path and witnessed by browser evidence, keeping "
        "the acceptance-evidence artifact count under the schema's "
        "100-artifact ceiling. Authenticated member-portal surfaces and "
        "the post-checkout payment-side surfaces remain "
        "evidence_kind=unavailable with recorded reasons.")
    doc["freeze_decision"] = {
        "named_supervisor": "claude-fable-5-offline-clone-run",
        "decided_at": decided_at,
        "rationale": (
            "Anonymous marketing, quote-funnel, and portal-shell contracts "
            f"freeze against the {CAPTURE_ID} three-frame capture before "
            "any candidate render exists. Thresholds derive only from "
            "source-side flicker floors (threshold = min(0.995, floor - "
            "0.002)); no ignore regions exist. Following the reference "
            "topology, the pixel oracle is exactly home.{desktop,tablet,"
            "mobile}; the other captured states are frozen source rasters "
            "witnessed by browser evidence (git history is the integrity "
            "ledger for retained bytes). Funnel interaction states were "
            "reached under the quote-funnel-synthetic-submission grant with "
            "the frozen Willow scenario; the walk stopped at the #/checkout "
            "contact page, which contains no payment fields. Member-portal "
            "checkpoints stay unavailable pending the user's read-only "
            "credential handoff; payment-side checkpoints stay unavailable "
            "by authorization policy. A later authenticated round may add "
            "checkpoints without altering these contracts."),
    }

    calibration = {
        "schema_version": "offline-clone.visual-stability-calibration-spec.v1",
        "site_id": "aspca-pet-insurance",
        "rows": calibration_rows,
    }
    calibration_report = {
        "schema_version": "aspca-pet-insurance.visual-calibration-report.v1",
        "status": "frozen",
        "site_id": "aspca-pet-insurance",
        "capture_id": CAPTURE_ID,
        "frames_per_checkpoint": 3,
        "metric": METRIC,
        "threshold_rule": (
            "threshold = min(0.995, flicker_floor - 0.002) per region, where "
            "flicker_floor is the minimum pairwise pixel-mae-similarity-v1 "
            "across the three pre-candidate source frames normalized to the "
            "frozen viewport box. Derived before any candidate render "
            "existed."),
        "rows": report_rows,
    }

    metadata = {
        "schema_version": "aspca-pet-insurance.capture-metadata.v1",
        "status": "captured",
        "capture_id": CAPTURE_ID,
        "captured_at_utc": "2026-08-13",
        "source_origins": ["https://www.aspcapetinsurance.com/"],
        "engine": {
            "primary": "browserbase",
            "region": "us-east-1",
            "browser": "Chromium headless via Playwright connect_over_cdp",
            "notes": (
                "The browserbase MCP endpoint is retired (410); sessions "
                "were created over the Browserbase REST API (blockAds + "
                "solveCaptchas) and driven with local Playwright over CDP. "
                "One session per capture round, switching viewport sizes "
                "in-session so the Kameleoon A/B assignment stayed constant. "
                "Funnel interaction states were captured under the "
                "quote-funnel-synthetic-submission grant (Willow scenario); "
                "the email field used a non-deliverable IANA-reserved "
                "example.com fallback because the funnel's ng-pattern "
                "rejects the .invalid TLD. The walk stopped at the "
                "#/checkout contact page; no payment field exists there and "
                "none was focused or filled."),
        },
        "baseline": {
            "locale": "en-US",
            "timezone": "America/New_York",
            "consent": "osano-accept-all-once-per-session",
        },
        "viewports": [
            {"name": k, "width": w, "height": h}
            for k, (w, h) in VIEWPORTS.items()
        ],
        "roles_captured": ["anonymous"],
        "roles_unavailable": {
            "member": (
                "pending the user's read-only credential handoff; portal "
                "capture will be GET-navigation only when granted"),
        },
        "frames_per_checkpoint": 3,
        "captures": [
            {k: c[k] for k in ("checkpoint", "viewport", "requested_url",
                               "final_url", "title", "frames", "frame_sha256",
                               "frames_identical", "engine")}
            for c in captures
        ],
    }

    coverage = json.loads((SITE / "scope" / "coverage.json").read_text())
    for dim in coverage["dimensions"]:
        if dim["id"] == "source-direct-states":
            dim["required_items"] = sorted(direct_state_items)
            dim["rationale"] = (
                "Post-freeze denominator: every anonymous state captured "
                f"directly from the source in {CAPTURE_ID}. Each item "
                "carries a frozen three-frame source raster; the pixel "
                "oracle subset is home.{desktop,tablet,mobile}.")

    (SITE / "scope" / "visual-calibration-spec.json").write_text(
        json.dumps(calibration, indent=2) + "\n")
    (SITE / "scope" / "visual-calibration-report.json").write_text(
        json.dumps(calibration_report, indent=2) + "\n")
    (SITE / "scope" / "checkpoints.json").write_text(
        json.dumps(doc, indent=2) + "\n")
    (SITE / "scope" / "coverage.json").write_text(
        json.dumps(coverage, indent=2) + "\n")
    with (SITE / "scope" / "claims.jsonl").open("w") as fh:
        for claim in claims:
            fh.write(json.dumps(claim) + "\n")
    (CAP_ROOT / "capture-metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n")

    floors = sorted((row["flicker_floor"], row["id"])
                    for row in report_rows if row["region"] == "full")
    print(f"checkpoints: {len(rows)}  captured: {len(direct_state_items)}  "
          f"calibration rows: {len(calibration_rows)}  report rows: "
          f"{len(report_rows)}  claims: {len(claims)}")
    print("oracle full-region floors:",
          {k: round(v, 6) for k, v in sorted(oracle_floors.items())})
    print("lowest full-region flicker floors:")
    for floor, rid in floors[:8]:
        print(f"  {floor:.6f}  {rid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
