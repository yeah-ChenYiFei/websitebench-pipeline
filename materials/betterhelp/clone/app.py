from __future__ import annotations

import hashlib
import html
import hmac
import json
import os
import secrets
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import business  # noqa: E402
from backend.site_backend_integration import open_site_services  # noqa: E402
from websitebench.local_clone_auth import (  # noqa: E402
    AuthConflict,
    AuthError,
    AuthRateLimited,
    AuthRejected,
)
from websitebench.site_backend import PaymentError  # noqa: E402

SITE_ID = "betterhelp"
BACKEND, AUTH = open_site_services()
with BACKEND.lifecycle.connection(transaction=True) as connection:
    business.migrate_v4(connection)
    business.ensure_future_slots(connection)
ADMIN_TOKEN = os.environ.get("WEBSITEBENCH_BETTERHELP_ADMIN_TOKEN") or secrets.token_urlsafe(32)
DEPLOYED_COOKIE = str(BACKEND.session_cookie["name"])
LOCAL_COOKIE = "websitebench-betterhelp-session"
RECOVERY_COOKIE = "websitebench-betterhelp-recovery"
APP = FastAPI(title="BetterHelp offline clone", docs_url=None, redoc_url=None, openapi_url=None)
APP.state.backend = BACKEND
APP.state.auth = AUTH
APP.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

NAV = [
    ("Business", "/business/", ""),
    ("About", "/about/", ""),
    ("Advice", "/advice/", ""),
    ("FAQ", "/faq/", ""),
    ("Reviews", "/reviews/", ""),
    ("Therapist jobs", "/counselor_application/", ""),
    ("Contact", "/contact/", ""),
]
FOOTER = [
    ("Home", "/"), ("Business", "/business/"), ("About", "/about/"),
    ("FAQ", "/faq/"), ("Reviews", "/reviews/"), ("Advice", "/advice/"),
    ("Careers", "/careers/"), ("Find a Therapist", "/therapists/"),
    ("Online Therapy", "/online-therapy/"), ("Contact", "/contact/"),
    ("For Therapists", "/counselor_application/"), ("AARP", "/aarp/"),
]

PACKAGE_LABELS = {"live-session": "Live counseling session"}
SESSION_LABELS = {"video": "Video session", "phone": "Phone session", "live-chat": "Live chat session"}
SPECIAL_REQUEST_LABELS = {
    "none": "No special requests",
    "synthetic-scheduling-request": "Scheduling request",
    "synthetic-accessibility-request": "Accessibility request",
}
INTAKE_LABELS = {
    "therapy_type": {"individual": "Individual therapy", "couples": "Couples therapy", "teen": "Teen therapy"},
    "state": {"California": "California", "New York": "New York", "Texas": "Texas", "Other": "Other"},
    "support": {"anxiety": "Anxiety", "stress": "Stress", "depression": "Depression", "relationships": "Relationships", "trauma": "Trauma", "grief": "Grief", "other": "Other"},
    "therapist_preference": {"no-preference": "No therapist preference", "woman": "Woman therapist", "man": "Man therapist"},
    "therapy_experience": {"first-time": "First time in therapy", "returning": "Returning to therapy"},
    "communication": {"video": "Video", "phone": "Phone", "live-chat": "Live chat"},
    "availability": {"weekday-daytime": "Weekday daytime", "weekday-evening": "Weekday evenings", "weekend": "Weekends"},
    "goal": {"coping-tools": "Build coping tools", "insight": "Gain insight", "relationships": "Improve relationships", "wellbeing": "Support wellbeing"},
}


def _loopback(request: Request) -> bool:
    return request.url.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}


def _cookie_name(request: Request) -> str:
    return LOCAL_COOKIE if _loopback(request) else DEPLOYED_COOKIE


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        _cookie_name(request),
        token,
        secure=not _loopback(request),
        httponly=True,
        samesite="lax",
        path="/",
    )


def _remember_recovery_device(
    request: Request, response: Response, account_id: str
) -> None:
    token = secrets.token_urlsafe(32)
    with BACKEND.lifecycle.connection(transaction=True) as connection:
        business.remember_recovery_device(connection, account_id, token)
    response.set_cookie(
        RECOVERY_COOKIE,
        token,
        secure=not _loopback(request),
        httponly=True,
        samesite="strict",
        max_age=2_592_000,
        path="/",
    )


