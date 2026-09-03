"""Server-rendered marketing and auth pages for the Asana offline clone.

Copy on the login/forgot pages is reproduced from directly captured anonymous
evidence (EA1). Marketing pages reproduce server-rendered headings observed by
EA2; their full source visuals were unavailable (renderer crash), so layout is
an honest local design in Asana's visual language, not a pixel claim.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

LOGO_SVG = (
    '<svg viewBox="0 0 112 22" width="112" height="22" aria-hidden="true">'
    '<path d="M108.202 16.703c.067.765.679 1.739 1.74 1.739h.62a.44.44 0 0 0 .438-.438V4.359h-.003a.437.437 0 0 0-.435-.414h-1.922a.437.437 0 0 0-.435.414h-.003v1.109c-1.178-1.452-3.035-2.055-4.897-2.055a7.667 7.667 0 0 0-7.665 7.67 7.668 7.668 0 0 0 7.665 7.672c1.862 0 3.892-.723 4.897-2.054v.002Zm-4.89-.633c-2.692 0-4.874-2.232-4.874-4.986 0-2.754 2.182-4.986 4.874-4.986 2.693 0 4.875 2.232 4.875 4.986 0 2.754-2.182 4.986-4.875 4.986ZM93.21 17.172v-7.06c0-3.981-2.51-6.666-6.51-6.666-1.91 0-3.476 1.105-4.029 2.055-.12-.743-.513-1.523-1.735-1.523h-.622a.439.439 0 0 0-.438.438v13.646h.003c.012.23.203.414.435.414h1.923c.232 0 .422-.184.435-.414h.002v-8.06a3.87 3.87 0 0 1 7.736 0l.001 8.06h.002c.013.23.203.414.435.414h1.923c.232 0 .422-.184.435-.414h.003v-.89ZM73.188 16.703c.067.765.68 1.739 1.74 1.739h.62c.24 0 .437-.197.437-.438V4.359h-.002a.438.438 0 0 0-.435-.414h-1.923a.438.438 0 0 0-.435.414h-.002v1.109c-1.178-1.452-3.035-2.055-4.898-2.055a7.667 7.667 0 0 0-7.664 7.67c0 4.237 3.431 7.672 7.664 7.672 1.863 0 3.892-.723 4.898-2.054v.002Zm-4.89-.633c-2.692 0-4.875-2.232-4.875-4.986 0-2.754 2.183-4.986 4.875-4.986s4.874 2.232 4.874 4.986c0 2.754-2.182 4.986-4.874 4.986ZM49.257 14.748c1.283.89 2.684 1.322 4.03 1.322 1.283 0 2.609-.665 2.609-1.823 0-1.546-2.89-1.787-4.705-2.405-1.815-.617-3.379-1.893-3.379-3.96 0-3.163 2.816-4.47 5.444-4.47 1.665 0 3.383.55 4.497 1.338.384.29.15.625.15.625l-1.063 1.52c-.12.17-.328.318-.628.133s-1.352-.93-2.956-.93c-1.603 0-2.57.74-2.57 1.66 0 1.1 1.256 1.447 2.727 1.823 2.562.691 5.357 1.522 5.357 4.666 0 2.786-2.604 4.508-5.483 4.508-2.181 0-4.038-.622-5.596-1.766-.324-.325-.098-.627-.098-.627l1.058-1.512c.216-.282.487-.184.606-.102ZM41.866 16.703c.068.765.68 1.739 1.74 1.739h.62a.44.44 0 0 0 .438-.438V4.359h-.003a.437.437 0 0 0-.435-.414h-1.922a.438.438 0 0 0-.435.414h-.003v1.109c-1.178-1.452-3.035-2.055-4.897-2.055a7.668 7.668 0 0 0-7.665 7.67c0 4.237 3.432 7.672 7.665 7.672 1.862 0 3.892-.723 4.897-2.054v.002Zm-4.89-.633c-2.692 0-4.874-2.232-4.874-4.986 0-2.754 2.182-4.986 4.875-4.986 2.692 0 4.874 2.232 4.874 4.986 0 2.754-2.182 4.986-4.874 4.986Z" fill="#0D0E10"/>'
    '<path d="M18.559 11.605a5.158 5.158 0 1 0 0 10.317 5.158 5.158 0 0 0 0-10.317Zm-13.401.001a5.158 5.158 0 1 0 0 10.315 5.158 5.158 0 0 0 0-10.315Zm11.858-6.448a5.158 5.158 0 1 1-10.316 0 5.158 5.158 0 0 1 10.316 0Z" fill="#F06A6A"/></svg>'
)

LANGUAGE_SVG = (
    '<svg viewBox="0 0 19 19" width="28" height="28" aria-hidden="true">'
    '<path d="M9.5 0A9.5 9.5 0 1 0 9.5 19 9.5 9.5 0 0 0 9.5 0Zm7.481 5.938h-3.622c-.296-1.841-.83-3.385-1.543-4.394a8.35 8.35 0 0 1 5.165 4.394ZM12.469 9.5c0 .831-.06 1.603-.119 2.375h-5.7A31 31 0 0 1 6.531 9.5c0-.831.06-1.603.119-2.375h5.7c.06.772.119 1.544.119 2.375ZM9.5 17.813c-1.01 0-2.138-1.841-2.672-4.75h5.344c-.535 2.909-1.663 4.75-2.672 4.75ZM6.828 5.938C7.363 3.028 8.491 1.188 9.5 1.188c1.01 0 2.138 1.84 2.672 4.75H6.828ZM7.184 1.544c-.712 1.01-1.246 2.553-1.543 4.394H2.019a8.35 8.35 0 0 1 5.165-4.394ZM1.544 7.125h3.919A31 31 0 0 0 5.344 9.5c0 .831.06 1.603.119 2.375H1.544A8.3 8.3 0 0 1 1.188 9.5c0-.831.118-1.603.356-2.375Zm.475 5.938h3.622c.297 1.84.831 3.384 1.543 4.393a8.35 8.35 0 0 1-5.165-4.393Zm9.797 4.393c.712-1.069 1.246-2.553 1.543-4.393h3.622a8.35 8.35 0 0 1-5.165 4.393Zm5.64-5.581h-3.919c.06-.772.119-1.544.119-2.375 0-.831-.06-1.603-.119-2.375h3.919c.237.772.356 1.544.356 2.375 0 .831-.119 1.603-.356 2.375Z" fill="#0D0E10"/></svg>'
)


def _head(title: str, extra: str = "") -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/site.css?v=public-nav-1">{extra}</head>"""


