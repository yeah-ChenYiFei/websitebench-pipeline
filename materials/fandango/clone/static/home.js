/* Homepage reference: 官网首页1.png, supported by public source DOM on 2026-09-04. */
let homeZip = localStorage.getItem('fandango-home-zip') || HOME_DATA.defaultZip;
let homePromoIndex = 0;
let homeResizeObserver;

function homeHref(href){
  const url=new URL(href, HOME_DATA.source);
  if(url.hostname==='store.fandango.com') return `/fanstore${url.pathname==='/'?'':url.pathname}${url.search}`;
  if(url.hostname==='athome.fandango.com') return url.pathname.includes('/details/')?`/streaming/movies/${url.pathname.split('/').pop()}`:'/streaming';
  if(url.hostname==='www.fandango.com'){
    if(url.pathname==='/movie-news'||url.pathname.startsWith('/movie-news/')||url.pathname.startsWith('/movie-photos/')||url.pathname.startsWith('/movie-trailer/')) return url.pathname+url.search;
    if(url.pathname.match(/^\/\d{5}_movietimes$/)) return `/theaters?zip=${url.pathname.slice(1,6)}`;
    if(url.pathname.endsWith('/theater-page')) return `/theaters/local/${url.pathname.split('/')[1].split('-').pop()}`;
    const routes={'/':'/','/movies-in-theaters':'/movies','/accounts/join-now':'/account','/accounts/dashboard':'/account','/offers':'/offers','/fandango-gift-cards':'/help#gift-cards','/policies/privacy-policy':'/policies/privacy-policy','/policies/terms-and-policies':'/policies/terms-of-use'};
    if(routes[url.pathname]) return routes[url.pathname];
    const movie=state.data.movies.find(m=>url.pathname===`/${m.id}/movie-overview`);
    if(movie) return `/movies/${movie.id}`;
    if(url.pathname.endsWith('/movie-overview')) return `/movies/reference/${url.pathname.split('/')[1]}`;
  }
  return href;
}
function homeLink(href,content,attributes=''){
  const target=homeHref(href);
  return `<a href="${esc(target)}" ${target.startsWith('/')?'data-link':'target="_blank" rel="noopener noreferrer"'} ${attributes}>${content}</a>`;
}
function homeIcon(name,extra=''){
  return `<img class="home-icon ${extra}" src="${HOME_DATA.icons[name]||`/static/home-assets/icon-nav-${name}.svg`}" alt="" aria-hidden="true">`;
}
function homePromos(){
  return [HOME_DATA.promo,...(state.data.offers||[]).map(o=>({...o,href:`/movies/${o.movie_id}`,icon:HOME_DATA.promo.icon})),...HOME_DATA.additionalPromos];
}
function homePromo(){
  const offers=homePromos();
  const index=((homePromoIndex%offers.length)+offers.length)%offers.length;
  const offer=offers[index];
  return `<div class="home-promo" aria-label="Promotions">
    <button class="home-promo-arrow previous" data-home-promo-step="-1" aria-label="Previous offer"></button>
    <div class="home-promo-content">${homeLink(offer.href,`<img src="${esc(offer.icon)}" alt=""><span><strong>${esc(offer.headline)}</strong><span>${esc(offer.detail)}</span></span>`)}
      <div class="home-promo-dots">${offers.map((o,i)=>`<button data-home-promo-go="${i}" aria-label="Show offer ${i+1}" aria-current="${index===i}"></button>`).join('')}</div>
    </div>
    <button class="home-promo-arrow next" data-home-promo-step="1" aria-label="Next offer"></button>
  </div>`;
}
function homeHeader(){
  const profile=state.data.profile;
  const items=[['/movies','movies','Movies'],[`/theaters?zip=${homeZip}`,'theaters','Theaters'],['/fanstore','fanstore','FanStore'],['/streaming','on-demand','Streaming'],['/movie-news','news','Movie News'],['/account','account',profile?profile.display_name.split(' ')[0]:'Sign In/Join']];
  return `<header class="home-header"><div class="home-utility"><a href="/help#gift-cards" data-link>Gift Cards</a><a href="/offers" data-link>Offers</a>${homeLink('https://www.fandango.com/fanclub/memberships',`${homeIcon('fanclub')} FanClub`)}</div>
    <div class="home-nav"><a class="home-logo" href="/" data-link aria-label="Fandango">${homeIcon('logo')}</a>
      <form class="home-search" data-search-form role="search"><input name="q" aria-label="Search by city, state, zip or movie" placeholder="Search by city, state, zip or movie"><button aria-label="Search"><svg viewBox="0 0 14 14" aria-hidden="true"><circle cx="5.5" cy="5.5" r="4.5"/><path d="m9 9 4 4"/></svg></button></form>
      <nav class="nav-icons" aria-label="Primary">${items.map(([href,icon,label])=>homeLink(href,`${homeIcon(icon)}<span>${esc(label)}</span>`)).join('')}</nav>
    </div>${homePromo()}</header>`;
}
function homeCarousel(id,title,rows,link='',features=false){
  return `<section class="home-section ${features?'home-features':''}" aria-labelledby="${id}-title"><h2 id="${id}-title">${title}</h2>${link?homeLink(link,'SEE ALL MOVIES','class="home-section-link"'):''}
    <div class="home-carousel ${id==='now'?'home-carousel-now':''}" data-home-carousel="${id}" aria-roledescription="carousel">
      <div class="home-track" id="${id}-track" tabindex="0" aria-label="${title}">
        ${rows.map(row=>`<article class="home-slide">${homeLink(row.href,`<div class="home-image"><img src="${esc(row.image)}" alt="${esc(row.title)}" width="${features?400:140}" height="${features?210:210}" loading="${id==='now'?'eager':'lazy'}">${row.gift?`<span class="home-gift" aria-label="Gift with purchase">${homeIcon('gift')}</span>`:''}${features&&row.video?homeIcon('play','home-play'):''}</div><h3>${esc(row.title)}</h3>${features?`<p>${esc(row.description)}</p>`:''}`)}</article>`).join('')}
      </div>
      <button class="home-carousel-arrow previous" data-home-step="-1" aria-label="Previous ${title.toLowerCase()}" aria-controls="${id}-track" disabled></button>
      <button class="home-carousel-arrow next" data-home-step="1" aria-label="Next ${title.toLowerCase()}" aria-controls="${id}-track"></button>
    </div></section>`;
}
function homeTheaters(){
  const theaters=homeZip==='90001'?HOME_DATA.theaters:state.data.theaters.map(t=>({name:t.name,distance:`${t.distance}mi`,address:t.location.split(',')[0],city:t.location.split(',').slice(1).join(',').trim(),href:`/theaters/${t.id}`}));
  return `<section class="home-theaters" aria-labelledby="home-theaters-title"><h2 id="home-theaters-title">THEATERS NEAR YOU</h2>
    <div class="home-location">ENTER CITY, STATE, OR ZIPCODE <button data-home-location aria-label="Theaters near ${homeZip}">${homeIcon('location')}${homeZip}</button></div>
    ${homeLink(homeZip==='90001'?'https://www.fandango.com/90001_movietimes':'/theaters','SEE MORE THEATERS','class="home-section-link"')}
    <div class="home-theater-grid">${theaters.map(t=>homeLink(t.href,`<div><h3>${esc(t.name)}</h3><span>${esc(t.distance)}</span></div><p>${esc(t.address)}<br>${esc(t.city)}</p>`,'class="home-theater"')).join('')}</div>
  </section>`;
}
function homeOffers(){
  return `<section class="home-offers" aria-labelledby="home-offers-title"><h2 id="home-offers-title">OFFERS</h2><a class="home-section-link" href="/offers" data-link>SEE ALL OFFERS</a>
    <div class="home-offer-grid">${HOME_DATA.offers.map(o=>`<article class="home-offer">${homeLink(o.href,`<img src="${o.image}" alt="${esc(o.title)}" loading="lazy" width="300" height="118">`)}<div><h3>${esc(o.title)}</h3><p>${esc(o.description)}</p>${homeLink(o.href,esc(o.cta),'class="home-offer-cta"')}</div></article>`).join('')}</div></section>`;
}
function homeFooter(){
  return `<footer class="home-footer"><nav class="home-footer-columns" aria-label="Explore Fandango">${HOME_DATA.footerColumns.map(c=>`<div><h3>${esc(c.title)}</h3>${c.links.map(l=>homeLink(l.href,esc(l.title))).join('')}</div>`).join('')}</nav>
    <div class="home-social"><div><h2>FOLLOW US</h2>${HOME_DATA.social.slice(0,4).map(l=>homeLink(l.href,homeIcon(l.icon),`aria-label="${esc(l.title)}"`)).join('')}</div><div><h2>GET FANDANGO APPS</h2>${HOME_DATA.social.slice(4).map(l=>homeLink(l.href,homeIcon(l.icon),`aria-label="${esc(l.title)}"`)).join('')}</div></div>
    <div class="home-legal"><div class="home-support-links">${HOME_DATA.footerLinks[0].map(l=>homeLink(l.href,esc(l.title))).join('')}<button data-home-notice="feedback">FEEDBACK</button></div>
      <div class="home-policy-links">${HOME_DATA.footerLinks[1].map((l,i)=>`${i===5?`<button data-home-notice="privacy">${homeIcon('privacy')}Your Privacy Choices</button>`:''}${homeLink(l.href,esc(l.title))}`).join('')}</div>
      <div class="home-affiliates">Fandango Affiliated Companies: ${HOME_DATA.footerLinks[2].map(l=>homeLink(l.href,esc(l.title))).join('')}</div>
      ${homeLink('https://together.nbcuni.com/advertise/','Advertise With Us','class="home-advertise"')}
      <img class="home-studios" src="${HOME_DATA.studios}" alt="Movie studio brands" loading="lazy">
      <p class="home-copyright">© 2026 Fandango | ${homeLink('https://versantmedia.com/','A Versant Media Company')}</p>
      <p class="home-disclaimer">WebsiteBench offline recreation. Not the official Fandango service. No real tickets, charges, emails or venue messages. Some links open the original website.</p>
    </div></footer>`;
}
function bindHomeCarousel(){
  homeResizeObserver?.disconnect();
  homeResizeObserver=new ResizeObserver(entries=>entries.forEach(entry=>entry.target.dispatchEvent(new Event('scroll'))));
  root.querySelectorAll('[data-home-carousel]').forEach(carousel=>{
    const track=carousel.querySelector('.home-track');
    const previous=carousel.querySelector('.previous');
    const next=carousel.querySelector('.next');
    const update=()=>{previous.disabled=track.scrollLeft<1;next.disabled=track.scrollLeft>=track.scrollWidth-track.clientWidth-1;};
    carousel.querySelectorAll('[data-home-step]').forEach(button=>button.addEventListener('click',()=>{
      const slide=track.querySelector('.home-slide');
      const step=slide.getBoundingClientRect().width+20;
      track.scrollBy({left:Number(button.dataset.homeStep)*step*Math.max(1,Math.floor(track.clientWidth/step)),behavior:'smooth'});
    }));
    track.addEventListener('scroll',update,{passive:true});
    track.addEventListener('keydown',event=>{if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();(event.key==='ArrowRight'?next:previous).click();}});
    homeResizeObserver.observe(track);
    update();
  });
}
function bindHomePromo(){
  const promo=root.querySelector('.home-promo');
  const change=index=>{homePromoIndex=index;promo.outerHTML=homePromo();bindHomePromo();};
  promo.querySelectorAll('[data-home-promo-step]').forEach(b=>b.addEventListener('click',()=>change(homePromoIndex+Number(b.dataset.homePromoStep))));
  promo.querySelectorAll('[data-home-promo-go]').forEach(b=>b.addEventListener('click',()=>change(Number(b.dataset.homePromoGo))));
  promo.querySelectorAll('[data-link]').forEach(a=>a.addEventListener('click',e=>{if(!e.defaultPrevented&&e.button===0&&!e.ctrlKey&&!e.metaKey){e.preventDefault();go(a.getAttribute('href'));}}));
}
function homeDialog(content){
  const old=root.querySelector('.home-dialog');if(old) old.remove();
  root.insertAdjacentHTML('beforeend',`<dialog class="home-dialog"><button class="home-dialog-close" aria-label="Close">×</button>${content}</dialog>`);
  const dialog=root.querySelector('.home-dialog');
  dialog.querySelector('.home-dialog-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  dialog.showModal();return dialog;
}
function homeLocationDialog(onChange){
  const dialog=homeDialog(`<h2>Enter city, state, or ZIP code</h2><form><label for="home-zip">Location</label><input id="home-zip" name="zip" value="${homeZip}" autocomplete="postal-code"><p class="home-location-hint">Available in this offline preview: Los Angeles, CA 90001 and New York, NY 10003.</p><p class="home-location-error" role="alert"></p><button class="primary" type="submit">UPDATE LOCATION</button></form>`);
  dialog.querySelector('form').addEventListener('submit',event=>{
    event.preventDefault();const value=new FormData(event.currentTarget).get('zip').toString().trim().toLowerCase();
    const zip={'90001':'90001','los angeles':'90001','los angeles, ca':'90001','10003':'10003','new york':'10003','new york, ny':'10003'}[value];
    if(!zip){dialog.querySelector('.home-location-error').textContent='This preview has captured data for 90001 and 10003 only.';return;}
    homeZip=zip;localStorage.setItem('fandango-home-zip',zip);dialog.close();if(typeof onChange==='function'){onChange(zip);return;}const y=scrollY;renderHome();window.scrollTo(0,y);
  });
}
function renderHome(){
  document.body.className='homepage';
  root.innerHTML=`${homeHeader()}<main class="home-main">
    ${homeCarousel('now','MOVIES IN THEATERS',HOME_DATA.now,'/movies')}
    ${homeCarousel('soon','COMING SOON TO THEATERS',HOME_DATA.soon)}
    ${homeCarousel('free','FREE TO WATCH',HOME_DATA.free,'https://athome.fandango.com/')}
    ${homeCarousel('features','FEATURES',HOME_DATA.features,'',true)}
    ${homeTheaters()}
    <div class="home-banner">${homeLink(HOME_DATA.banner.href,`<img src="${HOME_DATA.banner.image}" alt="Ryan Garcia vs. Conor Benn — Saturday September 12. Learn more." width="1232" height="258" loading="lazy">`)}</div>
    ${homeOffers()}
    <section class="home-new-soon"><h2>NEW &amp; COMING SOON</h2><div>${HOME_DATA.newSoon.map(m=>homeLink(m.href,`<img src="${m.image}" alt="${esc(m.title)}" width="144" height="221" loading="lazy">`)).join('')}</div></section>
  </main>${homeFooter()}`;
  bindGlobal();bindHomeCarousel();bindHomePromo();
  root.querySelector('[data-home-location]').addEventListener('click',homeLocationDialog);
  root.querySelectorAll('[data-home-notice]').forEach(b=>b.addEventListener('click',()=>homeDialog(b.dataset.homeNotice==='privacy'?'<h2>Your Privacy Choices</h2><p>This offline recreation does not sell or share your information, load advertising, or track you across websites.</p><p><a href="/policies/privacy-policy">Read the local privacy policy</a></p>':'<h2>Feedback</h2><p>This is an offline recreation. Feedback is not sent to Fandango. Share feedback with the owner of this preview.</p>')));
}
