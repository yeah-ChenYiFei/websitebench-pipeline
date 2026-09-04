const main = document.querySelector('#main');
const cartCount = document.querySelector('#cart-count');
const toastNode = document.querySelector('#toast');
const money = new Intl.NumberFormat('en-CA', {style: 'currency', currency: 'CAD'});
// Must match the free-shipping threshold in backend/store.py::cart_view.
const FREE_SHIPPING_OVER = 75;
const state = {catalog: [], cart: {items: [], count: 0, subtotal: 0}, account: null, accountData: null};

async function api(path, options = {}) {
  const config = {...options, headers: {'Content-Type': 'application/json', ...(options.headers || {})}};
  const response = await fetch(path, config);
  let value = {};
  try { value = await response.json(); } catch (_) {}
  if (!response.ok) throw Object.assign(new Error(value.error || 'Something went wrong.'), {status: response.status, value});
  return value;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function toast(message) {
  toastNode.textContent = message;
  toastNode.classList.add('show');
  window.setTimeout(() => toastNode.classList.remove('show'), 2800);
}

function updateHeader() {
  cartCount.textContent = state.cart?.count || 0;
  const signin = document.querySelector('[data-testid="signin-link"]');
  if (signin) {
    signin.href = state.account ? '/en-ca/account' : '/en-ca/account/login';
    signin.querySelector('span').textContent = state.account ? 'Account' : 'Sign In';
  }
}

function setMobileMenu(open) {
  const nav = document.querySelector('#primary-nav');
  const trigger = document.querySelector('[data-action="toggle-menu"]');
  const scrim = document.querySelector('#nav-scrim');
  if (!nav || !trigger || !scrim) return;
  nav.classList.toggle('open', open);
  scrim.classList.toggle('open', open);
  document.body.classList.toggle('menu-open', open);
  trigger.setAttribute('aria-expanded', String(open));
  trigger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  trigger.textContent = open ? '×' : '☰';
}

async function refresh() {
  const value = await api('/api/bootstrap');
  Object.assign(state, value);
  state.accountData = value.account_data;
  updateHeader();
}

function navigate(path) {
  setMobileMenu(false);
  setCartDrawer(false);
  history.pushState({}, '', path);
  const askPanel = document.querySelector('#ask-ai-panel');
  if (askPanel) askPanel.hidden = true;
  render.navigated = true;
  render();
  window.scrollTo(0, 0);
}

function crumbs(items) {
  return `<div class="breadcrumbs"><a href="/en-ca">Home</a> ${items.map(x => ` / ${escapeHtml(x)}`).join('')}</div>`;
}

function productCard(p) {
  return `<article class="product-card" data-product-card="${p.id}">
    <span class="badge">${escapeHtml(p.badge)}</span>
    <a class="image-wrap" href="/en-ca/products/${p.slug}"><img src="${p.image}" alt="${escapeHtml(p.name)}"></a>
    <h3><a href="/en-ca/products/${p.slug}">${escapeHtml(p.name)}</a></h3>
    <p class="stars">★ ${p.rating} <span class="muted">(${p.reviews} reviews)</span></p>
    <p>${escapeHtml(p.variants[0])} · ${p.variants.length} ${escapeHtml(p.variant_label)} options</p>
    <strong>${money.format(p.price)} CAD</strong>
    <div class="quick-actions"><a class="btn small" href="/en-ca/products/${p.slug}">QUICK SHOP</a><button class="btn outline small" data-favorite="${p.id}" aria-label="Save ${escapeHtml(p.name)}">♡</button></div>
  </article>`;
}

function carouselControls(id) {
  return `<div class="carousel-controls" aria-label="Carousel controls">
    <button type="button" data-carousel-move="-1" data-carousel-target="${id}" aria-label="Slide left">←</button>
    <button type="button" data-carousel-move="1" data-carousel-target="${id}" aria-label="Slide right">→</button>
  </div>`;
}

function syncCarouselProgress(rail) {
  const thumb = rail.nextElementSibling?.querySelector('span');
  if (!thumb) return;
  const ratio = Math.min(1, rail.clientWidth / Math.max(1, rail.scrollWidth));
  const progress = rail.scrollLeft / Math.max(1, rail.scrollWidth - rail.clientWidth);
  thumb.style.width = `${ratio * 100}%`;
  thumb.style.marginLeft = `${progress * (100 - ratio * 100)}%`;
}

async function homePage() {
  await window.FentyHome.render();
}

async function collectionPage(params) {
  const q = params.get('q') || '';
  const category = params.get('category') || '';
  const sort = params.get('sort') || 'featured';
  const value = await api(`/api/catalog?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}&sort=${encodeURIComponent(sort)}`);
  main.innerHTML = `<section class="section">${crumbs(['All Makeup'])}<div class="section-head"><div><p class="eyebrow">MAKEUP FOR ALL</p><h1>All Makeup</h1></div><strong data-result-count>${value.products.length} products</strong></div>
    <form class="filters" id="catalog-filters"><label class="field">Search<input name="q" value="${escapeHtml(q)}" placeholder="Search makeup" data-testid="search-input"></label><label class="field">Category<select name="category"><option value="">All categories</option>${['Face Makeup','Prime + Set','Lip Makeup','Skincare'].map(c => `<option ${category===c?'selected':''}>${c}</option>`).join('')}</select></label><label class="field">Sort<select name="sort"><option value="featured" ${sort==='featured'?'selected':''}>Featured</option><option value="price-low" ${sort==='price-low'?'selected':''}>Price: low to high</option><option value="price-high" ${sort==='price-high'?'selected':''}>Price: high to low</option><option value="rating" ${sort==='rating'?'selected':''}>Top rated</option></select></label><button class="btn" type="submit">APPLY</button></form>
    ${value.products.length ? `<div class="product-grid" data-results>${value.products.map(productCard).join('')}</div>` : noResults(q)}
    ${value.products.length > 1 ? compare(value.products.slice(0,3)) : ''}</section>`;
}

function noResults(q) {
  return `<div class="empty" data-testid="no-results"><p class="eyebrow">0 RESULTS</p><h2>We couldn't find a match for “${escapeHtml(q)}”</h2><p>Try a different keyword or clear your filters.</p><a class="btn" href="/en-ca/collections/makeup-shop-all">BACK TO ALL MAKEUP</a></div>`;
}

function compare(products) {
  return `<h2 style="margin-top:60px">Compare products</h2><table class="compare-table" data-testid="compare-table"><thead><tr><th>Product</th><th>Price</th><th>Rating</th><th>Availability</th></tr></thead><tbody>${products.map(p => `<tr><td><a href="/en-ca/products/${p.slug}">${escapeHtml(p.short_name)}</a></td><td>${money.format(p.price)}</td><td>${p.rating} / 5</td><td>${p.availability}</td></tr>`).join('')}</tbody></table>`;
}

async function searchPage(params) {
  const q = params.get('q') || '';
  const category = params.get('category') || '';
  const sort = params.get('sort') || 'featured';
  const value = q ? await api(`/api/catalog?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}&sort=${encodeURIComponent(sort)}`) : {products: []};
  main.innerHTML = `<section class="section">${crumbs(['Search'])}<h1>Search</h1><form class="search-bar" id="search-form"><input name="q" value="${escapeHtml(q)}" placeholder="What are you looking for?" aria-label="Search products" required data-testid="search-input"><button class="btn">SEARCH</button></form>
  ${q ? `<div class="section-head" style="margin-top:45px"><h2>Results for “${escapeHtml(q)}”</h2><strong>${value.products.length} products</strong></div>${value.products.length ? `<div class="product-grid">${value.products.map(productCard).join('')}</div>` : noResults(q)}` : '<div class="notice">Search by product name, category, shade, or benefit.</div>'}</section>`;
}

function productPage(slug) {
  const p = state.catalog.find(item => item.slug === slug);
  if (!p) return notFoundPage();
  const defaultVariant = p.id === 'foundation' ? '420' : p.variants[0];
  main.innerHTML = `<section class="product-detail" data-product-id="${p.id}"><div class="product-media"><img src="${p.image}" alt="${escapeHtml(p.name)}"></div><div class="product-info">${crumbs([p.name])}<p class="eyebrow">${escapeHtml(p.badge)}</p><h1>${escapeHtml(p.name)}</h1><p class="price">${money.format(p.price)} CAD</p><p class="stars">★ ${p.rating} · <u>${p.reviews} Reviews</u></p><p>${escapeHtml(p.description)}</p>
  <h2 class="eyebrow">${escapeHtml(p.variant_label)} <span id="selected-variant">${escapeHtml(defaultVariant)}</span></h2><div class="variant-grid">${p.variants.map(v => `<button class="variant" data-variant="${escapeHtml(v)}" aria-pressed="${v===defaultVariant}">${escapeHtml(v)}</button>`).join('')}</div>
  <h2 class="eyebrow">Size</h2><div class="size-grid">${p.sizes.map((s,i) => `<button class="size" data-size="${escapeHtml(s)}" aria-pressed="${i===0}">${escapeHtml(s)}</button>`).join('')}</div>
  <div class="quantity"><button data-qty="-1" aria-label="Decrease quantity">−</button><input id="product-quantity" value="1" inputmode="numeric" aria-label="Quantity"><button data-qty="1" aria-label="Increase quantity">+</button></div>
  <div class="product-actions"><button class="btn" data-add-cart="${p.id}" data-testid="add-to-bag">ADD TO BAG</button><button class="btn outline" data-favorite="${p.id}" aria-label="Save to favorites">♡</button></div><div id="product-error"></div></div></section>
  <section class="product-copy"><p class="eyebrow">DETAILS</p><h2>${escapeHtml(p.description)}</h2><p>${escapeHtml(p.details)}</p><p><strong>Availability:</strong> ${escapeHtml(p.availability)}</p><h3>CUSTOMER REVIEWS</h3><p>${p.rating} out of 5 from ${p.reviews.toLocaleString()} reviews. Review content is represented by the frozen aggregate only.</p></section>`;
}

function cartPage() {
  const active = state.cart.items.filter(i => !i.removed);
  const removed = state.cart.items.filter(i => i.removed);
  main.innerHTML = `<section class="section">${crumbs(['Shopping Bag'])}<h1>Your Bag</h1><div class="cart-layout"><div data-testid="cart-lines">${active.length ? active.map(cartLine).join('') : `<div class="empty"><h2>Your bag is empty</h2><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a></div>`}${removed.length ? `<h2 style="margin-top:35px">Recently removed</h2>${removed.map(cartLine).join('')}` : ''}</div>${cartSummary()}</div></section>`;
}

function cartLine(item) {
  const p = item.product;
  return `<article class="cart-line ${item.removed?'removed':''}" data-cart-line="${p.id}"><img src="${p.image}" alt=""><div><h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.variant_label)}: <strong>${escapeHtml(item.variant)}</strong></p><p>Size: ${escapeHtml(item.size)}</p>${item.removed ? `<button class="btn small" data-cart-restore="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">RESTORE</button>` : `<label>Quantity <select data-cart-qty="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">${[1,2,3,4,5].map(n=>`<option ${n===item.quantity?'selected':''}>${n}</option>`).join('')}</select></label> <button class="btn outline small" data-cart-remove="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">REMOVE</button>`}</div><strong>${money.format(item.line_total)}</strong></article>`;
}

function cartSummary() {
  const shipping = state.cart.subtotal >= 75 ? 0 : (state.cart.subtotal ? 8 : 0);
  return `<aside class="cart-summary"><h2>Order Summary</h2><div class="summary-row"><span>Subtotal</span><strong>${money.format(state.cart.subtotal || 0)}</strong></div><div class="summary-row"><span>Estimated shipping</span><strong>${shipping ? money.format(shipping) : 'FREE'}</strong></div><p class="muted">Taxes calculated at checkout.</p><a class="btn" style="width:100%" href="/en-ca/checkout" ${state.cart.count?'':'aria-disabled="true"'}>BEGIN CHECKOUT</a><p><small>Checkout uses a local sandbox. No real card or order is submitted.</small></p></aside>`;
}

async function checkoutPage() {
  let preview;
  try { preview = await api('/api/checkout/preview', {method:'POST', body:'{}'}); }
  catch (error) { main.innerHTML = `<section class="section"><div class="empty"><h1>Your bag is empty</h1><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a></div></section>`; return; }
  main.innerHTML = `<section class="section">${crumbs(['Cart','Checkout'])}<h1>Checkout</h1><div class="notice"><strong>LOCAL SANDBOX</strong> — This page never accepts real card numbers and cannot place a real order.</div><div class="checkout-layout"><form id="checkout-form"><h2>Contact</h2><label class="field">Email address<input type="email" name="email" required autocomplete="email"></label><h2>Delivery address</h2><div class="form-grid"><label class="field">Full name<input name="full_name" required></label><label class="field">Address<input name="line1" required></label><label class="field">City<input name="city" required></label><label class="field">Province<select name="province" required><option value="">Choose province</option><option>Ontario</option><option>Quebec</option><option>British Columbia</option></select></label><label class="field">Postal code<input name="postal_code" required></label><label class="field">Country<select name="country"><option>Canada</option></select></label></div><h2>Delivery</h2><label class="field">Shipping option<select name="fulfillment">${preview.fulfillment_options.map(x=>`<option>${x}</option>`).join('')}</select></label><h2>Promo or gift option</h2><div class="search-bar"><input name="promo" placeholder="Try FENTY10"><button class="btn outline" type="button" data-apply-promo>APPLY</button></div><h2>Payment</h2><label class="field">Simulation<select name="payment"><option value="sandbox-approved">Simulated approval</option><option value="sandbox-declined">Simulated decline</option><option value="sandbox-retry">Simulated retry</option></select></label><p class="muted">No card fields are present by design.</p><div id="checkout-error"></div><button class="btn" type="submit">REVIEW ORDER</button></form><aside class="review-card" id="checkout-review">${checkoutSummary(preview)}</aside></div></section>`;
  document.querySelector('#checkout-form').setAttribute('novalidate', '');
}

function checkoutSummary(p) {
  return `<h2>Order review</h2>${p.items.map(i=>`<div class="order-line"><img src="${i.product.image}" alt=""><div><strong>${escapeHtml(i.product.short_name)}</strong><br>${escapeHtml(i.variant)} · ${escapeHtml(i.size)} · Qty ${i.quantity}</div></div>`).join('')}<div class="summary-row"><span>Subtotal</span><strong>${money.format(p.subtotal)}</strong></div><div class="summary-row"><span>Discount</span><strong>−${money.format(p.discount||0)}</strong></div><div class="summary-row"><span>Shipping</span><strong>${p.shipping?money.format(p.shipping):'FREE'}</strong></div><div class="summary-row"><span>Estimated tax</span><strong>${money.format(p.tax||0)}</strong></div><div class="summary-row total"><span>Total</span><strong>${money.format(p.total||p.subtotal)}</strong></div><p class="success">Both selected products and their requested variants remain visible before any simulated payment.</p>`;
}

function authPage(kind) {
  if (state.account && kind === 'login') return accountPage('overview');
  const config = {
    login: {title:'Sign in', body:`<label class="field">Email<input type="email" name="email" required autocomplete="email"></label><label class="field">Password<input type="password" name="password" required autocomplete="current-password"></label><button class="btn">SIGN IN</button>`, links:`<a href="/en-ca/account/recover">Forgot password?</a><a href="/en-ca/account/register">Create account</a>`},
    register: {title:'Create account', body:`<label class="field">Name<input name="display_name" required autocomplete="name"></label><label class="field">Email<input type="email" name="email" required autocomplete="email"></label><label class="field">Password<input type="password" name="password" minlength="8" required autocomplete="new-password"></label><label><input type="checkbox" required> I agree to the <a href="/en-ca/pages/help-center"><u>Terms of Use</u></a> and <a href="/en-ca/pages/help-center"><u>Privacy Policy</u></a>.</label><p class="notice">Verification guidance: this offline demo verifies locally and never sends email.</p><button class="btn">CREATE ACCOUNT</button>`, links:`<a href="/en-ca/account/login">Already have an account? Sign in</a>`},
    recover: {title:'Reset your password', body:`<p>Enter the email address associated with your account. This preview does not send a message.</p><label class="field">Email address<input type="email" name="email" required autocomplete="email"></label><button class="btn">PREVIEW RESET</button>`, links:`<a href="/en-ca/account/login">Return to sign in</a>`}
  }[kind];
  main.innerHTML = `<section class="auth-card">${crumbs(['Account',config.title])}<h1>${config.title}</h1><form id="auth-form" data-auth-kind="${kind}" novalidate>${config.body}<div id="auth-error"></div></form><div class="auth-links">${config.links}</div><hr><p>Identity provider choices</p><button class="btn outline" disabled>Continue with Google (unavailable offline)</button> <button class="btn outline" disabled>Shop Pay (unavailable offline)</button></section>`;
}

function accountPage(tab) {
  if (!state.account) { navigate('/en-ca/account/login'); return; }
  const data = state.accountData || {addresses:[],favorites:[],orders:[]};
  const nav = `<nav class="account-nav"><a class="${tab==='overview'?'active':''}" href="/en-ca/account">Overview</a><a class="${tab==='favorites'?'active':''}" href="/en-ca/account/favorites">Favorites</a><a class="${tab==='addresses'?'active':''}" href="/en-ca/account/addresses">Addresses</a><a class="${tab==='orders'?'active':''}" href="/en-ca/account/orders">Orders</a><button class="btn outline" data-logout>SIGN OUT</button></nav>`;
  let body = '';
  if (tab === 'favorites') body = `<h2>Saved items</h2>${data.favorites.length?`<div class="product-grid">${data.favorites.map(productCard).join('')}</div>`:`<div class="empty"><h2>No saved items yet</h2><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a></div>`}`;
  else if (tab === 'addresses') body = `<h2>Shipping addresses</h2>${data.addresses.map(a=>`<div class="address-card"><strong>${escapeHtml(a.label)}</strong><p>${escapeHtml(a.full_name)}<br>${escapeHtml(a.line1)}<br>${escapeHtml(a.city)}, ${escapeHtml(a.province)} ${escapeHtml(a.postal_code)}<br>${escapeHtml(a.country)}</p></div>`).join('')}<form id="address-form" class="form-grid"><label class="field">Full name<input name="full_name" required></label><label class="field">Address<input name="line1" required></label><label class="field">City<input name="city" required></label><label class="field">Province<input name="province" required></label><label class="field">Postal code<input name="postal_code" required></label><label class="field">Country<input name="country" value="Canada" required></label><div class="full" id="address-error"></div><button class="btn full">SAVE ADDRESS</button></form>`;
  else if (tab === 'orders') body = `<h2>Order history</h2>${data.orders.length?data.orders.map(orderCard).join(''):`<div class="empty"><h2>No orders</h2></div>`}`;
  else body = `<p class="eyebrow">WELCOME BACK</p><h2>${escapeHtml(state.account.display_name)}</h2><p>${escapeHtml(state.account.email_normalized)}</p><div class="help-grid"><a class="help-card" href="/en-ca/account/orders"><h3>Orders</h3><p>${data.orders.length} seeded order${data.orders.length===1?'':'s'} · View status and management actions.</p></a><a class="help-card" href="/en-ca/account/favorites"><h3>Favorites</h3><p>${data.favorites.length} saved item${data.favorites.length===1?'':'s'}.</p></a><a class="help-card" href="/en-ca/account/addresses"><h3>Profile + addresses</h3><p>Manage local contact and fulfillment data.</p></a></div>`;
  main.innerHTML = `<section class="section">${crumbs(['Account'])}<h1>Account</h1><div class="account-layout">${nav}<div>${body}</div></div></section>`;
}

function orderCard(o) {
  return `<article class="order-card" data-order="${o.order_id}"><div class="order-head"><div><p class="eyebrow">ORDER ${escapeHtml(o.order_id)}</p><h3>${escapeHtml(o.status)}</h3><p>${escapeHtml(o.fulfillment)}</p></div><strong>${money.format(o.total)}</strong></div><div class="order-lines">${o.lines.map(l=>`<div class="order-line"><img src="${l.product.image}" alt=""><div><strong>${escapeHtml(l.product.short_name)}</strong><br>${escapeHtml(l.variant)} · ${escapeHtml(l.size)} · Qty ${l.quantity}</div></div>`).join('')}</div><div class="quick-actions"><button class="btn small" data-order-action="reorder" data-order-id="${o.order_id}">REORDER</button><button class="btn outline small" data-order-action="cancel" data-order-id="${o.order_id}" ${o.status==='Cancelled'?'disabled':''}>CANCEL</button><button class="btn outline small" data-order-action="return" data-order-id="${o.order_id}">START RETURN</button><a class="btn outline small" href="/en-ca/collections/makeup-shop-all">BACK TO MAKEUP</a></div></article>`;
}

function helpPage(contact=false) {
  main.innerHTML = `<section class="section">${crumbs([contact?'Contact Us':'Help Center'])}<h1>${contact?'Contact Us':'Help Center'}</h1><p>Get guidance without exposing private account data.</p><div class="help-grid"><article class="help-card"><h2>Orders + returns</h2><p>Track, cancel, reorder, or start a return from your local order history.</p><a class="btn small" href="/en-ca/account/orders">ORDER STATUS</a></article><article class="help-card"><h2>Account access</h2><p>Use sign in, registration, and no-send recovery previews.</p><a class="btn small" href="/en-ca/account/login">ACCOUNT HELP</a></article><article class="help-card"><h2>Shopping help</h2><p>Browse makeup, check availability, and recover from an empty search.</p><a class="btn small" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a></article></div><div class="notice"><strong>Customer service:</strong> customerservice@fentybeauty.com · 1-855-440-7474. These are displayed as source evidence; the offline clone does not contact them.</div></section>`;
}

function notFoundPage() {
  main.innerHTML = `<section class="not-found" data-testid="not-found"><p class="eyebrow">OOPS!</p><h1>SORRY, BUT THAT PAGE IS NOT A THING</h1><p>Your link might be incorrect, out-of-date, or the page may have moved.</p><div class="recovery-links"><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a><a class="btn" href="/en-ca">HOME</a><a class="btn outline" href="/en-ca/pages/help-center">HELP CENTER</a></div></section><section class="section"><h2>BEST SELLERS</h2><div class="product-grid">${state.catalog.slice(0,4).map(productCard).join('')}</div></section>`;
}

/* Inner-page fidelity system. These declarations intentionally supersede the
   compact first-pass templates above while preserving the same local APIs. */
function productCard(p) {
  return `<article class="product-card source-card" data-product-card="${p.id}">
    <div class="image-wrap-shell"><span class="badge">${escapeHtml(p.badge)}</span><button class="card-heart" data-favorite="${p.id}" aria-label="Save ${escapeHtml(p.name)}">♡</button>
    <a class="image-wrap" href="/en-ca/products/${p.slug}"><img src="${p.image}" alt="${escapeHtml(p.name)}"></a></div>
    <div class="card-copy"><h3><a href="/en-ca/products/${p.slug}">${escapeHtml(p.name)}</a></h3>
    <p class="stars">★★★★★ <span class="sr-rating">${p.rating} star rating</span></p>
    <p class="card-option">${escapeHtml(p.variants[0])}${p.variants.length > 1 ? ` &nbsp; <u>${p.variants.length} ${escapeHtml(p.variant_label)}s</u>` : ''}</p>
    <strong>${money.format(p.price)} CAD</strong><a class="card-shop-link" href="/en-ca/products/${p.slug}">QUICK SHOP</a></div>
  </article>`;
}

function catalogHero() {
  return `<section class="catalog-hero" aria-label="Fenty Beauty offer"><img src="/static/assets/catalog-banner.webp" alt="Gloss Bomb Heat deluxe sample offer"><div class="catalog-hero-copy"><span>VIRAL FAVE</span><strong>FREE GLOSS BOMB HEAT DELUXE SAMPLE ON $75+ ORDERS</strong><small>While supplies last.</small></div><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP NOW</a></section>`;
}

function visualCategories() {
  const categories = [
    ['Lip Makeup','category-lip.webp','Lip Makeup'],
    ['Face Makeup','category-face.avif','Face Makeup'],
    ['Cheek Makeup','category-cheek.avif','Face Makeup'],
    ['Eye Makeup','category-eye.avif','Face Makeup'],
    ['Brushes + Tools','category-tools.webp','Prime + Set']
  ];
  return `<div class="visual-categories" aria-label="Makeup categories">${categories.map(([label,image,value]) => `<a href="/en-ca/collections/makeup-shop-all?category=${encodeURIComponent(value)}"><img src="/static/assets/${image}" alt="${label}"><span>${label}</span></a>`).join('')}</div>`;
}

async function collectionPage(params) {
  const q = params.get('q') || '';
  const category = params.get('category') || '';
  const sort = params.get('sort') || 'featured';
  const value = await api(`/api/catalog?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}&sort=${encodeURIComponent(sort)}`);
  main.innerHTML = `${catalogHero()}<section class="catalog-page section">${crumbs(['All Makeup'])}<h1>All Makeup</h1>${visualCategories()}
    <form class="catalog-toolbar" id="catalog-filters"><button class="filter-trigger" type="button" aria-label="Filter products">☰ &nbsp; FILTER</button><label class="catalog-search">Search<input name="q" value="${escapeHtml(q)}" placeholder="Search makeup" data-testid="search-input"></label><label>Category<select name="category"><option value="">All categories</option>${['Face Makeup','Prime + Set','Lip Makeup','Skincare'].map(c => `<option ${category===c?'selected':''}>${c}</option>`).join('')}</select></label><label>Sort by<select name="sort"><option value="featured" ${sort==='featured'?'selected':''}>Featured</option><option value="price-low" ${sort==='price-low'?'selected':''}>Price: low to high</option><option value="price-high" ${sort==='price-high'?'selected':''}>Price: high to low</option><option value="rating" ${sort==='rating'?'selected':''}>Top rated</option></select></label><button class="btn" type="submit">APPLY</button><strong data-result-count>${value.products.length} PRODUCTS</strong></form>
    ${value.products.length ? `<div class="product-grid source-product-grid" data-results>${value.products.map(productCard).join('')}</div>` : noResults(q)}
    ${value.products.length > 1 ? compare(value.products.slice(0,4)) : ''}
    <section class="catalog-copy"><h2>SHOP ALL MAKEUP</h2><p>Discover makeup for all at Fenty Beauty, where inclusivity is at the heartbeat of every product. Explore our bestsellers, from complexion essentials and shade-matching foundation to universally loved lip luminizers.</p><p>Find your perfect match, build a routine and create looks designed to celebrate every skin tone.</p></section></section>`;
}

function noResults(q) {
  return `<div class="empty no-results" data-testid="no-results"><p class="eyebrow">0 RESULTS</p><h2>WE COULDN'T FIND A MATCH FOR “${escapeHtml(q)}”</h2><p>Check the spelling, try a broader term or clear your filters.</p><a class="btn" href="/en-ca/collections/makeup-shop-all">BACK TO ALL MAKEUP</a></div>`;
}

function compare(products) {
  return `<details class="catalog-compare"><summary>COMPARE SELECTED PRODUCTS <span>+</span></summary><div class="compare-cards" data-testid="compare-table">${products.map(p => `<article><h3>${escapeHtml(p.short_name)}</h3><strong>${money.format(p.price)} CAD</strong><dl><div><dt>RATING</dt><dd>${p.rating} / 5</dd></div><div><dt>TYPE</dt><dd>${escapeHtml(p.category)}</dd></div><div><dt>AVAILABILITY</dt><dd>${escapeHtml(p.availability)}</dd></div></dl></article>`).join('')}</div></details>`;
}

async function searchPage(params) {
  const q = params.get('q') || '';
  const category = params.get('category') || '';
  const sort = params.get('sort') || 'featured';
  const value = q ? await api(`/api/catalog?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}&sort=${encodeURIComponent(sort)}`) : {products: []};
  main.innerHTML = `<section class="search-page section">${crumbs(['Search'])}<p class="eyebrow">FIND YOUR FENTY</p><h1>Search</h1><form class="source-search" id="search-form"><input name="q" value="${escapeHtml(q)}" placeholder="What are you looking for?" aria-label="Search products" required data-testid="search-input"><button class="btn">SEARCH</button></form>
  ${q ? `<div class="search-result-head"><div><p class="eyebrow">SEARCH RESULTS FOR</p><h2>“${escapeHtml(q)}”</h2></div><strong>${value.products.length} PRODUCTS</strong></div>${value.products.length ? `<div class="product-grid source-product-grid">${value.products.map(productCard).join('')}</div>${value.products.length > 1 ? compare(value.products.slice(0,4)) : ''}` : noResults(q)}` : `<div class="search-suggestions"><h2>POPULAR SEARCHES</h2><a href="/en-ca/search?q=foundation">Foundation</a><a href="/en-ca/search?q=gloss">Gloss Bomb</a><a href="/en-ca/search?q=powder">Setting powder</a></div>`}</section>`;
}

function shadeColor(value, index) {
  if (!/^\d+$/.test(value)) return ['#d9c3ae','#b98463','#75452d'][index % 3];
  const palette = ['#f5c6a1','#edb98f','#e7ad7e','#dca070','#cf8e5c','#bd7847','#aa6037','#914a2b','#71371f','#4d281e'];
  return palette[Math.min(palette.length - 1, Math.floor(index * palette.length / 36))];
}

function productPage(slug) {
  const p = state.catalog.find(item => item.slug === slug);
  if (!p) return notFoundPage();
  const defaultVariant = p.id === 'foundation' ? '420' : p.variants[0];
  const hero = p.id === 'powder' ? '/static/assets/powder-hero.webp' : p.image;
  const secondary = p.id === 'foundation' ? '/static/assets/foundation-before-after.webp' : p.image;
  main.innerHTML = `<section class="pdp" data-product-id="${p.id}"><div class="pdp-gallery"><div class="pdp-thumbs"><button class="active"><img src="${hero}" alt="${escapeHtml(p.short_name)} product view"></button><button><img src="${secondary}" alt="${escapeHtml(p.short_name)} detail view"></button><button><img src="/static/assets/brand-beauty.webp" alt="Fenty Beauty model"></button></div><div class="pdp-main-image"><img src="${hero}" alt="${escapeHtml(p.name)}"></div></div>
  <div class="pdp-buy">${crumbs([p.name])}<div class="pdp-badges"><span>${escapeHtml(p.badge)}</span></div><h1>${escapeHtml(p.name)}</h1><p class="price">${money.format(p.price)} CAD</p><p class="stars">★★★★★ &nbsp; <u>${p.reviews} Reviews</u></p><p class="pdp-description">${escapeHtml(p.description)}</p>
  <div class="choice-label"><strong>${escapeHtml(p.variant_label)}</strong><span id="selected-variant">${escapeHtml(defaultVariant)}</span></div>${p.id === 'foundation' ? `<div class="tone-tabs"><button>All</button><button>Light</button><button>Light-Medium</button><button>Medium</button><button>Medium-Deep</button><button>Deep</button></div>` : ''}
  <div class="variant-grid ${p.id === 'foundation' ? 'shade-grid' : ''}">${p.variants.map((v,i) => `<button class="variant" data-variant="${escapeHtml(v)}" aria-pressed="${v===defaultVariant}" style="--swatch:${shadeColor(v,i)}"><span>${escapeHtml(v)}</span></button>`).join('')}</div>
  <div class="shade-readout"><span style="background:${shadeColor(defaultVariant, Math.max(0,p.variants.indexOf(defaultVariant)))}"></span><strong>${escapeHtml(defaultVariant)}</strong> — ${p.id === 'foundation' ? 'Medium Deep with warm golden undertones' : escapeHtml(p.variant_label)}</div>
  <div class="shade-tools"><button>◉ &nbsp; FIND SHADE</button><button>◉ &nbsp; TRY SHADE</button></div>
  <h2 class="choice-title">SIZE</h2><div class="size-grid">${p.sizes.map((s,i) => `<button class="size" data-size="${escapeHtml(s)}" aria-pressed="${i===0}"><strong>${escapeHtml(s)}</strong><small>${i ? 'Alternate size' : 'Most popular'}</small></button>`).join('')}</div>
  <div class="pdp-action-row"><div class="quantity"><button data-qty="-1" aria-label="Decrease quantity">−</button><input id="product-quantity" value="1" inputmode="numeric" aria-label="Quantity"><button data-qty="1" aria-label="Increase quantity">+</button></div><button class="btn add-bag" data-add-cart="${p.id}" data-testid="add-to-bag">ADD TO BAG</button><button class="btn outline save-pdp" data-favorite="${p.id}" aria-label="Save to favorites">♡</button></div><div id="product-error"></div>
  <div class="pdp-ai"><span>✦</span><input aria-label="Ask anything" placeholder="Ask anything"><button aria-label="Send question">→</button></div>
  <section class="pairing"><h2>DESIGNED TO BE USED WITH</h2><div><img src="/static/assets/starter.webp" alt="Fenty Skin moisturizer"><p>Hydra Vizor Invisible Moisturizer Broad Spectrum SPF 30<br><strong>From $53.00 CAD</strong></p><button class="btn outline small">ADD TO BAG</button></div></section>
  <div class="pdp-accordions"><details open><summary>DETAILS <span>−</span></summary><h2>${escapeHtml(p.description)}</h2><p>${escapeHtml(p.details)}</p><p><strong>THE LOWDOWN:</strong></p><ul><li>Longwear, comfortable formula</li><li>Designed for all skin tones</li><li>100% cruelty free</li><li>${escapeHtml(p.availability)}</li></ul></details><details><summary>INGREDIENTS <span>+</span></summary><p>See the frozen source product information for the complete ingredient list.</p></details><details><summary>HOW TO <span>+</span></summary><p>Apply with your fingertips, sponge or a Fenty Beauty brush and build as desired.</p></details><details><summary>RIHANNA'S INSPO <span>+</span></summary><p>Made to perform across skin tones and types.</p></details></div></div></section>
  <section class="section pdp-recommendations"><div class="section-head"><h2>HANDPICKED FOR YOU</h2>${carouselControls('pdp-recs')}</div><div class="home-product-rail" id="pdp-recs" data-home-carousel>${state.catalog.filter(x=>x.id!==p.id).concat(state.catalog.slice(0,2)).map(productCard).join('')}</div><div class="carousel-progress"><span></span></div></section>
  <section class="pdp-howto"><h2>${p.id === 'foundation' ? 'FACE LOOKIN’ FRESH MORNING + NIGHT' : 'THE FENTY FINISH'}</h2><p>Build your routine with prep, apply, blend and set.</p><div>${['PREP SKIN','PRIME','BLEND','SET + PERFECT'].map((x,i)=>`<article><img src="${i%2 ? secondary : '/static/assets/brand-skin.webp'}" alt="${x}"><h3>${x}</h3><p>${i===0?'Start with hydrated skin.':'Use thin layers and blend for a seamless finish.'}</p></article>`).join('')}</div></section>
  <section class="section pdp-faq"><h2>FREQUENTLY ASKED QUESTIONS</h2><details open><summary>How do I choose my match?<span>−</span></summary><p>Use the shade families above, then select the closest undertone and depth.</p></details><details><summary>Can I change the size?<span>+</span></summary><p>Select any available size before adding to bag.</p></details><details><summary>Is it cruelty free?<span>+</span></summary><p>Fenty Beauty is 100% cruelty free.</p></details></section>`;
  window.requestAnimationFrame(() => document.querySelectorAll('[data-home-carousel]').forEach(syncCarouselProgress));
}

function cartPage() {
  const active = state.cart.items.filter(i => !i.removed);
  const removed = state.cart.items.filter(i => i.removed);
  main.innerHTML = `<section class="bag-page section">${crumbs(['Shopping Bag'])}<div class="bag-title"><h1>SHOPPING BAG</h1><span>${state.cart.count} ITEMS</span></div><div class="shipping-meter"><strong>${state.cart.subtotal >= FREE_SHIPPING_OVER ? 'YOU QUALIFY FOR FREE STANDARD SHIPPING' : `${money.format(Math.max(0,FREE_SHIPPING_OVER-state.cart.subtotal))} AWAY FROM FREE STANDARD SHIPPING`}</strong><span><i style="width:${Math.min(100,state.cart.subtotal/FREE_SHIPPING_OVER*100)}%"></i></span></div><div class="cart-layout"><div class="bag-lines" data-testid="cart-lines">${active.length ? active.map(cartLine).join('') : `<div class="empty bag-empty"><h2>YOUR BAG IS EMPTY</h2><p>Fill it with your new Fenty favorites.</p><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP BESTSELLERS</a></div>`}${removed.length ? `<h2 class="removed-title">RECENTLY REMOVED</h2>${removed.map(cartLine).join('')}` : ''}</div>${cartSummary()}</div></section>`;
}

function cartLine(item) {
  const p = item.product;
  return `<article class="cart-line source-cart-line ${item.removed?'removed':''}" data-cart-line="${p.id}"><img src="${p.image}" alt="${escapeHtml(p.short_name)}"><div class="cart-line-copy"><p class="eyebrow">${escapeHtml(p.badge)}</p><h3>${escapeHtml(p.name)}</h3><p>${escapeHtml(p.variant_label)}: <strong>${escapeHtml(item.variant)}</strong></p><p>Size: ${escapeHtml(item.size)}</p>${item.removed ? `<button class="text-button" data-cart-restore="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">RESTORE ITEM</button>` : `<label>Quantity <select data-cart-qty="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">${[1,2,3,4,5].map(n=>`<option ${n===item.quantity?'selected':''}>${n}</option>`).join('')}</select></label><button class="text-button" data-cart-remove="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">REMOVE</button>`}</div><strong class="cart-line-price">${money.format(item.line_total)} CAD</strong></article>`;
}

function cartSummary() {
  const shipping = state.cart.shipping ?? 0;
  return `<aside class="cart-summary source-cart-summary"><h2>ORDER SUMMARY</h2><label class="promo-field">PROMO CODE OR GIFT CARD<div><input placeholder="Enter code"><button>APPLY</button></div></label><div class="summary-row"><span>Subtotal</span><strong>${money.format(state.cart.subtotal || 0)} CAD</strong></div><div class="summary-row"><span>Estimated shipping</span><strong>${shipping ? money.format(shipping) : 'FREE'}</strong></div><p class="muted">Taxes calculated at checkout.</p><div class="summary-row total"><span>ESTIMATED TOTAL</span><strong>${money.format((state.cart.subtotal||0)+shipping)} CAD</strong></div><a class="btn checkout-button" href="/en-ca/checkout" ${state.cart.count?'':'aria-disabled="true"'}>CHECKOUT</a><p class="sandbox-note">LOCAL SANDBOX — no real card or order is submitted.</p><div class="bag-benefits"><p>✓ Free standard shipping over CA$${FREE_SHIPPING_OVER}</p><p>✓ Easy returns</p><p>✓ Secure local checkout simulation</p></div></aside>`;
}

async function checkoutPage() {
  let preview;
  try { preview = await api('/api/checkout/preview', {method:'POST', body:'{}'}); }
  catch (error) { main.innerHTML = `<section class="section"><div class="empty bag-empty"><h1>YOUR BAG IS EMPTY</h1><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a></div></section>`; return; }
  main.innerHTML = `<section class="checkout-page"><div class="checkout-wordmark"><img src="/static/assets/fenty-logo.webp" alt="Fenty Beauty"><div><span class="active">INFORMATION</span><span>SHIPPING</span><span>PAYMENT</span></div></div><div class="checkout-shell"><form id="checkout-form" class="checkout-form"><div class="sandbox-banner"><strong>LOCAL CHECKOUT SANDBOX</strong><p>This screen mirrors checkout structure but never accepts real payment details or places a real order.</p></div><section><div class="checkout-heading"><h1>CONTACT</h1><a href="/en-ca/account/login">Already have an account? Sign in</a></div><label class="field">Email address<input type="email" name="email" required autocomplete="email" placeholder="Email"></label></section><section><h2>DELIVERY</h2><div class="form-grid"><label class="field">Full name<input name="full_name" required></label><label class="field">Address<input name="line1" required></label><label class="field">City<input name="city" required></label><label class="field">Province<select name="province" required><option value="">Province</option><option>Ontario</option><option>Quebec</option><option>British Columbia</option></select></label><label class="field">Postal code<input name="postal_code" required></label><label class="field">Country<select name="country"><option>Canada</option></select></label></div></section><section><h2>SHIPPING METHOD</h2><div class="shipping-options">${preview.fulfillment_options.map((x,i)=>`<label><input type="radio" name="fulfillment" value="${escapeHtml(x)}" ${i===0?'checked':''}><span>${escapeHtml(x)}</span><strong>${i===0?'FREE':'$18.00'}</strong></label>`).join('')}</div></section><section><h2>DISCOUNT CODE OR GIFT CARD</h2><div class="checkout-promo"><input name="promo" placeholder="Discount code or gift card"><button class="btn outline" type="button" data-apply-promo>APPLY</button></div></section><section><h2>PAYMENT</h2><p>All transactions in this clone are secure simulations.</p><label class="field">Payment simulation<select name="payment"><option value="sandbox-approved">Simulated approval</option><option value="sandbox-declined">Simulated decline</option><option value="sandbox-retry">Simulated retry</option></select></label></section><div id="checkout-error"></div><button class="btn review-order-button" type="submit">REVIEW ORDER</button></form><aside class="checkout-review" id="checkout-review">${checkoutSummary(preview)}</aside></div></section>`;
  document.querySelector('#checkout-form').setAttribute('novalidate', '');
}

function checkoutSummary(p) {
  return `<h2>YOUR ORDER</h2><div class="checkout-items">${p.items.map(i=>`<div class="checkout-item"><span class="checkout-item-image"><img src="${i.product.image}" alt=""><b>${i.quantity}</b></span><div><strong>${escapeHtml(i.product.short_name)}</strong><small>${escapeHtml(i.variant)} · ${escapeHtml(i.size)}</small></div><strong>${money.format(i.line_total)} CAD</strong></div>`).join('')}</div><div class="summary-row"><span>Subtotal</span><strong>${money.format(p.subtotal)} CAD</strong></div><div class="summary-row"><span>Discount</span><strong>−${money.format(p.discount||0)}</strong></div><div class="summary-row"><span>Shipping</span><strong>${p.shipping?money.format(p.shipping):'FREE'}</strong></div><div class="summary-row"><span>Estimated tax</span><strong>${money.format(p.tax||0)}</strong></div><div class="summary-row total"><span>TOTAL</span><strong>${money.format(p.total||p.subtotal)} CAD</strong></div><p class="success">Requested products, shades and sizes remain visible before simulated payment.</p>`;
}

function authPage(kind) {
  if (state.account && kind === 'login') return accountPage('overview');
  const config = {
    login: {eyebrow:'WELCOME BACK',title:'SIGN IN',intro:'Sign in to view orders, saved items and addresses.',body:`<label class="field">Email address<input type="email" name="email" required autocomplete="email"></label><label class="field password-field">Password<input type="password" name="password" required autocomplete="current-password"></label><a class="forgot-inline" href="/en-ca/account/recover">Forgot password?</a><button class="btn auth-submit">SIGN IN</button>`,links:`<p>NEW TO FENTY BEAUTY?</p><a class="btn outline auth-secondary" href="/en-ca/account/register">CREATE ACCOUNT</a>`},
    register: {eyebrow:'JOIN THE FENTY FAM',title:'CREATE ACCOUNT',intro:'Get first access to product drops, order history and saved favorites.',body:`<label class="field">Full name<input name="display_name" required autocomplete="name"></label><label class="field">Email address<input type="email" name="email" required autocomplete="email"></label><label class="field">Password<input type="password" name="password" minlength="8" required autocomplete="new-password"></label><label class="auth-check"><input type="checkbox" required><span>I agree to the <a href="/en-ca/pages/help-center"><u>Terms of Use</u></a> and <a href="/en-ca/pages/help-center"><u>Privacy Policy</u></a>.</span></label><p class="auth-guidance">Verification is completed locally. This clone does not send email.</p><button class="btn auth-submit">CREATE ACCOUNT</button>`,links:`<p>ALREADY HAVE AN ACCOUNT?</p><a class="btn outline auth-secondary" href="/en-ca/account/login">SIGN IN</a>`},
    recover: {eyebrow:'ACCOUNT HELP',title:'RESET YOUR PASSWORD',intro:'Enter your email address and we’ll preview the recovery guidance without sending a message.',body:`<label class="field">Email address<input type="email" name="email" required autocomplete="email"></label><button class="btn auth-submit">PREVIEW RESET</button>`,links:`<a class="auth-back" href="/en-ca/account/login">← RETURN TO SIGN IN</a>`}
  }[kind];
  main.innerHTML = `<section class="auth-page"><div class="auth-visual"><img src="/static/assets/brand-beauty.webp" alt="Rihanna wearing Fenty Beauty"><div><h2>THE FENTY BEAUTY EXPERIENCE</h2><p>Beauty for all, made to perform.</p></div></div><div class="auth-panel">${crumbs(['Account',config.title])}<p class="eyebrow">${config.eyebrow}</p><h1>${config.title}</h1><p class="auth-intro">${config.intro}</p><form id="auth-form" data-auth-kind="${kind}" novalidate>${config.body}<div id="auth-error"></div></form><div class="auth-links">${config.links}</div>${kind==='login'?`<div class="identity-divider"><span>OR</span></div><button class="identity-button" disabled>G &nbsp; CONTINUE WITH GOOGLE</button><button class="identity-button" disabled>SHOP &nbsp; CONTINUE WITH SHOP</button><small>Identity providers are displayed for source fidelity and remain unavailable offline.</small>`:''}</div></section>`;
}

function accountPage(tab) {
  if (!state.account) { navigate('/en-ca/account/login'); return; }
  const data = state.accountData || {addresses:[],favorites:[],orders:[]};
  const nav = `<nav class="account-nav"><p>MY ACCOUNT</p><a class="${tab==='overview'?'active':''}" href="/en-ca/account">Account overview</a><a class="${tab==='orders'?'active':''}" href="/en-ca/account/orders">Order history</a><a class="${tab==='favorites'?'active':''}" href="/en-ca/account/favorites">Saved items</a><a class="${tab==='addresses'?'active':''}" href="/en-ca/account/addresses">Addresses</a><button class="text-button" data-logout>SIGN OUT</button></nav>`;
  let body = '';
  if (tab === 'favorites') body = `<div class="account-heading"><div><p class="eyebrow">YOUR FENTY PICKS</p><h2>SAVED ITEMS</h2></div><span>${data.favorites.length} ITEMS</span></div>${data.favorites.length?`<div class="product-grid source-product-grid account-products">${data.favorites.map(productCard).join('')}</div>`:`<div class="empty"><h2>NO SAVED ITEMS YET</h2><p>Tap the heart on any product to save it here.</p><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a></div>`}`;
  else if (tab === 'addresses') body = `<div class="account-heading"><div><p class="eyebrow">DELIVERY DETAILS</p><h2>ADDRESSES</h2></div></div><div class="address-list">${data.addresses.map(a=>`<article class="address-card"><span>DEFAULT</span><strong>${escapeHtml(a.label)}</strong><p>${escapeHtml(a.full_name)}<br>${escapeHtml(a.line1)}<br>${escapeHtml(a.city)}, ${escapeHtml(a.province)} ${escapeHtml(a.postal_code)}<br>${escapeHtml(a.country)}</p></article>`).join('')}</div><form id="address-form" class="form-grid account-form"><h3 class="full">ADD A NEW ADDRESS</h3><label class="field">Full name<input name="full_name" required></label><label class="field">Address<input name="line1" required></label><label class="field">City<input name="city" required></label><label class="field">Province<input name="province" required></label><label class="field">Postal code<input name="postal_code" required></label><label class="field">Country<input name="country" value="Canada" required></label><div class="full" id="address-error"></div><button class="btn full">SAVE ADDRESS</button></form>`;
  else if (tab === 'orders') body = `<div class="account-heading"><div><p class="eyebrow">PURCHASE HISTORY</p><h2>ORDERS</h2></div></div>${data.orders.length?data.orders.map(orderCard).join(''):`<div class="empty"><h2>NO ORDERS YET</h2><a class="btn" href="/en-ca/collections/makeup-shop-all">START SHOPPING</a></div>`}`;
  else body = `<p class="eyebrow">WELCOME BACK</p><h2>${escapeHtml(state.account.display_name)}</h2><p>${escapeHtml(state.account.email_normalized)}</p><div class="account-dashboard"><a href="/en-ca/account/orders"><span>${data.orders.length}</span><h3>ORDERS</h3><p>Track, cancel, return or reorder.</p></a><a href="/en-ca/account/favorites"><span>${data.favorites.length}</span><h3>SAVED ITEMS</h3><p>See the products you love.</p></a><a href="/en-ca/account/addresses"><span>${data.addresses.length}</span><h3>ADDRESSES</h3><p>Manage delivery details.</p></a></div><section class="account-help"><h3>NEED HELP?</h3><p>Our customer service team is available Monday–Saturday.</p><a href="/en-ca/pages/help-center">VISIT HELP CENTER →</a></section>`;
  main.innerHTML = `<section class="account-page section">${crumbs(['Account'])}<div class="account-title"><h1>ACCOUNT</h1><button class="text-button" data-logout>SIGN OUT</button></div><div class="account-layout">${nav}<div class="account-content">${body}</div></div></section>`;
}

function orderCard(o) {
  return `<article class="order-card source-order-card" data-order="${o.order_id}"><div class="order-head"><div><p class="eyebrow">ORDER ${escapeHtml(o.order_id)}</p><h3>${escapeHtml(o.status)}</h3><p>Placed recently · ${escapeHtml(o.fulfillment)}</p></div><strong>${money.format(o.total)} CAD</strong></div><div class="order-lines">${o.lines.map(l=>`<div class="order-line"><img src="${l.product.image}" alt=""><div><strong>${escapeHtml(l.product.short_name)}</strong><br><small>${escapeHtml(l.variant)} · ${escapeHtml(l.size)} · Qty ${l.quantity}</small></div></div>`).join('')}</div><div class="order-actions"><button class="btn small" data-order-action="reorder" data-order-id="${o.order_id}">REORDER</button><button class="btn outline small" data-order-action="cancel" data-order-id="${o.order_id}" ${o.status==='Cancelled'?'disabled':''}>CANCEL ORDER</button><button class="btn outline small" data-order-action="return" data-order-id="${o.order_id}">START RETURN</button><a class="text-button" href="/en-ca/collections/makeup-shop-all">BACK TO MAKEUP</a></div></article>`;
}

function helpPage(contact=false) {
  const title = contact ? 'CONTACT US' : 'HELP CENTER';
  main.innerHTML = `<section class="help-page section">${crumbs([contact?'Contact Us':'Help Center'])}<div class="help-hero"><p class="eyebrow">WE GOT YOU</p><h1>${title}</h1><p>${contact?'Reach the right team for account, product and order support.':'Find answers about orders, shipping, returns, products and your account.'}</p><label><span>SEARCH HELP</span><input placeholder="What can we help with?"><button aria-label="Search help">→</button></label></div><div class="help-layout"><nav><h2>BROWSE HELP</h2><a href="#orders">Orders + returns</a><a href="#shipping">Shipping</a><a href="#account">Account access</a><a href="#products">Products + shades</a><a href="#contact">Contact us</a></nav><div class="help-content"><details id="orders" open><summary>ORDERS + RETURNS <span>−</span></summary><p>Track, cancel, reorder or start a return from local order history.</p><a href="/en-ca/account/orders">CHECK ORDER STATUS →</a></details><details id="shipping"><summary>SHIPPING INFORMATION <span>+</span></summary><p>Standard and express options appear during checkout. Free standard shipping is available over the displayed threshold.</p></details><details id="account"><summary>ACCOUNT ACCESS <span>+</span></summary><p>Sign in, create an account or preview password recovery without exposing private account data.</p><a href="/en-ca/account/login">ACCOUNT HELP →</a></details><details id="products"><summary>PRODUCT + SHADE HELP <span>+</span></summary><p>Browse makeup, inspect shade families and product availability, or use Ask AI for local catalog guidance.</p><a href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP →</a></details><details id="contact" ${contact?'open':''}><summary>CONTACT CUSTOMER SERVICE <span>${contact?'−':'+'}</span></summary><p>Operating hours are 9am–9pm EST Monday–Friday and 9am–6pm EST Saturday.</p><p><strong>customerservice@fentybeauty.com</strong><br><strong>1-855-440-7474</strong></p><p class="sandbox-note">These source contact details are displayed for reference; this offline clone never sends messages or places calls.</p></details></div></div></section>`;
}

function notFoundPage() {
  main.innerHTML = `<section class="not-found source-not-found" data-testid="not-found"><p class="eyebrow">OOPS!</p><h1>SORRY, BUT THAT PAGE<br>IS NOT A THING</h1><p>Your link might be incorrect, out-of-date, or you may have bookmarked a page that has moved.</p><div class="recovery-links"><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP MAKEUP</a><a class="btn" href="/en-ca/collections/makeup-shop-all?category=Skincare">SHOP SKIN</a><a class="btn" href="/en-ca/collections/makeup-shop-all?category=Body">SHOP BODY</a><a class="btn" href="/en-ca/collections/makeup-shop-all?category=Hair">SHOP HAIR</a></div></section><section class="section not-found-products"><div class="section-head"><h2>BEST SELLERS</h2><a href="/en-ca/collections/makeup-shop-all">SHOP BEST SELLERS →</a></div><div class="home-product-rail" data-home-carousel>${state.catalog.concat(state.catalog.slice(0,3)).map(productCard).join('')}</div><div class="carousel-progress"><span></span></div></section>`;
  window.requestAnimationFrame(() => document.querySelectorAll('[data-home-carousel]').forEach(syncCarouselProgress));
}

function extendedPdpDetails(foundation) {
  const rows = foundation
    ? [['FINISH','Soft matte'],['COVERAGE','Medium to full, buildable'],['SKIN TYPE','Balanced to oily'],['WEAR','Longwear + climate adaptive'],['SHADE RANGE','Multiple depth and undertone families']]
    : [['FINISH','Natural matte'],['COVERAGE','Universally sheer'],['SKIN TYPE','All skin types'],['FORMAT','Refillable compact'],['USE','Set, blur and touch up']];
  const copy = foundation
    ? `<h3>BUILD YOUR COVERAGE</h3><p>Start with a thin layer and blend outward. Add another light layer only where additional coverage is wanted so the finish stays smooth and flexible.</p><h3>WEAR + FINISH</h3><p>The formula is designed to stay comfortable through heat and humidity while managing the look of excess shine. The result is matte, but never flat or mask-like.</p><h3>SHADE APPROACH</h3><p>Depth and undertone work together. Compare the shade on the jaw and allow it to settle before deciding; the right match should visually disappear into the neck and chest.</p><h3>APPLICATION NOTES</h3><p>Prep with lightweight hydration, shake the bottle, then apply one pump with a dense brush or damp sponge. Press and roll over areas where more coverage is needed.</p><p>For a softer everyday finish, use less product through the perimeter of the face. Set only the areas that naturally become shiny.</p>`
    : `<h3>SET WITHOUT THE WEIGHT</h3><p>Use a soft brush to sweep a small amount over makeup, concentrating on the center of the face. The sheer texture is made for touch-ups without creating a heavy powder layer.</p><h3>BLUR + MATTIFY</h3><p>Press the included applicator onto shiny areas, then lift away. Avoid rubbing so makeup underneath remains undisturbed.</p><h3>UNIVERSAL FINISH</h3><p>The powder is designed to remain invisible across skin tones and under flash photography. Apply gradually and build only when needed.</p><h3>REFILLABLE COMPACT</h3><p>Keep the case and replace the inner pan when empty. The portable format is intended for quick, controlled touch-ups throughout the day.</p><p>For the freshest finish, clean applicators regularly and keep the compact closed between uses.</p>`;
  return `${copy}<div class="pdp-detail-facts">${rows.map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join('')}</div><h3>GOOD TO KNOW</h3><p>Use clean tools and apply in light layers. Product performance can vary with skin preparation, climate and the amount applied.</p>`;
}

function sourceProductPage(slug) {
  const p = state.catalog.find(item => item.slug === slug);
  if (!p) return notFoundPage();
  const foundation = p.id === 'foundation';
  const defaultVariant = foundation ? '420' : p.variants[0];
  const hero = foundation ? p.image : '/static/assets/powder-hero.webp';
  const secondary = foundation ? '/static/assets/foundation-before-after.webp' : p.image;
  const media = foundation
    ? [
        [hero, 'Foundation bottle on concrete'],
        [secondary, 'Foundation shade before and after'],
        ['/static/assets/brand-beauty.webp', 'Foundation application detail'],
        ['/static/assets/category-face.avif', 'Foundation complexion look'],
        ['/static/assets/category-tools.webp', 'Foundation tools and shades'],
      ]
    : [
        [hero, 'Invisimatte compact on concrete'],
        [secondary, 'Invisimatte powder texture'],
        ['/static/assets/category-face.avif', 'Invisimatte on skin'],
        ['/static/assets/brand-beauty.webp', 'Fenty Beauty complexion look'],
        ['/static/assets/category-tools.webp', 'Invisimatte application guide'],
      ];
  const variantControls = foundation ? `<div class="choice-label"><strong>SHADE</strong><span id="selected-variant">${escapeHtml(defaultVariant)}</span></div><div class="tone-tabs"><button aria-pressed="true">All</button><button>Light</button><button>Light-Medium</button><button>Medium</button><button>Medium-Deep</button><button>Deep</button></div><div class="variant-grid shade-grid">${p.variants.map((v,i) => `<button class="variant" data-variant="${escapeHtml(v)}" aria-pressed="${v===defaultVariant}" style="--swatch:${shadeColor(v,i)}"><span>${escapeHtml(v)}</span></button>`).join('')}</div><div class="shade-readout"><span style="background:${shadeColor(defaultVariant, Math.max(0,p.variants.indexOf(defaultVariant)))}"></span><strong>#${escapeHtml(defaultVariant)}</strong> — Medium Deep with warm golden undertones</div><div class="shade-tools"><button>● &nbsp; FIND SHADE</button><button>◉ &nbsp; TRY SHADE</button></div>` : `<button class="variant" data-variant="${escapeHtml(defaultVariant)}" aria-pressed="true" hidden>${escapeHtml(defaultVariant)}</button>`;
  const details = foundation ? `<h2>AN INSTANT FILTER THAT'S MATTE BUT NEVER FLAT—GET MAX COVERAGE WITHOUT THE WEIGHT</h2><p><strong>STRAIGHT UP:</strong></p><p>A soft matte, longwear foundation built to resist heat, sweat and shine while keeping coverage comfortable. The buildable formula smooths the look of pores and supports medium-to-full coverage.</p><p><strong>THE LOWDOWN:</strong></p><ul><li>Climate-adaptive wear for heat and humidity</li><li>Soft matte finish without a heavy feel</li><li>Buildable medium-to-full coverage</li><li>Instantly diffuses the look of pores</li><li>Comfortable, non-drying and oil free</li><li>Created across a boundary-breaking shade range</li></ul><p><strong>HOW'D WE DO?</strong></p><p>Fenty Beauty developed the formula around the balance of tone, undertone and texture so it performs across skin types. Apply a thin layer for everyday coverage or build where more coverage is wanted.</p><p>This product is 100% cruelty free. Fill weight: Standard 32 mL / 1.08 oz.</p>` : `<h2>UNIVERSALLY SHEER POWDER TO SET, BLUR + MATTIFY ON THE GO</h2><p><strong>GIVE IT TO ME QUICK:</strong></p><p>This instant mattifier helps blur the look of pores, absorb shine and extend makeup wear while remaining universal across skin tones.</p><p><strong>TELL ME MORE:</strong></p><ul><li>Universal sheer finish for all skin tones</li><li>No flashback or cakiness</li><li>Natural matte finish that extends makeup wear</li><li>Instantly blurs the look of pores</li><li>Comfortable for all skin types</li><li>Refillable, magnet-free packaging</li><li>Designed for touch-ups throughout the day</li></ul><p>Fenty Beauty is 100% cruelty free. Fill weight: Standard 8.5 g / 0.3 oz; Mini 4 g.</p>`;
  main.innerHTML = `<section class="pdp source-pdp" data-product-id="${p.id}"><div class="pdp-gallery"><div class="pdp-thumbs">${media.map(([src,alt],i)=>`<button class="${i===0?'active':''}" data-pdp-media="${src}" aria-label="View image ${i+1}"><img src="${src}" alt="${alt}"></button>`).join('')}</div><div class="pdp-main-image"><img src="${hero}" alt="${escapeHtml(p.name)}"></div></div><div class="pdp-buy">${crumbs([p.name])}<div class="pdp-badges"><span>${escapeHtml(p.badge)}</span>${foundation?'<span>SOFT MATTE</span>':''}</div><h1>${escapeHtml(p.name)}</h1><p class="price">${money.format(p.price)} CAD</p><p class="stars">★★★★★ &nbsp; <u>${p.reviews} Reviews</u></p><p class="pdp-description">${escapeHtml(p.description)}</p>${foundation?'<p>This hall of famer is retiring—stock up before it leaves for good.</p>':''}${variantControls}<h2 class="choice-title">SIZE</h2><div class="size-grid">${p.sizes.map((s,i) => `<button class="size" data-size="${escapeHtml(s)}" aria-pressed="${i===0}"><strong>${escapeHtml(s)}</strong><small>${i===0?money.format(p.price)+' CAD':'Alternate size'}</small></button>`).join('')}</div><div class="pdp-action-row"><div class="quantity"><button data-qty="-1" aria-label="Decrease quantity">−</button><input id="product-quantity" value="1" inputmode="numeric" aria-label="Quantity"><button data-qty="1" aria-label="Increase quantity">+</button></div><button class="btn add-bag" data-add-cart="${p.id}" data-testid="add-to-bag">ADD TO BAG</button><button class="btn outline save-pdp" data-favorite="${p.id}" aria-label="Save to favorites">♡</button></div><div id="product-error"></div><div class="pdp-ai"><span>✦</span><input aria-label="Ask anything" placeholder="Ask anything"><button aria-label="Send question">→</button></div><section class="pairing"><h2>${foundation?'PREP SKIN FOR MAKEUP':'DESIGNED TO BE USED WITH'}</h2><div><img src="/static/assets/starter.webp" alt="Fenty Skin moisturizer"><p>Hydra Vizor Invisible Moisturizer Broad Spectrum SPF 30<br><strong>From $53.00 CAD</strong></p><button class="btn outline small">ADD TO BAG</button></div></section>${foundation?'':`<a class="pdp-inline-promo" href="/en-ca/collections/makeup-shop-all"><img src="/static/assets/catalog-banner.webp" alt="Free Gloss Bomb Heat sample offer"></a>`}<div class="pdp-accordions source-detail-stack"><details open><summary>DETAILS <span>−</span></summary><div class="pdp-source-copy">${details}</div></details><details><summary>INGREDIENTS <span>+</span></summary><p>View the product packaging for the current complete ingredient list.</p></details>${foundation?'<details><summary>HOW TO <span>+</span></summary><p>Start with one pump, blend from the center of the face outward and build only where needed.</p></details>':''}<details><summary>RIHANNA'S INSPO <span>+</span></summary><p>Performance-driven complexion essentials made for every skin tone and type.</p></details></div></div></section><section class="section pdp-recommendations"><div class="section-head"><h2>HANDPICKED FOR YOU</h2>${carouselControls('pdp-recs')}</div><div class="home-product-rail" id="pdp-recs" data-home-carousel>${state.catalog.filter(x=>x.id!==p.id).concat(state.catalog.slice(0,3)).map(productCard).join('')}</div><div class="carousel-progress"><span></span></div></section><section class="pdp-howto"><h2>${foundation?'FACE LOOKIN’ FRESH MORNING + NIGHT':'HEAVY ON THE HYDRATION'}</h2><p>${foundation?'We’re breaking down your base routine for a soft matte finish.':'Make a splash in juicy makeup, skincare + haircare must-haves.'}</p><div>${['PREP SKIN','PRIME','USE A BRUSH','APPLY + PERFECT'].map((label,i)=>`<article><img src="${i%2?secondary:'/static/assets/brand-skin.webp'}" alt="${label}"><h3>${label}</h3><p>${i===0?'Start with hydrated skin.':'Use thin layers and blend for a seamless finish.'}</p></article>`).join('')}</div></section><section class="section pdp-faq"><h2>FREQUENTLY ASKED QUESTIONS</h2><details open><summary>How do I choose my match?<span>−</span></summary><p>Use the shade families above, then select the closest undertone and depth.</p></details><details><summary>Can I change the size?<span>+</span></summary><p>Select any available size before adding to bag.</p></details><details><summary>Is it cruelty free?<span>+</span></summary><p>Fenty Beauty is 100% cruelty free.</p></details></section>`;
  document.querySelector('.pdp-source-copy')?.insertAdjacentHTML('beforeend', extendedPdpDetails(foundation));
  window.requestAnimationFrame(() => document.querySelectorAll('[data-home-carousel]').forEach(syncCarouselProgress));
}

function drawerCartLine(item) {
  const p = item.product;
  return `<article class="drawer-cart-line" data-cart-line="${p.id}"><img src="${p.image}" alt="${escapeHtml(p.short_name)}"><div><p class="eyebrow">${escapeHtml(p.badge)}</p><h3>${escapeHtml(p.short_name)}</h3><p>${escapeHtml(p.variant_label)}: <strong>${escapeHtml(item.variant)}</strong></p><p>${escapeHtml(item.size)}</p><div class="drawer-line-actions"><label>QTY <select data-cart-qty="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">${[1,2,3,4,5].map(n=>`<option ${n===item.quantity?'selected':''}>${n}</option>`).join('')}</select></label><button class="text-button" data-cart-remove="${p.id}" data-variant="${escapeHtml(item.variant)}" data-size="${escapeHtml(item.size)}">REMOVE</button></div></div><strong>${money.format(item.line_total)} CAD</strong></article>`;
}

function renderCartDrawer() {
  const container = document.querySelector('#cart-drawer-content');
  if (!container) return;
  const active = (state.cart?.items || []).filter(item => !item.removed);
  const remaining = Math.max(0, 100 - (state.cart?.subtotal || 0));
  container.innerHTML = `<div class="cart-drawer-head"><h2>MY BAG <span>(${state.cart?.count || 0})</span></h2><button type="button" data-action="close-cart" aria-label="Close My Bag">×</button></div><div class="drawer-shipping"><strong>${remaining ? `${money.format(remaining)} AWAY FROM FREE STANDARD SHIPPING` : 'YOU QUALIFY FOR FREE STANDARD SHIPPING'}</strong><span><i style="width:${Math.min(100,state.cart?.subtotal || 0)}%"></i></span></div><div class="cart-drawer-body">${active.length ? active.map(drawerCartLine).join('') : `<div class="drawer-empty"><h3>YOUR BAG IS EMPTY</h3><p>Fill it with your new Fenty favorites.</p><a class="btn" href="/en-ca/collections/makeup-shop-all">SHOP BESTSELLERS</a></div>`}</div>${active.length ? `<div class="cart-drawer-foot"><div><span>SUBTOTAL</span><strong>${money.format(state.cart.subtotal || 0)} CAD</strong></div><p>Shipping and taxes calculated at checkout.</p><a class="btn" href="/en-ca/checkout">CHECKOUT</a><a href="/en-ca/cart"><u>VIEW MY BAG</u></a></div>` : ''}`;
}

function setCartDrawer(open) {
  const drawer = document.querySelector('#cart-drawer');
  const scrim = document.querySelector('#cart-scrim');
  if (!drawer || !scrim) return;
  if (open) renderCartDrawer();
  drawer.classList.toggle('open', open);
  scrim.classList.toggle('open', open);
  drawer.setAttribute('aria-hidden', String(!open));
  document.body.classList.toggle('cart-open', open);
  if (open) window.requestAnimationFrame(() => drawer.querySelector('[data-action="close-cart"]')?.focus());
}

function refreshCartSurfaces() {
  updateHeader();
  if (document.querySelector('#cart-drawer')?.classList.contains('open')) renderCartDrawer();
  if (location.pathname === '/en-ca/cart') cartPage();
}

async function render() {
  const path = location.pathname.replace(/\/$/, '') || '/';
  const params = new URLSearchParams(location.search);
  window.FentyHome.setActive(path === '/' || path === '/en-ca');
  document.title = 'Fenty Beauty by Rihanna | Beauty for All';
  try {
    if (path === '/' || path === '/en-ca') await homePage();
    else if (path === '/en-ca/collections/makeup-shop-all') await collectionPage(params);
    else if (path === '/en-ca/search') await searchPage(params);
    else if (path.startsWith('/en-ca/products/')) sourceProductPage(path.split('/').pop());
    else if (path === '/en-ca/cart') cartPage();
    else if (path === '/en-ca/checkout') await checkoutPage();
    else if (path === '/en-ca/account/login') authPage('login');
    else if (path === '/en-ca/account/register') authPage('register');
    else if (path === '/en-ca/account/recover') authPage('recover');
    else if (path === '/en-ca/account') accountPage('overview');
    else if (path === '/en-ca/account/favorites') accountPage('favorites');
    else if (path === '/en-ca/account/addresses') accountPage('addresses');
    else if (path === '/en-ca/account/orders') accountPage('orders');
    else if (path === '/en-ca/pages/help-center') helpPage();
    else if (path === '/en-ca/pages/contact-us') helpPage(true);
    else notFoundPage();
  } catch (error) {
    main.innerHTML = `<section class="section"><div class="error"><h1>Unable to load this view</h1><p>${escapeHtml(error.message)}</p><button class="btn" data-retry>TRY AGAIN</button></div></section>`;
  }
  // Only pull focus into the view on client-side navigation. Doing it on the
  // first render would strand the skip link, which sits before <main> in the DOM.
  if (render.navigated) main.focus({preventScroll:true});
  render.navigated = false;
}

document.addEventListener('click', async event => {
  const cartTrigger = event.target.closest('[data-action="open-cart"]');
  if (cartTrigger) { event.preventDefault(); setCartDrawer(true); return; }
  if (event.target.closest('[data-action="close-cart"]')) { setCartDrawer(false); return; }
  const anchor = event.target.closest('a[href]');
  if (anchor && anchor.origin === location.origin && !anchor.hasAttribute('download')) { event.preventDefault(); navigate(anchor.pathname + anchor.search + anchor.hash); return; }
  if (event.target.closest('[data-action="ask-ai"]')) { document.querySelector('#ask-ai-panel').hidden = false; return; }
  if (event.target.closest('[data-action="close-ask-ai"]')) { document.querySelector('#ask-ai-panel').hidden = true; return; }
  const carouselMove = event.target.closest('[data-carousel-move]');
  if (carouselMove) {
    const rail = document.querySelector(`#${carouselMove.dataset.carouselTarget}`);
    if (rail) rail.scrollBy({left: Number(carouselMove.dataset.carouselMove) * rail.clientWidth * 0.9, behavior: 'smooth'});
    return;
  }
  const menuToggle = event.target.closest('[data-action="toggle-menu"]');
  if (menuToggle) { setMobileMenu(menuToggle.getAttribute('aria-expanded') !== 'true'); return; }
  if (event.target.closest('[data-action="close-menu"]')) { setMobileMenu(false); return; }
  if (event.target.closest('[data-retry]')) { render(); return; }
  const mediaThumb = event.target.closest('[data-pdp-media]');
  if (mediaThumb) {
    const mainImage = document.querySelector('.pdp-main-image img');
    if (mainImage) { mainImage.src = mediaThumb.dataset.pdpMedia; mainImage.alt = mediaThumb.querySelector('img')?.alt || mainImage.alt; }
    document.querySelectorAll('[data-pdp-media]').forEach(node => node.classList.toggle('active', node === mediaThumb));
    return;
  }
  const variant = event.target.closest('[data-variant].variant');
  if (variant) { document.querySelectorAll('.variant').forEach(x=>x.setAttribute('aria-pressed','false')); variant.setAttribute('aria-pressed','true'); document.querySelector('#selected-variant').textContent=variant.dataset.variant; return; }
  const size = event.target.closest('[data-size].size');
  if (size) { document.querySelectorAll('.size').forEach(x=>x.setAttribute('aria-pressed','false')); size.setAttribute('aria-pressed','true'); return; }
  const qty = event.target.closest('[data-qty]');
  if (qty) { const input=document.querySelector('#product-quantity'); input.value=Math.max(1,Math.min(5,Number(input.value||1)+Number(qty.dataset.qty))); return; }
  const add = event.target.closest('[data-add-cart]');
  if (add) {
    const variantNode=document.querySelector('.variant[aria-pressed="true"]'), sizeNode=document.querySelector('.size[aria-pressed="true"]');
    if (!variantNode || !sizeNode) { document.querySelector('#product-error').innerHTML='<p class="error">Choose a variant and size before continuing.</p>'; return; }
    try { state.cart=await api('/api/cart/add',{method:'POST',body:JSON.stringify({product_id:add.dataset.addCart,variant:variantNode.dataset.variant,size:sizeNode.dataset.size,quantity:Number(document.querySelector('#product-quantity').value)})}); refreshCartSurfaces(); setCartDrawer(true); toast('Added to bag'); }
    catch(error){document.querySelector('#product-error').innerHTML=`<p class="error">${escapeHtml(error.message)}</p>`;} return;
  }
  const favorite = event.target.closest('[data-favorite]');
  if (favorite) { try { const value=await api('/api/favorites/toggle',{method:'POST',body:JSON.stringify({product_id:favorite.dataset.favorite})}); if(state.accountData)state.accountData.favorites=value.favorites; toast(value.saved?'Saved to favorites':'Removed from favorites'); } catch(error){ if(error.status===401)navigate('/en-ca/account/login'); else toast(error.message); } return; }
  const remove=event.target.closest('[data-cart-remove]'), restore=event.target.closest('[data-cart-restore]');
  if (remove||restore) { const node=remove||restore; state.cart=await api('/api/cart/update',{method:'POST',body:JSON.stringify({product_id:remove?remove.dataset.cartRemove:restore.dataset.cartRestore,variant:node.dataset.variant,size:node.dataset.size,removed:Boolean(remove)})}); refreshCartSurfaces(); toast(remove?'Item removed':'Item restored'); return; }
  const applyPromo=event.target.closest('[data-apply-promo]');
  if(applyPromo){const promo=new FormData(document.querySelector('#checkout-form')).get('promo');try{const p=await api('/api/checkout/preview',{method:'POST',body:JSON.stringify({promo})});document.querySelector('#checkout-review').innerHTML=checkoutSummary(p);toast(p.discount?'Promo applied':'Promo not recognized');}catch(e){toast(e.message);}return;}
  const logout=event.target.closest('[data-logout]');
  if(logout){await api('/api/auth/logout',{method:'POST',body:'{}'});await refresh();navigate('/en-ca');toast('Signed out');return;}
  const orderAction=event.target.closest('[data-order-action]');
  if(orderAction){try{const value=await api(`/api/orders/${orderAction.dataset.orderId}/${orderAction.dataset.orderAction}`,{method:'POST',body:'{}'});state.accountData.orders=value.orders;state.cart=value.cart;updateHeader();accountPage('orders');toast('Order updated');}catch(e){toast(e.message);}return;}
});

document.addEventListener('change', async event => {
  const qty = event.target.closest('[data-cart-qty]');
  if (qty) { state.cart=await api('/api/cart/update',{method:'POST',body:JSON.stringify({product_id:qty.dataset.cartQty,variant:qty.dataset.variant,size:qty.dataset.size,quantity:Number(qty.value)})});refreshCartSurfaces(); }
});

document.addEventListener('scroll', event => {
  const rail = event.target.closest?.('[data-home-carousel]');
  if (rail) syncCarouselProgress(rail);
}, true);

document.addEventListener('submit', async event => {
  event.preventDefault();
  const form=event.target;
  if(form.id==='catalog-filters'){const data=new FormData(form);navigate(`/en-ca/collections/makeup-shop-all?${new URLSearchParams(data).toString()}`);return;}
  if(form.id==='search-form'){const data=new FormData(form);navigate(`/en-ca/search?q=${encodeURIComponent(data.get('q'))}`);return;}
  if(form.id==='auth-form'){
    const kind=form.dataset.authKind, data=Object.fromEntries(new FormData(form)); const box=document.querySelector('#auth-error');
    if(!form.checkValidity()){box.innerHTML='<p class="error">Complete all required fields before continuing.</p>';form.reportValidity();return;}
    try{if(kind==='recover'){const v=await api('/api/auth/recovery-preview',{method:'POST',body:JSON.stringify(data)});box.innerHTML=`<p class="success">${escapeHtml(v.message)} <a href="${v.return_path}"><u>Return to sign in</u></a>.</p>`;return;}await api(kind==='register'?'/api/auth/register':'/api/auth/login',{method:'POST',body:JSON.stringify(data)});await refresh();navigate('/en-ca/account');toast(kind==='register'?'Account created':'Signed in');}catch(e){box.innerHTML=`<p class="error">${escapeHtml(e.message)}</p>`;}return;
  }
  if(form.id==='address-form'){const box=document.querySelector('#address-error');if(!form.checkValidity()){box.innerHTML='<p class="error">Complete every required field.</p>';form.reportValidity();return;}try{state.accountData=await api('/api/account/address',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});accountPage('addresses');toast('Address saved');}catch(e){box.innerHTML=`<p class="error">${escapeHtml(e.message)}</p>`;}return;}
  if(form.id==='checkout-form'){const box=document.querySelector('#checkout-error');if(!form.checkValidity()){box.innerHTML='<p class="error">Complete the required contact and delivery fields before review.</p>';form.reportValidity();return;}const data=Object.fromEntries(new FormData(form));const p=await api('/api/checkout/preview',{method:'POST',body:JSON.stringify({promo:data.promo})});document.querySelector('#checkout-review').innerHTML=checkoutSummary(p)+`<div class="notice"><strong>Ready for final review.</strong><br>${escapeHtml(data.fulfillment)}<br>Payment: ${escapeHtml(data.payment)}. No real order has been placed.</div>`;toast('Order review is ready');document.querySelector('#checkout-review').scrollIntoView({behavior:'smooth'});}
});

window.addEventListener('popstate', render);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.querySelector('#cart-drawer')?.classList.contains('open')) {
    setCartDrawer(false);
    document.querySelector('[data-action="open-cart"]')?.focus();
    return;
  }
  if (event.key === 'Escape' && document.querySelector('#primary-nav')?.classList.contains('open')) {
    setMobileMenu(false);
    document.querySelector('[data-action="toggle-menu"]')?.focus();
  }
});
refresh().then(render).catch(error => { main.innerHTML=`<section class="section"><div class="error"><h1>Unable to start offline store</h1><p>${escapeHtml(error.message)}</p></div></section>`; });