def _marketing_nav(active: str = "") -> str:
    def menu_link(title: str, href: str, copy: str = "", icon: str = "",
                  badge: str = "") -> str:
        icon_html = f'<i class="mnav-item-icon {icon}" aria-hidden="true">✣</i>' if icon else ""
        copy_html = f'<small>{copy}</small>' if copy else ""
        badge_html = f'<em>{badge}</em>' if badge else ""
        return (f'<li><a href="{href}">{icon_html}<span><strong>{title}</strong>'
                f'{copy_html}</span>{badge_html}<b aria-hidden="true">→</b></a></li>')

    def group(title: str, links: list[tuple[str, str, str, str, str]]) -> str:
        return (f'<section class="mnav-group"><p>{title}</p><ul>'
                + "".join(menu_link(*link) for link in links) + '</ul></section>')

    product_groups = [
        ("PRODUCTS", [
            ("Agentic Work Management", "/product/ai", "For cross-functional teams", "pink", ""),
            ("Asana Service Management", "/product/service-management", "For service teams", "green", "Coming soon"),
            ("Asana Client Management", "/product/client-management", "For teams delivering client work", "yellow", "Coming soon"),
            ("Command by Asana", "/product/command", "For developer teams", "blue", "Coming soon"),
            ("StackAI by Asana", "/product/stackai", "For every critical workflow", "gray", ""),
        ]),
        ("AI PLATFORM", [
            ("AI Teammates", "/product/ai/ai-teammates", "Ready-to-go AI agents for every team", "plain", ""),
            ("AI Studio", "/product/ai/ai-studio", "Powerful no-code automations", "plain", ""),
            ("Asana Dash", "/product/ai/dash", "Your AI Chief of Staff", "plain", ""),
        ]),
        ("ASANA FOUNDATIONS", [
            ("Admin and security", "/features/admin-security", "", "", ""),
            ("App integrations", "/apps", "", "", ""),
            ("Developer", "/developers", "", "", ""),
            ("Latest feature release", "/whats-new", "", "", ""),
        ]),
    ]
    solution_groups = [
        ("COMPANY TYPE", [("Enterprise", "/enterprise", "", "", ""), ("Small business", "/small-business", "", "", ""), ("Nonprofit", "/industry/nonprofit", "", "", ""), ("Agencies", "/agencies", "", "", "")]),
        ("TEAMS", [("Operations", "/teams/operations", "", "", ""), ("Marketing", "/teams/marketing", "", "", ""), ("IT", "/teams/it", "", "", ""), ("Leaders", "/teams/leaders", "", "", "")]),
        ("INDUSTRIES", [("Government", "/industry/government-solutions", "", "", ""), ("Healthcare", "/industry/healthcare", "", "", ""), ("Retail", "/industry/retail", "", "", ""), ("Financial services", "/industry/financial-services", "", "", ""), ("Education", "/industry/education", "", "", ""), ("Manufacturing", "/industry/manufacturing", "", "", "")]),
        ("USE CASES", [("Goal management", "/uses/goal-management", "", "", ""), ("Organizational planning", "/uses/organizational-planning", "", "", ""), ("Project intake", "/uses/project-intake", "", "", ""), ("Resource planning", "/uses/resource-planning", "", "", ""), ("Product launches", "/uses/product-launch", "", "", ""), ("View all use cases", "/uses", "", "", "")]),
    ]
    learning_groups = [
        ("LEARN", [("Resource center", "/resources", "", "", ""), ("Events and webinars", "/events", "", "", ""), ("Customer stories", "/customers", "", "", ""), ("Asana Academy", "/academy", "", "", ""), ("Certifications", "/certifications", "", "", ""), ("Trainings", "/academy/trainings", "", "", "")]),
        ("SUPPORT", [("Help Center", "/help", "", "", ""), ("Community", "/community", "", "", ""), ("Templates", "/templates", "", "", "")]),
        ("SERVICES", [("Customer Success", "/customer-success", "", "", ""), ("Find a partner", "/partners/channel/directory", "", "", ""), ("Become a partner", "/partners", "", "", "")]),
    ]
    menu_specs = [
        ("Products", "product", product_groups),
        ("Solutions", "solutions", solution_groups),
        ("Learning & support", "resources", learning_groups),
    ]
    menu_buttons = "".join(
        f'<button class="mnav-link has-menu{" active" if active == key else ""}" type="button" '
        f'data-nav-menu="{key}" aria-expanded="false" aria-controls="mnav-panel-{key}">{label}</button>'
        for label, key, _ in menu_specs
    )
    panels = "".join(
        f'<div class="mnav-panel mnav-panel-{key}" id="mnav-panel-{key}" role="tabpanel" '
        f'aria-hidden="true">{"".join(group(title, links) for title, links in groups)}</div>'
        for _, key, groups in menu_specs
    )
    items = menu_buttons + (
        f'<a href="/pricing" class="mnav-link{" active" if active == "pricing" else ""}">Pricing</a>'
    )
    if active == "pricing":
        actions = f"""<a class="mnav-language" href="/resources" aria-label="Choose your preferred language">{LANGUAGE_SVG}</a>
      <a class="pricing-sales-link" href="/solutions">Contact sales</a>
      <a class="btn primary sales" href="/create-account">Get started</a>"""
    else:
        actions = f"""<a class="mnav-language" href="/resources" aria-label="Choose your preferred language">{LANGUAGE_SVG}</a>
      <a class="btn ghost" href="/-/login">Log in</a>
      <a class="btn ghost sales" href="/solutions">Contact sales</a>
      <a class="btn primary" href="/create-account">Get started</a>"""
    return f"""<header class="mnav">
  <div class="mnav-inner">
    <a class="mnav-logo" href="/" aria-label="Asana home">{LOGO_SVG}<span>asana</span></a>
    <button class="mnav-burger" aria-label="Menu" aria-expanded="false" onclick="const links=document.querySelector('.mnav-links');const open=links.classList.toggle('open');this.setAttribute('aria-expanded',String(open))">☰</button>
    <nav class="mnav-links">{items}</nav>
    <div class="mnav-actions">{actions}</div>
  </div>
</header>
<div class="mnav-layer" hidden>
  <button class="mnav-scrim" type="button" aria-label="Close navigation menu"></button>
  <div class="mnav-mega-shell"><div class="mnav-panel-slot">{panels}</div>
    <div class="mnav-mega-footer"><a href="/sales"><i aria-hidden="true">▣</i>Contact sales</a>
      <a href="/demo/main"><i aria-hidden="true">◯</i>View demo</a>
      <a href="/download"><i aria-hidden="true">⇩</i>Download app</a></div>
  </div>
</div>"""


def _marketing_footer(full_home: bool = False) -> str:
    if full_home:
        cols = [
            ("New to Asana?", [("Product overview", "/product"), ("All features", "/product#features"),
                               ("Latest feature release", "/product#latest"), ("Pricing", "/pricing"),
                               ("Starter plan", "/pricing#starter"), ("Advanced plan", "/pricing#advanced"),
                               ("Enterprise", "/solutions#enterprise"), ("App integrations", "/product#integrations"),
                               ("AI work management", "/product#ai"), ("Project management", "/resources")]),
            ("Use cases", [("Campaign management", "/templates/marketing"), ("Content calendar", "/templates/marketing"),
                           ("Creative production", "/templates/design"), ("Goal management", "/templates/operations-pmo"),
                           ("New hire onboarding", "/templates/hr"), ("Organizational planning", "/templates/operations-pmo"),
                           ("Product launches", "/templates/product-engineering"), ("Resource planning", "/resources"),
                           ("Strategic planning", "/resources/category/strategic-planning"),
                           ("Task Management", "/product")]),
            ("Solutions", [("Small business", "/solutions"), ("Marketing", "/solutions#marketing"),
                           ("Operations", "/solutions#operations"), ("IT", "/templates/it"),
                           ("Product", "/solutions#product"), ("Sales", "/templates/sales-cx"),
                           ("Healthcare", "/solutions#enterprise"), ("Retail", "/solutions#enterprise"),
                           ("Government", "/solutions#enterprise"), ("Education", "/solutions#enterprise")]),
            ("Resources", [("Help Center", "/resources#support"), ("Get support", "/resources#support"),
                           ("Asana Academy", "/resources#guide"), ("Certifications", "/resources#guide"),
                           ("Forum", "/resources"), ("Resource center", "/resources"),
                           ("Events and webinars", "/resources"), ("Project templates", "/templates"),
                           ("Customer Success", "/resources"), ("Developers and API", "/resources")]),
            ("Company", [("About us", "/resources"), ("Leadership", "/resources"),
                         ("Customers", "/resources"), ("Careers", "/resources"),
                         ("Inside Asana", "/resources"), ("Culture", "/resources"),
                         ("Press", "/resources"), ("Investor relations", "/resources"),
                         ("Trust and security", "/resources"), ("Privacy", "/terms/privacy-statement")]),
        ]
        body = "".join(
            '<div class="fcol"><h4>%s</h4>%s</div>' % (
                title, "".join(f'<a href="{href}">{label}</a>' for label, href in links))
            for title, links in cols)
        return f"""<footer class="mfooter mfooter-home">
  <div class="mfooter-inner">
    <div class="fbrand" aria-label="Asana home">{LOGO_SVG}</div>
    <div class="fcols">{body}</div>
    <div class="flegal-row">
      <span>© 2026 Asana, Inc.</span><a href="/resources">◎ English</a>
      <span class="fsocial" aria-label="Social links"><a href="/resources">X</a><a href="/resources">in</a><a href="/resources">◎</a><a href="/resources">f</a><a href="/resources">▶</a></span>
      <a href="/terms/terms-of-service">Terms</a><span>&amp;</span><a href="/terms/privacy-statement">Privacy</a>
    </div>
    <div class="fapp-row"><a href="/resources"> App Store</a><a href="/resources">▶ Google Play</a></div>
  </div>
</footer>"""
    cols = [
        ("Asana", [("Home", "/"), ("Product", "/product"), ("Pricing", "/pricing"),
                   ("Templates", "/templates"), ("Log In", "/-/login")]),
        ("Solutions", [("Marketing", "/solutions#marketing"), ("Operations", "/solutions#operations"),
                       ("Product teams", "/solutions#product"), ("Enterprise", "/solutions#enterprise")]),
        ("Resources", [("Resource center", "/resources"), ("Asana guide", "/resources#guide"),
                       ("Templates", "/templates"), ("Support", "/resources#support")]),
        ("Get started", [("Sign Up", "/create-account"), ("View demo", "/demo/main"),
                         ("Terms", "/terms/terms-of-service"),
                         ("Privacy", "/terms/privacy-statement")]),
    ]
    body = "".join(
        '<div class="fcol"><h4>%s</h4>%s</div>' % (
            t, "".join(
                f'<a href="{h}"{" id=\"footer-support\"" if x == "Support" else ""}>{x}</a>'
                for x, h in ls))
        for t, ls in cols)
    return f"""<footer class="mfooter">
  <div class="mfooter-inner">
    <div class="fbrand">{LOGO_SVG}<span>asana</span></div>
    <div class="fcols">{body}</div>
    <p class="flegal">Offline WebsiteBench demo clone. Local data only — no
    connection to Asana, Inc.</p>
  </div>
</footer>"""