def _origin_tuple(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            return None
        port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
        return parsed.scheme.casefold(), parsed.hostname.casefold(), port
    except ValueError:
        return None


def _request_origin(request: Request) -> tuple[str, str, int]:
    scheme = request.url.scheme.casefold()
    return scheme, (request.url.hostname or "").casefold(), request.url.port or (443 if scheme == "https" else 80)


@APP.middleware("http")
async def local_runtime_boundary(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin") or request.headers.get("referer")
        # Edge may send Origin: null for a same-document local form navigation.
        # Keep the null/missing exception loopback-only; explicit origins are compared
        # by parsed scheme/host/port rather than a string prefix.
        if origin == "null":
            invalid_origin = not _loopback(request)
        elif origin:
            invalid_origin = _origin_tuple(origin) != _request_origin(request)
        else:
            invalid_origin = not _loopback(request)
        if invalid_origin:
            return JSONResponse({"error": "cross-origin state changes are not allowed"}, status_code=403)
    cookie_name = _cookie_name(request)
    supplied = request.cookies.get(cookie_name)
    token, session = AUTH.ensure_session(supplied)
    request.state.auth_token = token
    request.state.auth_info = session
    account = session.get("account") if session.get("authenticated") else None
    request.state.owner = f"account:{account['account_id']}" if account else None
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    current = str(getattr(request.state, "auth_token", token))
    if current != supplied:
        _set_session_cookie(request, response, current)
    return response


def authenticated_account(request: Request) -> dict | None:
    session = getattr(request.state, "auth_info", {})
    return session.get("account") if session.get("authenticated") else None


def request_owner(request: Request) -> str | None:
    return getattr(request.state, "owner", None)


def support_owner(request: Request) -> str:
    owner = request_owner(request)
    if owner:
        return owner
    token_digest = hashlib.sha256(f"{SITE_ID}:{request.state.auth_token}".encode("utf-8")).hexdigest()
    return f"anonymous:{token_digest}"


def synthetic_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized.endswith("@example.test"):
        raise ValueError("Only synthetic @example.test accounts are accepted.")
    return normalized


def synthetic_display_name(value: str) -> str:
    normalized = " ".join(value.strip().split())
    if normalized not in {"Alex Rivera", "Synthetic Member", "Test User", "Local Student"}:
        raise ValueError("Use one of the supported account names.")
    return normalized


def _mailbox_settings() -> tuple[str, int, str, str] | None:
    """Return validated loopback mailbox settings without exposing credentials."""

    host = os.environ.get("WEBSITEBENCH_SMTP_HOST", "").strip()
    if not host:
        return None
    if host.casefold() not in {"mailbox", "localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("verification mail target must be the local Harbor mailbox")
    namespace = os.environ.get("WEBSITEBENCH_MAILBOX_NAMESPACE", "").strip()
    capability = os.environ.get("WEBSITEBENCH_MAILBOX_CAPABILITY", "").strip()
    if not namespace or len(capability) < 32:
        raise RuntimeError("local Harbor mailbox capability is unavailable")
    try:
        port = int(os.environ.get("WEBSITEBENCH_SMTP_PORT", "1025"))
    except ValueError as exc:
        raise RuntimeError("verification mailbox port is invalid") from exc
    return host, port, namespace, capability


def _deliver_mailbox_code(*, recipient: str, code: str, purpose: str) -> bool:
    """Deliver a challenge to the configured loopback mailbox or fail closed."""

    settings = _mailbox_settings()
    if settings is None:
        return False
    host, port, namespace, capability = settings
    subject = (
        "Verify your BetterHelp account"
        if purpose == "registration"
        else "Reset your BetterHelp password"
    )
    message = EmailMessage()
    message["From"] = "BetterHelp <no-reply@example.test>"
    message["To"] = recipient
    message["Subject"] = subject
    message["X-WebsiteBench-Namespace"] = namespace
    message["X-WebsiteBench-Capability"] = capability
    message.set_content(f"Your BetterHelp verification code is {code}.")
    try:
        with smtplib.SMTP(host, port, timeout=5) as client:
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("verification mailbox delivery failed") from exc
    return True


def auth_status(exc: Exception) -> int:
    if isinstance(exc, AuthRateLimited):
        return 429
    if isinstance(exc, AuthConflict):
        return 409
    if isinstance(exc, AuthRejected):
        return 401
    return 422


def auth_required(request: Request, body: str = "Sign in to continue.") -> HTMLResponse | None:
    if authenticated_account(request) is not None:
        return None
    content = f"<main class='auth-page'><div class='auth-card'><h1>Sign in required</h1><div class='error' role='alert'>{esc(body)}</div><a class='green-button' href='/login/'>Log in</a></div></main>"
    return HTMLResponse(shell("Sign in required - BetterHelp", content, compact=True), status_code=401)


def completed_intake_required(request: Request) -> Response | None:
    denied = auth_required(request, "Complete your account before viewing therapist matches.")
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        current = business.intake(connection, request_owner(request))
    if current is None or not current["completed_at"]:
        return RedirectResponse("/get-started/", status_code=303)
    return None


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def link(label: str, href: str, cls: str = "") -> str:
    external = " target='_blank' rel='noreferrer'" if href.startswith("http") else ""
    return f"<a class='{cls}' href='{esc(href)}'{external}>{esc(label)}</a>"


def shell(title: str, body: str, *, compact: bool = False, cookie: bool = True, member: bool = False) -> str:
    nav = "".join(link(label, href, "nav-link") for label, href, _ in NAV)
    footer = "".join(link(label, href) for label, href in FOOTER)
    consent = "" if not cookie else (
        "<section class='cookie-banner' id='cookie-banner' role='region' aria-label='Cookie Consent'>"
        "<div class='cookie-copy'>We process personally identifiable and personal health information to conduct our business, as described in our "
        "<a href='/privacy/'>Privacy Policy</a>. Some data processing and sharing is required for our business to function. "
        "By clicking \"I agree\" we may share PII with third party advertising partners to deliver relevant ads or analytics partners to improve our services. "
        "To learn more or to opt-out go to \"Sharing settings\".</div>"
        "<div class='cookie-actions'><button class='text-button' data-open-sharing>Sharing settings</button>"
        "<button class='consent-button' data-close-cookie>I agree</button></div></section>"
    )
    header_class = "site-header compact" if compact else "site-header"
    account_nav = (
        "<form class='header-logout' method='post' action='/logout/'><button class='login-link' type='submit'>Logout</button></form>"
        if member else
        "<a class='login-link' href='/login/'>Log in</a><a class='get-started-link' href='/get-started/'>Get started</a>"
    )
    return f"""<!doctype html><html lang='en-US'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>{esc(title)}</title><meta name='description' content='Online therapy with licensed therapists, available from anywhere.'>
<link rel='icon' href='/static/assets/icon-reverse.png'><link rel='stylesheet' href='/static/site.css'><link rel='stylesheet' href='/static/next.css'></head><body>
<header class='{header_class}'><a class='brand' href='/' aria-label='BetterHelp home'><img src='/static/assets/logo-reverse.png' alt='BetterHelp home'></a>
<button class='menu-toggle' aria-label='Open menu' aria-expanded='false' data-menu-toggle>☰</button><nav class='main-nav' aria-label='Main Menu'>
{nav}{account_nav}</nav></header>
{body}<footer class='site-footer'><div class='crisis'>If you are in a crisis or any other person may be in danger - don't use this site. {link('These resources', '/gethelpnow/')} can provide you with immediate help.</div>
<div class='footer-links'>{footer}</div><div class='footer-bottom'>{link('Terms & Conditions','/terms/')} {link('Privacy Policy','/privacy/')} {link('Health Data','/health-data/')} {link('Do Not Sell My Information','/sharing-settings/')} {link('Web Accessibility','/accessibility/')}<span>© 2026 BetterHelp</span></div></footer>{consent}<script src='/static/site.js'></script></body></html>"""


def card(kind: str, title: str, subtitle: str, href: str, image: str) -> str:
    return f"<a class='therapy-card {kind}' href='{esc(href)}' style=\"--card-image:url('/static/assets/{image}')\"><span class='card-title'>{esc(title)}</span><span class='card-subtitle'>{esc(subtitle)} <b class='arrow'>→</b></span></a>"


def home_page() -> str:
    body = """<main class='home-page'><section class='hero'><div class='hero-inner'><h1>You deserve to be happy.</h1>
<fieldset><legend>What type of therapy are you looking for?</legend><div class='therapy-grid'>
""" + card("individual", "Individual", "For myself", "/get-started/?skip_redirect_question=1", "cta-individual.png") + card("couples", "Couples", "For me and my partner", "/get-started/?therapy_type=couples", "cta-couples.png") + card("teen", "Teen", "For my child", "/get-started/?therapy_type=teen", "cta-teen.png") + """</div></fieldset>
<p class='insurance-note'>BetterHelp accepts insurance, with an average copay of $23 per session<sup>*</sup><br>for eligible members.</p><p class='fine-print'><sup>*</sup>Insurance coverage, cost, and availability may vary by state, plan, provider network, therapist availability, and deductible status.</p></div></section>
<section class='light-section intro'><h2>The world's largest therapy service. 100% online.</h2><p>Professional support is available when and where you need it, with licensed therapists and flexible communication.</p></section>
<section class='light-section trust'><div><h2>Professional, licensed, and vetted therapists who you can trust</h2><p>Tap into a global network of licensed and experienced therapists who can help with depression, anxiety, relationships, trauma, grief, and more.</p><a class='green-button' href='/get-started/'>Get matched to a therapist</a></div><div class='avatar-row'><img src='/static/assets/therapist-michelle.jpg' alt='Therapist'><img src='/static/assets/therapist-susan.jpg' alt='Therapist'><img src='/static/assets/therapist-virginia.jpg' alt='Therapist'></div></section>
<section class='how-it-works'><h2>How it works</h2><div class='how-grid'><article><img src='/static/assets/how-it-works-1.png' alt='Get matched'><h3>Get matched to the best therapist for you</h3><p>Answer a few questions to find a licensed therapist who fits your needs and preferences.</p></article><article><img src='/static/assets/how-it-works-2.png' alt='Communicate your way'><h3>Communicate your way</h3><p>Talk to your therapist through text, chat, audio, or video.</p></article><article><img src='/static/assets/how-it-works-3.png' alt='Therapy when you need it'><h3>Therapy when you need it</h3><p>Message your therapist anytime and schedule live sessions when convenient.</p></article></div></section>
<section class='testimonial'><h2>What our members say</h2><div class='quote-card' data-carousel><p data-quote>“I feel heard and supported every time we talk.”</p><span data-author>— BetterHelp member</span><div class='carousel-controls'><button data-prev aria-label='Previous'>‹</button><button data-next aria-label='Next'>›</button></div></div><a href='/reviews/' class='under-link'>More success stories</a></section>
<section class='faq-preview'><h2>Frequently asked questions</h2><details><summary>How does online therapy work?</summary><p>BetterHelp connects you with a licensed therapist through a secure online platform.</p></details><details><summary>How do I get started?</summary><p>Answer a few questions and BetterHelp will help you find a therapist.</p></details><a class='green-button' href='/faq/'>Read our FAQs</a></section>
<section class='gift-section'><div><h2>Give the gift of a BetterHelp membership</h2><p>Therapy is one of the most meaningful gifts you can give to friends and loved ones.</p><a class='green-button' href='/gift/'>Gift a membership</a></div><img src='/static/assets/gift-give.jpg' alt='Hands presenting a wrapped gift box'></section></main>"""
    return shell("BetterHelp | Professional Therapy With A Licensed Therapist", body)


def content_page(title: str, heading: str, copy: str, *, extra: str = "") -> str:
    lead = f"<p>{esc(copy)}</p>" if copy else ""
    body = f"<main class='content-page'><section class='page-hero'><h1>{esc(heading)}</h1>{lead}</section>{extra}</main>"
    return shell(title, body, compact=True)


@APP.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(home_page())


@APP.get("/__websitebench/health", response_class=JSONResponse)
async def websitebench_health() -> JSONResponse:
    """Harbor compile-executable health contract; keep the payload exact."""
    return JSONResponse({"status": "ok"})


@APP.get("/healthz", response_class=JSONResponse)
async def diagnostic_health() -> JSONResponse:
    """Shared offline-clone live diagnostic startup probe."""
    return JSONResponse({"status": "ok"})


@APP.get("/about/", response_class=HTMLResponse)
async def about() -> HTMLResponse:
    extra = "<section class='editorial-grid'><article><h2>Our therapists</h2><p>Our network includes licensed professionals with experience across many areas of mental health.</p></article><article><h2>Our latest reviews</h2><p>Read what members say about their therapy experience.</p><a class='green-button' href='/reviews/'>See more reviews</a></article><article><h2>Our social impact</h2><p>BetterHelp is committed to expanding access to therapy globally.</p></article><article><h2>Our team</h2><p>We are passionate professionals driven by the mission of helping more people live a better life every day.</p><a class='green-button' href='/careers/'>Careers</a></article></section>"
    return HTMLResponse(content_page("About Us - BetterHelp", "About us", "BetterHelp was founded in 2013 to remove traditional barriers to therapy and make mental health care more accessible to everyone.", extra=extra))


@APP.get("/faq/", response_class=HTMLResponse)
async def faq() -> HTMLResponse:
    items = [
        ("What is BetterHelp?", "BetterHelp is an online counseling service that connects members with licensed therapists through a secure platform."),
        ("Who will be helping me?", "You will be matched with a licensed therapist whose experience and approach fit your goals and preferences."),
        ("Who are the therapists?", "Therapists in the network are licensed, trained mental health professionals with experience across many areas of care."),
        ("How are the therapists verified?", "Licenses and professional credentials are reviewed before a therapist joins the network, with ongoing quality checks."),
        ("Is BetterHelp right for me?", "Online counseling can be useful for many concerns, but it is not a substitute for emergency services or crisis care."),
        ("How much does it cost?", "Membership pricing depends on location and plan. Current pricing is shown during sign-up before you commit."),
        ("Can BetterHelp substitute for traditional face-to-face therapy?", "Online counseling offers flexible communication, while some needs may be better served by in-person or specialized care."),
        ("I signed up. How long until I'm matched with a therapist?", "Matching usually happens after the questionnaire is complete and may vary with your preferences and therapist availability."),
        ("How will I communicate with my therapist?", "You can use secure messaging and, when available, schedule live chat, audio, or video sessions."),
        ("How does messaging work?", "Send a message through your member area and your therapist can reply when they are available."),
        ("How do live chat sessions work?", "A live chat session is a scheduled real-time text conversation in the secure member area."),
        ("How do live audio sessions work?", "An audio session is scheduled in advance and takes place through the secure platform without video."),
        ("How do live video sessions work?", "A video session is a scheduled face-to-face conversation using the secure platform and a compatible device."),
        ("Can I go back and read the therapist's previous messages?", "Yes. Your conversation history remains available in your member area while your membership is active."),
        ("Is BetterHelp web accessible for disabled users?", "The service is designed to support keyboard navigation, readable content, and responsive use across devices."),
        ("How long can I use BetterHelp?", "You can continue while your membership is active and pause or cancel according to the plan terms."),
        ("How do I pay for therapy?", "Payment is handled securely during sign-up using the available payment options shown for your location."),
        ("Does BetterHelp accept insurance?", "Insurance availability depends on your state, plan, provider network, and eligibility. Details appear during sign-up."),
        ("What is the role of BetterHelp.com?", "BetterHelp provides the technology and service that supports communication between members and independent therapists."),
        ("How can I be sure this is an effective form of therapy?", "Therapy outcomes depend on the person, concern, and therapeutic relationship. Finding a good fit and participating consistently can help."),
        ("Will my therapist treat what I say as confidential?", "Therapists follow professional confidentiality requirements and explain the legal and safety limits that apply."),
        ("How is my privacy and security protected?", "The service uses account controls, secure connections, and privacy practices designed to protect member information."),
        ("Can I stay anonymous?", "You can choose how much identifying information to share with your therapist, while an account is required to use the service."),
        ("How can I get started with BetterHelp?", "Select a therapy path, create an account, and complete the matching questionnaire."),
        ("I'm a licensed therapist. How can I provide services using BetterHelp?", "Licensed therapists interested in joining can review the application information on the therapist jobs page."),
    ]
    extra = "<section class='faq-list'>" + "".join(
        f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>"
        for index, (q, a) in enumerate(items)
    ) + "</section><section class='center-cta'><h2>Ready to get started?</h2><a class='green-button' href='/get-started/'>Get matched with a therapist</a></section>"
    return HTMLResponse(content_page("FAQ - BetterHelp", "Frequently asked questions", "", extra=extra))


@APP.get("/advice/", response_class=HTMLResponse)
async def advice() -> HTMLResponse:
    recent = [
        ("A Therapist’s Guide to Insurance Credentialing", "advice-insurance.jpg", "Medically reviewed by Andrea Brant, LMHC"),
        ("Is Therapy Tax Deductible?", "advice-tax.jpg", "Medically reviewed by Andrea Brant, LMHC"),
        ("Do We Need Couples Therapy? 6 Signs It May Be Time to Go", "advice-couples.jpg", "Medically reviewed by Melissa Guarnaccia, LCSW"),
    ]
    popular = [
        ("What Is Therapy Stigma? Why It Still Exists and How to Overcome It", "advice-hero.jpg", "Medically reviewed by Courtney Cope, LMFT"),
        ("Finding The Right BetterHelp Therapist For Your Mental Health Needs", "advice-insurance.jpg", "Medically reviewed by Melissa Guarnaccia, LCSW"),
        ("What Are The Key Benefits Of Using BetterHelp For Online Therapy?", "advice-couples.jpg", "Medically reviewed by Julie Dodson, MA, LCSW"),
    ]
    topics = {
        "Depression": [
            "My Job Is Making Me Depressed But I Can't Quit",
            "10 Natural Remedies for Depression That May Complement Treatment",
            "Male Depression: Symptoms, Warning Signs, and Support Options",
            "Bed Rotting: Self-Care or Sign of Depression?",
        ],
        "Anxiety": [
            "What Is High-Functioning Anxiety? Signs, Causes, and Coping",
            "Anxiety Journal: How To Keep One For Mental Health",
            "7 Holistic Anxiety Remedy Techniques That May Actually Help",
            "Anxiety Attack vs. Panic Attack: Symptoms, Duration, And When To Get Help",
        ],
        "Therapy": [
            "The Silent Struggle: Why Many Men Still Avoid Talking About Mental Health",
            "Men And Therapy: Why Getting Support Can Be A Sign Of Strength",
            "Why LGBTQIA+ Friendly Fitness Spaces Matter for Mental Health",
            "AI Therapist vs. Human Therapist: Key Differences to Know",
        ],
    }

    def article_card(item: tuple[str, str, str]) -> str:
        title, image, review = item
        return f"<article class='advice-card'><img src='/static/assets/{esc(image)}' alt=''><div><h3>{esc(title)}</h3><p>{esc(review)}</p><a class='under-link' href='/advice/'>Read article</a></div></article>"

    topic_images = ["advice-hero.jpg", "advice-insurance.jpg", "advice-tax.jpg", "advice-couples.jpg"]
    topic_sections = "".join(
        f"<section class='advice-section'><div class='section-heading'><h2>{esc(topic)}</h2><a class='under-link' href='/advice/'>See more</a></div><div class='advice-grid advice-grid-four'>"
        + "".join(article_card((title, topic_images[index], "Medically reviewed by a licensed therapist")) for index, title in enumerate(titles))
        + "</div></section>"
        for topic, titles in topics.items()
    )
    categories = "".join(f"<a class='category-link' href='/advice/'>{esc(label)}</a>" for label in ("Relationships and Relations", "Psychology", "Therapy", "Psychologists", "Behavior"))
    body = (
        "<main class='advice-page'><div class='advice-titlebar'><h1>Advice</h1></div>"
        "<section class='advice-feature' data-advice-carousel><button class='advice-arrow' type='button' data-advice-prev aria-label='Previous advice article'>‹</button><div class='advice-feature-copy'><p class='sr-only' data-advice-status aria-live='polite'>Advice slide 1 of 3</p><h2 data-advice-title>How can I refresh my routine this spring if I’m feeling mentally drained?</h2><a class='advice-read' href='/advice/' data-advice-link>Read more</a><div class='advice-dots' aria-label='Advice slides'><button class='active' type='button' data-advice-dot='0' aria-label='Show slide 1'></button><button type='button' data-advice-dot='1' aria-label='Show slide 2'></button><button type='button' data-advice-dot='2' aria-label='Show slide 3'></button></div></div><img src='/static/assets/advice-hero.jpg' alt='A person looking through a window'><button class='advice-arrow' type='button' data-advice-next aria-label='Next advice article'>›</button></section>"
        "<section class='advice-section'><div class='section-heading'><h2>Recent</h2><a class='under-link' href='/advice/'>View all</a></div><div class='advice-grid'>" + "".join(article_card(item) for item in recent) + "</div></section>"
        "<section class='advice-section shaded'><div class='section-heading'><h2>Popular</h2><a class='under-link' href='/advice/'>View all</a></div><div class='advice-grid'>" + "".join(article_card(item) for item in popular) + "</div></section>"
        + topic_sections
        + "<section class='advice-support'><h2>Get the support you need from one of our therapists</h2><a class='green-button' href='/get-started/'>Get started</a></section>"
        "<section class='advice-section shaded'><div class='section-heading'><h2>Top categories</h2></div><div class='category-grid'>" + categories + "</div></section>"
        "<section class='editorial-note'><h2>The review process</h2><p>Our writers are researchers and advocates in the mental health space. Each article is medically reviewed by a licensed therapist. Articles are updated to reflect the latest health information.</p><a class='green-button' href='/advice/'>Meet the editorial team</a></section></main>"
    )
    return HTMLResponse(shell("Advice | Definitions, Research, Treatment, News, Mental Health Awareness, And Advice", body, compact=True))

@APP.get("/reviews/", response_class=HTMLResponse)
async def reviews() -> HTMLResponse:
    quotes = ["My therapist gives me tools I can use every day.", "I appreciate being able to communicate in a way that works for me.", "The matching process helped me find someone I connect with.", "Having support online made therapy accessible for me.", "I feel more hopeful after each session.", "The flexibility has made a real difference."]
    images = ["therapist-michelle.jpg", "therapist-susan.jpg", "therapist-virginia.jpg"]
    extra = "<section class='reviews-list'>" + "".join(f"<article class='review-card'><img src='/static/assets/{images[index % len(images)]}' alt=''><p>“{esc(q)}”</p><span>BetterHelp member</span></article>" for index, q in enumerate(quotes)) + "<button class='load-more' data-load-more>Load More</button></section>"
    return HTMLResponse(content_page("BetterHelp Reviews", "BetterHelp reviews", "", extra=extra))


@APP.get("/get-started/", response_class=HTMLResponse)
async def get_started(request: Request, step: int = 1) -> HTMLResponse:
    try:
        progress = max(1, min(8, int(step)))
    except (TypeError, ValueError):
        progress = 1
    saved = None
    if request_owner(request):
        with BACKEND.lifecycle.connection() as connection:
            saved = business.intake(connection, request_owner(request))
    answers = dict(saved["answers"] if saved else {})
    # Carry the selected home-page path into the first question so each card
    # is a functional local entry point rather than a placeholder anchor.
    if not saved:
        selected_type = request.query_params.get("therapy_type", "")
        if selected_type in {"individual", "couples", "teen"}:
            answers["therapy_type"] = selected_type
        elif request.query_params.get("skip_redirect_question") == "1":
            answers["therapy_type"] = "individual"
    progress = max(progress, min(8, int(saved["current_step"]) if saved else 1))
    if request.query_params.get("skip_redirect_question") == "1" and not saved and progress == 1:
        progress = 2
    questions = {
        1: ("What type of therapy are you looking for?", "therapy_type", [("individual", "Individual", "For myself"), ("couples", "Couples", "For me and my partner"), ("teen", "Teen", "For my child")]),
        2: ("Which state are you in?", "state", [("California", "California", ""), ("New York", "New York", ""), ("Texas", "Texas", ""), ("Other", "Other", "")]),
        3: ("What would you like support with?", "support", [("anxiety", "Anxiety", "Stress and worry"), ("relationships", "Relationships", "Connection and communication"), ("trauma", "Trauma", "Healing and recovery"), ("other", "Something else", "")]),
        4: ("Do you have a therapist preference?", "therapist_preference", [("no-preference", "No preference", "We'll focus on fit"), ("woman", "Woman", ""), ("man", "Man", "")]),
        5: ("Have you tried therapy before?", "therapy_experience", [("first-time", "This is my first time", ""), ("returning", "I've had therapy before", "")]),
        6: ("How would you like to communicate?", "communication", [("video", "Video sessions", ""), ("phone", "Phone sessions", ""), ("live-chat", "Live chat", "")]),
        7: ("When are you usually available?", "availability", [("weekday-daytime", "Weekday daytime", ""), ("weekday-evening", "Weekday evenings", ""), ("weekend", "Weekends", "")]),
        8: ("What is your main goal for therapy?", "goal", [("coping-tools", "Build coping tools", ""), ("insight", "Gain insight", ""), ("relationships", "Improve relationships", ""), ("wellbeing", "Support my wellbeing", "")]),
    }
    question, field, options = questions[progress]
    controls = "<div class='quiz-options'>" + "".join(
        f"<label><input type='radio' name='{field}' value='{esc(value)}' {'checked' if answers.get(field)==value else ''} required> <span>{esc(label)}</span><small>{esc(note)}</small></label>"
        for value, label, note in options
    ) + "</div>"
    if progress == 2:
        selected_hidden = (
            f"<input type='hidden' name='therapy_type' value='{esc(answers['therapy_type'])}'>"
            if answers.get("therapy_type")
            else ""
        )
        controls = selected_hidden + "<label class='select-label' for='state'>Select State</label><select id='state' name='state' required>" + "".join(f"<option value='{esc(v)}' {'selected' if answers.get('state')==v else ''}>{esc(v)}</option>" for v,_,_ in options) + "</select>"
    identity_note = "<p class='already'>Your answers are stored securely with your account.</p>"
    progress_segments = "".join(
        f"<i class='{'active' if index <= progress else ''}' aria-hidden='true'></i>"
        for index in range(1, 9)
    )
    process_note = (
        "<div class='quiz-info'><span aria-hidden='true'>i</span><p>Let's walk through the process of finding the best therapist for you. We'll start off with some basic questions.</p></div>"
        if progress == 1
        else ""
    )
    body = f"<main class='quiz-page'><div class='quiz-wrap'><div class='progress-label'><span class='sr-only'>Quiz progress {progress} of 8</span><div class='progress-segments'>{progress_segments}</div></div><h1 class='quiz-heading'>Help us match you to the <em>right therapist</em></h1><p class='quiz-intro'>It's important to have a therapist who you can establish a personal connection with. The following questions are designed to match you to a licensed therapist based on your therapy needs and personal preferences.</p><form method='post' action='/get-started/' class='quiz-card'><input type='hidden' name='step' value='{progress}'><p class='quiz-question'>{esc(question)}</p>{controls}{process_note}<button class='green-button' type='submit'>{'See my matches' if progress == 8 else 'Next'}</button>{identity_note}<p class='already'>Already registered? <a href='/login/'>Log in</a></p></form><aside class='ai-note'><strong>The role of AI in identifying a therapist</strong><p>We use technology to help surface options while keeping people at the center of care.</p></aside></div></main>"
    return HTMLResponse(shell("BetterHelp - Get Started & Sign-Up Today", body, compact=True))


@APP.post("/get-started/", response_class=HTMLResponse)
async def get_started_post(request: Request) -> Response:
    denied = auth_required(request, "Create an account before saving your questionnaire.")
    if denied:
        return denied
    form = await request.form()
    try:
        step = int(str(form.get("step") or "0"))
        field_map = {1: "therapy_type", 2: "state", 3: "support", 4: "therapist_preference", 5: "therapy_experience", 6: "communication", 7: "availability", 8: "goal"}
        field = field_map[step]
        value = str(form.get(field) or "")
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            if step == 2 and form.get("therapy_type"):
                business.save_intake_answer(connection, request_owner(request), 1, str(form["therapy_type"]))
            saved = business.save_intake_answer(connection, request_owner(request), step, value)
        if step == 8 and saved["completed_at"]:
            return RedirectResponse("/matches/", status_code=303)
        return RedirectResponse(f"/get-started/?step={step + 1}", status_code=303)
    except (KeyError, ValueError) as exc:
        progress = max(1, min(8, int(str(form.get("step") or "1"))))
        return HTMLResponse(shell("Questionnaire error", f"<main class='quiz-page'><div class='quiz-wrap'><div class='error' role='alert'>{esc(exc)}</div><a class='green-button' href='/get-started/?step={progress}'>Try again</a></div></main>", compact=True), status_code=422)


@APP.get("/login/", response_class=HTMLResponse)
async def login() -> HTMLResponse:
    review = (
        "<section class='login-reviews' aria-label='Member reviews'>"
        "<button class='login-review-arrow' type='button' data-prev aria-label='Previous review'>‹</button>"
        "<article class='login-review-card'><p data-quote>“I feel heard and supported every time we talk.”</p>"
        "<span data-author>— BetterHelp member</span></article>"
        "<button class='login-review-arrow' type='button' data-next aria-label='Next review'>›</button>"
        "<div class='login-review-dots' aria-label='Review slides'>"
        "<button class='active' type='button' data-login-dot='0' aria-label='Show review 1'></button>"
        "<button type='button' data-login-dot='1' aria-label='Show review 2'></button>"
        "<button type='button' data-login-dot='2' aria-label='Show review 3'></button>"
        "</div></section>"
    )
    body = "<main class='auth-page login-scene'><blockquote class='login-quote'><p>\u201cNothing will work unless you do.\u201d</p><cite>Maya Angelou</cite></blockquote><div class='auth-card login-card'><button class='google-login' type='button' data-google-login><span aria-hidden='true'>G</span> Sign in with Google</button><p class='provider-note' data-provider-note hidden>Please use your email address to continue.</p><div class='login-divider'><span>or</span></div><form method='post' action='/login/'><label class='sr-only' for='emailInput'>Email Address</label><input id='emailInput' name='email' type='email' autocomplete='email' placeholder='Email Address' required><label class='sr-only' for='login-password'>Password</label><input id='login-password' name='password' type='password' autocomplete='current-password' placeholder='Password' required><button id='redesigned-login-btn' class='green-button' type='submit'>Log in</button></form><a class='forgot' href='/password-reset/'>Forgot password?</a><p class='login-signup'>New to BetterHelp? <a href='/signup/'>Get started</a></p></div></main>" + review
    return HTMLResponse(shell("Login", body, compact=True))


@APP.post("/login/", response_class=HTMLResponse)
async def login_post(request: Request) -> Response:
    form = await request.form()
    try:
        result = AUTH.sign_in(str(request.state.auth_token), email=synthetic_email(str(form.get("email") or "")), password=str(form.get("password") or ""))
        response = RedirectResponse("/member/", status_code=303)
        _set_session_cookie(request, response, str(result["session_token"]))
        _remember_recovery_device(
            request, response, str(result["account"]["account_id"])
        )
        request.state.auth_token = str(result["session_token"])
        return response
    except (AuthError, ValueError) as exc:
        status = auth_status(exc)
        body = "<main class='auth-page'><div class='auth-card'><h1>Log in</h1><div class='error' role='alert'>The email or password is incorrect.</div><a class='green-button' href='/login/'>Try again</a></div></main>"
        return HTMLResponse(shell("Login error", body, compact=True), status_code=status)


def registration_verification_body(*, mail_status: str = "AVAILABLE") -> str:
    return (
        "<main class='auth-page'><div class='auth-card'><h1>Verify your account</h1>"
        "<p class='auth-lead'>Enter the six-digit verification code from your email.</p>"
        f"<div class='ai-note verification-note' data-mail-status='{esc(mail_status)}'>"
        "Your verification message is ready.</div>"
        "<a class='green-button inbox-link' href='/mailbox/?purpose=registration' "
        "target='_blank' rel='noopener'>Open verification inbox</a>"
        "<form method='post' action='/signup/'><input type='hidden' name='phase' value='verify'>"
        "<label for='code'>Verification code</label>"
        "<input id='code' name='code' inputmode='numeric' pattern='[0-9]{6}' required>"
        "<button class='green-button' type='submit'>Verify account</button></form></div></main>"
    )


def password_reset_verification_body(
    *, mail_status: str = "AVAILABLE", error: str = ""
) -> str:
    error_html = f"<div class='error' role='alert'>{esc(error)}</div>" if error else ""
    return (
        "<main class='auth-page'><div class='auth-card'><h1>Choose a new password</h1>"
        f"{error_html}"
        f"<div class='ai-note verification-note' data-mail-status='{esc(mail_status)}'>"
        "If the account exists, a reset message is ready.</div>"
        "<a class='green-button inbox-link' href='/mailbox/?purpose=password-reset' "
        "target='_blank' rel='noopener'>Open verification inbox</a>"
        "<form method='post' action='/password-reset/'>"
        "<input type='hidden' name='phase' value='complete'>"
        "<label for='reset-code'>Reset code</label><input id='reset-code' name='code' required>"
        "<label for='new-password'>New password</label>"
        "<input id='new-password' name='new_password' type='password' minlength='8' required>"
        "<button class='green-button' type='submit'>Update password</button></form></div></main>"
    )


@APP.get("/signup/", response_class=HTMLResponse)
async def signup(request: Request, phase: str = "") -> HTMLResponse:
    if phase == "verify":
        status = AUTH.session_flow_status(
            str(request.state.auth_token), purpose="registration"
        )
        if status["state"] == "challenge":
            return HTMLResponse(
                shell(
                    "Verify your BetterHelp account",
                    registration_verification_body(),
                    compact=True,
                )
            )
    body = "<main class='auth-page'><div class='auth-card'><h1>Create your account</h1><p class='auth-lead'>Use an email address you can access to verify your account.</p><p class='auth-guidance'>By continuing, you agree to the <a href='/terms/'>Terms &amp; Conditions</a> and acknowledge the <a href='/privacy/'>Privacy Policy</a>.</p><form method='post' action='/signup/'><input type='hidden' name='phase' value='start'><label for='name'>Name</label><input id='name' name='name' required><label for='signup-email'>Email Address</label><input id='signup-email' name='email' type='email' placeholder='alex@example.test' required><label for='signup-password'>Password</label><input id='signup-password' name='password' type='password' minlength='8' required><button class='green-button' type='submit'>Create account</button></form></div></main>"
    return HTMLResponse(shell("Sign up - BetterHelp", body, compact=True))


@APP.post("/signup/", response_class=HTMLResponse)
async def signup_post(request: Request) -> Response:
    form = await request.form()
    phase = str(form.get("phase") or "start")
    token = str(request.state.auth_token)
    try:
        if phase == "start":
            email = synthetic_email(str(form.get("email") or ""))
            AUTH.start_registration(token, email=email, display_name=synthetic_display_name(str(form.get("name") or "")), password=str(form.get("password") or ""))
            mail = AUTH.local_mail_for_session(token, purpose="registration")
            if mail is None:
                raise AuthError("Verification message unavailable.")
            delivered = _deliver_mailbox_code(
                recipient=email,
                code=str(mail["verification_code"]),
                purpose="registration",
            )
            mail_status = "DELIVERED" if delivered else "AVAILABLE"
            body = registration_verification_body(mail_status=mail_status)
            return HTMLResponse(shell("Verify your BetterHelp account", body, compact=True))
        AUTH.verify_registration_code(token, str(form.get("code") or ""))
        result = AUTH.complete_registration(token)
        response = RedirectResponse("/get-started/", status_code=303)
        _set_session_cookie(request, response, str(result["session_token"]))
        _remember_recovery_device(
            request, response, str(result["account"]["account_id"])
        )
        request.state.auth_token = str(result["session_token"])
        return response
    except (AuthError, ValueError) as exc:
        status = 422 if phase == "verify" else auth_status(exc)
        body = f"<main class='auth-page'><div class='auth-card'><h1>Create your account</h1><div class='error' role='alert'>{esc('Enter the permitted account details and a valid verification code.')}</div><a class='green-button' href='/signup/'>Try again</a></div></main>"
        return HTMLResponse(shell("Sign up error", body, compact=True), status_code=status)
    except RuntimeError:
        body = "<main class='auth-page'><div class='auth-card'><h1>Verification temporarily unavailable</h1><div class='error' role='alert'>The verification message could not be delivered. Please try again.</div><a class='green-button' href='/signup/'>Return to sign up</a></div></main>"
        return HTMLResponse(shell("Verification unavailable", body, compact=True), status_code=503)


@APP.post("/logout/", response_class=HTMLResponse)
async def logout(request: Request) -> Response:
    AUTH.sign_out(str(request.state.auth_token))
    response = RedirectResponse("/", status_code=303)
    _set_session_cookie(request, response, AUTH.create_anonymous_session())
    return response


@APP.get("/password-reset/", response_class=HTMLResponse)
async def password_reset_get(request: Request, phase: str = "") -> HTMLResponse:
    if phase == "complete":
        status = AUTH.session_flow_status(
            str(request.state.auth_token), purpose="password-reset"
        )
        if status["state"] == "challenge":
            return HTMLResponse(
                shell(
                    "Password recovery",
                    password_reset_verification_body(),
                    compact=True,
                )
            )
    body = "<main class='auth-page'><div class='auth-card'><h1>Reset your password</h1><p>If the account exists, a verification code will be available.</p><form method='post' action='/password-reset/'><input type='hidden' name='phase' value='start'><label for='reset-email'>Email Address</label><input id='reset-email' name='email' type='email' required><button class='green-button' type='submit'>Send reset code</button></form><a class='forgot' href='/login/'>Return to sign in</a></div></main>"
    return HTMLResponse(shell("Password recovery", body, compact=True))


@APP.post("/password-reset/", response_class=HTMLResponse)
async def password_reset_post(request: Request) -> Response:
    form = await request.form()
    token = str(request.state.auth_token)
    phase = str(form.get("phase") or "start")
    try:
        if phase == "start":
            email = synthetic_email(str(form.get("email") or ""))
            with BACKEND.lifecycle.connection() as connection:
                authorized = business.recovery_device_authorized(
                    connection,
                    email,
                    request.cookies.get(RECOVERY_COOKIE),
                )
            delivered = False
            if authorized:
                AUTH.start_password_reset(token, email=email)
                mail = AUTH.local_mail_for_session(
                    token, purpose="password-reset"
                )
                if mail is None:
                    raise AuthError("Password reset message unavailable.")
                delivered = _deliver_mailbox_code(
                    recipient=email,
                    code=str(mail["verification_code"]),
                    purpose="password-reset",
                )
            body = password_reset_verification_body(
                mail_status="DELIVERED" if delivered else "AVAILABLE"
            )
            return HTMLResponse(shell("Password recovery", body, compact=True))
        AUTH.verify_password_reset_code(token, str(form.get("code") or ""))
        new_token = AUTH.complete_password_reset(token, new_password=str(form.get("new_password") or ""))
        response = RedirectResponse("/member/", status_code=303)
        _set_session_cookie(request, response, new_token)
        _, session = AUTH.ensure_session(new_token)
        account = session.get("account")
        if account is not None:
            _remember_recovery_device(
                request, response, str(account["account_id"])
            )
        request.state.auth_token = new_token
        return response
    except (AuthError, ValueError):
        if phase == "complete":
            status = AUTH.session_flow_status(
                token, purpose="password-reset"
            )
            if status["state"] == "challenge":
                body = password_reset_verification_body(
                    error="The reset request could not be completed. Check the code and try again."
                )
                return HTMLResponse(
                    shell("Password recovery error", body, compact=True),
                    status_code=422,
                )
        body = "<main class='auth-page'><div class='auth-card'><h1>Password recovery error</h1><div class='error' role='alert'>The reset request could not be completed.</div><a class='green-button' href='/password-reset/'>Try again</a></div></main>"
        return HTMLResponse(shell("Password recovery error", body, compact=True), status_code=422)
    except RuntimeError:
        body = "<main class='auth-page'><div class='auth-card'><h1>Password recovery temporarily unavailable</h1><div class='error' role='alert'>The reset message could not be delivered. Please try again.</div><a class='green-button' href='/password-reset/'>Try again</a></div></main>"
        return HTMLResponse(shell("Password recovery unavailable", body, compact=True), status_code=503)


@APP.get("/mailbox/", response_class=HTMLResponse)
async def verification_inbox(request: Request, purpose: str) -> HTMLResponse:
    if not _loopback(request):
        return HTMLResponse("Verification inbox unavailable.", status_code=403)
    if purpose not in {"registration", "password-reset"}:
        return HTMLResponse("Verification inbox unavailable.", status_code=422)
    mail = AUTH.local_mail_for_session(
        str(request.state.auth_token), purpose=purpose
    )
    if mail is None:
        return HTMLResponse(
            shell(
                "Verification inbox - BetterHelp",
                "<main class='auth-page'><div class='auth-card'><h1>Verification inbox</h1>"
                "<p>No verification message is available for this browser session.</p>"
                "<a class='green-button' href='/signup/'>Return to sign up</a></div></main>",
                compact=True,
                cookie=False,
            ),
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    registration = purpose == "registration"
    subject = (
        "Verify your BetterHelp account"
        if registration
        else "Reset your BetterHelp password"
    )
    continue_href = "/signup/?phase=verify" if registration else "/password-reset/?phase=complete"
    continue_label = "Return to account verification" if registration else "Return to password reset"
    body = (
        "<main class='auth-page'><div class='auth-card inbox-card'>"
        "<h1>Verification inbox</h1>"
        f"<p class='mail-subject'>{esc(subject)}</p>"
        f"<p>To: <strong>{esc(mail['recipient'])}</strong></p>"
        "<p>Your six-digit verification code is:</p>"
        f"<output class='verification-code' data-verification-code='{esc(mail['verification_code'])}'>"
        f"{esc(mail['verification_code'])}</output>"
        f"<a class='green-button' href='{continue_href}'>{continue_label}</a>"
        "</div></main>"
    )
    return HTMLResponse(
        shell("Verification inbox - BetterHelp", body, compact=True, cookie=False),
        headers={"Cache-Control": "no-store"},
    )


def therapy_process_page(account: dict, preferences: dict, *, notice: str = "", readiness: bool = False) -> str:
    notice_html = f"<div class='inline-notice' role='status'>{esc(notice)}</div>" if notice else ""
    illustrations = ["next-begin.svg", "next-steps.svg", "next-ways.svg"]
    steps = "".join(
        f"<article class='process-step'><img src='/static/assets/{illustrations[index - 1]}' alt=''><span class='process-number'>{index}</span><div><h3>{esc(title)}</h3><p>{esc(copy)}</p></div></article>"
        for index, (title, copy) in enumerate([
            ("Get matched with a therapist", "We use your preferences and availability to surface a qualified, licensed therapist."),
            ("Review your match", "Your therapist can review what you shared and introduce themselves through the secure member area."),
            ("Begin communicating online", "Send text, audio, or video messages at any time, and schedule a live session when it works for you."),
        ], start=1)
    )
    comparison_rows = "".join(
        f"<tr><th scope='row'>{esc(label)}</th><td>{esc(online)}</td><td>{esc(in_person)}</td></tr>"
        for label, online, in_person in [
            ("Provided by a licensed therapist", "Yes", "Yes"),
            ("In-office visits", "No", "Yes"),
            ("Messaging any time", "Yes", "No"),
            ("Chat sessions", "Yes", "No"),
            ("Phone sessions", "Yes", "No"),
            ("Video sessions", "Yes", "No"),
            ("Easy scheduling", "Yes", "No"),
            ("Digital worksheets", "Yes", "No"),
            ("Group sessions", "Yes", "Unsure"),
            ("Smart provider matching", "Yes", "No"),
            ("Easy to switch providers", "Yes", "No"),
            ("Access therapy from anywhere", "Yes", "No"),
        ]
    )
    checked = " checked" if preferences.get("keep_active", True) else ""
    readiness_html = ""
    if readiness:
        readiness_html = "<div class='readiness-overlay'><section class='readiness-dialog' role='dialog' aria-modal='true' aria-labelledby='readiness-heading'><h2 id='readiness-heading'>Why don't you want to try therapy?</h2><p>You can review your options before continuing.</p><form method='post' action='/next/'><button class='text-button' name='action' value='readiness-not-ready' type='submit'>Still not ready</button><button class='green-button' name='action' value='readiness-start' type='submit'>I am ready to start</button><button class='trial-button' name='action' value='readiness-trial' type='submit'>Start my trial now</button></form></section></div>"
    return f"<main class='content-page next-page'><section class='next-welcome'><div><h1>{esc(account['display_name'])}, welcome to BetterHelp!</h1><p>Thanks for telling us your preferences. As we search for your therapist, read this guide and review your membership options.</p>{notice_html}</div><img src='/static/assets/next-counseling.svg' alt='Preparing to begin online therapy'></section><section class='process-section'><h2>More about the therapy process</h2><div class='process-grid'>{steps}</div></section><section class='next-options'><article><img src='/static/assets/next-ways.svg' alt=''><h2>How will I talk to my therapist?</h2><p>Choose secure text, audio, or video messages whenever you need to reach out. You can also schedule a 30 to 45 minute live session by phone, video, or live chat.</p></article><article><img src='/static/assets/next-outcomes.svg' alt=''><h2>What if I want a different therapist?</h2><p>You can request a different match when your needs or preferences change. We will show other available providers based on your location and availability.</p></article><article><img src='/static/assets/next-info.svg' alt=''><h2>How long can I use the service?</h2><p>Use the service as long as you need. You can manage or cancel your membership from your account settings.</p></article></section><section class='pricing-section'><div><span class='eyebrow'>Membership</span><h2><del>$90</del> $65 per week</h2><p>Your membership includes a weekly live session and text, audio, and video messaging whenever you like. Cancel anytime. HSA/FSA cards may be accepted depending on your provider.</p><div class='next-actions'><form method='post' action='/next/'><input type='hidden' name='action' value='start-therapy'><button class='green-button' type='submit'>Start therapy</button></form><a class='text-button' href='/financialaid/'>I can't afford therapy</a></div></div><div class='promo-panel'><h3>Have a benefit code?</h3><form method='post' action='/api/apply_promo_code'><label for='benefit-code'>Enter benefit code:</label><input id='benefit-code' name='promo-code' maxlength='32' autocomplete='off' required><button class='green-button' type='submit'>Check eligibility</button></form></div></section><section class='comparison-section'><h2>BetterHelp vs. traditional in-office therapy</h2><div class='comparison-table-wrap'><table><thead><tr><th scope='col'>Feature</th><th scope='col'>BetterHelp</th><th scope='col'>In-office</th></tr></thead><tbody>{comparison_rows}</tbody></table></div></section><section class='member-settings' aria-labelledby='language-settings-heading'><div><h2 id='language-settings-heading'>Language settings</h2><form method='post' action='/next/' data-member-settings><input type='hidden' name='action' value='save-settings'><label for='member-language'>Language</label><select id='member-language' name='language'><option selected>English</option></select><label class='keep-active'><input type='checkbox' name='keep_active' value='yes'{checked}> Keep me active</label><button class='green-button' type='submit'>Save</button></form></div><form method='post' action='/logout/'><button class='text-button' type='submit'>Log out</button></form></section>{readiness_html}</main>"


def therapy_process_response(request: Request, *, notice: str = "", status_code: int = 200, readiness: bool = False) -> HTMLResponse:
    with BACKEND.lifecycle.connection() as connection:
        preferences = business.member_preferences(connection, request_owner(request))
    return HTMLResponse(
        shell(
            "Get started - BetterHelp",
            therapy_process_page(authenticated_account(request), preferences, notice=notice, readiness=readiness),
            compact=True,
            member=True,
        ),
        status_code=status_code,
    )


@APP.get("/next/", response_class=HTMLResponse)
async def next_page(request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        current = business.intake(connection, request_owner(request))
    if current is None or not current["completed_at"]:
        return RedirectResponse("/get-started/", status_code=303)
    return therapy_process_response(request)


@APP.post("/next/", response_class=HTMLResponse)
async def next_page_post(request: Request) -> Response:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        current = business.intake(connection, request_owner(request))
    if current is None or not current["completed_at"]:
        return RedirectResponse("/get-started/", status_code=303)
    form = await request.form()
    action = str(form.get("action") or "")
    if action == "start-therapy":
        return therapy_process_response(request, readiness=True)
    if action == "readiness-start":
        return RedirectResponse("/matches/", status_code=303)
    if action == "readiness-not-ready":
        return therapy_process_response(request, notice="You can return when you are ready.")
    if action == "readiness-trial":
        return therapy_process_response(request, notice="A free trial is not available for this account.", status_code=422)
    if action == "benefit-code":
        code = " ".join(str(form.get("benefit_code") or "").split()).upper()
        if not code or len(code) > 32:
            return therapy_process_response(request, notice="Enter a valid benefit code.", status_code=422)
        return therapy_process_response(request, notice="Benefit code does not apply", status_code=422)
    if action == "save-settings":
        language = str(form.get("language") or "")
        keep_active = str(form.get("keep_active") or "") == "yes"
        try:
            with BACKEND.lifecycle.connection(transaction=True) as connection:
                business.save_member_preferences(
                    connection,
                    request_owner(request),
                    language=language,
                    keep_active=keep_active,
                )
        except ValueError as error:
            return therapy_process_response(request, notice=str(error), status_code=422)
        return therapy_process_response(request, notice="Settings saved.")
    return therapy_process_response(request, notice="Choose an option to continue.", status_code=422)


@APP.post("/api/apply_promo_code", response_class=HTMLResponse)
async def apply_promo_code(request: Request) -> Response:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        current = business.intake(connection, request_owner(request))
    if current is None or not current["completed_at"]:
        return RedirectResponse("/get-started/", status_code=303)
    form = await request.form()
    code = " ".join(str(form.get("promo-code") or "").split()).upper()
    if not code or len(code) > 32:
        return therapy_process_response(request, notice="Enter a valid benefit code.", status_code=422)
    return therapy_process_response(request, notice="Benefit code does not apply", status_code=422)


@APP.get("/member/", response_class=HTMLResponse)
async def member(request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    account = authenticated_account(request)
    owner = request_owner(request)
    with BACKEND.lifecycle.connection() as connection:
        progress = business.intake(connection, owner)
        rows = business.bookings(connection, owner)
        saved = business.saved_providers(connection, owner)
    answered = len(progress["answers"]) if progress else 0
    completed = "8 of 8 completed" if progress and progress["completed_at"] else f"{answered} of 8 completed"
    body = f"<main class='content-page member-page'><section class='page-hero'><h1>Welcome, {esc(account['display_name'])}</h1><p>{esc(account['email_normalized'])}</p></section><section class='member-grid'><a class='member-panel' href='/get-started/'><h2>Initial questionnaire</h2><p>{completed}</p><span>Continue matching →</span></a><a class='member-panel' href='/next/'><h2>Therapy process</h2><p>Learn what happens after matching and review membership options.</p><span>Read the guide →</span></a><a class='member-panel' href='/member/bookings/'><h2>My sessions</h2><p>{len(rows)} saved counseling sessions</p><span>View history →</span></a><a class='member-panel' href='/member/saved/'><h2>Saved therapists</h2><p>{len(saved)} saved matches</p><span>View saved →</span></a></section><form method='post' action='/logout/'><button class='green-button' type='submit'>Log out</button></form></main>"
    return HTMLResponse(shell("My BetterHelp member area", body, compact=True))


@APP.get("/matches/", response_class=HTMLResponse)
async def matches(request: Request, q: str = "") -> HTMLResponse:
    denied = completed_intake_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        current = business.intake(connection, request_owner(request))
        rows = business.providers(connection, q, str((current or {}).get("answers", {}).get("support", "")))
    cards = "".join(
        f"<article class='provider-card'><img src='/static/assets/{esc(row['image'])}' alt='Therapist'><div><h2>{esc(row['name'])}, {esc(row['credentials'])}</h2><p>{esc(row['bio'])}</p><p class='provider-specialties'>{esc(', '.join(json.loads(row['specialties_json'])))}</p><a class='green-button' href='/therapists/{esc(row['provider_id'])}/'>View profile</a><form method='post' action='/providers/{esc(row['provider_id'])}/save/'><button class='text-button' type='submit'>Save therapist</button></form></div></article>"
        for row in rows
    )
    if not cards:
        cards = "<div class='empty-state' data-no-results><h2>No therapists found</h2><p>Try a different search or support area.</p><a class='green-button' href='/matches/'>Show all matches</a></div>"
    body = f"<main class='content-page'><section class='page-hero'><h1>Your therapist matches</h1><p>These licensed providers were selected from your questionnaire.</p><form method='get' action='/matches/' class='search-form'><label for='match-search'>Search matches</label><input id='match-search' name='q' value='{esc(q)}' placeholder='Search by name or specialty'><button class='green-button'>Search</button></form></section><section class='provider-list'>{cards}</section></main>"
    return HTMLResponse(shell("Therapist matches - BetterHelp", body, compact=True))


@APP.get("/therapists/", response_class=HTMLResponse)
async def therapists(request: Request, q: str = "", specialty: str = "", sort: str = "name-asc") -> HTMLResponse:
    selected_sort = sort if sort in {"name-asc", "name-desc", "availability"} else "name-asc"
    with BACKEND.lifecycle.connection() as connection:
        rows = business.providers(connection, q, specialty, selected_sort)
    cards = "".join(f"<article class='provider-card'><img src='/static/assets/{esc(row['image'])}' alt='Therapist'><div><h2>{esc(row['name'])}, {esc(row['credentials'])}</h2><p>{esc(row['bio'])}</p><a class='green-button' href='/therapists/{esc(row['provider_id'])}/'>View profile</a></div></article>" for row in rows)
    if not cards:
        cards = "<div class='empty-state'><h2>No therapists found</h2><p>No providers matched that search.</p></div>"
    sort_options = "".join(
        f"<option value='{value}' {'selected' if selected_sort == value else ''}>{label}</option>"
        for value, label in (("name-asc", "Name A–Z"), ("name-desc", "Name Z–A"), ("availability", "Soonest availability"))
    )
    body = f"<main class='content-page'><section class='page-hero'><h1>Find a therapist</h1><p>Search the provider directory by name or specialty.</p><form method='get' class='search-form'><input aria-label='Search therapists' name='q' value='{esc(q)}' placeholder='Try anxiety'><input name='specialty' value='{esc(specialty)}' placeholder='Specialty'><label for='provider-sort'>Sort by</label><select id='provider-sort' name='sort'>{sort_options}</select><button class='green-button' type='submit'>Search</button></form></section><section class='provider-list'>{cards}</section></main>"
    return HTMLResponse(shell("Find a therapist - BetterHelp", body, compact=True))


@APP.get("/therapists/{provider_id}/", response_class=HTMLResponse)
async def therapist_detail(provider_id: str) -> HTMLResponse:
    with BACKEND.lifecycle.connection() as connection:
        row = business.provider(connection, provider_id)
        slots = business.provider_slots(connection, provider_id) if row else []
    if row is None:
        return HTMLResponse(shell("Therapist not found", "<main class='not-found'><h1>Therapist not found</h1><a class='green-button' href='/therapists/'>Back to therapists</a></main>", compact=True), status_code=404)
    times = "".join(f"<option value='{esc(slot['slot_id'])}'>{esc(slot['starts_at'])} UTC</option>" for slot in slots)
    body = f"<main class='content-page provider-detail'><section class='page-hero'><img class='provider-portrait' src='/static/assets/{esc(row['image'])}' alt='Therapist'><h1>{esc(row['name'])}, {esc(row['credentials'])}</h1><p>{esc(row['bio'])}</p><p>Specialties: {esc(', '.join(json.loads(row['specialties_json'])))}</p><form method='post' action='/providers/{esc(row['provider_id'])}/save/'><button class='text-button' type='submit'>Save therapist</button></form></section><section class='booking-panel'><h2>Choose an available session</h2><form method='post' action='/book/{esc(row['provider_id'])}/'><label for='slot'>Availability</label><select id='slot' name='slot_id' required>{times}</select><button class='green-button' type='submit'>Book this therapist</button></form></section></main>"
    return HTMLResponse(shell("Therapist profile - BetterHelp", body, compact=True))


@APP.post("/providers/{provider_id}/save/", response_class=HTMLResponse)
async def save_provider(provider_id: str, request: Request) -> Response:
    denied = completed_intake_required(request)
    if denied:
        return denied
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            business.save_provider(connection, request_owner(request), provider_id)
        return RedirectResponse("/member/saved/", status_code=303)
    except ValueError as exc:
        return HTMLResponse(shell("Save therapist error", f"<main class='content-page'><div class='error' role='alert'>{esc(exc)}</div></main>", compact=True), status_code=404)


@APP.get("/member/saved/", response_class=HTMLResponse)
async def saved_provider_page(request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        rows = business.saved_providers(connection, request_owner(request))
    cards = "".join(f"<article class='provider-card'><img src='/static/assets/{esc(row['image'])}' alt='Therapist'><div><h2>{esc(row['name'])}</h2><p>{esc(row['bio'])}</p><a class='green-button' href='/therapists/{esc(row['provider_id'])}/'>View profile</a></div></article>" for row in rows) or "<div class='empty-state'><h2>No saved therapists</h2><a class='green-button' href='/matches/'>View matches</a></div>"
    return HTMLResponse(shell("Saved therapists - BetterHelp", f"<main class='content-page'><section class='page-hero'><h1>Saved therapists</h1></section><section class='provider-list'>{cards}</section></main>", compact=True))


@APP.post("/book/{provider_id}/", response_class=HTMLResponse)
async def book_provider(provider_id: str, request: Request) -> Response:
    denied = completed_intake_required(request)
    if denied:
        return denied
    form = await request.form()
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            row = business.create_booking(connection, request_owner(request), provider_id, str(form.get("slot_id") or ""))
        return RedirectResponse(f"/booking/{row['booking_id']}/details/", status_code=303)
    except (ValueError, LookupError) as exc:
        return HTMLResponse(shell("Booking error", f"<main class='content-page'><div class='error' role='alert'>{esc(exc)}</div><a class='green-button' href='/therapists/{esc(provider_id)}/'>Choose another time</a></main>", compact=True), status_code=422)


@APP.get("/booking/{booking_id}/details/", response_class=HTMLResponse)
async def booking_details_get(booking_id: str, request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        row = business.owned_booking(connection, request_owner(request), booking_id)
    if row is None:
        return HTMLResponse(shell("Booking not found", "<main class='not-found'><h1>Booking not found</h1><a class='green-button' href='/matches/'>Return to matches</a></main>", compact=True), status_code=404)
    account = authenticated_account(request)
    body = f"<main class='content-page'><section class='page-hero'><h1>Booking details</h1><p>{esc(row['provider_name'])} · {esc(row['starts_at'])} UTC</p></section><form class='auth-card booking-form' method='post' action='/booking/{esc(booking_id)}/details/'><label for='display-name'>Name</label><input id='display-name' name='display_name' value='{esc(account['display_name'])}' required><label for='package-id'>Service package</label><select id='package-id' name='package_id' required><option value='live-session'>Live counseling session — $70.00 USD</option></select><label for='session-type'>Session format</label><select id='session-type' name='session_type' required><option value='video'>Video session</option><option value='phone'>Phone session</option><option value='live-chat'>Live chat session</option></select><label for='special-request'>Special requests</label><select id='special-request' name='special_request' required><option value='none'>No special requests</option><option value='synthetic-scheduling-request'>Scheduling request</option><option value='synthetic-accessibility-request'>Accessibility request</option></select><label><input type='checkbox' name='consent' value='yes' required> I understand the counseling session details.</label><button class='green-button' type='submit'>Continue to payment</button></form></main>"
    return HTMLResponse(shell("Booking details - BetterHelp", body, compact=True))


@APP.post("/booking/{booking_id}/details/", response_class=HTMLResponse)
async def booking_details_post(booking_id: str, request: Request) -> Response:
    denied = auth_required(request)
    if denied:
        return denied
    form = await request.form()
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            business.save_booking_details(
                connection,
                request_owner(request),
                booking_id,
                str(form.get("display_name") or ""),
                str(form.get("consent") or "") == "yes",
                package_id=str(form.get("package_id") or ""),
                session_type=str(form.get("session_type") or ""),
                special_request=str(form.get("special_request") or ""),
                expected_display_name=authenticated_account(request)["display_name"],
            )
        return RedirectResponse(f"/booking/{booking_id}/payment/", status_code=303)
    except LookupError:
        return HTMLResponse(shell("Booking not found", "<main class='not-found'><h1>Booking not found</h1></main>", compact=True), status_code=404)
    except ValueError as exc:
        return HTMLResponse(shell("Booking details error", f"<main class='content-page'><div class='error' role='alert'>{esc(exc)}</div><a href='/booking/{esc(booking_id)}/details/'>Try again</a></main>", compact=True), status_code=422)


@APP.get("/booking/{booking_id}/payment/", response_class=HTMLResponse)
async def payment_get(booking_id: str, request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        row = business.owned_booking(connection, request_owner(request), booking_id)
    if row is None:
        return HTMLResponse(shell("Booking not found", "<main class='not-found'><h1>Booking not found</h1></main>", compact=True), status_code=404)
    body = f"<main class='content-page'><section class='page-hero'><h1>Review and payment</h1><p>{esc(PACKAGE_LABELS[row['package_id']])} · {esc(SESSION_LABELS[row['session_type']])}</p><p>{esc(row['provider_name'])} · {esc(row['starts_at'])} UTC · Secure online session</p><p>Special request: {esc(SPECIAL_REQUEST_LABELS[row['special_request']])}</p><p><strong>Total: $70.00 USD</strong></p></section><form method='post' action='/booking/{esc(booking_id)}/payment/' class='auth-card'><p>Select a saved payment method to continue.</p><label for='scenario'>Payment method</label><select id='scenario' name='scenario_id' required><option value='sandbox-approved'>Visa ending in 4242</option><option value='sandbox-declined'>Visa ending in 0002</option><option value='sandbox-retry'>Visa ending in 0119</option></select><button class='green-button' type='submit'>Confirm payment</button></form></main>"
    return HTMLResponse(shell("Payment - BetterHelp", body, compact=True))


@APP.post("/booking/{booking_id}/payment/", response_class=HTMLResponse)
async def payment_post(booking_id: str, request: Request) -> Response:
    denied = auth_required(request)
    if denied:
        return denied
    form = await request.form()
    forbidden = {"card_number", "pan", "cvv", "cvc", "expiry", "expiration", "token", "payment_method"}
    if forbidden.intersection(form.keys()):
        return HTMLResponse(shell("Payment input rejected", "<main class='content-page'><div class='error' role='alert'>Payment card details cannot be entered here.</div></main>", compact=True), status_code=422)
    scenario = str(form.get("scenario_id") or "")
    if scenario not in {"sandbox-approved", "sandbox-declined", "sandbox-retry"}:
        return HTMLResponse(shell("Payment error", "<main class='content-page'><div class='error' role='alert'>Choose a payment method.</div></main>", compact=True), status_code=422)
    account = authenticated_account(request)
    try:
        row, result = business.pay_booking(BACKEND, request_owner(request), booking_id, account["email_normalized"], scenario)
        if result["status"] == "DECLINED":
            return HTMLResponse(shell("Payment declined", "<main class='content-page'><div class='error' role='alert'>The payment was declined.</div><a class='green-button' href='/booking/%s/payment/'>Try again</a></main>" % esc(booking_id), compact=True), status_code=402)
        if result["status"] == "RETRYABLE":
            return HTMLResponse(shell("Payment retry", "<main class='content-page'><div class='error' role='alert'>The payment needs you to try again.</div><a class='green-button' href='/booking/%s/payment/'>Try again</a></main>" % esc(booking_id), compact=True), status_code=409)
        return RedirectResponse(f"/booking/{booking_id}/confirmation/", status_code=303)
    except LookupError:
        return HTMLResponse(shell("Booking not found", "<main class='not-found'><h1>Booking not found</h1></main>", compact=True), status_code=404)
    except (ValueError, PaymentError) as exc:
        status = 409 if "appointment time" in str(exc).casefold() else 422
        return HTMLResponse(shell("Payment error", f"<main class='content-page'><div class='error' role='alert'>{esc(exc)}</div></main>", compact=True), status_code=status)


@APP.get("/booking/{booking_id}/confirmation/", response_class=HTMLResponse)
async def booking_confirmation(booking_id: str, request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        row = business.owned_booking(connection, request_owner(request), booking_id)
    if row is None:
        return HTMLResponse(shell("Booking not found", "<main class='not-found'><h1>Booking not found</h1></main>", compact=True), status_code=404)
    statuses = {
        "confirmed": ("Session confirmed", "Confirmation is available in My sessions."),
        "cancelled": ("Session cancelled", "This appointment was cancelled."),
        "details-ready": ("Session awaiting payment", "Complete payment to confirm this session."),
        "draft": ("Session details required", "Complete the booking details to continue."),
    }
    status, notice = statuses.get(row["status"], ("Session unavailable", "This session is no longer available."))
    intake_answers = json.loads(row["intake_snapshot_json"])
    intake_items = "".join(
        f"<li><strong>{esc(field.replace('_', ' ').title())}:</strong> {esc(INTAKE_LABELS.get(field, {}).get(intake_answers[field], intake_answers[field]))}</li>"
        for field in ("therapy_type", "state", "support", "therapist_preference", "therapy_experience", "communication", "availability", "goal")
        if field in intake_answers
    )
    intake_summary = (
        f"<h2>Your matching preferences</h2><ul class='confirmation-summary'>{intake_items}</ul>"
        if intake_items
        else "<h2>Your matching preferences</h2><p>Matching preference summary is unavailable for this earlier appointment.</p>"
    )
    body = f"<main class='content-page confirmation-page'><section class='success-panel' role='status'><h1>{status}</h1><p>{esc(row['provider_name'])} · {esc(row['starts_at'])} UTC</p><p>{esc(PACKAGE_LABELS[row['package_id']])} · {esc(SESSION_LABELS[row['session_type']])} · Secure online session</p><p>Special request: {esc(SPECIAL_REQUEST_LABELS[row['special_request']])}</p><p><strong>Total: $70.00 USD</strong></p>{intake_summary}<p>Booking ID: {esc(booking_id)}</p><p>{notice}</p><a class='green-button' href='/member/bookings/'>View my sessions</a></section></main>"
    return HTMLResponse(shell("Session confirmation - BetterHelp", body, compact=True))


@APP.get("/member/bookings/", response_class=HTMLResponse)
async def member_bookings(request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    with BACKEND.lifecycle.connection() as connection:
        rows = business.bookings(connection, request_owner(request))
    card_parts = []
    for row in rows:
        booking_id = esc(row["booking_id"])
        confirmation = f"<a class='green-button' href='/booking/{booking_id}/confirmation/'>View confirmation</a>" if row["status"] == "confirmed" else ""
        controls = ""
        if row["status"] == "confirmed":
            with BACKEND.lifecycle.connection() as availability_connection:
                slots = business.provider_slots(availability_connection, row["provider_id"])
            options = "".join(
                f"<option value='{esc(slot['slot_id'])}'>{esc(slot['starts_at'])} UTC</option>"
                for slot in slots
            )
            reschedule = (
                f"<form class='booking-action-form' data-reschedule-booking='{booking_id}' "
                f"method='post' action='/booking/{booking_id}/manage/'>"
                f"<input type='hidden' name='action' value='reschedule'>"
                f"<label for='reschedule-{booking_id}'>Change time</label>"
                f"<select id='reschedule-{booking_id}' name='slot_id' required>{options}</select>"
                f"<button class='text-button' type='submit'>Reschedule</button></form>"
                if options
                else "<p class='muted-note'>No other times are available.</p>"
            )
            cancel = (
                f"<form class='booking-action-form booking-cancel-form' data-cancel-booking='{booking_id}' "
                f"method='post' action='/booking/{booking_id}/manage/'>"
                f"<input type='hidden' name='action' value='cancel'>"
                f"<button class='text-button' type='submit'>Cancel session</button></form>"
            )
            review = (
                f"<form class='booking-action-form' data-review-booking='{booking_id}' "
                f"method='post' action='/booking/{booking_id}/review/'>"
                f"<label for='rating-{booking_id}'>Rate this session</label>"
                f"<select id='rating-{booking_id}' name='rating' required>"
                f"<option value=''>Choose a rating</option><option value='1'>1 - Poor</option>"
                f"<option value='2'>2 - Fair</option><option value='3'>3 - Good</option>"
                f"<option value='4'>4 - Very good</option><option value='5'>5 - Excellent</option>"
                f"</select><label for='comment-{booking_id}'>Review</label>"
                f"<select id='comment-{booking_id}' name='comment' required>"
                f"<option value=''>Choose a review</option>"
                f"<option value='This session was helpful.'>This session was helpful.</option>"
                f"</select><button class='text-button' type='submit'>Save review</button></form>"
            ) if business.reviewable(row) else ""
            controls = f"<div class='booking-actions'>{reschedule}{cancel}{review}</div>"
        card_parts.append(
            f"<article class='booking-card' data-booking-id='{booking_id}'>"
            f"<h2>{esc(row['provider_name'])}</h2>"
            f"<p>{esc(row['starts_at'])} UTC · {esc(SESSION_LABELS[row['session_type']])} · <strong>{esc(row['status'])}</strong></p>"
            f"<p>Booking ID: {booking_id}</p>{confirmation}{controls}</article>"
        )
    cards = "".join(card_parts) or "<div class='empty-state'><h2>No sessions yet</h2><a class='green-button' href='/matches/'>Find a therapist</a></div>"
    return HTMLResponse(shell("My sessions - BetterHelp", f"<main class='content-page'><section class='page-hero'><h1>My sessions</h1></section><section class='booking-list'>{cards}</section></main>", compact=True))


@APP.post("/booking/{booking_id}/manage/", response_class=HTMLResponse)
async def booking_manage(booking_id: str, request: Request) -> Response:
    denied = auth_required(request)
    if denied:
        return denied
    form = await request.form()
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            business.manage_booking(connection, request_owner(request), booking_id, str(form.get("action") or ""), str(form.get("slot_id") or ""))
        return RedirectResponse("/member/bookings/", status_code=303)
    except LookupError:
        return HTMLResponse(shell("Booking not found", "<main class='not-found'><h1>Booking not found</h1></main>", compact=True), status_code=404)
    except ValueError as exc:
        return HTMLResponse(shell("Booking update error", f"<main class='content-page'><div class='error' role='alert'>{esc(exc)}</div></main>", compact=True), status_code=422)


@APP.post("/booking/{booking_id}/review/", response_class=HTMLResponse)
async def booking_review(booking_id: str, request: Request) -> Response:
    denied = auth_required(request)
    if denied:
        return denied
    form = await request.form()
    try:
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            business.add_review(connection, request_owner(request), booking_id, int(str(form.get("rating") or "0")), str(form.get("comment") or ""))
        return RedirectResponse("/member/bookings/", status_code=303)
    except (LookupError, ValueError):
        return HTMLResponse(shell("Review error", "<main class='content-page'><div class='error' role='alert'>A confirmed session and review are required.</div></main>", compact=True), status_code=422)


@APP.post("/contact/", response_class=HTMLResponse)
async def contact_post(request: Request) -> Response:
    form = await request.form()
    try:
        first_name = synthetic_display_name(f"{form.get('first_name') or ''} {form.get('last_name') or ''}")
        email = synthetic_email(str(form.get("email") or ""))
        topic = str(form.get("topic") or "")
        message = str(form.get("message") or "")
        if not first_name or not email:
            raise ValueError("Enter a first name, last name, and valid email address.")
        if not message.strip():
            raise ValueError("Enter a short message.")
        owner = support_owner(request)
        with BACKEND.lifecycle.connection(transaction=True) as connection:
            request_id = business.add_support_request(connection, owner, topic, message)
        return RedirectResponse(f"/contact/?submitted={request_id}", status_code=303)
    except ValueError as exc:
        return HTMLResponse(shell("Contact error", f"<main class='content-page'><div class='error' role='alert'>{esc(exc)}</div></main>", compact=True), status_code=422)


@APP.get("/contact/", response_class=HTMLResponse)
async def contact_get(request: Request, submitted: str = "") -> HTMLResponse:
    with BACKEND.lifecycle.connection() as connection:
        valid_submission = business.support_request_owned(connection, support_owner(request), submitted)
    notice = "<div class='success-panel' role='status'>Your support request was received. A member of the Customer Success Team will review it.</div>" if valid_submission else ""
    topics = [
        ("registered-client", "I am a registered client and I need support."),
        ("current-therapist", "I am a current BetterHelp therapist and I need support."),
        ("therapist-applicant", "I am a therapist interested in joining or a current applicant."),
        ("service-question", "I have a question about the service."),
        ("billing", "I have a billing-related question."),
        ("press", "I have a press-related question."),
        ("business", "I have a business-related inquiry."),
        ("organization", "I am interested in BetterHelp for my organization."),
    ]
    options = "".join(f"<option value='{value}'>{esc(label)}</option>" for value, label in topics)
    body = f"<main class='content-page contact-page'><section class='page-hero'><h1>Contact us</h1><p>Our Customer Success Team is here to help with questions, concerns, and feedback. You can also find answers in our <a href='/faq/'>frequently asked questions</a>.</p>{notice}</section><section class='contact-layout'><form class='auth-card contact-form' method='post' action='/contact/'><h2>Send us a message</h2><div class='form-row'><label for='first-name'>First name</label><input id='first-name' name='first_name' autocomplete='given-name' required><label for='last-name'>Last name</label><input id='last-name' name='last_name' autocomplete='family-name' required></div><label for='contact-email'>Email address</label><input id='contact-email' name='email' type='email' placeholder='alex@example.test' required><label for='topic'>What can we help with?</label><select id='topic' name='topic' required><option value='' selected disabled>Select a topic</option>{options}</select><label for='message'>Message</label><textarea id='message' name='message' maxlength='500' placeholder='Tell us how we can help' required></textarea><button class='green-button' type='submit'>Submit</button></form><aside class='contact-details'><h2>BetterHelp</h2><address>3155 Olsen Dr.<br>Suite #375<br>San Jose, CA 95117<br>USA</address><p><a href='mailto:contact@betterhelp.com'>contact@betterhelp.com</a></p><p>For urgent concerns, visit our <a href='/help/'>Help center</a>.</p></aside></section></main>"
    return HTMLResponse(shell("Contact BetterHelp", body, compact=True))


@APP.get("/help/", response_class=HTMLResponse)
async def help_page() -> HTMLResponse:
    extra = "<section class='faq-list'><details open><summary>How do I get started?</summary><p>Create an account, then complete the matching questionnaire.</p></details><details><summary>How do I verify my account?</summary><p>Enter the verification code provided after registration.</p></details><details><summary>How do I change a session?</summary><p>Open My sessions to reschedule or cancel a confirmed session.</p></details></section>"
    return HTMLResponse(content_page("Help - BetterHelp", "Help and recovery", "Find answers about your account and sessions.", extra=extra))


@APP.get("/financialaid/", response_class=HTMLResponse)
async def financial_aid(request: Request) -> HTMLResponse:
    denied = auth_required(request)
    if denied:
        return denied
    extra = "<section class='editorial-grid'><article><h2>Reduced membership cost</h2><p>Financial aid may be available when the standard membership price does not fit your budget.</p></article><article><h2>Review your options</h2><p>Return to the therapy process page to review membership details or enter an eligible benefit code.</p><a class='green-button' href='/next/'>Review membership</a></article></section>"
    return HTMLResponse(content_page("Financial aid - BetterHelp", "Financial aid", "Explore options that may make therapy more affordable.", extra=extra))


@APP.post("/__admin/reset", response_class=JSONResponse)
async def admin_reset(request: Request) -> JSONResponse:
    if not _loopback(request):
        return JSONResponse({"error": "loopback only"}, status_code=403)
    if not hmac.compare_digest(request.headers.get("X-WebsiteBench-Admin-Token", ""), ADMIN_TOKEN):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    def reset_all(connection):
        BACKEND.lifecycle.reset_embedded(connection, confirm_site_id=SITE_ID)
        business.migrate_v4(connection)
        business.reset_mutable(connection)
    AUTH.reset_site_state(site_reset=reset_all, seed_accounts=[])
    response = JSONResponse({"reset": True, "site_id": SITE_ID})
    _set_session_cookie(request, response, AUTH.create_anonymous_session())
    return response


@APP.get("/{path:path}", response_class=HTMLResponse)
async def fallback(path: str) -> HTMLResponse:
    normalized = "/" + path.strip("/") + "/"
    pages = {
        "/advice/": ("Advice", "Explore articles and practical ideas for mental health and wellbeing."),
        "/therapists/": ("Find a therapist", "Explore how BetterHelp helps you connect with a licensed therapist."),
        "/online-therapy/": ("Online therapy", "Professional support from wherever you are."),
        "/contact/": ("Contact", "Find answers and support for your BetterHelp experience."),
        "/gift/": ("Gift a membership", "Give the gift of online therapy to someone you care about."),
        "/gethelpnow/": ("Get help now", "If you are in crisis or may be in danger, contact local emergency services or a crisis resource."),
        "/terms/": ("Terms & Conditions", "Review the terms that apply to BetterHelp services."),
        "/privacy/": ("Privacy Policy", "Learn how BetterHelp handles information and privacy."),
        "/health-data/": ("Health Data", "Learn how health information is handled and protected."),
        "/accessibility/": ("Web Accessibility", "Learn about accessibility features and support."),
        "/careers/": ("Careers", "Explore opportunities with BetterHelp."),
        "/counselor_application/": ("Therapist jobs", "Learn about opportunities for licensed therapists."),
        "/aarp/": ("AARP", "BetterHelp information for AARP members."),
        "/business/": ("Business", "BetterHelp solutions for organizations and their people."),
        "/sharing-settings/": ("Sharing settings", "Manage your privacy and sharing preferences."),
    }
    if normalized in pages:
        heading, copy = pages[normalized]
        return HTMLResponse(content_page(f"{heading} - BetterHelp", heading, copy))
    return HTMLResponse(shell("Page not found - BetterHelp", "<main class='not-found'><h1>Page not found</h1><p>We couldn't find that page.</p><a class='green-button' href='/'>Return home</a></main>", compact=True), status_code=404)


app = APP

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:APP", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8458")))
