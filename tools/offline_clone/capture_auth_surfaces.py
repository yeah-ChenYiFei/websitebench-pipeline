#!/usr/bin/env python3
"""Capture the sign-in / register surfaces of each clone's source site.

Diagnostic reconnaissance only.  This writes under
``materials/<site>/artifacts/parity/auth/`` and never under ``source-current``
or ``artifacts/offline-clone/acceptance`` — it cannot satisfy a source, assets,
frontend, backend or release gate.  Promoting any of it to frozen evidence is a
separate, deliberate re-freeze step.

Safety contract (mirrors ``materials/capterra/tools/browserbase_*.py``):

* Navigation is GET-only.  A browser-side guard installed before the page runs
  intercepts every form submission, ``fetch``/``XMLHttpRequest`` non-GET and
  ``window.open``.  Nothing intercepted is ever dispatched, so an interaction
  physically cannot create a source-side effect; the caller is answered locally
  with a synthetic 401 so a single-page app degrades to its signed-out view
  instead of crashing (see ``GET_ONLY_GUARD``).
* One narrow exception, opt-in per site via ``VIEW_RPC_ALLOW``: a site that
  renders its auth *dialog* by POSTing for a view spec has that one read
  permitted, because blocking it makes the dialog render its own error state
  and defeats the capture.  It is a read — no account, session or order is
  created — and form submission stays blocked.  Every capture record names the
  pattern that was in force under ``capture_policy.view_rpc_allow``.
* Only the approved origin for the site under capture is navigated.
* No cookies, storage, request headers or response bodies are persisted.
  Query strings are dropped from every recorded URL.

Usage::

    export BROWSERBASE_API_KEY=...
    export LD_LIBRARY_PATH="$HOME/chromium-libs/usr/lib/x86_64-linux-gnu"
    export FONTCONFIG_FILE="$HOME/chromium-libs/etc/fonts/fonts.conf"
    .venv/bin/python tools/offline_clone/capture_auth_surfaces.py --site etsy
    .venv/bin/python tools/offline_clone/capture_auth_surfaces.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
BROWSERBASE_API = "https://api.browserbase.com/v1"
DEFAULT_PROJECT_ID = "14721ce0-3dde-4208-9fbb-a8fa539b0f74"

VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}

# Each surface is discovered from the site's own navigation where possible and
# only falls back to a documented path.  `sign_in_text` drives the discovery.
SITES: dict[str, dict[str, Any]] = {
    "amazon": {
        "origin": "https://www.amazon.com",
        "surfaces": {
            "signin": "/ap/signin?openid.return_to=https%3A%2F%2Fwww.amazon.com%2F",
            "register": "/ap/register",
        },
        # Deep-linking /ap/* from a cold session serves the block page, so
        # reach the sign-in surface the way a visitor does instead.
        "discover": {
            "signin": ["#nav-link-accountList", "a[href*='/ap/signin']"],
            "register": [
                "#createAccountSubmit",
                "a[href*='/ap/register']",
                "#nav-link-accountList",
            ],
        },
        "settle_ms": 12000,
    },
    # edX serves its auth surfaces from a separate authn host; the marketing
    # host only links to them.  Confirmed by walking www.edx.org's own nav.
    # authn.edx.org is a React SPA that ships an empty `#root`: the title is
    # final long before the form exists, so a title-only settle screenshots a
    # blank page.  Wait for a real password input instead.
    "edx": {
        "origin": "https://authn.edx.org",
        "warmup": "https://www.edx.org/",
        "extra_origins": ["https://www.edx.org"],
        "surfaces": {"signin": "/login", "register": "/register"},
        "ready_selector": {
            "signin": "form input[type=password], #password",
            "register": "form input[type=password], #password",
        },
        "ready": {
            "signin": r"password",
            "register": r"password",
        },
        "settle_ms": 45000,
    },
    # Capterra has no standalone auth page at all.  Probed 2026-08-06 through a
    # Browserbase proxy egress: `/log-in/`, `/users/sign_in` and `/users/sign_up`
    # each return a genuine HTTP 404 with the site's own "page you were looking
    # for doesn't exist" body — the two paths this entry used to request were
    # never real.  Identity is an in-page modal (`data-testid=
    # "native-uw-auth-overlay"`) opened by the header's "Join or Log in", and it
    # is passwordless: CONTINUE WITH GOOGLE / CONTINUE WITH LINKEDIN / Continue
    # with email.  `auth_relevance` can therefore never reach 5 here however
    # good the capture is, because there is no password field in the source.
    # `proxies` is required: from the default egress every www.capterra.com URL,
    # the home page included, answers 403 behind an interstitial that never
    # clears, so a non-proxied run records `challenge-not-cleared` and nothing
    # else.
    "capterra": {
        "origin": "https://www.capterra.com",
        "proxies": True,
        "surfaces": {"signin": "/", "register": "/"},
        "extra_origins": [
            "https://reviews.capterra.com",
            "https://auth.capterra.com",
            "https://login.capterra.com",
            "https://account.gartner.com",
        ],
        "discover": {
            "signin": [
                "header button:has-text('Join or Log in')",
                "button:has-text('Join or Log in')",
            ],
            "register": [
                "header button:has-text('Join or Log in')",
                "button:has-text('Join or Log in')",
            ],
        },
        "ready_selector": {
            "signin": "[data-testid='native-uw-auth-overlay']",
            "register": "[data-testid='native-uw-auth-overlay']",
        },
        "ready": {
            "signin": r"welcome to capterra|continue with",
            "register": r"welcome to capterra|continue with",
        },
        "settle_ms": 40000,
    },
    # Petfinder opens sign-in as a header-driven dialog rather than a page, so
    # the path navigation below is only a fallback for the click discovery.
    # `/user/register/` is a genuine upstream 404: registration is a *tab inside
    # the same dialog*, which is why its discovery entries are click chains that
    # open the dialog first and then switch tab.  A title/body regex cannot see
    # a dialog, so both surfaces gate on a visible password field instead.
    "petfinder": {
        "origin": "https://www.petfinder.com",
        # Choosing "Sign in" inside the dialog hands off to Purina's Auth0
        # identifier-first host — Petfinder shares an identity provider with
        # the rest of Purina, which the dialog itself states.  Approved for the
        # same GET-only capture as taskrabbit's Auth0 host below.
        "extra_origins": ["https://auth.purina.com"],
        "surfaces": {"signin": "/user/login/", "register": "/user/register/"},
        # The dialog opens on a *choice* pane — "Create Account" / "Sign in"
        # over an "or continue with" provider grid — so the email form is two
        # clicks deep, not one.  Confirmed from the stored capture's page.html.
        "discover": {
            "signin": [
                [
                    "header button:has-text('SIGN IN')",
                    'button[aria-label="Sign in"]',
                ],
                "header button:has-text('SIGN IN')",
                "header a[href*='login']",
            ],
            "register": [
                [
                    "header button:has-text('SIGN IN')",
                    'button[aria-label="Create Account"]',
                ],
                ["header button:has-text('SIGN IN')", "button:has-text('Sign up')"],
                "a:has-text('Create an account')",
            ],
        },
        "ready_selector": {
            "signin": "[role=dialog] input[type=password], form input[type=password]",
            "register": (
                "[role=dialog] input[type=password], form input[type=password]"
            ),
        },
        "ready": {"signin": r"password|sign in", "register": r"password|sign up|create"},
        "settle_ms": 20000,
    },
    "tripit": {
        "origin": "https://www.tripit.com",
        "surfaces": {"signin": "/account/login", "register": "/account/create"},
    },
    "change": {
        "origin": "https://www.change.org",
        "surfaces": {"signin": "/login_or_join", "register": "/login_or_join"},
    },
    "taskrabbit": {
        "origin": "https://www.taskrabbit.com",
        # /login and /signup both redirect into the Auth0 universal-login host.
        "extra_origins": [
            "https://login.taskrabbit.com",
            "https://account.taskrabbit.com",
            "https://taskrabbit.com",
        ],
        "surfaces": {"signin": "/login", "register": "/signup"},
        "ready": {"signin": r"password|log ?in|continue", "register": r"password|sign ?up|continue"},
        "settle_ms": 25000,
    },
    # Etsy's header sign-in is a dialog opened by a button, so there is no link
    # for discovery to follow; /signin and /join are the standalone surfaces.
    "etsy": {
        "origin": "https://www.etsy.com",
        "surfaces": {"signin": "/signin", "register": "/join"},
        # The trigger is `button.signin-header-action.select-signin` inside
        # `<nav aria-label="Main">`, which is *not* a `<header>` descendant —
        # a `header button` selector silently matches nothing.  It opens
        # `#join-neu-overlay` (aria-label "Sign In or Register Overlay"), whose
        # body is lazy-loaded on click, so the shell alone proves nothing.
        # Register is a tab inside that same overlay; the signed-out header
        # carries no separate register control.
        "discover": {
            "signin": [
                "button.signin-header-action",
                "button.select-signin",
                "button.inline-overlay-trigger",
                "a[href*='/signin']",
            ],
            "register": [
                ["button.signin-header-action", "button.select-register"],
                [
                    "button.signin-header-action",
                    "#join-neu-overlay button:has-text('Register')",
                ],
                ["button.signin-header-action", "#join-neu-overlay a:has-text('Register')"],
                "a[href*='/join']",
            ],
        },
        # Etsy starts serving a contentless stub (title `etsy.com`) once a
        # session has visited the auth path a few times, so gate on the field
        # itself: the stub has no password input and will keep waiting rather
        # than screenshot an empty page.
        "ready_selector": {
            "signin": (
                "#join-neu-overlay input[type=password], "
                "#join-neu-form input[type=password], input[type=password]"
            ),
            "register": (
                "#join-neu-overlay input[type=password], "
                "#join-neu-form input[type=password], input[type=password]"
            ),
        },
        "ready": {
            "signin": r"sign in \| etsy|forgot your password",
            "register": r"join \| etsy|get your account set up",
        },
        "settle_ms": 25000,
    },
}

# A narrowly-scoped exception to the GET-only rule, per site.
#
# Some sites render an auth *dialog* by RPC rather than by navigation, and
# implement that read over POST.  Etsy's header sign-in control fetches its
# overlay body from `POST /api/v3/ajax/bespoke/member/neu/specs/Join_Neu_Controller`;
# with that call blocked the overlay renders "An error has occurred, please try
# again!" and the capture scores 0.  That is the capture policy defeating
# itself, not a bot wall — verified by instrumenting the guard and observing
# that the only auth-related blocked call was this one view-spec fetch.
#
# The repo contract is "opening menus and dialogs is fine, submitting forms is
# not".  These endpoints *are* the dialog-opening mechanism: they fetch a view
# spec and create no account, session or order.  Only URLs matching a site's
# explicit pattern are let through, and only for POST; form submission,
# `sendBeacon`, `window.open` and every other non-GET stay blocked exactly as
# before.  Each capture record names the pattern it ran with, so a reader can
# see which requests the policy permitted.
VIEW_RPC_ALLOW: dict[str, str] = {
    "etsy": r"/api/v3/ajax/bespoke/(member|public)/neu/specs/",
}

# Installed before any page script runs.  Blocks every source-side mutation.
# A blocked non-GET is answered with a synthetic 401 instead of a thrown error.
# The request is still never dispatched — the source-side-effect guarantee is
# unchanged — but the *shape* of the block matters to the page.  Throwing inside
# `XMLHttpRequest.open` corrupts an axios instance well enough to take a whole
# single-page app down: authn.edx.org renders `[data-testid=error-page]` and
# never draws its form, so the capture froze an error screen and scored 0.  A
# 401 is what these bootstrap calls (`POST /login_refresh`) already return for
# an anonymous visitor, which is exactly what this session is, so the app takes
# its ordinary signed-out path and renders the surface we came to record.
GET_ONLY_GUARD = """
(() => {
  const BLOCKED_BODY = '{"detail":"blocked by capture policy"}';
  const VIEW_RPC = __VIEW_RPC_ALLOW__;
  // A read implemented over POST: permitted only when the site declares the
  // pattern, and only for POST.  Never applies to form submission.
  const viewRpc = (verb, url) => (
    VIEW_RPC !== null && verb === 'POST' && VIEW_RPC.test(String(url || ''))
  );
  const safe = (verb) => verb === 'GET' || verb === 'HEAD';
  const nativeFetch = window.fetch;
  window.fetch = (input, init) => {
    const method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    const url = (typeof input === 'string') ? input : ((input && input.url) || '');
    if (!safe(method) && !viewRpc(method, url)) {
      return Promise.resolve(new Response(BLOCKED_BODY, {
        status: 401,
        statusText: 'Unauthorized',
        headers: {'Content-Type': 'application/json'},
      }));
    }
    return nativeFetch(input, init);
  };
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    const verb = String(method || 'GET').toUpperCase();
    this.__captureBlocked = !safe(verb) && !viewRpc(verb, url);
    return open.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...rest) {
    if (!this.__captureBlocked) return send.apply(this, rest);
    // Never reaches the network.  Only the local object is made to look like
    // an unauthenticated response so the page's own error handling can run.
    Object.defineProperty(this, 'readyState', {value: 4, configurable: true});
    Object.defineProperty(this, 'status', {value: 401, configurable: true});
    Object.defineProperty(this, 'responseText', {value: BLOCKED_BODY, configurable: true});
    Object.defineProperty(this, 'response', {value: BLOCKED_BODY, configurable: true});
    setTimeout(() => {
      try { this.onreadystatechange && this.onreadystatechange(); } catch (e) {}
      try { this.dispatchEvent(new ProgressEvent('readystatechange')); } catch (e) {}
      try { this.dispatchEvent(new ProgressEvent('load')); } catch (e) {}
      try { this.dispatchEvent(new ProgressEvent('loadend')); } catch (e) {}
    }, 0);
  };
  window.open = () => null;
  document.addEventListener('submit', (e) => { e.preventDefault(); e.stopImmediatePropagation(); }, true);
  navigator.sendBeacon = () => false;
})();
"""

# Extracts the structure a clone has to reproduce: field order, labels, the
# third-party sign-in row, legal copy and the visible headings.
EXTRACT = """
() => {
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const labelFor = (el) => {
    if (el.labels && el.labels.length) return el.labels[0].innerText.trim();
    return (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim();
  };
  const forms = Array.from(document.querySelectorAll('form')).filter(vis).map((f) => ({
    id: f.id || null,
    method: (f.getAttribute('method') || 'get').toLowerCase(),
    fields: Array.from(f.querySelectorAll('input,select,textarea')).filter(
      (el) => el.type !== 'hidden'
    ).map((el) => ({
      tag: el.tagName.toLowerCase(),
      type: el.type || null,
      name: el.name || null,
      label: labelFor(el),
      required: el.required === true,
      autocomplete: el.getAttribute('autocomplete'),
    })),
    buttons: Array.from(f.querySelectorAll('button,input[type=submit]')).filter(vis)
      .map((b) => (b.innerText || b.value || '').trim()).filter(Boolean),
  }));
  const thirdParty = Array.from(document.querySelectorAll('a,button')).filter(vis)
    .map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim())
    .filter((t) => /google|apple|facebook|amazon|microsoft|sso|single sign/i.test(t));
  return {
    title: document.title,
    lang: document.documentElement.lang || null,
    headings: Array.from(document.querySelectorAll('h1,h2')).filter(vis)
      .map((h) => h.innerText.trim()).filter(Boolean).slice(0, 12),
    forms,
    thirdPartyControls: Array.from(new Set(thirdParty)).slice(0, 12),
    links: Array.from(document.querySelectorAll('a[href]')).filter(vis)
      .map((a) => a.innerText.trim()).filter(Boolean).slice(0, 60),
    legal: Array.from(document.querySelectorAll('p,small,span')).filter(vis)
      .map((el) => el.innerText.trim())
      .filter((t) => /terms|privacy|cookie|policy|agree/i.test(t) && t.length < 400)
      .slice(0, 8),
  };
}
"""


def _api(method: str, path: str, body: dict | None = None) -> dict:
    key = os.environ.get("BROWSERBASE_API_KEY")
    if not key:
        raise SystemExit("BROWSERBASE_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BROWSERBASE_API + path,
        data=data,
        method=method,
        headers={"X-BB-API-Key": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read() or b"{}")


def safe_url(raw: str) -> str:
    """Record scheme/host/path only — query strings can carry session state."""

    parts = urlsplit(raw)
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else raw


CHALLENGE_TITLES = ("just a moment", "one moment", "attention required", "verifying")
BLOCK_MARKERS = (
    "looking for something?",
    "enter the characters you see",
    "sorry, we just need to make sure",
    "access denied",
    "request blocked",
)


def _selector_ready(page, selector: str) -> bool:
    """Whether a declared readiness selector currently matches something visible."""

    try:
        target = page.locator(selector).first
        return bool(target.count()) and target.is_visible()
    except Exception:
        return False


def settle(
    page, wait_ms: int, ready: str | None = None, ready_selector: str | None = None
) -> None:
    """Wait out interstitial challenges and client-side hydration.

    `ready` is a regex the page must satisfy (title or body) before the wait
    ends — several of these surfaces render a placeholder title first, and
    screenshotting that placeholder would freeze the wrong page.

    `ready_selector` is the stronger form of the same idea: a CSS selector that
    must match a *visible* element.  Single-page auth hosts (authn.edx.org)
    serve their final title with an empty mount point, so only the presence of
    the field itself proves the form has hydrated.  When both are given the
    selector wins and the regex is the fallback for the last attempt.
    """

    pattern = re.compile(ready, re.IGNORECASE) if ready else None
    page.wait_for_timeout(2000)
    waited = 2000
    while waited < wait_ms:
        try:
            title = page.title() or ""
            challenged = any(m in title.lower() for m in CHALLENGE_TITLES)
            if title and not challenged:
                if ready_selector:
                    target = page.locator(ready_selector).first
                    if target.count() and target.is_visible():
                        break
                elif pattern is None:
                    break
                else:
                    body = (page.inner_text("body") or "")[:6000]
                    if pattern.search(title) or pattern.search(body):
                        break
        except Exception:
            pass
        page.wait_for_timeout(2500)
        waited += 2500
    page.wait_for_timeout(1500)


def auth_relevance(structure: dict[str, Any]) -> int:
    """How much this capture actually looks like an auth surface.

    Used only to refuse replacing a good capture with a worse one.  Several
    origins start serving a contentless stub, or bounce back to the home page,
    once a session has visited the auth path a few times; overwriting real
    evidence with that is worse than not retrying at all.
    """

    score = 0
    for form in structure.get("forms") or []:
        fields = form.get("fields") or []
        types = {str(field.get("type") or "") for field in fields}
        names = " ".join(str(field.get("name") or "") for field in fields).lower()
        if "password" in types:
            score += 4
        if "email" in types or "email" in names or "username" in names:
            score += 2
        if fields:
            score += 1
    if structure.get("thirdPartyControls"):
        score += 2
    return score


def blocked_reason(page) -> str | None:
    """Report a bot wall honestly rather than persisting it as a capture."""

    try:
        title = (page.title() or "").lower()
        text = (page.inner_text("body") or "").lower()[:4000]
    except Exception:
        return "unreadable"
    if any(marker in title for marker in CHALLENGE_TITLES):
        return "challenge-not-cleared"
    for marker in BLOCK_MARKERS:
        if marker in title or marker in text:
            return f"bot-wall:{marker}"
    return None


def capture_site(browser, site: str, spec: dict[str, Any]) -> dict[str, Any]:
    from playwright.sync_api import Error as PlaywrightError

    origin = spec["origin"]
    approved = {urlsplit(origin).netloc}
    approved.update(urlsplit(o).netloc for o in spec.get("extra_origins", []))
    out_root = REPO_ROOT / "materials" / site / "artifacts" / "parity" / "auth"
    record: dict[str, Any] = {
        "schema_version": "websitebench.clone-parity-auth-capture.v1",
        "site_id": site,
        "origin": origin,
        "authority": "diagnostic-tools-only-do-not-satisfy-release-gates",
        "capture_policy": {
            "safe_methods": ["GET", "HEAD"],
            "mutations": "blocked",
            # Named so a reader of this record can see exactly which non-GET
            # requests the run permitted, and satisfy themselves that they are
            # dialog-content reads rather than mutations.
            "view_rpc_allow": VIEW_RPC_ALLOW.get(site),
        },
        "surfaces": {},
    }

    settle_ms = spec.get("settle_ms", 6000)
    discover = spec.get("discover", {})
    allow_pattern = VIEW_RPC_ALLOW.get(site)
    guard_script = GET_ONLY_GUARD.replace(
        "__VIEW_RPC_ALLOW__",
        f"/{allow_pattern}/" if allow_pattern else "null",
    )
    for surface in spec["surfaces"]:
        record["surfaces"][surface] = {}

    for viewport, size in VIEWPORTS.items():
        # One context per viewport, reused across surfaces.  A fresh context per
        # surface would discard the cleared interstitial cookie and re-trigger
        # the challenge on every navigation.
        context = browser.new_context(
            viewport=size, locale="en-US", timezone_id="America/New_York"
        )
        context.add_init_script(guard_script)
        page = context.new_page()
        try:
            page.goto(
                spec.get("warmup", origin + "/"),
                wait_until="domcontentloaded",
                timeout=60000,
            )
            settle(page, settle_ms)
        except Exception:
            pass

        for surface, path in spec["surfaces"].items():
            entry: dict[str, Any] = {"requested_path": path}
            try:
                reached = False
                # Prefer walking in from the warmed-up page: some origins serve
                # a block page to a cold deep link but not to a real click.
                # An entry may be a single selector or a chain of them, for
                # surfaces that live behind two clicks (open a dialog, then
                # switch to its register tab).  Every click in a chain must
                # land, or the whole chain is abandoned.
                for entry_selectors in discover.get(surface, []):
                    chain = (
                        [entry_selectors]
                        if isinstance(entry_selectors, str)
                        else list(entry_selectors)
                    )
                    try:
                        clicked_all = True
                        for selector in chain:
                            target = page.locator(selector).first
                            if not target.count() or not target.is_visible():
                                clicked_all = False
                                break
                            target.click(timeout=8000)
                            page.wait_for_load_state("domcontentloaded", timeout=30000)
                            # Let an in-page dialog mount before the next click
                            # in the chain looks for its contents.
                            page.wait_for_timeout(1500)
                        if not clicked_all:
                            continue
                        ready_selector = spec.get("ready_selector", {}).get(surface)
                        settle(
                            page,
                            settle_ms,
                            spec.get("ready", {}).get(surface),
                            ready_selector,
                        )
                        # A click that opens an *empty* dialog is not arrival.
                        # When a site declares what "ready" looks like and it
                        # never appears, fall through to the documented path
                        # rather than freezing the page behind the dialog —
                        # otherwise Etsy's lazily-populated overlay counts as a
                        # reached sign-in surface and /signin is never tried.
                        reached = blocked_reason(page) is None and (
                            ready_selector is None or _selector_ready(page, ready_selector)
                        )
                        if reached:
                            break
                    except Exception:
                        continue
                if not reached:
                    page.goto(
                        origin + path, wait_until="domcontentloaded", timeout=60000
                    )
                    settle(
                        page,
                        settle_ms,
                        spec.get("ready", {}).get(surface),
                        spec.get("ready_selector", {}).get(surface),
                    )

                final = page.url
                blocked = blocked_reason(page)
                if urlsplit(final).netloc not in approved:
                    entry["status"] = "off-approved-origin"
                    entry["final_url"] = safe_url(final)
                elif blocked:
                    entry["status"] = "blocked"
                    entry["blocked_reason"] = blocked
                    entry["final_url"] = safe_url(final)
                else:
                    directory = out_root / surface / viewport
                    structure = page.evaluate(EXTRACT)
                    # Never overwrite a good capture with a worse one.  Several
                    # origins start serving a contentless stub to a repeatedly
                    # visited session, and a retry that clobbers real evidence
                    # is worse than no retry at all.
                    existing = directory / "structure.json"
                    score = auth_relevance(structure)
                    if existing.is_file():
                        prior = json.loads(existing.read_text(encoding="utf-8"))
                        if auth_relevance(prior) > score:
                            entry["status"] = "kept-better-earlier-capture"
                            entry["note"] = (
                                f"this attempt scored {score} against the stored "
                                f"capture's {auth_relevance(prior)}"
                            )
                            record["surfaces"][surface][viewport] = entry
                            print(
                                f"  {site:11s} {surface:9s} {viewport:8s} "
                                f"{entry['status']}",
                                flush=True,
                            )
                            continue
                    directory.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(directory / "viewport.png"))
                    page.screenshot(
                        path=str(directory / "fullpage.png"), full_page=True
                    )
                    html = page.content()
                    (directory / "page.html").write_text(html, encoding="utf-8")
                    (directory / "structure.json").write_text(
                        json.dumps(structure, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    entry.update(
                        {
                            "status": "captured",
                            "final_url": safe_url(final),
                            "html_bytes": len(html),
                            "title": structure.get("title"),
                            "form_count": len(structure.get("forms", [])),
                            "third_party_controls": structure.get(
                                "thirdPartyControls", []
                            ),
                            "artifacts": str(directory.relative_to(REPO_ROOT)),
                        }
                    )
            except PlaywrightError as exc:
                entry["status"] = "error"
                entry["error"] = type(exc).__name__
            except Exception as exc:  # noqa: BLE001 - recorded, never retried blindly
                entry["status"] = "error"
                entry["error"] = f"{type(exc).__name__}"
            record["surfaces"][surface][viewport] = entry
            print(
                f"  {site:11s} {surface:9s} {viewport:8s} "
                f"{entry.get('status')} {entry.get('blocked_reason') or entry.get('title') or ''}"[:150],
                flush=True,
            )
        context.close()

    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "capture.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def report_status() -> int:
    """Print what is actually on disk, so nobody rebuilds from a stub."""

    print(f"{'site':11s} {'surface':9s} {'score':>5s}  {'status':26s} title")
    for site in sorted(SITES):
        index = REPO_ROOT / "materials" / site / "artifacts" / "parity" / "auth"
        record = read_capture_index(index)
        for surface in SITES[site]["surfaces"]:
            path = index / surface / "desktop" / "structure.json"
            if not path.is_file():
                print(f"{site:11s} {surface:9s} {'-':>5s}  {'not captured':26s}")
                continue
            structure = json.loads(path.read_text(encoding="utf-8"))
            entry = (record.get(surface) or {}).get("desktop") or {}
            score = auth_relevance(structure)
            verdict = "usable" if score >= 5 else "WEAK — recapture" if score else "UNUSABLE"
            print(
                f"{site:11s} {surface:9s} {score:5d}  "
                f"{(entry.get('blocked_reason') or entry.get('status') or verdict):26s} "
                f"{str(structure.get('title'))[:40]!r}"
            )
    print(
        "\nscore: password field +4, email/username +2, any fields +1, "
        "third-party controls +2.  >=5 is a usable rebuild source."
    )
    return 0


def read_capture_index(directory: Path) -> dict[str, Any]:
    path = directory / "capture.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("surfaces", {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="append", choices=sorted(SITES))
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--status",
        action="store_true",
        help="report the quality of the captures already on disk and exit",
    )
    parser.add_argument("--project-id", default=os.environ.get(
        "BROWSERBASE_PROJECT_ID", DEFAULT_PROJECT_ID))
    args = parser.parse_args()

    if args.status:
        return report_status()

    targets = sorted(SITES) if args.all else (args.site or [])
    if not targets:
        parser.error("pass --site <name> (repeatable), --all, or --status")

    # Proxy egress is per-session, not per-navigation, so a run that includes any
    # site needing it takes it for all of them.  It only changes where the
    # request comes from; the GET-only guard is unaffected.
    proxies = any(SITES[site].get("proxies") for site in targets)
    session = _api(
        "POST",
        "/sessions",
        {
            "projectId": args.project_id,
            "keepAlive": False,
            "timeout": 3600,
            "proxies": proxies,
            "browserSettings": {"blockAds": True, "solveCaptchas": True},
            "userMetadata": {"purpose": "websitebench-auth-surface-recon"},
        },
    )
    print(
        f"browserbase session {session['id'][:8]}… "
        f"(proxy egress: {'on' if proxies else 'off'})",
        flush=True,
    )

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(session["connectUrl"])
            for site in targets:
                capture_site(browser, site, SITES[site])
            browser.close()
    finally:
        try:
            _api(
                "POST",
                f"/sessions/{session['id']}",
                {"projectId": args.project_id, "status": "REQUEST_RELEASE"},
            )
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