def _page(title: str, active: str, main: str) -> str:
    support = ""
    if active == "pricing":
        support = """<aside class="synthetic-help" aria-label="Synthetic local help" hidden>
  <div class="synthetic-help-panel" id="synthetic-help-panel">
    <button class="synthetic-help-close" type="button" aria-label="Close help"
      onclick="document.querySelector('.synthetic-help').hidden=true"
    >×</button>
    <p class="synthetic-help-copy desktop-copy">Get clear, local guidance for choosing a<br>
      plan that fits your team's current work.<br>
      Review collaboration needs,<br>
      billing options, and helpful features in<br>
      this demo.</p>
    <p class="synthetic-help-copy mobile-copy">Local synthetic pricing guidance is here.<br>
      Compare team plans and workflow goals.<br>
      Nothing is sent outside this demo.</p>
  </div>
  <button class="synthetic-help-launcher" type="button" aria-controls="synthetic-help-panel"
    onclick="const panel=document.getElementById('synthetic-help-panel');panel.dataset.touched='1';panel.hidden=!panel.hidden">
    <span class="synthetic-help-mark" aria-hidden="true"><i></i><i></i><i></i></span>
    <span>Synthetic help</span>
  </button>
</aside><script>
(() => {
  const help = document.querySelector('.synthetic-help');
  const panel = document.getElementById('synthetic-help-panel');
  const opener = document.getElementById('footer-support');
  opener.addEventListener('click', event => {
    event.preventDefault(); help.hidden = false; panel.hidden = false;
  });
})();
</script>"""
    is_home = active == ""
    body_class = "marketing home-marketing" if is_home else "marketing"
    home_script = '<script src="/static/home.js" defer></script>' if is_home else ""
    return (_head(title) + f"<body class='{body_class}'>" + _marketing_nav(active)
            + f"<main>{main}</main>" + _marketing_footer(is_home)
            + '<script src="/static/public-nav.js" defer></script>' + home_script
            + support + "</body></html>")


NAV_DETAIL_PAGES = {
    "/product/ai": "product",
    "/product/service-management": "product",
    "/product/client-management": "product",
    "/product/command": "product",
    "/product/stackai": "product",
    "/product/ai/ai-teammates": "product",
    "/product/ai/ai-studio": "product",
    "/product/ai/dash": "product",
    "/features/admin-security": "product",
    "/apps": "product",
    "/developers": "product",
    "/whats-new": "product",
    "/enterprise": "solutions",
    "/small-business": "solutions",
    "/industry/nonprofit": "solutions",
    "/agencies": "solutions",
    "/teams/operations": "solutions",
    "/teams/marketing": "solutions",
    "/teams/it": "solutions",
    "/teams/leaders": "solutions",
    "/industry/government-solutions": "solutions",
    "/industry/healthcare": "solutions",
    "/industry/retail": "solutions",
    "/industry/financial-services": "solutions",
    "/industry/education": "solutions",
    "/industry/manufacturing": "solutions",
    "/uses/goal-management": "solutions",
    "/uses/organizational-planning": "solutions",
    "/uses/project-intake": "solutions",
    "/uses/resource-planning": "solutions",
    "/uses/product-launch": "solutions",
    "/uses": "solutions",
    "/events": "resources",
    "/customers": "resources",
    "/academy": "resources",
    "/certifications": "resources",
    "/academy/trainings": "resources",
    "/help": "resources",
    "/community": "resources",
    "/customer-success": "resources",
    "/partners/channel/directory": "resources",
    "/partners": "resources",
    "/sales": "resources",
    "/download": "resources",
}


def nav_detail_page(path: str) -> str:
    active = NAV_DETAIL_PAGES[path]
    snapshot_file = (Path(__file__).resolve().parent.parent / "static" /
                     "official-pages" / f"{path.strip('/').replace('/', '--')}.json")
    snapshot = json.loads(snapshot_file.read_text(encoding="utf-8"))
    stylesheets = "".join(snapshot["stylesheets"])
    if snapshot.get("external"):
        static_root = Path(__file__).resolve().parent.parent / "static"
        inline_styles = []
        for stylesheet in snapshot["stylesheets"]:
            match = re.search(r'href="/static/([^"]+\.css)"', stylesheet)
            if match:
                css_file = static_root / match.group(1)
                inline_styles.append(f"<style>{css_file.read_text(encoding='utf-8')}</style>")
            elif stylesheet.startswith("<style>"):
                inline_styles.append(stylesheet)
        body_attributes = dict(snapshot.get("body_attributes", {}))
        external_header = ""
        external_script = ""
        extra_head = ""
        if path == "/help":
            body_attributes["class"] = f'marketing {body_attributes.get("class", "")}'.strip()
            external_header = _marketing_nav("resources")
            external_script = '<script src="/static/public-nav.js" defer></script>'
            extra_head = '<link rel="stylesheet" href="/static/site.css?v=official-pages-3">'
        elif path.startswith("/academy"):
            body_attributes["class"] = f'marketing {body_attributes.get("class", "")}'.strip()
            external_header = _marketing_nav("resources")
            external_script = '<script src="/static/public-nav.js" defer></script>'
            extra_head = """<link rel="stylesheet" href="/static/site.css?v=official-pages-3">
<style>
body.marketing>.mnav{display:block!important;position:relative!important;top:auto!important;height:68px!important;visibility:visible!important;opacity:1!important;z-index:10000!important}
#asana-homepage .styles-module_hero-container__lEZxv{position:relative;display:block;margin:24px}
#asana-homepage .styles-module_hero__o-pUo{width:100%;aspect-ratio:213/125;background-position:center;background-size:cover;border-radius:28px}
#asana-homepage .styles-module_content-container__hl45r{position:absolute;z-index:2;top:48px;left:40px;align-items:flex-start;padding:0}
#asana-homepage .styles-module_content-container__hl45r h1{max-width:620px;color:#fff;text-align:left}
#asana-homepage .styles-module_cta-container__fwAZH{display:flex;flex-direction:row;gap:8px;width:auto}
#asana-homepage .styles-module_cta-container__fwAZH a{width:auto!important;background:rgba(255,255,255,.15)!important;border:1px solid #fff!important;color:#fff!important}
@media(max-width:767px){#asana-homepage .styles-module_content-container__hl45r{position:relative;top:auto;left:auto;padding:32px 24px}#asana-homepage .styles-module_content-container__hl45r h1{color:inherit}#asana-homepage .styles-module_cta-container__fwAZH{flex-direction:column;width:100%}}
</style>"""
        elif path == "/community":
            extra_head = """<style>
.custom-search-banner__content h1,.community-stats-item .title,.community-stats-item .title a{opacity:1!important;visibility:visible!important;color:#fff!important}
.custom-search-banner .search-term__input{opacity:1!important;visibility:visible!important;color:#2d2e2f!important;-webkit-text-fill-color:#2d2e2f!important}
.custom-search-banner .search-term__input::placeholder{color:#777!important;opacity:1!important}
</style>"""
        body_attrs = " ".join(
            f'{html.escape(key)}="{html.escape(value)}"'
            for key, value in body_attributes.items()
        )
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(snapshot["title"])}</title><link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
{"".join(inline_styles)}{extra_head}<style>html,body{{overflow-x:hidden}}</style></head>
<body {body_attrs}>{external_header}{snapshot["html"]}{external_script}</body></html>"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(snapshot["title"])}</title><link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
{stylesheets}<link rel="stylesheet" href="/static/site.css?v=official-pages-2"></head>
<body class="marketing official-snapshot">{_marketing_nav(active)}{snapshot["html"]}
<script src="/static/public-nav.js" defer></script></body></html>"""

def home_page() -> str:
    ai_tabs = [
        ("Asana Work Graph®", "A neural network of every person, task, project, goal, and dependency, so humans and agents always know who is doing what, by when, and toward which goal.", "/static/source/product-hero.png", "Connected work graph across goals, projects, and AI agents"),
        ("Multiplayer", "Every workflow, app, and agent runs in a shared space where humans and agents act on the same plan and see the same context.", "/static/source/resource-ai-at-work.avif", "People and AI coordinating work in one shared space"),
        ("Shared memory", "AI Teammates learn from completed work, feedback, and preferences, so every workflow starts smarter than the last.", "/static/source/home-project.webp", "A shared product launch plan with human and AI teammates"),
        ("Enterprise governance", "Every agent has an identity, scoped permissions, an audit trail, and cost constraints governed from the same console as human users.", "/static/source/resource-workflow-automation.avif", "Governed workflow automation in Asana"),
    ]
    ai_controls = "".join(
        f'''<button class="ai-story-tab{' is-active' if index == 0 else ''}" type="button" role="tab"
          aria-selected="{'true' if index == 0 else 'false'}" data-image="{image}" data-alt="{alt}" data-stage-title="{title}">
          <span>{title}</span><b aria-hidden="true">{'−' if index == 0 else '+'}</b><p>{copy}</p></button>'''
        for index, (title, copy, image, alt) in enumerate(ai_tabs)
    )
    teammates = [
        ("Launch Planner", "Turns project goals into step-by-step timelines so you can hit every deadline without constant coordination.", "ROADMAP SYNCING · GTM SEQUENCING", "#9EF2A4"),
        ("Workflow Optimizer", "Finds bottlenecks in your workflows and suggests fixes so work keeps moving.", "ARTIFACT AUDITING · MESSAGING COMPLIANCE", "#FFD4FF"),
        ("Compliance Specialist", "Reviews project docs against regulatory standards so teams stay compliant without slowing down.", "POLICY REVIEW · DEPENDENCY MAPPING", "#B8A1FF"),
        ("Status Reporter", "Turns project updates into executive-ready reports to keep leaders aligned and in the loop.", "STATUS SYNTHESIS · GTM SEQUENCING", "#F6FF8E"),
        ("Data Quality Manager", "Cleans up missing data and naming formats so your workspace stays organized and reliable.", "LINGUISTIC QA · REGIONAL NUANCING", "#FFC785"),
    ]
    teammate_cards = "".join(
        f'''<article class="teammate-card"><i style="--agent-color:{color}" aria-hidden="true">✣</i>
          <h3>{title}</h3><p>{copy}</p><small>SKILLS</small><strong>{skills}</strong></article>'''
        for title, copy, skills, color in teammates
    )
    products = [
        ("Agentic Work Management", "Agentic Work Management brings together AI Teammates, AI Studio, Asana Dash, and MCP and AI Connectors — so your team and your agents run critical workflows together.", "/static/source/home-project.webp", "Launch plan run by human and AI teammates", "#FFD4FF"),
        ("Asana Service Management", "One AI-native enterprise service management platform for IT, HR, facilities, and legal.", "/static/source/resource-workflow-automation.avif", "Automated service management workflow", "#9EF2A4"),
        ("Asana Client Management", "Build lasting client relationships on an AI-native platform built for agency work.", "/static/source/resource-work-management.avif", "Connected client work management", "#F6FF8E"),
        ("Command by Asana", "Ship faster with humans and agents in sync.", "/static/source/resource-project-planning.avif", "Project planning with humans and agents in sync", "#9EDCF2"),
        ("StackAI by Asana", "Drag and drop to create powerful Agentic Workflows connected to any app, with enterprise-level governance.", "/static/source/resource-strategic-planning.avif", "Enterprise agentic workflow builder", "#FFFFFF"),
    ]
    product_tabs = "".join(
        f'''<button class="productivity-tab{' is-active' if index == 0 else ''}" type="button" role="tab"
          style="--pill:{color}" aria-selected="{'true' if index == 0 else 'false'}"
          data-title="{title}" data-copy="{copy}" data-image="{image}" data-alt="{alt}">{title}</button>'''
        for index, (title, copy, image, alt, color) in enumerate(products)
    )
    return _page("The OS for human-agent teams • Asana", "", """
