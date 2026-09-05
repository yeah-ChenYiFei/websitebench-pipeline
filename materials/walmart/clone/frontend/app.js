'use strict';
(() => {
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const storage = {
    read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
    write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } }
  };
  let panel = null, opener = null, toastTimer;
  const toast = message => {
    const node = $('.toast'); node.textContent = message; node.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { node.hidden = true; }, 4500);
  };
  function closePanel(restore = true) {
    if (!panel) return;
    panel.hidden = true; panel.classList.remove('show-detail');
    $$('[data-open]').forEach(b => b.setAttribute('aria-expanded', 'false'));
    $('[data-scrim]').hidden = true; document.body.classList.remove('overlay-open');
    $('main').inert = false; $('.site-footer').inert = false;
    panel = null;
    if (restore && opener?.isConnected) opener.focus();
  }
  function openPanel(name, trigger) {
    const next = $(`[data-panel="${name}"]`);
    if (!next) return;
    if (panel === next) { closePanel(); return; }
    closePanel(false); hideSuggestions();
    panel = next; opener = trigger; panel.hidden = false;
    $$(`[data-open="${name}"]`).forEach(b => b.setAttribute('aria-expanded', 'true'));
    $('[data-scrim]').hidden = false; document.body.classList.add('overlay-open');
    $('main').inert = true; $('.site-footer').inert = true;
    if (name === 'feedback') {
      $('#feedback-text').value = storage.read('wm-feedback', '');
      const rating = storage.read('wm-feedback-rating', '');
      $$('[name=feedback-rating]').forEach(input => { input.checked = input.value === rating; });
      $('#feedback-status').textContent = '';
    }
    requestAnimationFrame(() => $('button, a, input', panel)?.focus());
  }
  $$('[data-open]').forEach(b => b.addEventListener('click', () => openPanel(b.dataset.open, b)));
  $$('[data-close]').forEach(b => b.addEventListener('click', () => closePanel()));
  $('[data-scrim]').addEventListener('click', () => closePanel());
  document.addEventListener('pointerdown', e => {
    if (panel && !panel.contains(e.target) && !e.target.closest('[data-open]')) closePanel(false);
    if (!e.target.closest('.search-form')) hideSuggestions();
  });
  function activateTab(button, mobile = false) {
    const menu = button.closest('.mega-panel');
    $$('.menu-tab', menu).forEach(b => { const active = b === button; b.classList.toggle('active', active); b.setAttribute('aria-expanded', String(active)); });
    $$('.menu-content', menu).forEach(p => { p.hidden = p.id !== button.dataset.menuTab; });
    $('.menu-detail', menu).scrollTop = 0;
    if (mobile && matchMedia('(max-width:760px)').matches) { menu.classList.add('show-detail'); $('.menu-content:not([hidden]) button', menu).focus(); }
  }
  $$('[data-menu-tab]').forEach(b => {
    b.addEventListener('click', () => activateTab(b, true));
    b.addEventListener('pointerenter', e => { if (e.pointerType === 'mouse' && !matchMedia('(max-width:760px)').matches) activateTab(b); });
    b.addEventListener('keydown', e => {
      const buttons = $$('.menu-tab', b.closest('.menu-tabs'));
      const index = buttons.indexOf(b);
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const next = buttons[(index + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]; next.focus(); activateTab(next); }
      if (e.key === 'ArrowRight') { e.preventDefault(); activateTab(b, true); $('.menu-content:not([hidden]) a', b.closest('.mega-panel'))?.focus(); }
    });
  });
  $$('[data-menu-back]').forEach(b => b.addEventListener('click', () => { const menu = b.closest('.mega-panel'); menu.classList.remove('show-detail'); $('.menu-tab.active', menu).focus(); }));
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') { hideSuggestions(); closePanel(); }
    if (e.key === 'Tab' && panel) {
      const focusable = $$('a[href], button:not([disabled]), input, textarea, select', panel).filter(n => n.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (e.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { e.preventDefault(); first?.focus(); }
    }
  });

  const locations = {
    '95829': {city:'Sacramento', store:'Sacramento Supercenter', address:'8915 Gerber Road, Sacramento, CA 95829', methods:['Shipping','Pickup','Delivery']},
    '10001': {city:'New York', store:'New York preview location', address:'ZIP 10001 · shipping preview only', methods:['Shipping']},
    '90210': {city:'Beverly Hills', store:'Beverly Hills preview location', address:'ZIP 90210 · shipping and delivery preview', methods:['Shipping','Delivery']}
  };
  let preference = storage.read('wm-fulfillment', {zip:'95829',method:'Shipping'});
  if (!locations[preference.zip] || !locations[preference.zip].methods.includes(preference.method)) preference = {zip:'95829',method:'Shipping'};
  function applyLocation() {
    const place = locations[preference.zip];
    $$('[data-location]').forEach(n => { n.textContent = `${place.city}, ${preference.zip} · ${preference.method}`; });
    $$('[data-store]').forEach(n => { n.textContent = place.store; });
    $$('[data-store-address]').forEach(n => { n.textContent = place.address; });
    $$('[data-method-label]').forEach(n => { n.textContent = preference.method; });
    $$('[data-method]').forEach(b => { b.setAttribute('aria-pressed', String(b.dataset.method === preference.method)); b.disabled = !place.methods.includes(b.dataset.method); b.title = b.disabled ? 'Unavailable at this preview location' : ''; });
    $('#test-zip').value = preference.zip;
    if ($('#zip') && !$('#zip').value) $('#zip').value = preference.zip;
    $$('[data-availability]').forEach(n => {
      const available = n.dataset.availability.toLowerCase().includes(preference.method.toLowerCase()) && place.methods.includes(preference.method);
      n.textContent = available ? `${preference.method} · ${place.city} ${preference.zip} (preview)` : `${preference.method} unavailable here · choose another method`;
    });
  }
  $$('[data-method]').forEach(b => b.addEventListener('click', () => {
    preference.method = b.dataset.method;
    const saved = storage.write('wm-fulfillment', preference); applyLocation();
    $('#location-status').textContent = saved ? `${preference.method} selected.` : 'Selected for this page. Browser storage is unavailable.';
  }));
  $('#location-form').addEventListener('submit', e => {
    e.preventDefault(); const zip = $('#test-zip').value.trim();
    if (!locations[zip]) { $('#location-status').textContent = 'This preview supports ZIP 95829, 10001 and 90210.'; $('#test-zip').setAttribute('aria-invalid','true'); return; }
    $('#test-zip').removeAttribute('aria-invalid'); preference.zip = zip;
    if (!locations[zip].methods.includes(preference.method)) preference.method = locations[zip].methods[0];
    const saved = storage.write('wm-fulfillment', preference); applyLocation();
    $('#location-status').textContent = saved ? 'Location saved on this device.' : 'Location changed for this page; browser storage is unavailable.';
  });
  applyLocation();
  window.addEventListener('storage', e => { if (e.key === 'wm-fulfillment') { const next = storage.read('wm-fulfillment',preference); if (locations[next.zip]?.methods.includes(next.method)) { preference = next; applyLocation(); } } });

  const search = $('#global-search'), suggestions = $('#search-suggestions');
  let suggestionIndex = -1, debounce, controller;
  function hideSuggestions() { suggestions.hidden = true; search.setAttribute('aria-expanded','false'); search.removeAttribute('aria-activedescendant'); suggestionIndex = -1; }
  async function loadSuggestions() {
    const q = search.value.trim();
    controller?.abort();
    if (!q) { hideSuggestions(); return; }
    controller = new AbortController();
    try {
      const response = await fetch(`/api/search-suggestions?q=${encodeURIComponent(q)}`, {signal:controller.signal});
      if (!response.ok) throw new Error('Suggestions unavailable');
      const items = await response.json();
      if (search.value.trim() !== q || document.activeElement !== search) return;
      suggestions.replaceChildren();
      const rows = [...items, {label:`Search for “${q}”`,url:`/search?q=${encodeURIComponent(q)}`,kind:'All results'}];
      rows.forEach((item,i) => {
        const a = document.createElement('a'); a.href = item.url; a.id = `suggestion-${i}`; a.setAttribute('role','option'); a.setAttribute('aria-selected','false'); a.tabIndex=-1;
        const label=document.createElement('span'); label.textContent=item.label;
        const kind=document.createElement('small'); kind.textContent=item.kind;
        a.append(label,kind); suggestions.append(a);
      });
      suggestions.hidden=false; suggestionIndex=-1; search.setAttribute('aria-expanded','true');
    } catch (error) { if (error.name !== 'AbortError') hideSuggestions(); }
  }
  search.addEventListener('input', () => { clearTimeout(debounce); debounce=setTimeout(loadSuggestions,140); });
  search.addEventListener('focus', () => { closePanel(false); if (search.value.trim()) loadSuggestions(); });
  search.addEventListener('keydown', e => {
    if (e.key === 'Escape') { hideSuggestions(); return; }
    if (suggestions.hidden) return;
    const rows = $$('[role=option]',suggestions);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); suggestionIndex=(suggestionIndex+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length;
      rows.forEach((row,i) => row.setAttribute('aria-selected',String(i===suggestionIndex)));
      search.setAttribute('aria-activedescendant',rows[suggestionIndex].id); rows[suggestionIndex].scrollIntoView({block:'nearest'});
    }
    if (e.key === 'Enter' && suggestionIndex>=0) { e.preventDefault(); location.assign(rows[suggestionIndex].href); }
    if (e.key === 'Tab') hideSuggestions();
  });

  const reducedMotion = matchMedia('(prefers-reduced-motion:reduce)').matches;
  $$('[data-carousel]').forEach(carousel => {
    const track=$('.scroll-track',carousel), prev=$('[data-direction="-1"]',carousel), next=$('[data-direction="1"]',carousel);
    const update=()=>{prev.disabled=track.scrollLeft<=2;next.disabled=track.scrollLeft+track.clientWidth>=track.scrollWidth-2;};
    $$('[data-direction]',carousel).forEach(b=>b.addEventListener('click',()=>track.scrollBy({left:Number(b.dataset.direction)*track.clientWidth,behavior:reducedMotion?'instant':'smooth'})));
    track.addEventListener('scroll',update,{passive:true});new ResizeObserver(update).observe(track);update();
  });
  $$('video').forEach(video=>video.addEventListener('play',()=>{$$('video').forEach(other=>{if(other!==video)other.pause();});}));
  $$('[data-favorite]').forEach(b=>b.addEventListener('click',()=>{openPanel('account',$('[data-open="account"]'));toast('Sign-in is unavailable in this preview. No favorite was saved.');}));
  $$('[data-social]').forEach(b=>b.addEventListener('click',()=>{const tags=$(`#social-tags-${b.dataset.social}`);tags.hidden=!tags.hidden;b.setAttribute('aria-expanded',String(!tags.hidden));}));
  let heroIndex=0, heroTimer;
  const heroSlides=$$('[data-hero-slide]');
  function selectHero(index) {
    heroIndex=(index+heroSlides.length)%heroSlides.length;
    heroSlides.forEach((slide,i)=>{slide.hidden=i!==heroIndex;});
    $$('[data-hero-select]').forEach((dot,i)=>dot.setAttribute('aria-pressed',String(i===heroIndex)));
  }
  $$('[data-hero-select]').forEach(b=>b.addEventListener('click',()=>selectHero(Number(b.dataset.heroSelect))));
  $$('[data-hero-step]').forEach(b=>b.addEventListener('click',()=>selectHero(heroIndex+Number(b.dataset.heroStep))));
  $('[data-hero-play]')?.addEventListener('click',e=>{
    const button=e.currentTarget;
    if(heroTimer){clearInterval(heroTimer);heroTimer=null;button.setAttribute('aria-label','Play carousel');button.textContent='▶';}
    else{heroTimer=setInterval(()=>selectHero(heroIndex+1),8000);button.setAttribute('aria-label','Pause carousel');button.textContent='Ⅱ';}
  });
  const dealClock=$('[data-deal-deadline]');
  if(dealClock?.dataset.dealDeadline){
    const deadline=Date.parse(dealClock.dataset.dealDeadline);
    const tick=()=>{
      const seconds=Math.max(0,Math.floor((deadline-Date.now())/1000));
      if(!Number.isFinite(deadline)){dealClock.textContent='Countdown unavailable';return;}
      if(!seconds){dealClock.textContent='This configured offer has ended';return;}
      const days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600),minutes=Math.floor(seconds%3600/60);
      dealClock.textContent=`Ends in ${days?days+'d ':''}${String(hours).padStart(2,'0')}:${String(minutes).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;
    };
    tick();setInterval(tick,1000);
  }
  $('#feedback-form').addEventListener('submit',e=>{e.preventDefault();const saved=storage.write('wm-feedback',$('#feedback-text').value.trim()) && storage.write('wm-feedback-rating',$('[name=feedback-rating]:checked').value);$('#feedback-status').textContent=saved?'Saved on this device. Nothing was sent.':'Browser storage is unavailable; feedback was not saved.';});
  $('[data-filter-toggle]')?.addEventListener('click',e=>{const filters=$('.filters');const open=filters.classList.toggle('is-open');e.currentTarget.setAttribute('aria-expanded',String(open));if(open)$('select',filters)?.focus();});
  $$('input[data-option-price]').forEach(input=>input.addEventListener('change',()=>{
    $('[data-price]').textContent=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(input.dataset.optionPrice)/100);
    $('[data-option-label]').textContent=input.closest('label').querySelector('span').textContent;
    const url=new URL(location.href);url.searchParams.set('option',input.value);history.replaceState(null,'',url);
  }));
  $$('.quick-add').forEach(form=>form.addEventListener('submit',async e=>{
    e.preventDefault();const button=$('button',form);button.disabled=true;
    try {
      const values=Object.fromEntries(new FormData(form));values.quantity=1;
      const response=await fetch('/api/cart/items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
      if(!response.ok)throw new Error('Could not add this item. Please try again.');
      const cart=await response.json();updateCart(cart);toast('Added to cart');
    }catch(error){toast(error.message);}finally{button.disabled=false;}
  }));
  function updateCart(cart){
    $('[data-cart-count]').textContent=cart.cart_count;
    $('[data-cart-total]').textContent=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cart.subtotal_cents/100);
    $('.cart-link').setAttribute('aria-label',`Cart with ${cart.cart_count} items`);
  }
  window.addEventListener('pageshow',async()=>{try{const response=await fetch('/api/cart');if(response.ok)updateCart(await response.json());}catch{/* Server-rendered cart remains visible when offline. */}});
})();
