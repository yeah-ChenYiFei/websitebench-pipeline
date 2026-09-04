/* Homepage campaign captured from the US storefront on 2026-09-04. */
window.FentyHome = (() => {
  let data;
  let original;
  let active = false;
  let observer;
  let dialog;
  let returnFocus;
  const saved = new Set(JSON.parse(localStorage.getItem('fenty-home-saved') || '[]'));
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const catalog = '/en-ca/collections/makeup-shop-all';
  const skin = `${catalog}?category=Skincare`;
  const lip = `${catalog}?category=Lip%20Makeup`;
  const foundationId = '15135168430125';
  const picture = (item, alt, className = '') => `<picture class="${className}">${item.mobile ? `<source media="(max-width:767px)" srcset="${item.mobile}">` : ''}<img src="${item.desktop}" alt="${esc(alt)}" loading="lazy" decoding="async"></picture>`;
  const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">${{
    account:'<circle cx="12" cy="7" r="3.4"/><path d="M5 21v-3a7 7 0 0 1 14 0v3Z"/>',
    search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    heart:'<path d="M12 21S2 15 2 8a5 5 0 0 1 10-1A5 5 0 0 1 22 8c0 7-10 13-10 13Z"/>',
    bag:'<path d="M5 7h14l-1 14H6Z"/><path d="M9 10V6a3 3 0 0 1 6 0v4"/>',
    arrow:'<path d="M3 12h18m-7-7 7 7-7 7"/>'
  }[name]}</svg>`;

  function closeDialog() {
    if (!dialog?.open) return;
    dialog.querySelectorAll('video').forEach(v => v.pause());
    dialog.close();
    returnFocus?.focus();
  }

  function showDialog(title, content) {
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'fh-dialog';
      document.body.append(dialog);
      dialog.addEventListener('click', e => { if (e.target === dialog) closeDialog(); });
      dialog.addEventListener('close', () => dialog.querySelectorAll('video').forEach(v => v.pause()));
    }
    returnFocus = document.activeElement;
    dialog.innerHTML = `<button class="fh-dialog-close" data-home-close aria-label="Close dialog">×</button><h2 id="fh-dialog-title">${esc(title)}</h2>${content}`;
    dialog.setAttribute('aria-labelledby', 'fh-dialog-title');
    if (!dialog.open) dialog.showModal();
  }

  function openProduct(id) {
    const p = data.products[id];
    if (!p) return;
    location.assign(p.sourcePath);
  }

  function rating(p) {
    if (!p.rating) return '';
    const value = parseFloat(p.rating);
    return `<div class="fh-rating" role="img" aria-label="${esc(p.rating)}"><span aria-hidden="true">☆☆☆☆☆</span><span aria-hidden="true" style="width:${value * 20}%">★★★★★</span></div>`;
  }

  function productCard(p) {
    return `<article class="fh-product" data-source-product="${p.id}"><div class="fh-product-media"><button class="fh-product-image" data-home-product="${p.id}" aria-label="View ${esc(p.name)}"><img src="${p.image}" alt="${esc(p.name)}" loading="lazy" decoding="async">${p.hoverImage ? `<img class="fh-hover-image" src="${p.hoverImage}" alt="" loading="lazy" decoding="async">` : ''}</button>${p.badge ? `<span class="fh-badge">${esc(p.badge)}</span>` : ''}<button class="fh-save" data-home-save="${p.id}" aria-label="Save ${esc(p.name)}" aria-pressed="${saved.has(p.id)}">${icon('heart')}</button><button class="fh-quick-button" data-home-product="${p.id}">QUICK SHOP</button></div><div class="fh-product-copy"><h3><button data-home-product="${p.id}">${esc(p.name)}</button></h3>${rating(p)}${p.details.length ? `<p class="fh-product-options">${esc(p.details.join(' · ')).replace(/(\d+ (?:Shades|Sizes))/g, '<u>$1</u>')}</p>` : ''}<p>${esc(p.price)}${p.id === '7990498394157' ? ' <span class="fh-value">($82.00 Value)</span>' : ''}</p></div></article>`;
  }

  const controls = id => `<div class="fh-arrows"><button data-home-scroll="-1" data-rail="${id}" aria-label="Previous items">←</button><button data-home-scroll="1" data-rail="${id}" aria-label="Next items">→</button></div>`;
  function products(title, subtitle, ids, id, promo = '') {
    return `<section class="fh-products" aria-labelledby="${id}-heading" data-home-section="${id}"><div class="fh-heading"><div><h2 id="${id}-heading">${title}</h2><p>${subtitle}</p></div>${controls(id)}</div><div class="fh-product-rail" id="${id}" data-home-carousel>${promo}${ids.map(id => productCard(data.products[id])).join('')}</div><div class="carousel-progress" aria-hidden="true"><span></span></div></section>`;
  }

  function footer() {
    const help = '/en-ca/pages/help-center';
    return `<section class="fh-signup"><h2>DOWN FOR MORE? WE GOT YOU!</h2><p>The latest product drops, offers, in-store event info + more—straight to your inbox.</p><form data-home-subscribe="email"><label class="fh-sr" for="fh-email">Email address</label><input id="fh-email" name="email" type="email" placeholder="Email address" required autocomplete="email"><button aria-label="Submit email preview">${icon('arrow')}</button></form><form data-home-subscribe="phone"><label class="fh-sr" for="fh-phone">Phone number</label><input id="fh-phone" name="phone" type="tel" placeholder="Phone number" required pattern="[+()0-9 .-]{7,20}" autocomplete="tel"><button aria-label="Submit phone preview">${icon('arrow')}</button></form><p class="fh-consent">By subscribing to Fenty Beauty &amp; Fenty Skin you consent to receive recurring automated promotional and personalized marketing messages (e.g. cart reminders) via automated technology including email and text messages. Consent is not a condition of any purchase. View Terms of Use &amp; Privacy Policy. Message and data rates may apply. Reply HELP for help or STOP to opt-out.</p><p class="fh-subscribe-result" role="status"></p><div class="fh-footer-logo"><svg fill="white" style="width:60%;height:auto;display:block" id="Layer_1" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 285.65 15.79"><path d="m201.03,8.67l1.67-4.58,1.64,4.58h-3.32Zm5.74,6.72l.05.15h3.03l-5.64-15.22-.11-.32h-2.69l-5.75,15.24-.11.3h2.97l1.56-4.24h5.22l1.48,4.09Zm-23.67-2.55h-8.63v-4.07h7.79v-2.67h-7.79v-3.44h8.63V0h-11.38v15.54h11.38v-2.69Zm-30.52,0h-4.14v-4.07h4.07c1.51,0,2.25.67,2.25,2.04,0,1.25-.84,2.03-2.18,2.03m-4.14-10.18h4.01c1.32,0,1.91.53,1.91,1.72,0,1.59-1.42,1.72-1.85,1.72h-4.07v-3.44Zm7.33,4.63c.84-.72,1.34-1.78,1.34-2.89,0-2.68-1.83-4.41-4.66-4.41h-6.76v15.54h6.8c2.95,0,5.02-1.95,5.02-4.74,0-1.56-.61-2.78-1.74-3.49m76.46,2.53c0,2.02-1.27,3.27-3.32,3.27s-3.34-1.29-3.34-3.27V0h-2.73v9.82c0,3.51,2.49,5.96,6.07,5.96s6.07-2.45,6.07-5.96V0h-2.75v9.82Zm16.19-7.16h4.58v12.87h2.75V2.67h4.58V0h-11.91v2.67Zm34.05-2.67l-3.63,6.16-3.49-5.93-.14-.24h-3.2l5.44,8.89v6.64h2.75v-6.64l5.44-8.89h-3.18ZM53.23,10.71V0h-2.73v15.54h2.72l7.08-10.73v10.73h2.75V0h-2.74l-7.09,10.71Zm23.53-8.04h4.58v12.87h2.75V2.67h4.57V0h-11.9v2.67ZM0,15.54h2.75v-6.8h7.3v-2.63H2.75v-3.44h8.14V0H0v15.54Zm24.88,0h11.38v-2.69h-8.63v-4.07h7.79v-2.67h-7.79v-3.44h8.63V0h-11.38v15.54Zm80.92,0h2.75v-6.64l5.44-8.89h-3.18l-3.63,6.16-3.48-5.93-.14-.24h-3.2l5.44,8.89v6.64Z"></path></svg></div></section><div class="fh-footer-right"><div class="fh-footer-columns"><section><h2>CUSTOMER SERVICE</h2><p>Operating hours are from 9am–9pm EST Monday-Friday and 9am–6pm EST Saturday. Reach out today!</p><p>customerservice@fentybeauty.com</p><p>1-855-440-7474</p>${[['Order Status','/en-ca/account/orders'],['Shipping Information',help],['Returns','/en-ca/account/orders'],['Contact Us','/en-ca/pages/contact-us'],['Help & FAQs',help],['My Account','/en-ca/account'],['Gift Card Balance',help]].map(([label,url]) => `<a href="${url}">${label}</a>`).join('')}</section><section><h2>ABOUT</h2><p>Rihanna was inspired to create the world of Fenty Beauty brands after years of partnering with the best of the best in the beauty industry—and still seeing a void for products that performed across all skin tones + types and hair textures.</p><a href="/en-ca#fenty-brands">About the Brands</a><a href="${help}">Clara Lionel Foundation</a><a href="${help}">Careers</a></section><figure><img src="/static/assets/footer-rihanna.webp" alt="Rihanna" loading="lazy"></figure></div><div class="fh-footer-social" aria-label="Social media">${[['TikTok','tiktok','https://www.tiktok.com/@fentybeauty'],['Instagram','instagram','https://www.instagram.com/fentybeauty'],['Facebook','facebook','https://www.facebook.com/fentybeauty'],['Twitter','twitter','https://twitter.com/fentybeauty'],['YouTube','youtube','https://www.youtube.com/c/fentybeauty']].map(([name,id,url])=>`<a href="${url}" target="_blank" rel="noopener noreferrer" aria-label="${name}"><svg aria-hidden="true"><use href="/static/assets/home-20260904/source-icons.svg#icon-${id}"></use></svg></a>`).join('')}</div><div class="fh-footer-bottom"><button data-home-region>🇺🇸 United States | English⌄</button><nav aria-label="Policies">${['Privacy','Terms of Use','Refund Policy','CA Supply Chain Act','Canadian Modern Slavery Report','Accessibility','Do Not Sell or Share My Personal Information'].map(x=>`<a href="${help}">${x}</a>`).join('')}</nav></div></div>`;
  }

  function setActive(value) {
    if (!original) {
      original = {region:document.querySelector('.region').innerHTML,promo:document.querySelector('.promo').innerHTML,footer:document.querySelector('.footer').innerHTML};
    }
    if (active === value) return;
    active = value;
    closeDialog();
    observer?.disconnect();
    document.body.classList.toggle('home-view', active);
    document.documentElement.lang = active ? 'en-US' : 'en-CA';
    const region = document.querySelector('.region');
    region.innerHTML = active ? '🇺🇸 United States | English' : original.region;
    region.toggleAttribute('data-home-region', active);
    document.querySelector('.promo').innerHTML = active ? `Try award winners! Free body + lip gifts on $75+ orders. | <a href="${catalog}">SHOP NOW</a> | <a href="/en-ca/pages/help-center">TERMS</a>` : original.promo;
    document.querySelector('.footer').innerHTML = active ? footer() : original.footer;
    document.querySelector('.primary-nav .fh-ask')?.remove();
    if (active) {
      document.querySelector('.primary-nav').insertAdjacentHTML('beforeend','<button class="fh-ask" data-action="ask-ai">✦ &nbsp; Ask AI</button>');
      document.querySelector('.mobile-tools').insertAdjacentHTML('afterbegin','<button class="mobile-menu fh-menu-toggle" data-action="toggle-menu" aria-label="Open menu" aria-expanded="false" aria-controls="primary-nav">☰</button>');
      document.querySelector('.site-header').insertAdjacentHTML('afterend','<button id="nav-scrim" class="nav-scrim fh-nav-scrim" data-action="close-menu" aria-label="Close menu"></button>');
    } else {
      setMobileMenu(false);
      document.querySelector('.fh-menu-toggle')?.remove();
      document.querySelector('.fh-nav-scrim')?.remove();
    }
    // Keep the existing bag/count nodes and event handlers intact.
    document.querySelectorAll('.utilities a').forEach((a,i) => {
      if (active && !a.dataset.homeOriginal) {
        a.dataset.homeOriginal = a.innerHTML;
        const count = a.querySelector('#cart-count');
        const label = a.querySelector('span');
        a.innerHTML = icon(['account','search','heart','bag'][i]);
        if (label) a.append(label);
        if (count) a.append(count);
      } else if (!active && a.dataset.homeOriginal) {
        const count = a.querySelector('#cart-count');
        a.innerHTML = a.dataset.homeOriginal;
        if (count) a.querySelector('#cart-count').replaceWith(count);
        delete a.dataset.homeOriginal;
      }
    });
  }

  async function renderHome() {
    data ||= await fetch('/static/home-data.json?v=20260904').then(r => { if (!r.ok) throw new Error('Homepage content could not load.'); return r.json(); });
    if (!active) return;
    const promo = `<article class="fh-lip-promo">${picture(data.lipPromo,'Free Butta Drop and Gloss Bomb deluxe samples')}<div><h3>FREE GIFTS</h3><p>Exclusive Butta Drop + Gloss Bomb deluxe samples on $75+ orders.</p><a class="fh-button dark" href="${catalog}">SHOP NOW</a></div></article>`;
    document.querySelector('#main').innerHTML = `<section class="fh-hero" data-home-section="hero" aria-label="Fluid Flex Foundation campaign"><video id="fh-hero-video" poster="/static/assets/home-20260904/hero-reference.jpg" muted loop playsinline preload="metadata" aria-label="Pro Filt’r Fluid Flex campaign film"><source src="${data.hero.mobile}" media="(max-width:640px)" type="video/mp4"><source src="${data.hero.desktop}" type="video/mp4"></video><div class="fh-hero-copy"><p class="fh-eyebrow">NEW</p><h1>PRO FILT'R FLUID FLEX FOUNDATION</h1><p>Made to move with you.</p><button class="fh-button" data-home-product="${foundationId}">SHOP NOW</button></div><button class="fh-video-toggle" data-home-hero aria-label="Pause campaign video">Ⅱ</button></section>
      <section class="fh-shade" data-home-section="shade-finder">${picture(data.shade,'Find your Fluid Flex shade')}<div><h2>PRO FILT'R FLUID FLEX FOUNDATION</h2><p>DISCOVER YOUR PERFECT MATCH WITH OUR SHADE FINDER TOOL</p><button class="fh-button" data-home-product="${foundationId}">FIND YOUR SHADE</button></div></section>
      ${products('FOREVER FAVES','The award winners + bestsellers you can’t get enough of.',data.forever,'forever-faves')}
      <section class="fh-emotion" data-home-section="emotion"><div class="fh-emotion-heading"><h2>BENDS + STRETCHES TO EVERY (E)MOTION</h2><p>Pro Filt'r Fluid Flex Foundation</p><button class="fh-text-button" data-home-product="${foundationId}">SHOP NOW</button></div><div class="fh-mosaic">${data.lookbook.map((src,i)=>`<button class="fh-emotion-${i}" data-home-look="${i}" aria-label="View ${i===2?'Fluid Flex Foundation':'Rihanna wearing Fluid Flex 386W'}"><img src="${src}" alt="${i===2?'Fluid Flex Foundation':'Rihanna wearing Fluid Flex 386W'}" loading="lazy"></button>`).join('')}</div><p class="fh-emotion-caption">MADE TO MOVE WITH YOU</p></section>
      <section class="fh-routine" data-home-section="routine"><div class="fh-heading"><div><h2>MEET YOUR NEW ROUTINE</h2><p>Go-to steps for a smooth finish, every time.</p></div></div><div class="fh-steps">${data.routine.map((step,i)=>`<article class="fh-step ${i===0?'is-active':''}" data-step="${i}">${picture(step,step.title)}<h3>${esc(step.label)}</h3><button class="fh-step-toggle" data-home-step="${i}" aria-label="${esc(step.label)}" aria-expanded="${i===0}" aria-controls="fh-step-copy-${i}"></button><div class="fh-step-copy" id="fh-step-copy-${i}" ${i===0?'':'inert'}><p class="fh-eyebrow">${esc(step.step)}</p><h4>${esc(step.title)}</h4><p>${esc(step.description)}</p>${i===3?`<button class="fh-button" data-home-product="${foundationId}">SHOP NOW</button>`:`<a class="fh-button" href="${i<3?skin:i===5?'/en-ca/products/invisimatte-instant-setting-blotting-powder':catalog+'?category=Prime%20%2B%20Set'}">SHOP NOW</a>`}</div></article>`).join('')}</div></section>
      <section class="fh-seamless" data-home-section="seamless">${picture(data.seamless,'Fluid Flex Foundation: create a seamless base')}<div><h2>CREATE A SEAMLESS BASE</h2><p>Prep skin for Pro Filt'r Fluid Flex with Fenty Skin bestsellers.</p><a class="fh-text-button" href="${skin}">SHOP SKINCARE</a></div></section>
      ${products('ICONIC PICKS FOR BOMB LIPS',"There's a Gloss Bomb for everyone—explore bestsellers, lip-loving formulas + poppin’ shades.",data.lips,'bomb-lips',promo)}
      <section class="fh-creators" data-home-section="creators" aria-label="Shop creator videos"><div class="fh-creator-rail" id="creator-videos">${(data.creators||[]).map((c,i)=>`<article class="fh-creator ${i===4?'is-center':''}" data-creator="${i}"><button class="fh-creator-play" data-home-video="${i}" aria-label="Play ${esc(c.title)}"><video muted loop playsinline preload="none" poster="${c.poster}" data-src="${c.video}"></video></button><button class="fh-creator-mute" data-home-mute="${i}" aria-label="Unmute video">⌁</button><button class="fh-creator-product" data-home-product="${c.productId}"><img src="${c.productImage}" alt=""><span>${esc(c.productName)}<small>${esc(c.price)}</small></span><b>+</b></button></article>`).join('')}</div>${controls('creator-videos')}</section>
      <section class="fh-brands" data-home-section="brands" id="fenty-brands"><div class="fh-heading"><div><h2>THE FENTY BEAUTY BRANDS</h2><p>Rihanna's vision of haircare, makeup, skincare + fragrance for all.</p></div></div><div class="fh-brand-rail">${['FENTY BEAUTY','FENTY SKIN','FENTY HAIR','FENTY FRAGRANCE'].map((name,i)=>`<a href="${[catalog,skin,catalog+'?category=Hair',catalog+'?category=Fragrance'][i]}"><img src="${data.brands[i]}" alt="${name}" loading="lazy"><strong>${name}</strong></a>`).join('')}</div></section>`;
    const hero = document.querySelector('#fh-hero-video');
    const comparable = new URLSearchParams(location.search).get('home-reference') === '1';
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!comparable && !reduced) {
      hero.addEventListener('loadedmetadata', () => { hero.currentTime = Math.min(14, hero.duration - .1); hero.play().catch(()=>{}); }, {once:true});
    } else document.querySelector('[data-home-hero]').setAttribute('aria-label','Play campaign video');
    observer = new IntersectionObserver(entries => entries.forEach(entry => {
      const video = entry.target;
      if (entry.isIntersecting && !comparable && !reduced) { if (!video.src) video.src = video.dataset.src; video.play().catch(()=>{}); }
      else video.pause();
    }), {threshold:.25});
    document.querySelectorAll('.fh-creator video').forEach(v=>observer.observe(v));
    document.querySelectorAll('[data-home-carousel]').forEach(syncCarouselProgress);
    requestAnimationFrame(() => {
      const rail = document.querySelector('#creator-videos');
      const center = rail.children[4];
      if (center) rail.scrollLeft = center.offsetLeft - rail.offsetLeft - (rail.clientWidth-center.clientWidth)/2;
      if (location.hash === '#fenty-brands') document.querySelector('#fenty-brands').scrollIntoView();
    });
  }

  document.addEventListener('click', e => {
    if (!active) return;
    const target = e.target.closest('button,a');
    if (!target) return;
    if (target.hasAttribute('data-home-close')) closeDialog();
    else if (target.hasAttribute('data-home-product')) openProduct(target.dataset.homeProduct);
    else if (target.hasAttribute('data-home-save')) {
      const id = target.dataset.homeSave;
      saved.has(id) ? saved.delete(id) : saved.add(id);
      localStorage.setItem('fenty-home-saved',JSON.stringify([...saved]));
      document.querySelectorAll(`[data-home-save="${id}"]`).forEach(b=>{b.setAttribute('aria-pressed',String(saved.has(id)));if(!b.classList.contains('fh-save'))b.textContent=saved.has(id)?'SAVED':'SAVE TO FAVORITES';});
      toast(saved.has(id)?'Saved to your homepage favorites':'Removed from homepage favorites');
    } else if (target.matches('a[aria-label="Favorites"]')) {
      showDialog('YOUR FAVORITES', saved.size?`<div class="fh-saved-grid">${[...saved].filter(id=>data.products[id]).map(id=>productCard(data.products[id])).join('')}</div>`:'<p>Save your favorites using the heart on each product.</p>');
    } else if (target.hasAttribute('data-home-region')) {
      showDialog('UNITED STATES | ENGLISH','<p>This homepage shows the US campaign and prices in USD. The existing shopping catalog uses Canada / CAD.</p><a class="btn" href="/en-ca/collections/makeup-shop-all">OPEN CANADA CATALOG</a>');
    } else if (target.hasAttribute('data-home-step')) {
      document.querySelectorAll('.fh-step').forEach((step,i)=>{const selected=i===Number(target.dataset.homeStep);step.classList.toggle('is-active',selected);step.querySelector('.fh-step-toggle').setAttribute('aria-expanded',String(selected));step.querySelector('.fh-step-copy').inert=!selected;});
    } else if (target.hasAttribute('data-home-scroll')) {
      const rail=document.getElementById(target.dataset.rail), dir=Number(target.dataset.homeScroll);
      const card=rail.querySelector('article');
      if(rail.id==='creator-videos') {
        const cards=[...rail.children],current=cards.findIndex(c=>c.classList.contains('is-center'));
        const next=cards[(current+dir+cards.length)%cards.length];
        rail.scrollTo({left:next.offsetLeft-rail.offsetLeft-(rail.clientWidth-next.clientWidth)/2,behavior:'smooth'});
      } else rail.scrollBy({left:dir*(card.getBoundingClientRect().width+8),behavior:'smooth'});
    } else if (target.hasAttribute('data-home-look')) {
      showDialog('MADE TO MOVE WITH YOU',`<img class="fh-look-large" src="${data.lookbook[Number(target.dataset.homeLook)]}" alt="Rihanna wears Fluid Flex 386W"><button class="btn" data-home-product="${foundationId}">SHOP FLUID FLEX</button>`);
    } else if (target.hasAttribute('data-home-video')) {
      const c=data.creators[Number(target.dataset.homeVideo)];
      showDialog(c.productName,`<video class="fh-video-player" src="${c.video}" poster="${c.poster}" autoplay controls playsinline></video><button class="btn" data-home-product="${c.productId}">${esc(c.productName)}</button>`);
    } else if (target.hasAttribute('data-home-mute')) {
      const v=target.closest('.fh-creator').querySelector('video'); if(!v.src)v.src=v.dataset.src;v.muted=!v.muted;v.play().catch(()=>{});target.setAttribute('aria-label',v.muted?'Unmute video':'Mute video');
    } else if (target.hasAttribute('data-home-hero')) {
      const v=document.querySelector('#fh-hero-video');v.paused?v.play().catch(()=>{}):v.pause();target.setAttribute('aria-label',v.paused?'Play campaign video':'Pause campaign video');
    } else if (target.hash==='#fenty-brands') {
      document.querySelector('#fenty-brands').scrollIntoView({behavior:'smooth'});
    } else { if (target.closest('.fh-dialog') && target.tagName==='A') closeDialog(); return; }
    e.preventDefault();e.stopImmediatePropagation();
  },true);

  document.addEventListener('submit', e=>{
    const form=e.target.closest('[data-home-subscribe]');if(!active||!form)return;
    e.preventDefault();e.stopImmediatePropagation();
    const result=document.querySelector('.fh-subscribe-result');
    if(form.checkValidity()){result.textContent='Preview only: your entry is valid. Nothing was sent or subscribed.';form.reset();}else form.reportValidity();
  },true);
  document.addEventListener('scroll', e=>{
    if(e.target.id!=='creator-videos')return;
    const rail=e.target, mid=rail.getBoundingClientRect().left+rail.clientWidth/2;
    let closest=null, distance=Infinity;
    [...rail.children].forEach(c=>{const r=c.getBoundingClientRect(),d=Math.abs(r.left+r.width/2-mid);if(d<distance){distance=d;closest=c;}});
    [...rail.children].forEach(c=>c.classList.toggle('is-center',c===closest));
  },true);
  return {render:renderHome,setActive};
})();