<section class="hero source-home">
  <div class="source-orbit" aria-hidden="true">
    <canvas class="mobile-orbit-canvas" width="975" height="1250"></canvas>
    <svg class="orbit-wires" viewBox="0 0 1280 674" preserveAspectRatio="none">
      <path class="wire hot" d="M250 79H348Q365 79 365 62V60Q365 43 382 43H457M584 43H665Q682 43 682 60V70H789M826 70H1043Q1060 70 1060 87V103"/>
      <path class="wire pale" d="M111 126V420Q111 437 128 437H132Q149 437 149 454V601M292 630H535Q552 630 552 614Q552 601 569 601H597M635 627H825Q842 627 842 610V563M921 627H1019Q1036 627 1036 610V563"/>
      <path class="wire hot" d="M1060 162V228H1134Q1152 228 1152 246V298"/>
      <path class="wire pale" d="M1152 352V445Q1152 463 1134 463H1053Q1036 463 1036 480V513"/>
      <circle cx="250" cy="79" r="3"/><circle cx="457" cy="43" r="3"/><circle cx="584" cy="43" r="3"/><circle cx="789" cy="70" r="3"/><circle cx="826" cy="70" r="3"/><circle cx="1060" cy="103" r="3"/><circle cx="1060" cy="162" r="3"/><circle cx="1152" cy="298" r="3"/><circle cx="1152" cy="352" r="3"/><circle cx="1036" cy="513" r="3"/><circle cx="149" cy="601" r="3"/><circle cx="292" cy="630" r="3"/><circle cx="842" cy="627" r="3"/><circle cx="921" cy="627" r="3"/>
    </svg>
    <svg class="orbit-mobile-wires" viewBox="0 0 390 500" preserveAspectRatio="none">
      <path class="hot" d="M159 82H194Q196 82 196 88Q196 98 207 98H248"/>
      <path class="hot" d="M329 116V180"/>
      <path class="hot" d="M52 205V187Q52 176 63 176H123"/>
      <path class="hot" d="M221 176H254Q265 176 265 187Q265 199 276 199H309"/>
      <path class="soft" d="M183 228H232Q243 228 243 239V295"/>
      <circle cx="159" cy="82" r="2"/><circle cx="248" cy="98" r="2"/><circle cx="329" cy="116" r="2"/><circle cx="329" cy="180" r="2"/><circle cx="52" cy="205" r="2"/><circle cx="123" cy="176" r="2"/><circle cx="221" cy="176" r="2"/><circle cx="309" cy="199" r="2"/><circle cx="183" cy="228" r="2"/><circle cx="243" cy="295" r="2"/>
    </svg>
    <span class="orbit-node team-person"></span><span class="orbit-node team-bot">✿</span>
    <span class="orbit-node team-plan">▲</span><span class="orbit-node google-node">▲</span>
    <span class="orbit-card launch">Launch product<br>in 4 weeks</span>
    <span class="orbit-chip planner">Launch Planner</span>
    <span class="orbit-card readiness"><b>Pricing Strategist</b><small>Sales and launch readiness</small></span>
    <span class="orbit-card launched"><i aria-hidden="true"></i><span>Product launched!</span></span>
    <span class="orbit-card edits"><i aria-hidden="true"></i><span>Approve edits</span></span>
    <span class="orbit-card enablement"><i aria-hidden="true"></i><span>Enablement</span></span>
    <span class="orbit-node campaign-node">✿</span><span class="orbit-chip campaign-chip">Campaign Planner</span>
    <span class="orbit-node bottom-person-one"></span><span class="orbit-node bottom-person-two"></span>
    <img class="orbit-texture texture-initial" src="/static/source/home-initial.webp" alt="">
    <img class="orbit-texture texture-launch" src="/static/source/home-launch.webp" alt="">
    <img class="orbit-texture texture-avatar1" src="/static/source/home-avatar1.webp" alt="">
    <img class="orbit-texture texture-google" src="/static/source/home-google.webp" alt="">
    <img class="orbit-texture texture-drive" src="/static/source/home-drive.png" alt="">
    <img class="orbit-texture texture-campaign" src="/static/source/home-campaign.webp" alt="">
    <img class="orbit-texture texture-enablement" src="/static/source/home-enablement.webp" alt="">
    <img class="orbit-texture texture-avatar2" src="/static/source/home-avatar2.webp" alt="">
    <img class="orbit-texture texture-pricing" src="/static/source/home-pricing.webp" alt="">
    <img class="orbit-texture texture-launched" src="/static/source/home-launched.webp" alt="">
    <img class="orbit-texture texture-approve" src="/static/source/home-approve.webp" alt="">
  </div>
  <script>(()=>{const canvas=document.querySelector('.mobile-orbit-canvas');if(!canvas)return;
  const draw=()=>{const x=canvas.getContext('2d');x.clearRect(0,0,975,1250);x.save();x.scale(2.5,2.5);
  const line=(color,fn)=>{x.beginPath();fn();x.strokeStyle=color;x.lineWidth=2;x.lineCap='round';x.lineJoin='round';x.stroke()};
  const rr=(a,b,w,h,r,fill='#fff',stroke='#d9d9d9')=>{x.beginPath();x.roundRect(a,b,w,h,r);x.fillStyle=fill;x.fill();if(stroke){x.strokeStyle=stroke;x.lineWidth=1;x.stroke()}};
  line('#ed686b',()=>{x.moveTo(159,82);x.lineTo(194,82);x.quadraticCurveTo(207,82,207,94);x.quadraticCurveTo(207,98,215,98);x.lineTo(248,98)});
  line('#ed686b',()=>{x.moveTo(329,116);x.lineTo(329,180)});
  line('#ed686b',()=>{x.moveTo(52,205);x.lineTo(52,187);x.quadraticCurveTo(52,176,63,176);x.lineTo(123,176)});
  line('#f39ac8',()=>{x.moveTo(183,228);x.lineTo(232,228);x.quadraticCurveTo(243,228,243,239);x.lineTo(243,295)});
  rr(24,57,136,57,8);x.beginPath();x.moveTo(34,114);x.lineTo(34,122);x.lineTo(46,114);x.fillStyle='#fff';x.fill();x.strokeStyle='#d9d9d9';x.lineWidth=1;x.stroke();
  x.fillStyle='#0d0e10';x.font='300 13px "TWK Lausanne"';x.fillText('Launch product',42,80);x.fillText('in 4 weeks',42,95);
  x.beginPath();x.arc(96,117,14,0,Math.PI*2);x.fillStyle='#fff';x.fill();x.strokeStyle='#73df90';x.lineWidth=3;x.stroke();rr(91,112,10,10,2,'#fff','#111');x.fillStyle='#111';x.font='8px Arial';x.fillText('✿',92,120);
  rr(113,109,65,12,2,'#b1f0ab',null);x.fillStyle='#111';x.font='300 7px "TWK Lausanne"';x.fillText('Launch Planner',116,118);
  const node=(cx,cy,bg,inner)=>{x.beginPath();x.arc(cx,cy,20,0,Math.PI*2);x.fillStyle=bg;x.fill();x.strokeStyle='#d9d9d9';x.lineWidth=1;x.stroke();x.beginPath();x.arc(cx,cy,16.5,0,Math.PI*2);x.strokeStyle='#fff';x.lineWidth=3;x.stroke();inner&&inner(cx,cy)};
  node(268,97,'#fff',(cx,cy)=>{x.beginPath();x.arc(cx,cy,12,0,Math.PI*2);x.fillStyle='#111';x.fill();x.beginPath();x.arc(cx,cy+1,8,0,Math.PI*2);x.fillStyle='#e5aa7e';x.fill();x.fillStyle='#1767a5';x.fillRect(cx-9,cy-13,5,8)});
  node(308,97,'#306ff6',(cx,cy)=>{x.beginPath();x.arc(cx,cy,12,0,Math.PI*2);x.fillStyle='#fff';x.fill();x.fillStyle='#111';x.font='14px Arial';x.textAlign='center';x.textBaseline='middle';x.fillText('✿',cx,cy)});
  node(342,97,'#f7cbfc',(cx,cy)=>{x.beginPath();x.arc(cx,cy,12,0,Math.PI*2);x.fillStyle='#fff';x.fill();x.fillStyle='#111';x.font='13px Arial';x.textAlign='center';x.textBaseline='middle';x.fillText('⌃',cx,cy+1)});
  rr(123,160,98,31,8);rr(131,166,18,18,4,'#306ff6',null);x.fillStyle='#fff';x.fillRect(135,170,8,1);x.fillRect(135,174,8,1);x.fillRect(135,178,8,1);x.fillStyle='#0d0e10';x.font='300 11px "TWK Lausanne"';x.textAlign='left';x.textBaseline='alphabetic';x.fillText('Enablement',154,180);
  node(330,201,'#fff',(cx,cy)=>{x.beginPath();x.moveTo(cx,cy-12);x.lineTo(cx-11,cy+9);x.lineTo(cx+11,cy+9);x.closePath();x.fillStyle='#79b66f';x.fill();x.beginPath();x.moveTo(cx-9,cy+8);x.lineTo(cx-1,cy-8);x.lineTo(cx+5,cy+8);x.closePath();x.fillStyle='#5ea4e8';x.fill();x.beginPath();x.moveTo(cx+1,cy-8);x.lineTo(cx+10,cy+8);x.lineTo(cx+5,cy+8);x.closePath();x.fillStyle='#c7d94f';x.fill()});
  rr(24,205,159,47,8);x.beginPath();x.arc(46,228,13,0,Math.PI*2);x.fillStyle='#ebf56e';x.fill();x.fillStyle='#111';x.font='12px Arial';x.textAlign='center';x.textBaseline='middle';x.fillText('✿',46,228);rr(63,212,63,9,1,'#ebf56e',null);x.fillStyle='#111';x.font='300 7px "TWK Lausanne"';x.textAlign='left';x.textBaseline='alphabetic';x.fillText('Pricing Strategist',65,220);x.font='300 8px "TWK Lausanne"';x.fillText('Sales and launch readiness',64,238);
  rr(106,295,181,47,8);x.beginPath();x.arc(129,318,11,0,Math.PI*2);x.fillStyle='#499e4e';x.fill();x.strokeStyle='#fff';x.lineWidth=2;x.beginPath();x.moveTo(124,318);x.lineTo(128,322);x.lineTo(135,313);x.stroke();x.fillStyle='#0d0e10';x.font='300 15px "TWK Lausanne"';x.textAlign='left';x.textBaseline='alphabetic';x.fillText('Product launched!',148,324);
  x.restore()};document.fonts.ready.then(draw);window.addEventListener('resize',draw,{passive:true});})();</script>
  <h1>The OS for<br><span class="grad">human-agent</span> teams</h1>
  <h2>Supercharge your teams to get things done</h2>
  <p class="signup-note">Try Asana for free. No credit card required.</p>
  <div class="source-sso">
    <a class="source-sso-btn" href="/create-account"><span class="google-g">G</span>Google</a>
    <a class="source-sso-btn" href="/create-account"><span class="microsoft-mark">■</span>Microsoft</a>
  </div>
  <div class="source-or"><span>or</span></div>
  <form class="source-signup" action="/create-account" method="get">
    <input aria-label="Work email address" placeholder="name@company.com" type="email" name="email">
    <button type="submit"><span class="desktop-label">Sign up</span><span class="mobile-label">Get started</span></button>
  </form>
  <p class="source-fineprint">By signing up, I agree to Asana's <a href="/resources">Terms of Service</a> and acknowledge the <a href="/resources">Privacy Statement</a>.</p>
  <aside class="home-synthetic-help" aria-label="Synthetic local help">
    <div class="home-synthetic-panel" hidden><button type="button" aria-label="Close local help" onclick="this.parentElement.hidden=true">×</button><p>Local synthetic help only. Nothing is sent.</p></div>
    <button class="home-synthetic-launcher" type="button" onclick="this.previousElementSibling.hidden=!this.previousElementSibling.hidden"><span class="synthetic-help-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>Ask local help</span></button>
  </aside>
