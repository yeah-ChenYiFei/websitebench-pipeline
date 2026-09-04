/* The panels contain the captured US storefront markup, not catalog templates. */
(() => {
  let menus, host, root, active = -1, exitTimer;
  const nav = document.querySelector('#primary-nav');
  if (!nav) return;
  const triggers = [...nav.querySelectorAll('a')].slice(0, 9);
  const initialHrefs = triggers.map(a => a.getAttribute('href'));
  const ready = fetch('/static/navigation/menus.json').then(r => r.json()).then(value => {
    menus = value;
    host = document.createElement('div');
    host.id = 'source-navigation';
    host.hidden = true;
    root = host.attachShadow({mode:'open'});
    root.innerHTML = `<link rel="stylesheet" href="/static/navigation/menu-imports.css"><link rel="stylesheet" href="/static/navigation/menu-tokens.css"><style>
      :host{font-family:Brown,sans-serif;font-size:16px;line-height:1.5;color:#2d2929;background:white;display:block}
      :host([hidden]){display:none}a{cursor:pointer}@layer base{svg-icon{display:inline-flex}}svg-icon svg{width:100%;height:100%}
      .menu-body{background:#fff}.mobile-back{display:none}.menu-body>ul{margin:0}
      @media(max-width:1023px){.mobile-back{display:flex;width:100%;align-items:center;gap:16px;border-bottom:1px solid #ddd;padding:18px;font-size:16px;background:white}.menu-body>ul{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:auto;grid-template-areas:none;padding:20px;gap:20px}.menu-body>ul>li:first-child{grid-area:auto;grid-column:1/-1}.menu-body>ul>li:first-child>ul{gap:16px}.menu-body .product-card{min-width:0}}
    </style><button class="mobile-back" type="button">← <span></span></button><div class="menu-body color-scheme-1"></div>`;
    document.body.append(host);
    host.addEventListener('pointerenter', () => clearTimeout(exitTimer));
    host.addEventListener('pointerleave', scheduleClose);
    root.querySelector('.mobile-back').addEventListener('click', () => close(true));
    root.addEventListener('click', event => {
      const toggle = event.target.closest('[data-accordion-toggle]');
      if (toggle) {
        const expanded = toggle.getAttribute('aria-expanded') !== 'true';
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.closest('custom-accordion').querySelector('[data-accordion-content]').toggleAttribute('data-open', expanded);
      }
      const button = event.target.closest('quick-shop-toggle button');
      if (button) {
        const card = button.closest('.product-card');
        const target = card?.querySelector('a[href*="/products/"]');
        if (target) location.assign(button.closest('quick-shop-toggle').getAttribute('product-url') || target.href);
      }
    });
    root.addEventListener('submit', event => {
      event.preventDefault();
      const target = event.target.closest('.product-card')?.querySelector('a[href*="/products/"]');
      if (target) location.assign(target.href);
    });
    sync();
  });
  function sync() {
    const home = document.body.classList.contains('home-view');
    if (home && menus?.[0].countryFlag) {
      const region = document.querySelector('.region');
      if (!region.querySelector('img')) region.innerHTML = `<img src="${menus[0].countryFlag}" alt="" width="18" height="13"> United States | English`;
    }
    triggers.forEach((a, i) => {
      a.href = home && menus ? menus[i].href : initialHrefs[i];
      a.setAttribute('aria-haspopup', 'true');
      a.setAttribute('aria-expanded', String(home && active === i));
      a.setAttribute('aria-controls', 'source-navigation');
    });
    if (!home) close();
  }
  function position() {
    if (!host || host.hidden) return;
    const bottom = Math.max(0, document.querySelector(innerWidth < 1024 ? '.header-row' : '.site-header').getBoundingClientRect().bottom);
    host.style.top = `${bottom}px`;
    host.style.setProperty('--header-height', `${bottom}px`);
    host.style.maxHeight = `calc(100dvh - ${bottom}px)`;
  }
  async function open(i) {
    if (!document.body.classList.contains('home-view')) return;
    clearTimeout(exitTimer);
    await ready;
    if (active !== i) {
      active = i;
      root.querySelector('.menu-body').innerHTML = innerWidth < 1024 ? menus[i].mobileHtml || menus[i].html : menus[i].html;
      root.querySelector('.mobile-back span').textContent = menus[i].title;
      root.querySelectorAll('img').forEach(img => img.loading = 'eager');
      host.scrollTop = 0;
    }
    host.hidden = false;
    document.body.classList.add('source-menu-open');
    sync();
    position();
  }
  function close(focus = false) {
    const previous = active;
    active = -1;
    clearTimeout(exitTimer);
    if (host) host.hidden = true;
    if (document.body.classList.contains('source-menu-open')) document.body.classList.remove('source-menu-open');
    triggers.forEach(a => a.setAttribute('aria-expanded', 'false'));
    if (focus && previous >= 0) triggers[previous].focus();
  }
  function scheduleClose() { if (innerWidth >= 1024) exitTimer = setTimeout(close, 300); }
  triggers.forEach((a, i) => {
    a.addEventListener('pointerenter', () => { if (innerWidth >= 1024) open(i); });
    a.addEventListener('pointerleave', scheduleClose);
    a.addEventListener('keydown', event => {
      if (['ArrowDown', ' '].includes(event.key)) {
        event.preventDefault();
        open(i).then(() => root.querySelector('.menu-body a')?.focus());
      }
    });
  });
  // Run before the existing SPA handler; captured destination pages own their routes.
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a');
    const i = triggers.indexOf(anchor);
    if (i >= 0 && document.body.classList.contains('home-view')) {
      event.preventDefault();event.stopImmediatePropagation();
      if (innerWidth < 1024) open(i);
      else if (menus) location.assign(menus[i].href);
    } else if (active >= 0 && !event.composedPath().includes(host) && !nav.contains(event.target)) close();
  }, true);
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && active >= 0) {event.preventDefault();close(true);} });
  document.addEventListener('focusin', event => { if (active >= 0 && !nav.contains(event.target) && event.target !== host) close(); });
  new MutationObserver(sync).observe(document.body, {attributes:true,attributeFilter:['class']});
  window.addEventListener('resize', position);
  window.addEventListener('scroll', position, {passive:true});
})();
