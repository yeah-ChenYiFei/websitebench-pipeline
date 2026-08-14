#!/usr/bin/env python3
"""Interaction-state capture for the ASPCA Pet Health Insurance quote funnel
and portal-auth surfaces via Browserbase CDP.

Walks the AngularJS hash-routed funnel under the user-granted
quote-funnel-synthetic-submission mutation with the synthetic Willow scenario
(cat, 2 Years, Female, Domestic Shorthair, ZIP 44301) and captures each state
in the same frame/meta layout as capture_source.py under
source-current/<capture_id>/<state_id>/<viewport>/.

Hard boundaries enforced in code:
  * HARD STOP before any payment field: no selector matching a card, CVC, or
    expiry input is ever focused or filled; checkout is captured page-load-only
    and its form structure is read from attributes without focusing anything.
  * The email field receives the recorded non-deliverable synthetic fallback
    address unless a human-provided address is passed via --email.
  * No portal credentials are entered here, ever (login-validation uses a
    syntactically invalid probe address and a one-character placeholder
    password that is not any real secret; nothing is submitted).

Besides frames, the walk emits under source-current/<capture_id>/:
  * walk-log.json      -- ordered action/observation log (ledger input)
  * rating-claims.json -- (input tuple -> observed prices) for the rating
                          table, provenance directly-observed
  * state-capture-index.json -- meta records for all interaction states

Selectors were extracted from the captured quote-start DOM
(source-current/2026-08-13.aspca-pet-insurance-r1/quote-start/desktop/page.html):
species radios #dog/#cat, #petsName, #zipcode, #choAge (value "2" = 2 Years),
#male/#female, breed combobox #inputBreedList -> #breedComboBox items
#breedChoice-N, #emailAddress, submit button.g-recaptcha[type=submit]
("See My Rates").

Usage:
    python3 materials/aspca-pet-insurance/tools/capture_states.py \
        [--email human-provided@example.net] [--only quote-rates,...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from capture_source import (  # noqa: E402
    REGION_JS, bb_connect_url, bb_create_session, bb_release, bb_request,
    census, dismiss_consent, hide_scrollbars, resource_census, sha256_file,
)

SITE = pathlib.Path(__file__).resolve().parents[1]
CAPTURE_ID = "2026-08-13.aspca-pet-insurance-r1"
OUT = SITE / "source-current" / CAPTURE_ID
FUNNEL_URL = "https://www.aspcapetinsurance.com/quote/#/"
PORTAL_URL = "https://www.aspcapetinsurance.com/portal/#/login"
ORIGIN = "https://www.aspcapetinsurance.com"

# Recorded synthetic fallback (RFC 2606 reserved TLD, guaranteed
# non-deliverable). REAL_EMAIL_AUTHORIZED stays false when this is used.
# The funnel's ng-pattern caps the TLD at 4 chars, so a .invalid address can
# never validate; the recorded fallback is the IANA-reserved example.com.
FALLBACK_EMAIL = "willow-capture-2026-08-13@example.com"

WILLOW = {"species": "Cat", "name": "Willow", "zip": "44301",
          "age_value": "2", "age_label": "2 Years", "gender": "Female",
          "breed": "Domestic Shorthair"}

# Substrings that mark a field as payment-sensitive. Any field whose
# name/id/placeholder/label matches one of these is never focused or filled.
PAYMENT_MARKERS = ("card", "cvc", "cvv", "expir", "account number", "routing",
                   "bank", "billing zip", "cc-")

VIEWPORTS = {"desktop": (1440, 900), "tablet": (1024, 768),
             "mobile": (390, 844)}

PRICE_JS = """() => {
  const seen = [];
  const re = /\\$\\s?\\d[\\d,]*(?:\\.\\d{2})?(?:\\s*\\/\\s*(?:mo|month))?/g;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const t = walker.currentNode.textContent;
    let m;
    while ((m = re.exec(t)) !== null) {
      const el = walker.currentNode.parentElement;
      if (el && el.offsetParent !== null)
        seen.push({text: m[0].trim(),
                   context: (el.closest('[class]')?.className || '')
                             .toString().slice(0, 120)});
    }
  }
  return seen;
}"""

FORM_STRUCTURE_JS = """() => Array.from(
  document.querySelectorAll('input, select, textarea, button[type=submit]'))
  .filter(e => e.offsetParent !== null)
  .map(e => ({tag: e.tagName.toLowerCase(), type: e.type || null,
              name: e.name || null, id: e.id || null,
              placeholder: e.placeholder || null,
              label: (e.labels && e.labels[0] ? e.labels[0].innerText : null),
              autocomplete: e.getAttribute('autocomplete')}))"""

SELECT_CENSUS_JS = """() => Array.from(document.querySelectorAll('select'))
  .filter(e => e.offsetParent !== null)
  .map(e => ({id: e.id || null, name: e.name || null,
              label: (e.labels && e.labels[0] ? e.labels[0].innerText
                      : null),
              selected: e.value,
              options: Array.from(e.options).map(o => ({value: o.value,
                                                        text: o.text.trim()}))
             }))"""


class WalkError(RuntimeError):
    pass


class Walk:
    def __init__(self, page, email: str, email_is_human: bool):
        self.page = page
        self.email = email
        self.email_is_human = email_is_human
        self.log: list[dict] = []
        self.rating: list[dict] = []
        self.records: list[dict] = []
        self.on_rates = False

    # -- logging ---------------------------------------------------------
    def note(self, action: str, **detail) -> None:
        entry = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"), "action": action, **detail,
            "hash_route": self.page.evaluate("()=>location.hash")}
        self.log.append(entry)
        print(f"    . {action} {detail if detail else ''} "
              f"[{entry['hash_route']}]", flush=True)

    # -- guarded input ---------------------------------------------------
    def assert_not_payment(self, locator) -> None:
        ident = locator.evaluate(
            "e=>[e.name,e.id,e.placeholder,e.getAttribute('aria-label'),"
            "e.getAttribute('autocomplete'),"
            "e.labels&&e.labels[0]?e.labels[0].innerText:''"
            "].join(' ').toLowerCase()")
        if any(m in ident for m in PAYMENT_MARKERS):
            raise WalkError(f"payment-marked field refused: {ident!r}")

    def fill(self, selector: str, value: str, label: str) -> None:
        loc = self.page.locator(selector).first
        self.assert_not_payment(loc)
        loc.click()
        loc.fill(value)
        self.note("fill", field=label,
                  value=("<email>" if label == "email" else value))

    def choose(self, input_id: str, label: str) -> None:
        loc = self.page.locator(f"#{input_id}")
        try:
            loc.check(timeout=4000)
        except Exception:  # styled radio hides the input; click its label
            self.page.locator(f"label[for='{input_id}']").first.click()
        self.note("choose", field=label)

    # -- capture ---------------------------------------------------------
    def capture_state(self, state_id: str, family: str, priority: str,
                      viewports: list[str], interaction_note: dict,
                      settle_ms: int = 2500) -> None:
        for vp_name in viewports:
            width, height = VIEWPORTS[vp_name]
            self.page.set_viewport_size({"width": width, "height": height})
            self.page.wait_for_timeout(settle_ms)
            dest = OUT / state_id / vp_name
            dest.mkdir(parents=True, exist_ok=True)
            shas = []
            for n in range(1, 4):
                fp = dest / f"frame-{n}.png"
                self.page.screenshot(path=str(fp), full_page=True)
                shas.append(sha256_file(fp))
                if n < 3:
                    self.page.wait_for_timeout(700)
            (dest / "page.html").write_text(self.page.content())
            links = census(self.page)
            (dest / "links.json").write_text(json.dumps(links, indent=2))
            (dest / "resources.json").write_text(
                json.dumps(resource_census(self.page), indent=2))
            meta = {
                "checkpoint": state_id, "family": family,
                "priority": priority.upper(), "viewport": vp_name,
                "requested_url": PORTAL_URL if family == "portal-auth"
                else FUNNEL_URL,
                "final_url": self.page.url, "title": self.page.title(),
                "body_text_len": len(self.page.eval_on_selector(
                    "body", "e=>e.innerText")),
                "frames": 3, "frame_sha256": shas,
                "frames_identical": len(set(shas)) == 1,
                "link_count": len(links), "engine": "browserbase",
                "nav_fallback": None,
                "regions": self.page.evaluate(REGION_JS),
                "interaction": interaction_note,
            }
            (dest / "meta.json").write_text(json.dumps(meta, indent=2))
            self.records.append(meta)
            print(f"  ok {state_id}/{vp_name} "
                  f"{'=' if meta['frames_identical'] else '~'} "
                  f"body={meta['body_text_len']}", flush=True)
        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.wait_for_timeout(600)

    def prices(self) -> list[dict]:
        return self.page.evaluate(PRICE_JS)


# ---------------------------------------------------------------------------
# funnel navigation
# ---------------------------------------------------------------------------

def fresh_funnel(walk: Walk) -> None:
    """Reset SPA state (angular-local-storage persists form data)."""
    page = walk.page
    page.goto(ORIGIN + "/quote/", wait_until="domcontentloaded",
              timeout=60000)
    page.evaluate("()=>{try{localStorage.clear();sessionStorage.clear()}"
                  "catch(e){}}")
    page.goto(FUNNEL_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("text=See My Rates", timeout=30000)
    page.wait_for_timeout(2500)
    dismiss_consent(page)
    walk.on_rates = False
    walk.note("fresh-funnel")


def fill_willow(walk: Walk) -> None:
    walk.choose("cat", "species=Cat")
    walk.fill("#petsName", WILLOW["name"], "pet-name")
    walk.fill("#zipcode", WILLOW["zip"], "zip")
    walk.page.select_option("#choAge", WILLOW["age_value"])
    walk.note("select", field="age", value=WILLOW["age_label"])
    walk.choose("female", "gender=Female")
    # breed combobox: keystrokes drive the angular search list
    breed_input = walk.page.locator("#inputBreedList")
    breed_input.click()
    breed_input.press_sequentially(WILLOW["breed"], delay=40)
    walk.note("type", field="breed-search", value=WILLOW["breed"])
    try:
        item = walk.page.locator(
            "#breedComboBox >> text=" + WILLOW["breed"]).first
        item.click(timeout=8000)
    except Exception:
        walk.page.locator("#breedChoice-0").click(timeout=5000)
    walk.note("choose", field="breed", value=WILLOW["breed"])
    walk.fill("#emailAddress", walk.email, "email")


def submit_rates(walk: Walk) -> None:
    page = walk.page
    start_hash = page.evaluate("()=>location.hash")
    page.locator("button.g-recaptcha[type=submit]").first.click()
    walk.note("click", target="See My Rates")
    page.wait_for_function(
        "h => location.hash !== h", arg=start_hash, timeout=90000)
    page.wait_for_timeout(6000)
    try:
        page.wait_for_selector("text=/\\$\\s?\\d/", timeout=30000)
    except Exception:
        walk.note("warn", message="no price text detected after submit")
    walk.on_rates = True
    walk.note("rates-loaded", prices=walk.prices()[:12])


def ensure_rates(walk: Walk) -> None:
    # Guard against stale on_rates state: an earlier step may have navigated
    # the SPA away from the plans route without resetting the flag.
    if walk.on_rates:
        if walk.page.evaluate("()=>location.hash") != "#/plans":
            walk.on_rates = False
    if not walk.on_rates:
        fresh_funnel(walk)
        fill_willow(walk)
        submit_rates(walk)


def close_modal(walk: Walk) -> None:
    for sel in ("button.close:visible", "button[aria-label='Close']:visible"):
        loc = walk.page.locator(sel)
        if loc.count():
            try:
                loc.first.click(timeout=3000)
                walk.page.wait_for_timeout(800)
                return
            except Exception:
                continue


def click_by_text(walk: Walk, patterns: list[str],
                  timeout_ms: int = 5000) -> str | None:
    for pat in patterns:
        loc = walk.page.locator(
            "a:visible, button:visible").filter(
            has_text=re.compile(pat, re.I))
        if loc.count():
            try:
                loc.first.click(timeout=timeout_ms)
                return pat
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# walk steps
# ---------------------------------------------------------------------------

def step_validation(walk: Walk) -> None:
    fresh_funnel(walk)
    walk.page.locator("button.g-recaptcha[type=submit]").first.click()
    walk.note("click", target="See My Rates (empty form)")
    walk.page.wait_for_timeout(2500)
    walk.capture_state(
        "quote-start-validation", "quote-funnel", "p0", ["desktop"],
        {"action": "empty-submit", "performed":
         ["clicked See My Rates with all required fields empty",
          "captured inline validation state"]})


def step_rates(walk: Walk) -> None:
    ensure_rates(walk)
    walk.capture_state(
        "quote-rates", "quote-funnel", "p0",
        ["desktop", "tablet", "mobile"],
        {"action": "willow-submit", "performed":
         [f"filled Willow scenario ({WILLOW['species']}, {WILLOW['name']}, "
          f"ZIP {WILLOW['zip']}, {WILLOW['age_label']}, {WILLOW['gender']}, "
          f"{WILLOW['breed']})",
          "email: " + ("human-provided (withheld)" if walk.email_is_human
                       else "synthetic non-deliverable fallback"),
          "clicked See My Rates; waited for priced plan cards"]},
        settle_ms=4000)
    walk.rating.append({
        "inputs": {**{k: v for k, v in WILLOW.items()
                      if k != "age_value"}},
        "state": "quote-rates-initial",
        "hash_route": walk.page.evaluate("()=>location.hash"),
        "observed_prices": walk.prices(),
        "select_controls": walk.page.evaluate(SELECT_CENSUS_JS),
        "provenance": "directly-observed"})


def step_plan_detail(walk: Walk) -> None:
    """Open the coverage-detail panel from the plans view.

    Evidence (quote-rates/desktop/page.html): a 'See what's covered' button
    opens the detail panel with Coverage Details / FAQs tabs and coverage
    accordions. One accordion id embeds a curly apostrophe
    (accordBtn-What's-Not-Covered-faq), so accordions are clicked by text.
    """
    ensure_rates(walk)
    performed = []
    hit = click_by_text(walk, [r"see what'?s covered"], timeout_ms=8000)
    if hit:
        walk.note("click", target="See what's covered")
        walk.page.wait_for_timeout(3000)
        performed.append("clicked 'See what's covered'")
    else:
        performed.append("'See what's covered' affordance not found")
    # '.' in the patterns matches straight or curly apostrophes.
    for pat, name in ((r"what.s covered", "What's Covered"),
                      (r"what.s not covered", "What's Not Covered")):
        acc = walk.page.locator("button[id^='accordBtn']:visible").filter(
            has_text=re.compile(pat, re.I))
        opened = False
        if acc.count():
            try:
                acc.first.click(timeout=5000)
                opened = True
            except Exception:
                opened = False
        if opened:
            walk.note("click", target=f"accordion {name}")
            walk.page.wait_for_timeout(1500)
            performed.append(f"expanded accordion '{name}'")
        else:
            performed.append(f"accordion '{name}' not found")
    walk.capture_state(
        "quote-plan-detail", "quote-funnel", "p1", ["desktop"],
        {"action": "open-plan-detail", "performed": performed})
    close_modal(walk)


def step_resume(walk: Walk) -> None:
    """Capture the 'Fetch a Previous Quote' resume view (#/quote-search).

    Evidence (quote-rates/desktop/page.html): the plans view surfaces no
    save-quote affordance; the funnel's persistence surface is the nav link
    'Fetch a Previous Quote' -> #/quote-search, which is deep-linkable.
    """
    walk.page.goto(ORIGIN + "/quote/#/quote-search",
                   wait_until="domcontentloaded", timeout=60000)
    walk.page.wait_for_timeout(3000)
    dismiss_consent(walk.page)
    walk.on_rates = False
    walk.note("goto", target="#/quote-search (Fetch a Previous Quote)")
    performed = ["navigated directly to #/quote-search "
                 "('Fetch a Previous Quote')"]
    if walk.page.evaluate("()=>location.hash") != "#/quote-search":
        hit = click_by_text(walk, [r"fetch a previous quote"],
                            timeout_ms=8000)
        if hit:
            walk.note("click", target="Fetch a Previous Quote nav link")
            walk.page.wait_for_timeout(2500)
            performed.append("deep link redirected; reached the view via "
                             "the nav link instead")
        else:
            walk.note("warn", message="quote-search not reachable: deep "
                      "link redirected and nav link not found")
            performed.append("deep link redirected and nav link not found")
    performed += ["form view only; nothing submitted",
                  "no save-quote affordance exists on the plans view; "
                  "resume is the funnel's persistence surface"]
    walk.capture_state(
        "quote-resume", "quote-funnel", "p1", ["desktop"],
        {"action": "open-resume-quote", "performed": performed})


# Build-Your-Own-Plan radio targets, from quote-rates/desktop/page.html:
# each dimension is duplicated across responsive layers (id suffixes l1/l2,
# ng-models ...level1/level2); the radios are visually hidden, so the click
# goes to whichever layer's label[for] is visible. Targets differ from the
# initial selection ($500 deductible / 80% / varying limits) so a price
# delta is observable.
CUSTOMIZE_TARGETS = [
    ("deductible", ("250l2", "250l1"), "annual deductible -> $250"),
    ("reimbursement", ("90l2", "90l1"), "reimbursement -> 90%"),
    ("annual-limit", ("5000l2", "5000l1"), "annual limit -> $5,000"),
]


def click_visible_radio_label(walk: Walk, ids: tuple[str, ...]) -> str | None:
    # NB: ids start with a digit, so CSS '#250l2' is invalid — use
    # attribute selectors throughout.
    for rid in ids:
        lab = walk.page.locator(f"label[for='{rid}']")
        try:
            if lab.count() and lab.first.is_visible():
                lab.first.click(timeout=5000)
                return rid
        except Exception:
            continue
    return None


def step_customize(walk: Walk) -> None:
    ensure_rates(walk)
    performed = []
    try:
        walk.page.locator("#accordBtn-build-your-own").first.click(
            timeout=8000)
        walk.note("click", target="Build Your Own Plan accordion")
        walk.page.wait_for_timeout(2500)
        performed.append("opened 'Build Your Own Plan' accordion")
    except Exception as exc:  # noqa: BLE001
        performed.append(
            f"could not open Build Your Own Plan accordion ({exc})"[:200])
    for role, ids, desc in CUSTOMIZE_TARGETS:
        before = walk.prices()
        rid = click_visible_radio_label(walk, ids)
        if not rid:
            performed.append(
                f"{role}: no visible radio label among {list(ids)}")
            continue
        walk.page.wait_for_timeout(3500)
        try:
            control = walk.page.locator(f"input[id='{rid}']").evaluate(
                "e=>({id:e.id,name:e.name,value:e.value,checked:e.checked})")
        except Exception:  # noqa: BLE001
            control = {"id": rid}
        walk.rating.append({
            "inputs": {**{k: v for k, v in WILLOW.items()
                          if k != "age_value"},
                       "customization": desc},
            "state": f"customize-{role}",
            "hash_route": walk.page.evaluate("()=>location.hash"),
            "prices_before": before, "observed_prices": walk.prices(),
            "control": control,
            "provenance": "directly-observed"})
        performed.append(f"{role}: selected radio id={rid} ({desc})")
        walk.note("customize", control=role, radio=rid)
    # Preventive care is an add-on button pair (Add Basic / Add Prime),
    # not a checkbox.
    before = walk.prices()
    hit = click_by_text(walk, [r"add basic"], timeout_ms=8000)
    if hit:
        walk.note("click", target="Add Basic (preventive care)")
        walk.page.wait_for_timeout(3500)
        walk.rating.append({
            "inputs": {**{k: v for k, v in WILLOW.items()
                          if k != "age_value"},
                       "preventive_care": "basic added"},
            "state": "customize-preventive",
            "hash_route": walk.page.evaluate("()=>location.hash"),
            "prices_before": before, "observed_prices": walk.prices(),
            "provenance": "directly-observed"})
        performed.append("added Basic preventive care ('Add Basic')")
    else:
        performed.append("preventive: 'Add Basic' button not found")
    walk.capture_state(
        "quote-plan-customize", "quote-funnel", "p0",
        ["desktop", "mobile"],
        {"action": "customize-plan", "performed": performed},
        settle_ms=3500)


MODAL_TEXT_JS = """() => Array.from(
  document.querySelectorAll("[class*='modal'], [role='dialog']"))
  .filter(e => e.offsetParent !== null)
  .map(e => e.innerText.trim()).filter(Boolean).slice(0, 6)"""


def step_checkout(walk: Walk) -> None:
    """Advance from the plans view via its Continue CTA (controller.submit).

    Evidence (quote-rates/desktop/page.html): the checkout CTA is the
    'Continue' button; a quick-enroll decision modal may interpose. If it
    does, the modal itself is captured — it is never blindly advanced.
    """
    ensure_rates(walk)
    performed = []
    # A tier normally arrives pre-selected ('Plan Selected'); if none is,
    # select the first tier so Continue can act.
    selected = walk.page.locator("button:visible").filter(
        has_text=re.compile(r"plan selected", re.I))
    if not selected.count():
        picked = click_by_text(walk, [r"select plan"], timeout_ms=5000)
        if picked:
            walk.note("click", target="Select Plan (none was selected)")
            walk.page.wait_for_timeout(2000)
            performed.append("selected the first tier ('Select Plan')")
    start_hash = walk.page.evaluate("()=>location.hash")
    hit = click_by_text(walk, [r"^\s*continue\s*$", r"\bcontinue\b",
                               r"enroll", r"checkout"], timeout_ms=8000)
    if not hit:
        walk.note("warn", message="no checkout CTA found on rates view")
        return
    walk.note("click", target=f"checkout CTA /{hit}/i")
    performed.append(f"clicked CTA matching /{hit}/i")
    try:
        walk.page.wait_for_function(
            "h => location.hash !== h", arg=start_hash, timeout=20000)
        route_changed = True
    except Exception:
        route_changed = False
    walk.page.wait_for_timeout(4000)
    if route_changed:
        performed.append("route advanced to "
                         + walk.page.evaluate("()=>location.hash"))
    else:
        modals = walk.page.evaluate(MODAL_TEXT_JS)
        if modals:
            walk.note("modal", visible_text=[m[:200] for m in modals[:3]])
            performed.append("a decision modal interposed (likely "
                             "quick-enroll); captured the modal itself, "
                             "not advanced")
        else:
            walk.note("warn", message="hash unchanged after checkout CTA "
                      "and no modal visible")
            performed.append("route did not change after CTA")
    structure = walk.page.evaluate(FORM_STRUCTURE_JS)
    walk.note("checkout-structure", fields=structure)
    walk.capture_state(
        "quote-checkout", "quote-funnel", "p0", ["desktop", "mobile"],
        {"action": "enter-checkout", "performed": performed +
         ["captured checkout view page-load only",
          "HARD STOP honored: no payment field focused or filled",
          "form structure recorded from attributes without focus"]},
        settle_ms=4000)
    walk.on_rates = False


def step_ineligible(walk: Walk) -> None:
    fresh_funnel(walk)
    walk.fill("#zipcode", "00000", "zip-probe")
    walk.page.locator("body").click(position={"x": 5, "y": 5})
    walk.page.wait_for_timeout(3000)
    err = walk.page.evaluate(
        """() => Array.from(
             document.querySelectorAll('[class*=error], [role=alert]'))
           .filter(e => e.offsetParent !== null)
           .map(e => e.innerText.trim()).filter(Boolean)""")
    walk.note("zip-probe", zip="00000", visible_errors=err)
    walk.capture_state(
        "quote-ineligible", "quote-funnel", "p1", ["desktop"],
        {"action": "zip-ineligible-probe", "performed":
         ["filled ZIP 00000 and blurred",
          f"visible error text: {err}" if err else
          "no visible error state; checkpoint reclassifies clone-local"]})
    walk.on_rates = False


def goto_portal(walk: Walk) -> None:
    walk.page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)
    # Same-URL goto is a no-op for the SPA, which would leave a previously
    # opened auth panel (forgot-password / register) on screen; reload to
    # guarantee the pristine login view.
    walk.page.reload(wait_until="domcontentloaded", timeout=60000)
    try:
        walk.page.wait_for_selector("input[type=password]", timeout=30000)
    except Exception:
        walk.note("warn", message="portal password field not detected")
    walk.page.wait_for_timeout(2500)
    dismiss_consent(walk.page)
    walk.on_rates = False
    walk.note("portal-login-loaded")


def step_portal_validation(walk: Walk) -> None:
    goto_portal(walk)
    email_sel = ("input[type=email]:visible, input[name*='email' i]:visible, "
                 "input[formcontrolname*='email' i]:visible, "
                 "input[type=text]:visible")
    walk.fill(email_sel, "not-an-email", "portal-probe-email")
    pw = walk.page.locator("input[type=password]:visible").first
    walk.assert_not_payment(pw)
    pw.click()
    pw.fill("x")
    walk.note("fill", field="portal-probe-password",
              value="<one-character placeholder, not a secret>")
    walk.page.locator("body").click(position={"x": 5, "y": 5})
    walk.page.wait_for_timeout(2000)
    walk.capture_state(
        "portal-login-validation", "portal-auth", "p1", ["desktop"],
        {"action": "client-validation-probe", "performed":
         ["entered syntactically invalid email and one-character "
          "placeholder password; blurred",
          "nothing submitted; no real credentials involved"]})


def step_portal_forgot(walk: Walk) -> None:
    goto_portal(walk)
    hit = click_by_text(walk, [r"forgot"])
    walk.page.wait_for_timeout(3000)
    walk.capture_state(
        "portal-forgot-password", "portal-auth", "p1", ["desktop"],
        {"action": "open-forgot-password",
         "performed": ([f"clicked link matching /{hit}/i; form view only, "
                        "not submitted"] if hit
                       else ["no forgot-password link found"])})


def step_portal_register(walk: Walk) -> None:
    goto_portal(walk)
    hit = click_by_text(walk, [r"register", r"create .*account",
                               r"sign up"])
    walk.page.wait_for_timeout(3000)
    walk.capture_state(
        "portal-register", "portal-auth", "p1", ["desktop"],
        {"action": "open-register",
         "performed": ([f"clicked link matching /{hit}/i; form view only, "
                        "not submitted"] if hit
                       else ["no register link found"])})


# Order matters: plan-detail and customize keep the SPA on #/plans so one
# funnel fill serves them plus checkout; checkout and resume navigate away
# and therefore run after them.
STEPS = [
    ("quote-start-validation", step_validation),
    ("quote-rates", step_rates),
    ("quote-plan-detail", step_plan_detail),
    ("quote-plan-customize", step_customize),
    ("quote-checkout", step_checkout),
    ("quote-resume", step_resume),
    ("quote-ineligible", step_ineligible),
    ("portal-login-validation", step_portal_validation),
    ("portal-forgot-password", step_portal_forgot),
    ("portal-register", step_portal_register),
]


def run_walk(walk: Walk, only: set[str] | None) -> None:
    for state_id, fn in STEPS:
        if only and state_id not in only:
            continue
        print(f"-- {state_id}", flush=True)
        try:
            fn(walk)
        except WalkError:
            raise  # payment guard: abort the whole walk
        except Exception as exc:  # noqa: BLE001
            walk.note("step-error", state=state_id, error=str(exc)[:400])
            print(f"  ERROR {state_id}: {exc}", file=sys.stderr, flush=True)
            walk.on_rates = False


def persist(walk: Walk, only: set[str] | None) -> None:
    # On --only reruns, archive the previous walk-log (it is evidence of the
    # earlier runs) and merge rating observations instead of overwriting.
    log_path = OUT / "walk-log.json"
    if only is not None and log_path.exists():
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path.rename(OUT / f"walk-log-prior-{stamp}.json")
    (OUT / "walk-log.json").write_text(json.dumps({
        "schema_version": "aspca-pet-insurance.walk-log.v1",
        "capture_id": CAPTURE_ID,
        "email_mode": ("human-provided" if walk.email_is_human
                       else "synthetic-fallback"),
        "email_address": ("<human-provided, withheld>"
                          if walk.email_is_human else walk.email),
        "real_email_authorized": walk.email_is_human,
        "email_substitution_note": (
            None if walk.email_is_human else
            "First-choice synthetic address used the reserved .invalid TLD; "
            "the funnel's ng-pattern email validator "
            "(/[a-z0-9A-Z._%+-]+@[a-z0-9A-Z.-]+\\.[a-zA-Z]{2,4}$/) caps the "
            "TLD at 4 characters and rejected it, so the recorded fallback "
            "on the IANA-reserved example.com domain was used instead. "
            "Non-deliverable by policy; real_email_authorized stays false."),
        "mutation_grant": "quote-funnel-synthetic-submission",
        "entries": walk.log}, indent=2))
    claims_path = OUT / "rating-claims.json"
    prior_obs: list[dict] = []
    if only is not None and claims_path.exists():
        prior = json.loads(claims_path.read_text())
        new_states = {o["state"] for o in walk.rating}
        prior_obs = [o for o in prior.get("observations", [])
                     if o["state"] not in new_states]
    claims_path.write_text(json.dumps({
        "schema_version": "aspca-pet-insurance.rating-claims.v1",
        "capture_id": CAPTURE_ID,
        "scenario": "willow",
        "observations": prior_obs + walk.rating}, indent=2))
    index_path = OUT / "state-capture-index.json"
    existing = []
    if only is not None and index_path.exists():
        prior = json.loads(index_path.read_text())
        redone = {(m["checkpoint"], m["viewport"]) for m in walk.records}
        existing = [m for m in prior.get("captures", [])
                    if (m["checkpoint"], m["viewport"]) not in redone]
    index_path.write_text(json.dumps({
        "schema_version": "aspca-pet-insurance.state-capture-index.v1",
        "capture_id": CAPTURE_ID,
        "captures": existing + walk.records}, indent=2))
    print(f"\nwrote {len(walk.records)} state records, "
          f"{len(walk.rating)} rating observations", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", default="",
                    help="human-provided disposable address; fallback is the "
                         "recorded non-deliverable synthetic")
    ap.add_argument("--only", default="", help="comma-separated state ids")
    ap.add_argument("--record-trajectory", action="store_true")
    ap.add_argument("--trajectory-id", default="tc-001",
                    help="trajectory output dir name; use a fresh id on "
                         "reruns so earlier recordings are preserved")
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s} or None
    email = args.email or FALLBACK_EMAIL

    sess = bb_create_session(1440, 900)
    print("browserbase session created (id withheld from logs)")
    ws_url = bb_connect_url(sess)
    recorder = None
    exit_code = 0
    walk = None
    try:
        if args.record_trajectory:
            traj_out = SITE / "artifacts" / "trajectory" / args.trajectory_id
            traj_out.mkdir(parents=True, exist_ok=True)
            debug = bb_request("GET", f"/v1/sessions/{sess['id']}/debug")
            debug_ws = debug.get("wsUrl", "")
            if debug_ws:
                recorder = subprocess.Popen(
                    ["websitebench-browser-trajectory", "record",
                     "--cdp-url", debug_ws,
                     "--allowed-origin", ORIGIN,
                     "--output", str(traj_out)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"trajectory recorder started ({args.trajectory_id})")
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws_url)
            try:
                ctx = browser.contexts[0]
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                hide_scrollbars(page)
                page.set_viewport_size({"width": 1440, "height": 900})
                walk = Walk(page, email, bool(args.email))
                run_walk(walk, only)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        print(f"walk failed: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if walk is not None:
            persist(walk, only)
        if recorder is not None:
            recorder.terminate()
            try:
                recorder.wait(timeout=15)
            except subprocess.TimeoutExpired:
                recorder.kill()
            print("trajectory recorder stopped")
        bb_release(sess["id"])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