</section>""" + f"""
<section class="home-trust" aria-label="Customer trust">
  <p><strong>85%</strong> of Fortune 100<br>companies choose Asana<sup>1</sup></p>
  <div class="home-logos" aria-label="Customer logos"><span>amazon</span><span>accenture</span><span>Johnson&amp;Johnson</span><span class="dell-logo">DELL</span><span>◆ MERCK</span></div>
</section>

<section class="home-ai-story" aria-labelledby="ai-story-heading">
  <div class="home-section-heading"><h2 id="ai-story-heading">AI that works the way your team works</h2></div>
  <div class="ai-story-layout">
    <div class="ai-story-stage" aria-live="polite">
      <span class="ai-stage-kicker">WORK GRAPH</span><h3 id="ai-stage-title">Asana Work Graph®</h3>
      <img id="ai-stage-image" src="{ai_tabs[0][2]}" alt="{ai_tabs[0][3]}">
      <div class="ai-stage-route" aria-hidden="true"><i>Goal</i><b>→</b><i>Project</i><b>→</b><i>AI teammate</i></div>
    </div>
    <div class="ai-story-tabs" role="tablist" aria-label="How Asana AI works">{ai_controls}</div>
  </div>
</section>

<section class="home-teammates" aria-labelledby="teammates-heading">
  <p class="section-kicker">AI TEAMMATES</p><h2 id="teammates-heading">Your team just got bigger</h2>
  <div class="teammates-intro"><p>Pre-built AI agents that work alongside your team inside real workflows, with shared memory, governance, and context from the Work Graph, so they are ready to go on day one.</p><a href="/product#ai">Learn more <span>→</span></a></div>
  <div class="teammate-rail">{teammate_cards}</div>
