"""Server-rendered marketing and auth pages for the Asana offline clone.

Copy on the login/forgot pages is reproduced from directly captured anonymous
evidence (EA1). Marketing pages reproduce server-rendered headings observed by
EA2; their full source visuals were unavailable (renderer crash), so layout is
an honest local design in Asana's visual language, not a pixel claim.
"""

from __future__ import annotations

import html

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
<link rel="stylesheet" href="/static/site.css?v=pricing-contract-2">{extra}</head>"""


def _marketing_nav(active: str = "") -> str:
    links = [("Products", "/product", True), ("Solutions", "/solutions", True),
             ("Learning & support", "/resources", True), ("Pricing", "/pricing", False)]
    items = "".join(
        f'<a href="{href}" class="mnav-link{" has-menu" if menu else ""}{" active" if href.strip("/") == active else ""}">{label}</a>'
        for label, href, menu in links)
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
</header>"""


def _marketing_footer() -> str:
    cols = [
        ("Asana", [("Home", "/"), ("Product", "/product"), ("Pricing", "/pricing"),
                   ("Templates", "/templates")]),
        ("Solutions", [("Project management", "/solutions"), ("Workflow automation", "/solutions"),
                       ("Resource planning", "/solutions")]),
        ("Resources", [("Resources", "/resources"), ("Guide", "/resources"),
                       ("Forum", "/resources"), ("Support", "/resources")]),
        ("Company", [("Log In", "/-/login"), ("Sign Up", "/create-account")]),
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
    return (_head(title) + "<body class='marketing'>" + _marketing_nav(active)
            + f"<main>{main}</main>" + _marketing_footer() + support + "</body></html>")


def home_page() -> str:
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
</section>
<section class="home-intro">
  <h2>AI that works the way your team works</h2>
</section>
<section class="strip home-ai-grid">
  <div class="cards3">
    <div class="mcard"><h3>Your team just got bigger</h3><p>Hand routine work to
    AI teammates that follow your processes and report back in your projects.</p></div>
    <div class="mcard"><h3>Deliver real productivity for every team</h3><p>From
    campaigns to launches, connect every task to the goals that matter.</p></div>
    <div class="mcard"><h3>Get started easily</h3><p>Start from a template,
    import a spreadsheet, or build your first project in minutes.</p></div>
  </div>
</section>
<section class="strip alt home-scale">
  <h2>The only platform that can support your company at any scale</h2>
  <p class="center-sub">Projects, portfolios, goals and reporting in one
  place — from a single team to the whole organization.</p>
  <div class="hero-cta center"><a class="btn primary lg" href="/create-account">Get started</a></div>
</section>
<section class="home-depth home-workflows"><h2>Turn every workflow into clear, connected work</h2><div class="home-depth-grid"><article><h3>Plan</h3><p>Organize projects, owners, and milestones in one shared view.</p></article><article><h3>Coordinate</h3><p>Keep handoffs moving with rules and reusable templates.</p></article></div></section>
<section class="home-depth home-teams"><h2>Built for every team</h2><div class="cards3"><article class="mcard"><h3>Marketing</h3><p>Connect campaigns to business goals.</p></article><article class="mcard"><h3>Operations</h3><p>Standardize requests and approvals.</p></article><article class="mcard"><h3>Product</h3><p>Coordinate roadmaps and launches.</p></article></div></section>
<section class="home-depth home-security"><h2>Enterprise controls with a simple team experience</h2><p>Local demo content for permissions, reporting, and dependable work management.</p></section>
<section class="home-depth home-stories"><h2>Teams move work forward with Asana</h2><div class="home-depth-grid"><article><h3>Clear priorities</h3><p>Everyone can see what matters next.</p></article><article><h3>Measurable progress</h3><p>Projects stay connected to outcomes.</p></article></div></section>
<section class="home-final"><h2>Work on big ideas, without the busywork</h2><a class="btn primary lg" href="/create-account">Get started</a></section>""")


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
    return _page("Content Not Found • Asana", "", """
<section class="not-found-page">
  <video class="not-found-video" autoplay muted loop playsinline preload="auto" poster="/static/source/404-hero-frame.png" aria-hidden="true"><source src="/static/source/404-hero.mp4" type="video/mp4"></video>
  <div class="not-found-copy"><h1>This page doesn’t exist. But you exist.</h1>
    <p>This is your sign to take a break. And take a breath. In and out. When you’re ready, ease back to work below.</p>
  </div>
</section>
<section class="not-found-rescue">
  <article><h2>Your team's tasks and conversations</h2><a href="/">Go to Asana <span>→</span></a></article>
  <article><h2>Support articles, videos, and suggested ways to use Asana</h2><a href="/resources">Visit support <span>→</span></a></article>
  <article><h2>News and updates from the Asana team</h2><a href="/resources">Read our Blog <span>→</span></a></article>
  <article><h2>Real-time status updates about the Asana app</h2><a href="/resources">Check status <span>→</span></a></article>
</section>""")


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