</section>

<section class="home-productivity" aria-labelledby="productivity-heading">
  <div class="productivity-inner"><h2 id="productivity-heading">Deliver real productivity for every team</h2>
    <div class="productivity-tabs" role="tablist" aria-label="Asana products">{product_tabs}</div>
    <div class="productivity-stage" aria-live="polite">
      <article class="productivity-side productivity-side-left"><span>CONNECTED WORK</span><strong id="product-left-title">Goals and portfolios</strong><p id="product-left-copy">Strategy stays connected to every project.</p></article>
      <article class="productivity-main"><div><i aria-hidden="true">✣</i><span><h3 id="product-title">{products[0][0]}</h3><p id="product-copy">{products[0][1]}</p></span></div><img id="product-image" src="{products[0][2]}" alt="{products[0][3]}"></article>
      <article class="productivity-side productivity-side-right"><span>HUMAN + AI</span><strong id="product-right-title">One shared plan</strong><p id="product-right-copy">People and agents act with the same context.</p></article>
    </div>
  </div>
</section>

<section class="home-case" aria-label="Customer story">
  <div class="case-connector" aria-hidden="true"><i></i><b>✣</b></div>
  <div class="case-grid"><div class="case-image"><img src="/static/source/home-cos.webp" alt="COS fashion collection displayed in a bright showroom"></div>
    <blockquote><div class="cos-logo">COS</div><span class="quote-mark">”</span><p>By building scalable workflows and leveraging AI with intention, we’ve been able to increase visibility and speed while focusing our energy on strategic execution.</p><footer><strong>Simone Williams</strong><small>Chief Digital, Technology &amp; Business Development Officer, COS</small></footer></blockquote>
  </div>
</section>

<section class="home-get-started" aria-labelledby="get-started-heading">
  <div><h2 id="get-started-heading">Get started easily</h2><p>Tour the platform, read a few deep dives, or kickstart your work management journey with the right template.</p></div>
  <nav aria-label="Get started resources"><a href="/demo/main"><span><strong>Try the Asana demo</strong><small>See Asana in action</small></span><b>→</b></a><a href="/resources"><span><strong>Discover resources</strong><small>Help articles and tutorials</small></span><b>→</b></a><a href="/templates"><span><strong>Start with a template</strong><small>Get started faster with a template</small></span><b>→</b></a></nav>
</section>

<section class="home-recognition" aria-labelledby="recognition-heading">
  <div class="recognition-connector" aria-hidden="true"><i></i><b>✣</b></div><h2 id="recognition-heading">Recognized as a leader</h2>
  <div class="award-grid"><article><div class="award-art award-gartner"><span class="gartner-grid"><i></i><i></i><i></i><i></i><i></i><i></i></span></div><h3>A Leader in the Collaborative Work Management three years in a row</h3><a href="/resources">Learn more <span>→</span></a></article>
  <article><div class="award-art award-g2"><span><b>RANKED #2</b><i>2025<br><strong>Top 50</strong><small>PROJECT MANAGEMENT PRODUCTS</small></i></span><span><b>RANKED #2</b><i>2025<br><strong>Top 50</strong><small>SMALL BUSINESS PRODUCTS</small></i></span><span><b>RANKED #3</b><i>2025<br><strong>Top 100</strong><small>BEST SOFTWARE PRODUCTS</small></i></span></div><h3>A leader in Work Management and OKR Software with more than 12,000 user reviews</h3><a href="/resources">Read user reviews <span>→</span></a></article></div>
</section>

<section class="home-bottom-cta"><h2>The only platform that can support your company at any scale</h2><a class="btn" href="/create-account">Get started</a><p><sup>1</sup> Accurate as of December 2023, includes free and paid users.</p></section>""")


def product_page() -> str:
    return _page("Product • Asana", "product", """
<section class="product-contract">
  <h1>The only work management&#8232;platform built for scale</h1>
  <p class="product-lead">With Asana, humans and agents run an organization’s critical workflows together, on the same plan, toward the same goals.</p>
  <div class="product-sso"><a href="/create-account"><span class="google-g">G</span>Google</a><a href="/create-account"><span class="microsoft-mark">■</span>Microsoft</a></div>
  <div class="product-or"><span>or</span></div>
  <form class="product-signup" action="/create-account" method="get"><input type="email" name="email" aria-label="Work email address" placeholder="name@company.com"><button type="submit">Continue</button></form>
  <p class="product-fine">By signing up, I agree to the Asana <a href="/resources">Privacy Policy</a> and <a href="/resources">Terms of Service</a>.</p>
  <img class="product-source-visual" src="/static/source/product-hero.png"
    alt="Where your teams and AI coordinate work together">
</section>
<section class="product-depth product-overview"><h2>See work clearly across your organization</h2><p>Coordinate projects, goals, portfolios, and workflows in one local workspace.</p></section>
<section class="product-depth product-workflows"><h2>Move work forward with connected workflows</h2><p>Use forms, rules, and reusable templates to keep every handoff clear.</p></section>
<section class="product-depth product-scale"><h2>Built for teams at every scale</h2><p>Local controls, reporting, and permissions keep work dependable.</p></section>
<section class="product-depth product-final"><h2>Get started with Asana</h2><a class="btn primary lg" href="/create-account">Get started</a></section>""")


def solutions_page() -> str:
    solutions = [
        ("marketing", "Marketing", "Plan campaigns, manage creative production, and connect every launch to measurable goals."),
        ("operations", "Operations", "Standardize intake, approvals, and cross-functional processes without losing visibility."),
        ("product", "Product", "Keep roadmaps, launches, customer feedback, and engineering handoffs in one shared plan."),
        ("enterprise", "Enterprise", "Coordinate work securely across departments with goals, portfolios, and reporting."),
    ]
    cards = "".join(
        f'<article id="{slug}"><span>0{index}</span><h2>{title}</h2><p>{copy}</p>'
        f'<a href="/templates">Explore templates <b>→</b></a></article>'
        for index, (slug, title, copy) in enumerate(solutions, 1)
    )
    return _page("Work management solutions • Asana", "solutions", f"""
<section class="solutions-hero"><p class="solutions-kicker">ASANA SOLUTIONS</p>
  <h1>Move every team’s work forward</h1>
  <p>Connect strategy, planning, and execution in one flexible work management platform.</p>
  <div><a class="btn primary lg" href="/create-account">Get started</a><a class="btn ghost lg" href="/demo/main">View demo</a></div>
</section>
<section class="solutions-grid">{cards}</section>
<section class="solutions-band"><p>ONE CONNECTED PLATFORM</p><h2>From company goals to the work that delivers them</h2>
  <div><article><strong>Clarity</strong><span>See owners, deadlines, and progress at a glance.</span></article>
  <article><strong>Consistency</strong><span>Turn proven processes into reusable workflows.</span></article>
  <article><strong>Impact</strong><span>Connect projects to goals and report on outcomes.</span></article></div>
</section>
<section class="solutions-proof"><h2>Built for focused teams and growing organizations</h2>
  <p>Use projects for day-to-day work, portfolios for oversight, and goals for shared direction.</p>
  <a href="/product">Explore the product <span>→</span></a>
</section>
<section class="solutions-final"><h2>Work smarter. Move faster.</h2><a class="btn primary lg" href="/create-account">Get started for free</a></section>
""")


def resources_page() -> str:
    cards = [
        ("work-management", "Work management", "Resources to help you better coordinate plans, projects, and processes with Asana.", "#c8efff", "#1d3187"),
        ("project-planning", "Project planning", "Resources to help you organize and track everything your team needs to deliver successful projects.", "#ffe7ea", "#77002f"),
        ("workflow-automation", "Workflow automation", "Resources to help you build intelligent workflows and keep work moving automatically.", "#c9f9d7", "#083f2f"),
        ("ai-at-work", "AI at work", "Resources to help your team get more efficient and achieve growth with AI.", "#fad4fb", "#70008c"),
        ("strategic-planning", "Strategic planning", "Resources to help you map out large-scale strategies and connect them to everyday work.", "#c8efff", "#1d3187"),
    ]
    rail = "".join(f'''<a class="resource-topic" href="/resources/category/{slug}" style="--topic-bg:{bg};--topic-ink:{ink}">
      <img src="/static/source/resource-{slug}.avif" alt=""><div><h2>{title}</h2><p>{copy}</p></div></a>'''
      for slug, title, copy, bg, ink in cards)
    return _page("Resources • Asana", "resources", f"""
<section class="resources-contract">
  <p class="resources-kicker">RESOURCE CENTER</p><h1>Explore the resource<br class="desktop-only"> center</h1>
  <a class="resources-demo" href="/demo/main">View demo</a>
  <div class="resource-rail">{rail}</div>
</section>
<section class="resource-depth"><h2>Resources for every way your team works</h2><p>Explore practical guides, customer stories, and local learning paths.</p></section>
<section class="resource-depth resource-dark"><h2>Turn plans into progress</h2><p>Connect strategy, projects, and workflows in one place.</p></section>
<section class="resource-depth"><h2>Learn from teams doing their best work</h2></section>
<section class="resource-final"><h2>Ready to get started?</h2><a class="btn primary lg" href="/create-account">Get started</a></section>
""")


def templates_page() -> str:
    teams = [
        ("Marketing", "Manage your next campaign, build a content calendar, and more.", "/templates/marketing"),
        ("Operations", "Create repeatable processes for requests, planning, and team operations.", "/templates/operations-pmo"),
        ("Design", "Organize creative requests, reviews, and production schedules.", "/templates/design"),
        ("IT", "Standardize requests, incidents, and technology projects.", "/templates/it"),
        ("Product & Engineering", "Plan roadmaps, launches, and cross-functional product work.", "/templates/product-engineering"),
        ("HR", "Coordinate recruiting, onboarding, and employee programs.", "/templates/hr"),
        ("Sales & Customer Success", "Track accounts, handoffs, and customer outcomes.", "/templates/sales-cx"),
    ]
    icons = [
        '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 16C3.6 16 0 12.4 0 8C0 3.6 3.6 0 8 0C12.4 0 16 3.6 16 8C16 12.4 12.4 16 8 16ZM8 1C4.15 1 1 4.15 1 8C1 11.85 4.15 15 8 15C11.85 15 15 11.85 15 8C15 4.15 11.85 1 8 1ZM11.4 6.45C11.6 6.25 11.6 5.95 11.4 5.75C11.2 5.55 10.9 5.55 10.7 5.75L6.4 10.05L4.85 8.5C4.65 8.3 4.3 8.3 4.15 8.5C4 8.7 4 9 4.15 9.2L6.05 11.1C6.25 11.3 6.55 11.3 6.75 11.1L11.4 6.45Z"/></svg>',
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 2.5h8v2h2.5v13h-13v-13H6v-2Zm1 1v2h6v-2H7Zm-2.5 2v11h11v-11H14v1H6v-1H4.5Zm3 3h5v1h-5v-1Zm0 3h5v1h-5v-1Z"/></svg>',
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5 17.5 7v6L10 17.5 2.5 13V7L10 2.5Zm0 1.2L4 7.3v5.1l6 3.6 6-3.6V7.3l-6-3.6Zm0 2.1 3.7 2.2-3.7 2.2L6.3 8 10 5.8Zm-3.2 4 2.7 1.6v3.1l-2.7-1.6V9.8Zm6.4 0v3.1l-2.7 1.6v-3.1l2.7-1.6Z"/></svg>',
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 3h14v14H3V3Zm1 1v12h12V4H4Zm2 2h3v3H6V6Zm5 0h3v3h-3V6Zm-5 5h3v3H6v-3Zm5 0h3v3h-3v-3Z"/></svg>',
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 3h12v3h2v11H2V6h2V3Zm1 1v3h10V4H5Zm-2 4v8h14V8H3Zm3 2h8v1H6v-1Zm0 3h5v1H6v-1Z"/></svg>',
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7Zm0 1a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5ZM4 17c.3-3.3 2.3-5.5 6-5.5s5.7 2.2 6 5.5h-1c-.3-2.7-1.9-4.5-5-4.5S5.3 14.3 5 17H4Z"/></svg>',
        '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 15.5h14v1H3v-1Zm1-2 3.5-4 3 2 4.5-6 1 .7-5 6.7-3.3-2.2-3 3.5-.7-.7Z"/></svg>',
    ]
    arrow = '<svg class="template-arrow" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="8"/><path d="M5 7.62h5.1L8.25 5.77a.38.38 0 0 1 .53-.53l2.5 2.5a.38.38 0 0 1 0 .53l-2.5 2.5a.38.38 0 0 1-.53-.53l1.82-1.85H5a.38.38 0 0 1 0-.77Z"/></svg>'
    team_cards = "".join(f'''<article class="template-team"><i aria-hidden="true">{icons[index]}</i><div><h2>{title}</h2><p>{copy}</p><a href="{href}">See templates{arrow}</a></div></article>'''
                         for index, (title, copy, href) in enumerate(teams))
    return _page("Templates • Asana", "templates", f"""
<section class="templates-contract">
  <h1>AI workflow template gallery</h1>
  <p class="templates-lead">Any team can plan and manage their projects more successfully starting with Asana templates.</p>
  <div class="templates-sso"><a href="/templates"><svg class="public-google-mark" width="24" height="24" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.5 5.4 2.5 13.2l7.8 6.1C12.2 13.4 17.6 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z"/><path fill="#FBBC05" d="M10.3 28.7a14.5 14.5 0 0 1 0-9.4l-7.8-6.1a24 24 0 0 0 0 21.6l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.5-5.9l-7.6-5.9c-2.1 1.4-4.8 2.3-7.9 2.3-6.4 0-11.8-3.9-13.7-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z"/></svg>Google</a><a href="/templates"><svg class="public-microsoft-mark" width="18" height="18" viewBox="0 0 21 21" aria-hidden="true"><rect x="1" y="1" width="9" height="9" fill="#f25022"/><rect x="11" y="1" width="9" height="9" fill="#7fba00"/><rect x="1" y="11" width="9" height="9" fill="#00a4ef"/><rect x="11" y="11" width="9" height="9" fill="#ffb900"/></svg>Microsoft</a></div>
  <div class="templates-or"><span>or</span></div>
  <form class="templates-signup" action="/create-account" method="get"><input type="email" name="email" aria-label="Work email address" placeholder="name@company.com"><button type="submit">Continue</button></form>
  <p class="templates-fine">By signing up, I agree to Asana's <a href="/terms/terms-of-service">Terms of Service</a> and acknowledge the <a href="/terms/privacy-statement">Privacy Statement</a>.</p>
</section>
<section class="templates-explore"><h2>Explore by team</h2><div class="template-rail">{team_cards}</div></section>
<section class="template-depth"><h2>Popular templates to help your team move faster</h2></section>
<section class="template-depth template-dark"><h2>Turn every repeatable process into a clear workflow</h2></section>
<section class="template-final"><h2>Start with a template today</h2><a class="btn primary lg" href="/create-account">Get started</a></section>
""")


def pricing_page() -> str:
    tiers = [
        ("Personal", "For one or two people managing personal projects.", "$0", "Free forever",
         ["Manage tasks and personal to-dos:", "2 users", "Unlimited tasks and projects",
          "List, board, and calendar views", "Collaborate with teammates"],
         "Try for free", "/create-account", ""),
        ("Starter", "For growing teams that need to track their projects’ progress and hit deadlines.", "$10.99", "Per user, per month billed annually",
         ["Everything in Personal, plus:", "Timeline view", "Project dashboards",
          "Forms and rules", "Up to 500 teammates"],
         "Try for free", "/create-account", "Purchase now"),
        ("Advanced", "For companies that need to manage a portfolio of work and goals across departments.", "$24.99", "Per user, per month billed annually",
         ["Everything in Starter, plus:", "Portfolios and goals", "Workload",
          "Advanced reporting", "Approvals and proofing"],
         "Try for free", "/create-account", "Purchase now"),
        ("Enterprise", "For companies that need to coordinate and automate complex work across departments, without limits.", "Contact sales for pricing", "",
         ["Everything in Advanced, plus:", "Enterprise-grade controls to manage"
          " access, protect data, and keep your organization secure at scale."],
         "Contact sales", "/solutions", ""),
    ]
    cards = ""
    for name, description, price, per, feats, cta, href, purchase in tiers:
        lis = "".join(f"<li>{f}</li>" for f in feats)
        purchase_link = (f'<a class="purchase" href="{href}">{purchase}<span aria-hidden="true">➜</span></a>'
                         if purchase else '<span class="purchase placeholder" aria-hidden="true"></span>')
        cards += f"""<article class="tier tier-{name.lower()}">
<h3>{name}</h3><p class="tier-desc">{description}</p>
<div class="price">{price}</div><p class="per">{per}</p>
<a class="btn {'primary' if name == 'Starter' else 'ghost'}" href="{href}"><span class="desktop-cta">{cta}</span><span class="mobile-cta">{'Get started' if cta == 'Try for free' else cta}</span></a>
{purchase_link}<ul>{lis}</ul></article>"""
    addons = [
        ("AI Teammates", "Build AI teammates that collaborate with your teams and handle repeatable work."),
        ("Timesheets and Budgets", "Track time, budgets, and progress without leaving the work."),
        ("Compliance management", "Support regulated workflows with controls for complex organizations."),
        ("Permissions management", "Manage access and permissions across teams and projects."),
    ]
    addon_cards = "".join(
        f'<article class="pricing-addon"><h3>{title}</h3><p>{copy}</p>'
        '<div><a class="btn primary" href="/solutions">Contact sales</a>'
        '<a class="btn ghost" href="/resources">Learn more</a></div></article>'
        for title, copy in addons)
    faq = [
        "Which plan is right for my team?", "Can I try Asana before I buy?",
        "How does billing work?", "What security and privacy options are available?",
        "Can I change plans later?", "Does Asana offer nonprofit discounts?",
    ]
    faq_items = "".join(f'<details><summary>{item}</summary><p>Learn more about this option in our local product guide.</p></details>' for item in faq)
    main = f"""
<div class="pricing-page">
<section class="pricing-hero"><h1>Pick the plan that fits your<br> team</h1></section>
<section class="pricing-plans"><div class="billing-toggle"><span>Monthly</span><i aria-hidden="true"></i><strong>Yearly</strong><em>Save up to 18%</em></div><div class="tiers">{cards}</div></section>
<section class="pricing-note"><p>Every paid plan includes unlimited projects, tasks, storage, and activity logs.</p></section>
<section class="pricing-addons">{addon_cards}</section>
<section class="pricing-loved"><h4>Loved by 100,000+ organizations across the globe</h4><div class="logo-dots" aria-hidden="true">●&nbsp;&nbsp;●&nbsp;&nbsp;●&nbsp;&nbsp;●&nbsp;&nbsp;●</div></section>
<section class="pricing-faq"><h2>Frequently asked questions</h2><div class="faq-list">{faq_items}</div></section>
</div>"""
    return _page("Asana Pricing | Personal, Starter, Advanced, & Enterprise plans • Asana", "pricing", main)


# ------------------------------------------------------------------ auth

def _auth_shell(title: str, body: str) -> str:
    footer_links = ["Asana.com", "Support", "Integrations", "Forum",
                    "Developers & API", "Resources", "Guide", "Templates",
                    "Pricing", "Terms", "Privacy"]
    links = "".join(f'<a href="/">{x}</a>' for x in footer_links)
    return f"""{_head(title)}<body class="authpage">
<header class="auth-logo"><a href="/" aria-label="Asana home">{LOGO_SVG}<span>asana</span></a></header>
<main class="auth-main">{body}</main>
<footer class="auth-footer"><nav>{links}</nav>
<p>This offline demo stores data locally. No real emails are sent.</p></footer>
<script src="/static/auth.js" defer></script></body></html>"""


_SSO_BUTTONS = """<div class="sso-row">
<button type="button" class="sso" data-sso="Google" aria-label="Continue with Google">
<svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.5 5.4 2.5 13.2l7.8 6.1C12.2 13.4 17.6 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.6 5.9c4.4-4.1 7-10.1 7-17.6z"/><path fill="#FBBC05" d="M10.3 28.7a14.5 14.5 0 0 1 0-9.4l-7.8-6.1a24 24 0 0 0 0 21.6l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.5-5.9l-7.6-5.9c-2.1 1.4-4.8 2.3-7.9 2.3-6.4 0-11.8-3.9-13.7-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z"/></svg></button>
<button type="button" class="sso" data-sso="Microsoft" aria-label="Continue with Microsoft">
<svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true"><rect x="1" y="1" width="9" height="9" fill="#f25022"/><rect x="11" y="1" width="9" height="9" fill="#7fba00"/><rect x="1" y="11" width="9" height="9" fill="#00a4ef"/><rect x="11" y="11" width="9" height="9" fill="#ffb900"/></svg></button>
</div>
<div class="or-rule"><span>or</span></div>"""


def login_page() -> str:
    return _auth_shell("Log in - Asana", f"""
<div class="auth-card" id="login-card">
  <h2>Welcome to Asana</h2>
  <h3>To get started, please sign in</h3>
  {_SSO_BUTTONS}
  <form id="login-form" novalidate>
    <div class="field"><label for="email">Email address</label>
      <input id="email" name="email" type="email" autocomplete="email" required></div>
    <div class="field hidden" id="password-field"><label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password"></div>
    <p class="form-error" id="login-error" role="alert" hidden></p>
    <button class="btn primary block" type="submit" id="login-continue">Continue</button>
  </form>
  <p class="auth-alt"><a href="/-/forgot_password">Forgot password?</a>
  <span>or</span> <a href="/create-account">Sign up</a></p>
</div>
<p class="auth-fineprint">Offline demo: SSO buttons are visual placeholders and
explain that only local email accounts work here.</p>""")


def signup_page(email: str = "") -> str:
    escaped_email = html.escape(email, quote=True)
    return _auth_shell("Sign up - Asana", f"""
<div class="auth-card" id="signup-card">
  <h2>You're one click away from being more productive</h2>
  <h3>Sign up with your work email</h3>
  {_SSO_BUTTONS}
  <form id="signup-form" novalidate>
    <div class="field"><label for="name">Full name</label>
      <input id="name" name="name" autocomplete="name" required></div>
    <div class="field"><label for="email">Email address</label>
      <input id="email" name="email" type="email" autocomplete="email" value="{escaped_email}" required></div>
    <div class="field"><label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="new-password"
       minlength="8" required aria-describedby="pw-hint">
      <p class="hint" id="pw-hint">At least 8 characters.</p></div>
    <p class="form-error" id="signup-error" role="alert" hidden></p>
    <button class="btn primary block" type="submit">Sign up</button>
  </form>
  <div id="verify-step" class="hidden">
    <h3>Check your inbox</h3>
    <p>We sent a verification code to your address. In this offline demo the
    code is delivered to the local outbox below.</p>
    <div class="local-outbox" id="local-outbox" aria-live="polite"></div>
    <form id="verify-form" novalidate>
      <div class="field"><label for="code">Verification code</label>
        <input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" required></div>
      <p class="form-error" id="verify-error" role="alert" hidden></p>
      <button class="btn primary block" type="submit">Verify</button>
    </form>
  </div>
  <p class="auth-alt">Already have an account? <a href="/-/login">Log in</a></p>
</div>""")


def forgot_page() -> str:
    return _auth_shell("Log in - Asana", """
<div class="auth-card" id="forgot-card">
  <h2>Forgot password?</h2>
  <h3>Enter your email address for instructions</h3>
  <form id="forgot-form" novalidate>
    <div class="field"><label for="email">Email address</label>
      <input id="email" name="email" type="email" autocomplete="email" required></div>
    <p class="form-error" id="forgot-error" role="alert" hidden></p>
    <button class="btn primary block" type="submit">Send instructions</button>
  </form>
  <div id="reset-step" class="hidden">
    <h3>Reset your password</h3>
    <p>In this offline demo the reset code appears in the local outbox below.</p>
    <div class="local-outbox" id="local-outbox" aria-live="polite"></div>
    <form id="reset-form" novalidate>
      <div class="field"><label for="code">Reset code</label>
        <input id="code" name="code" inputmode="numeric" required></div>
      <div class="field"><label for="new-password">New password</label>
        <input id="new-password" name="password" type="password" minlength="8" required></div>
      <p class="form-error" id="reset-error" role="alert" hidden></p>
      <button class="btn primary block" type="submit">Reset password</button>
    </form>
  </div>
  <p class="auth-alt"><a href="/-/login">Log in</a> <span>or</span>
  <a href="/create-account">Sign up</a></p>
</div>""")


def app_shell() -> str:
    app_style = '<link rel="stylesheet" href="/static/app.css">'
    return f"""{_head("Asana", app_style)}<body class="appbody">
<div id="app" data-app-root></div>
<script src="/static/app.js" defer></script>
</body></html>"""
