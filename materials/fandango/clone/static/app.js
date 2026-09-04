const root = document.querySelector('#app');
const toast = document.querySelector('#toast');
const state = {data:null, search:[], selectedSeats:[], checkoutReview:null, confirmation:null, theaters:null};

function esc(value='') { return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function money(value) { return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(Number(value||0)); }
function longDate(value) {
  if (!value) return '';
  const [y,m,d] = value.split('-').map(Number);
  return new Intl.DateTimeFormat('en-US',{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(y,m-1,d)));
}
async function api(path, options={}) {
  const response = await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
  let data={}; try{data=await response.json();}catch(_){ }
  if(!response.ok) throw new Error(data.error||`Request failed (${response.status})`);
  return data;
}
function notify(message){ toast.textContent=message; toast.classList.add('show'); clearTimeout(notify.timer); notify.timer=setTimeout(()=>toast.classList.remove('show'),2400); }
function go(path){ history.pushState({},'',path); state.checkoutReview=null; render(); window.scrollTo(0,0); }
async function refresh(){ state.data=await api('/api/bootstrap'); return state.data; }

/* ---------- chrome ---------- */
function header(){ return homeHeader(); }
function layout(content){ document.body.className='fandango-page'; root.innerHTML=`${header()}<main>${content}</main>${homeFooter()}`; bindGlobal(); bindHomePromo(); bindNavigationChrome(); }

/* ---------- posters + cards ---------- */
function posterMarkup(movie, extra=''){
  return `<div class="poster">${extra}<img src="${esc(movie.poster)}" alt="${esc(movie.title)} (${movie.year}) movie poster" loading="lazy" width="400" height="592"></div>`;
}
function scoreBadge(movie){
  if(!movie.score) return `<span class="score-badge">Not yet scored</span>`;
  return `<span class="score-badge ${movie.score>=85?'fresh':''}"><i></i>${movie.score}% Audience</span>`;
}
function movieCard(movie){
  const soon=movie.status==='coming-soon';
  return `<article class="movie-card" data-movie-card="${movie.id}">
    <a class="poster-link" href="/movies/${movie.id}" data-link aria-label="${esc(movie.title)} (${movie.year})">${posterMarkup(movie, soon?'<span class="presale">PRE-SALE</span>':'')}</a>
    <h3><a href="/movies/${movie.id}" data-link>${esc(movie.title)} (${movie.year})</a></h3>
    ${movie.score?scoreBadge(movie):''}
  </article>`;
}

/* ---------- home ---------- */
function home(){
  renderHome();
}

/* ---------- listing ---------- */
async function moviesPage(){
  const params=new URLSearchParams(location.search);
  const query=params.get('q')||'';
  const genre=params.get('genre')||'';
  const sort=params.get('sort')||'rating';
  const maxPrice=params.get('max_price')||'';
  const service=params.get('service')||'';
  // "Now Playing" is the default tab, matching the source listing page.
  const status=params.get('status')||(params.get('q')?'':'now-playing');
  const theater=params.get('theater')||'';
  const showFilters=params.get('filters')==='1'||genre||maxPrice||service||theater||query;
  const search=new URLSearchParams({q:query,genre,sort,service,status,theater});
  if(maxPrice) search.set('max_price',maxPrice);
  const data=await api(`/api/movies?${search}`);
  state.search=data.movies;
  const tab=path=>{const p=new URLSearchParams(location.search);if(path)p.set('status',path);else p.delete('status');return `/movies?${p}`;};
  layout(`<div class="shell">
    <nav class="listing-tabs">
      <a class="${status==='coming-soon'?'':'active'}" href="${tab('')}" data-link><span aria-hidden="true">🎬</span>Now Playing</a>
      <a class="${status==='coming-soon'?'active':''}" href="${tab('coming-soon')}" data-link><span aria-hidden="true">📅</span>Coming Soon</a>
      <button class="filter-toggle" type="button" data-toggle-filters>Filters <span aria-hidden="true">⚙</span></button>
    </nav>
    ${showFilters?`<div class="filters"><form data-filter>
      <label>Keyword<input name="q" value="${esc(query)}" placeholder="Movie, genre or theater"></label>
      <label>Genre<select name="genre"><option value="">All genres</option>${(data.genres||[]).map(g=>`<option ${genre===g?'selected':''}>${esc(g)}</option>`).join('')}</select></label>
      <label>Theater<select name="theater"><option value="">All theaters</option>${(data.theaters||[]).map(t=>`<option value="${t.id}" ${theater===t.id?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label>
      <label>Max ticket price<select name="max_price"><option value="">Any price</option><option value="26" ${maxPrice==='26'?'selected':''}>Under $26</option><option value="20" ${maxPrice==='20'?'selected':''}>Under $20</option><option value="18.5" ${maxPrice==='18.5'?'selected':''}>Under $18.50</option></select></label>
      <label>Service<select name="service"><option value="">Any service</option>${['Reserved Seating','Mobile Ticket','Closed Caption','IMAX','Dolby Cinema','RPX'].map(s=>`<option ${service===s?'selected':''}>${esc(s)}</option>`).join('')}</select></label>
      <label>Sort<select name="sort"><option value="rating" ${sort==='rating'?'selected':''}>Audience rating</option><option value="price" ${sort==='price'?'selected':''}>Lowest price</option><option value="title" ${sort==='title'?'selected':''}>Title A–Z</option></select></label>
      <input type="hidden" name="status" value="${esc(status)}"><input type="hidden" name="filters" value="1">
      <button type="submit">Apply</button></form></div>`:''}
    <h1 class="section-title" style="margin-top:26px">${query?`Results for “${esc(query)}”`:status==='coming-soon'?'Coming Soon To Theaters':'Movies In Theaters'}</h1>
    ${query?`<p class="card-meta">Searching now playing and coming soon.</p>`:''}
    <p class="result-count">${data.movies.length} movie${data.movies.length===1?'':'s'} near New York, NY for ${longDate(state.data.friday)}</p>
    ${data.movies.length
      ? `<div class="poster-grid">${data.movies.map(movieCard).join('')}</div>`
      : `<div class="empty"><h2>No movies found</h2><p>We couldn’t find anything matching <strong>${esc(query||'those filters')}</strong>.</p><a class="primary" href="/movies" data-link>Browse available movies</a></div>`}
  </div>`);
  root.querySelector('[data-filter]')?.addEventListener('submit',event=>{event.preventDefault();const p=new URLSearchParams(new FormData(event.currentTarget));[...p.keys()].forEach(k=>{if(!p.get(k))p.delete(k);});go(`/movies?${p}`);});
  root.querySelector('[data-toggle-filters]')?.addEventListener('click',()=>{const p=new URLSearchParams(location.search);showFilters?p.delete('filters'):p.set('filters','1');go(`/movies?${p}`);});
}

/* ---------- movie detail ---------- */
function findMovie(movieId){ return state.data.movies.find(row=>row.id===movieId); }
function showtimeButtons(movieId, theater, onDate){
  const date=onDate||theater.date||state.data.friday;
  return theater.showtimes.map(show=>`<button data-showtime data-movie="${movieId}" data-theater="${theater.id}" data-show="${show.id}" data-date="${date}"><strong>${show.time}</strong><small>${esc(show.format)}</small><small>${money(show.price)} · ${show.available} seats</small></button>`).join('');
}
function theaterDetail(movie, theater, onDate){
  return `<article class="showtime-theater"><header><div><h3><a href="/theaters/${theater.id}" data-link>${esc(theater.name)}</a></h3><p>${esc(theater.location)} · ${theater.distance} mi</p><p>${theater.services.map(esc).join(' · ')}</p></div><span class="availability">Tickets available</span></header><div class="showtimes">${showtimeButtons(movie.id, theater, onDate)}</div><details><summary>Policies &amp; amenities</summary><p>${esc(theater.policy)}</p></details></article>`;
}
function dateStrip(dates, selected, hrefFor){
  return `<div class="date-strip" role="group" aria-label="Choose a showtime date">${dates.map(row=>`<a class="date-tile ${row.date===selected?'active':''}" href="${hrefFor(row.date)}" data-link aria-current="${row.date===selected}"><small>${esc(row.weekday)}</small><span>${esc(row.month)}</span><strong>${row.day}</strong></a>`).join('')}</div>`;
}
function formatChips(formats, selected, hrefFor){
  return `<div class="format-chips" role="group" aria-label="Filter by format"><a class="chip ${selected?'':'active'}" href="${hrefFor('')}" data-link>All</a>${formats.map(f=>`<a class="chip ${selected===f?'active':''}" href="${hrefFor(f)}" data-link>${esc(f)}</a>`).join('')}</div>`;
}
async function moviePage(movieId){
  const params=new URLSearchParams(location.search);
  const wanted=params.get('date')||'';
  const format=params.get('format')||'';
  let data;
  try{ data=await api(`/api/movies/${encodeURIComponent(movieId)}?date=${encodeURIComponent(wanted)}`); }
  catch(_){ notFound(); return; }
  const movie=data.movie, selectedDate=data.date;
  const saved=state.data.favorites.includes(movie.id);
  const formats=[...new Set(movie.theaters.flatMap(t=>t.showtimes.map(s=>s.format)))];
  const shown=movie.theaters
    .map(theater=>({...theater, showtimes: format?theater.showtimes.filter(s=>s.format===format):theater.showtimes}))
    .filter(theater=>theater.showtimes.length);
  const href=(d,f)=>{const p=new URLSearchParams(location.search);d?p.set('date',d):p.delete('date');f?p.set('format',f):p.delete('format');const q=p.toString();return `/movies/${movie.id}${q?'?'+q:''}`;};
  layout(`<section class="movie-hero"><div class="shell movie-hero-grid">
    ${posterMarkup(movie)}
    <div><p class="eyebrow">${esc(movie.genre)}</p><h1>${esc(movie.title)} (${movie.year})</h1>
    <p class="rating-chip">${esc(movie.rating)}</p>
    <div class="scores">${scoreBadge(movie)}${movie.critic_score?`<span class="score-badge"><i></i>${movie.critic_score}% Critics</span>`:''}<span class="card-meta">${[movie.runtime, movie.director?`Directed by ${movie.director}`:''].filter(Boolean).map(esc).join(' · ')}</span></div>
    ${movie.synopsis?`<p class="synopsis">${esc(movie.synopsis)}</p>`:''}
    ${movie.cast?`<p class="synopsis"><strong>Cast:</strong> ${esc(movie.cast)}</p>`:''}
    <div class="hero-actions"><button class="save-btn" type="button" disabled>▶ Trailer</button><button class="save-btn" data-favorite="${movie.id}">${saved?'★ Saved to My Movies':'♡ Save to My Movies'}</button></div></div>
  </div></section>
  <div class="shell"><section class="section"><div class="section-head"><div><p class="eyebrow">Theaters near New York, NY</p><h2>Showtimes for ${longDate(selectedDate)}</h2></div><a href="/theaters" data-link>Browse all theaters</a></div>
  ${dateStrip(data.dates, selectedDate, d=>href(d,format))}
  ${formats.length>1?formatChips(formats, format, f=>href(selectedDate===state.data.friday?'':selectedDate, f)):''}
  ${shown.length?shown.map(theater=>theaterDetail(movie,theater,selectedDate)).join(''):`<div class="empty"><h2>No showtimes for this selection</h2><p>Try another date or format.</p><a class="primary" href="${href('','')}" data-link>Reset filters</a></div>`}</section></div>`);
  bindShowtimes();
}

/* ---------- theaters ---------- */
async function theatersPage(theaterId=''){
  const wanted=new URLSearchParams(location.search).get('date')||'';
  const data=await api(`/api/theaters?date=${encodeURIComponent(wanted)}`);
  state.theaters=data.theaters;
  const selectedDate=data.date;
  const rows=theaterId?data.theaters.filter(t=>t.id===theaterId):data.theaters;
  if(theaterId && !rows.length){notFound();return;}
  const href=d=>`${theaterId?`/theaters/${theaterId}`:'/theaters'}${d?`?date=${d}`:''}`;
  layout(`<section class="page-title"><div class="shell"><p class="eyebrow">Theaters</p>
    <h1>${theaterId?esc(rows[0].name):'Movie Theaters Near New York, NY'}</h1>
    <p>${theaterId?`${esc(rows[0].location)} · ${rows[0].distance} mi away`:'Compare distance, amenities, formats and showtimes near you.'}</p>
    ${dateStrip(data.dates, selectedDate, href)}</div></section>
  <div class="shell">${rows.map(theater=>`<section class="section"><div class="section-head"><div><h2>${esc(theater.name)}</h2><p class="card-meta">${esc(theater.location)} · ${theater.distance} mi · ${theater.services.map(esc).join(' · ')}</p></div>${theaterId?'':`<a href="/theaters/${theater.id}" data-link>See theater</a>`}</div>
    ${theater.movies.length?theater.movies.map(movie=>`<article class="theater-movie">${posterMarkup(movie)}<div><h3><a href="/movies/${movie.id}" data-link>${esc(movie.title)}</a></h3><p class="card-meta">${[movie.rating, movie.runtime, movie.score?`${movie.score}% Audience`:''].filter(Boolean).map(esc).join(' · ')}</p><div class="showtimes">${showtimeButtons(movie.id, {id:theater.id, showtimes:movie.showtimes, date:selectedDate})}</div></div></article>`).join(''):'<p class="card-meta">No showtimes scheduled at this theater.</p>'}
    <details><summary>Policies &amp; amenities</summary><p>${esc(theater.policy)}</p></details></section>`).join('')}</div>`);
  bindShowtimes();
}
function bindShowtimes(){
  root.querySelectorAll('[data-showtime]').forEach(button=>button.addEventListener('click',async()=>{
    try{
      await api('/api/selection/showtime',{method:'POST',body:JSON.stringify({movie_id:button.dataset.movie,theater_id:button.dataset.theater,showtime_id:button.dataset.show,date:button.dataset.date})});
      await refresh(); state.selectedSeats=[]; go('/tickets');
    }catch(err){notify(err.message);}
  }));
}

/* ---------- booking ---------- */
function bookingSteps(active){ const steps=['Tickets','Seats','Review','Confirmation']; return `<ol class="steps">${steps.map((step,i)=>`<li class="${i<=active?'active':''}"><span>${i+1}</span>${step}</li>`).join('')}</ol>`; }
function selectionSummary(selection){
  return `<aside class="order-summary"><h2>Your Movie</h2><h3>${esc(selection.movie||'Choose a showtime')}</h3>${selection.theater?`<p>${esc(selection.theater)}<br>${longDate(selection.date)} · ${esc(selection.time)}<br>${esc(selection.format)}</p>`:''}${selection.ticket_count?`<p><strong>${selection.ticket_count} ticket${selection.ticket_count===1?'':'s'}</strong></p>`:''}${selection.seats?.length?`<p>Seats ${selection.seats.map(esc).join(', ')}</p>`:''}${selection.total?`<dl><div><dt>Tickets</dt><dd>${money(selection.subtotal)}</dd></div><div><dt>Convenience fees</dt><dd>${money(selection.fees)}</dd></div><div><dt>Tax</dt><dd>${money(selection.tax)}</dd></div><div class="total"><dt>Total</dt><dd>${money(selection.total)}</dd></div></dl>`:''}</aside>`;
}
function ticketsPage(){
  const selection=state.data.selection;
  if(!selection.movie){ layout(`<div class="shell"><div class="empty"><h1>Choose a showtime first</h1><p>Pick a movie and time to start a ticket order.</p><a class="primary" href="/movies" data-link>Find Showtimes</a></div></div>`);return; }
  layout(`<div class="shell booking-shell">${bookingSteps(0)}<div class="booking-grid"><section><p class="eyebrow">Select Tickets</p><h1>How many tickets?</h1><form class="ticket-form" data-ticket-form><label>Adult <input name="adults" type="number" min="0" max="8" value="${selection.ticket_types?.Adult??3}"></label><label>Child <input name="children" type="number" min="0" max="8" value="${selection.ticket_types?.Child||0}"></label><label>Senior <input name="seniors" type="number" min="0" max="8" value="${selection.ticket_types?.Senior||0}"></label><div class="inline-error"></div><button class="primary" type="submit">Continue to Seats</button></form></section>${selectionSummary(selection)}</div></div>`);
  root.querySelector('[data-ticket-form]').addEventListener('submit',async event=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);try{await api('/api/selection/tickets',{method:'POST',body:JSON.stringify({adults:Number(form.get('adults')),children:Number(form.get('children')),seniors:Number(form.get('seniors'))})});await refresh();state.selectedSeats=[];go('/tickets/seats');}catch(err){element.querySelector('.inline-error').textContent=err.message;}});
}
function seatMap(){
  const selection=state.data.selection;
  if(!selection.ticket_count){go('/tickets');return;}
  const sold=new Set(selection.sold_seats||[]);
  const rows=selection.seat_rows||['A','B','C','D','E','F','G','H'];
  const perRow=selection.seats_per_row||12;
  const seats=rows.map(row=>`<div class="seat-row"><span>${row}</span>${Array.from({length:perRow},(_,i)=>{const id=`${row}${i+1}`;const center=['D','E','F'].includes(row)&&i>=4&&i<=7;return `<button class="seat ${sold.has(id)?'sold':''} ${state.selectedSeats.includes(id)?'selected':''} ${center?'center':''}" ${sold.has(id)?'disabled':''} data-seat="${id}" aria-label="Seat ${id}${sold.has(id)?', sold':''}" aria-pressed="${state.selectedSeats.includes(id)}">${i+1}</button>`;}).join('')}<span>${row}</span></div>`).join('');
  layout(`<div class="shell booking-shell">${bookingSteps(1)}<div class="booking-grid"><section><p class="eyebrow">Reserved Seating</p><h1>Choose ${selection.ticket_count} adjacent seat${selection.ticket_count===1?'':'s'}</h1><p class="card-meta">Seats must be next to each other in one row. Center seats in rows D–F are highlighted.</p><div class="screen">SCREEN</div><div class="seat-map">${seats}</div><div class="seat-legend"><span><i></i>Available</span><span><i class="center"></i>Center D–F</span><span><i class="selected"></i>Selected</span><span><i class="sold"></i>Sold</span></div><p data-seat-status class="card-meta">${state.selectedSeats.length?`Selected: ${state.selectedSeats.join(', ')}`:'No seats selected'}</p><div class="inline-error"></div><button class="primary" data-continue-seats>Continue to Review</button></section>${selectionSummary({...selection,seats:state.selectedSeats})}</div></div>`);
  root.querySelectorAll('[data-seat]').forEach(button=>button.addEventListener('click',()=>{const id=button.dataset.seat;if(state.selectedSeats.includes(id)){state.selectedSeats=state.selectedSeats.filter(s=>s!==id);}else if(state.selectedSeats.length<selection.ticket_count){state.selectedSeats.push(id);}else{notify(`You selected ${selection.ticket_count} tickets. Deselect a seat first.`);return;}seatMap();}));
  root.querySelector('[data-continue-seats]').addEventListener('click',async()=>{try{await api('/api/selection/seats',{method:'POST',body:JSON.stringify({seats:state.selectedSeats})});await refresh();go('/checkout');}catch(err){root.querySelector('.inline-error').textContent=err.message;}});
}
function checkout(){
  const selection=state.checkoutReview||state.data.selection;
  if(!selection.seats?.length){layout(`<div class="shell"><div class="empty"><h1>Your seat selection is incomplete</h1><p>Pick a showtime and seats before checkout.</p><a class="primary" href="/movies" data-link>Start over</a></div></div>`);return;}
  layout(`<div class="shell booking-shell">${bookingSteps(2)}<div class="booking-grid"><section><p class="eyebrow">Checkout</p><h1>Review and confirm</h1><div class="sandbox-note"><strong>Local Sandbox Payment</strong><p>No card number is accepted and no charge will occur.</p></div><form class="checkout-form" data-review-form><label>Email for local receipt<input name="email" type="email" value="${esc(selection.contact_email||'')}" placeholder="you@example.com" required></label><label>Billing ZIP / postal code<input name="postal_code" value="${esc(selection.billing_postal_code||'')}" placeholder="10003" required></label><fieldset><legend>Payment method</legend><label class="radio"><input type="radio" checked disabled> Local Sandbox — no real payment</label></fieldset><div class="inline-error"></div><button class="primary" type="submit">Calculate Total &amp; Review</button></form>${state.checkoutReview?`<div class="final-review"><h2>Final booking review</h2><p>Verify the movie, showtime, theater, ticket count and adjacent seats before confirming.</p><button class="primary" data-confirm-booking>Confirm Local Booking</button></div>`:''}</section>${selectionSummary(selection)}</div></div>`);
  root.querySelector('[data-review-form]').addEventListener('submit',async event=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);try{state.checkoutReview=await api('/api/checkout/review',{method:'POST',body:JSON.stringify({email:form.get('email'),postal_code:form.get('postal_code')})});checkout();}catch(err){element.querySelector('.inline-error').textContent=err.message;}});
  root.querySelector('[data-confirm-booking]')?.addEventListener('click',async()=>{try{state.confirmation=await api('/api/checkout/confirm',{method:'POST',body:'{}'});await refresh();go('/confirmation');}catch(err){notify(err.message);}});
}
function confirmation(){
  const booking=state.confirmation||state.data.bookings[0];
  if(!booking){layout(`<div class="shell"><div class="empty"><h1>No booking to show</h1><a class="primary" href="/movies" data-link>Find Showtimes</a></div></div>`);return;}
  layout(`<div class="shell confirmation">${bookingSteps(3)}<div class="checkmark">✓</div><p class="eyebrow">Local Booking Confirmed</p><h1>You’re going to ${esc(booking.movie)}!</h1><p class="confirmation-id">Confirmation ${esc(booking.id)}</p><div class="confirmation-card"><h2>${esc(booking.movie)}</h2><dl><div><dt>Theater</dt><dd>${esc(booking.theater)}</dd></div><div><dt>Date &amp; time</dt><dd>${longDate(booking.date)} · ${esc(booking.time)}</dd></div><div><dt>Format</dt><dd>${esc(booking.format)}</dd></div><div><dt>Tickets</dt><dd>${booking.tickets}</dd></div><div><dt>Seats</dt><dd>${booking.seats.map(esc).join(', ')}</dd></div><div><dt>Total</dt><dd>${money(booking.total)}</dd></div></dl></div><p class="card-meta">This confirmation exists only in the local WebsiteBench clone. No real ticket was issued.</p><p><a class="primary" href="/account/bookings" data-link>Manage My Tickets</a></p></div>`);
}

/* ---------- auth ---------- */
function authPage(mode){
  const register=mode==='register', recover=mode==='recover';
  layout(`<section class="auth-page"><div class="auth-card"><a class="logo" href="/" data-link><span class="ticket">F</span>FANDANGO</a>
  <h1>${register?'Create your account':recover?'Reset your password':'Sign in'}</h1>
  <p>${register?'Save movies and manage tickets in one place.':recover?'Preview the reset flow without sending an email.':'Access saved movies and upcoming or past tickets.'}</p>
  <form data-auth-form>${register?'<label>Full name<input name="display_name" autocomplete="name" required></label>':''}
  <label>Email address<input name="email" type="email" autocomplete="email" required></label>
  ${recover?'':`<label>Password<input name="password" type="password" minlength="8" autocomplete="${register?'new-password':'current-password'}" required></label>`}
  ${register?'<label class="radio"><input name="terms" type="checkbox" required> I agree to the <a href="/policies/terms-of-use" data-link>Terms of Use</a> and <a href="/policies/privacy-policy" data-link>Privacy Policy</a>. Your email is verified locally — this site never sends mail.</label>':''}
  <div class="inline-error"></div><button class="primary" type="submit">${register?'Create Account':recover?'Continue':'Sign In'}</button></form>
  <div class="auth-links">${register?'<a href="/account/login" data-link>Already have an account?</a>':recover?'<a href="/account/login" data-link>Return to sign in</a>':'<a href="/account/register" data-link>Create account</a><a href="/account/recover" data-link>Forgot password?</a>'}</div>
  ${recover?'':'<div class="idp"><span>or continue with</span><button type="button" disabled>Google</button><button type="button" disabled>Apple</button></div>'}</div></section>`);
  root.querySelector('[data-auth-form]').addEventListener('submit',async event=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);const endpoint=recover?'recovery-preview':register?'register':'login';try{const result=await api(`/api/auth/${endpoint}`,{method:'POST',body:JSON.stringify(Object.fromEntries(form))});if(recover){element.querySelector('.inline-error').textContent=result.message;}else{await refresh();go('/account');notify(register?'Account created locally. No verification email was sent.':'Signed in');}}catch(err){element.querySelector('.inline-error').textContent=err.message;}});
}

/* ---------- account ---------- */
function account(section='overview'){
  if(!state.data.profile){authPage('login');return;}
  const bookings=state.data.bookings;
  const favorites=state.data.movies.filter(movie=>state.data.favorites.includes(movie.id));
  const content=section==='favorites'
    ? `<h1>My Movies</h1>${favorites.length?`<div class="poster-grid">${favorites.map(movieCard).join('')}</div>`:'<div class="empty"><h2>No saved movies yet</h2><p>Save a movie to find it here later.</p><a class="primary" href="/movies" data-link>Browse movies</a></div>'}`
    : section==='bookings'
      ? `<h1>My Tickets</h1><div class="booking-list">${bookings.length?bookings.map(bookingCard).join(''):'<div class="empty"><h2>No tickets yet</h2><a class="primary" href="/movies" data-link>Find Showtimes</a></div>'}</div>`
      : `<h1>Hi, ${esc(state.data.profile.display_name)}</h1><div class="account-cards"><a href="/account/bookings" data-link><strong>${bookings.length}</strong><span>Upcoming &amp; past tickets</span></a><a href="/favorites" data-link><strong>${favorites.length}</strong><span>Saved movies</span></a></div><button class="save-btn" data-logout>Sign Out</button>`;
  layout(`<div class="shell account-layout"><aside><h2>My Account</h2><a href="/account" data-link>Overview</a><a href="/account/bookings" data-link>My Tickets</a><a href="/favorites" data-link>My Movies</a><a href="/help" data-link>Help</a></aside><div class="account-content">${content}</div></div>`);
  root.querySelector('[data-logout]')?.addEventListener('click',async()=>{await api('/api/auth/logout',{method:'POST',body:'{}'});await refresh();go('/');});
  bindBookingActions();
}
function bookingCard(booking){
  return `<article class="booking-card" data-booking="${booking.id}"><div><span class="status">${esc(booking.status)}</span><h2>${esc(booking.movie)}</h2><p>${esc(booking.theater)} · ${longDate(booking.date)} · ${esc(booking.time)}</p><p>${booking.tickets} tickets · Seats ${booking.seats.map(esc).join(', ')} · ${money(booking.total)}</p>${booking.contact_status?`<p class="notice">${esc(booking.contact_status)}</p>`:''}${booking.review?`<p class="notice">Review: ${esc(booking.review)}</p>`:''}</div><div class="booking-actions"><button data-booking-action="reschedule" data-id="${booking.id}">Reschedule</button><button data-booking-action="cancel" data-id="${booking.id}">Cancel</button><button data-booking-action="contact" data-id="${booking.id}">Contact Theater</button><button data-booking-action="review" data-id="${booking.id}">Write Review</button><button data-booking-action="book-again" data-id="${booking.id}">Book Again</button><a href="/movies" data-link>Back to Movies</a></div></article>`;
}
function bindBookingActions(){
  root.querySelectorAll('[data-booking-action]').forEach(button=>button.addEventListener('click',async()=>{
    let value=null; if(button.dataset.bookingAction==='review') value='5 stars — Great local test experience';
    try{ await api(`/api/bookings/${button.dataset.id}/${button.dataset.bookingAction}`,{method:'POST',body:JSON.stringify({value})}); await refresh();
      if(button.dataset.bookingAction==='book-again'){state.selectedSeats=[];go('/tickets');}else{account('bookings');notify('Booking updated locally');}
    }catch(err){notify(err.message);}
  }));
}

/* ---------- offers ---------- */
function offersPage(){
  const offers=state.data.offers||[];
  const byId=Object.fromEntries(state.data.movies.map(movie=>[movie.id,movie]));
  layout(`<section class="page-title"><div class="shell"><p class="eyebrow">Offers</p><h1>Special Offers</h1>
    <p>Current promotions on movies playing near New York, NY. Every offer applies at checkout in this local recreation.</p></div></section>
  <div class="shell"><section class="section"><div class="offer-list">
    ${offers.map(offer=>{const movie=byId[offer.movie_id];return `<article class="offer-card">
      ${movie?`<a class="poster-link" href="/movies/${movie.id}" data-link>${posterMarkup(movie)}</a>`:''}
      <div><p class="eyebrow">Offer</p><h2><a href="/movies/${offer.movie_id}" data-link>${esc(offer.headline)}</a></h2>
      <p class="card-meta">${esc(offer.detail)}</p>
      <a class="btn-ticket" href="/movies/${offer.movie_id}" data-link>Get Tickets</a></div>
    </article>`;}).join('')}
  </div>
  <p class="card-meta" style="margin-top:20px">Looking for gift cards? See <a href="/help#gift-cards" data-link>the gift card guidance</a> in the Help Center.</p>
  </section></div>`);
}

/* ---------- help, legal, 404 ---------- */
function help(){
  layout(`<section class="page-title"><div class="shell"><p class="eyebrow">Help Center</p><h1>How can we help?</h1><form class="help-search"><input aria-label="Search help" placeholder="Search tickets, refunds or account help"><button type="submit">Search</button></form></div></section>
  <div class="shell help-grid"><article><h2>Tickets &amp; Showtimes</h2><p>Learn how to choose quantities, formats and adjacent seats.</p><a href="/movies" data-link>Find showtimes</a></article>
  <article><h2>Account Access</h2><p>Get help signing in, registering or previewing password recovery.</p><a href="/account/recover" data-link>Password help</a></article>
  <article><h2>Refunds &amp; Failed Actions</h2><p>Manage a local booking, reschedule or cancel before showtime.</p><a href="/account/bookings" data-link>Manage tickets</a></article>
  <article><h2>Contact a Theater</h2><p>The local flow saves a contact request but never sends a real message.</p><a href="/account/bookings" data-link>Open ticket history</a></article>
  <article><h2>Theater Policies</h2><p>Amenities, formats and refund windows for every theater near you.</p><a href="/theaters" data-link>Browse theaters</a></article>
  <article id="gift-cards"><h2>Gift Cards</h2><p>Fandango gift cards are redeemed at checkout on the real site. This offline recreation accepts no card numbers and issues no balances, so gift card redemption is disabled here.</p><a href="/offers" data-link>See current offers</a></article>
  <article><h2>Terms &amp; Privacy</h2><p>What this local recreation stores and what it never collects.</p><a href="/policies/privacy-policy" data-link>Read the policy</a></article></div>`);
  root.querySelector('.help-search').addEventListener('submit',e=>{e.preventDefault();notify('Help results: tickets, account access, refunds and failed actions');});
}
const LEGAL={
  '/policies/terms-of-use':{title:'Terms of Use',intro:'These terms describe how this local Fandango recreation may be used.',sections:[
    ['Acceptance','By browsing showtimes or creating an account here you accept these terms. This is an offline WebsiteBench recreation, so no agreement is formed with Fandango Media, LLC.'],
    ['Tickets and bookings','Every booking, confirmation code and seat assignment produced here exists only in a local database. No ticket is issued and no theater is notified.'],
    ['Payment','No card numbers are accepted anywhere in this recreation, and no charge is ever made. The checkout step is a structural simulation only.'],
    ['Acceptable use','Do not use this recreation to reach the live Fandango service and do not enter real payment or identity details.'],
    ['Changes','These terms may be revised as the recreation changes. Continued use after a revision means you accept it.'],
  ]},
  '/policies/privacy-policy':{title:'Privacy Policy',intro:'This policy explains what this local Fandango recreation stores and what it never collects.',sections:[
    ['What we store','Your display name, email address, password hash, saved movies, ticket selections and bookings are written to a SQLite database on the machine running this site.'],
    ['What we never collect','No card numbers, billing addresses beyond a postal code, government identifiers or location data are requested or accepted.'],
    ['No third parties','Nothing is shared with Fandango, theaters, advertisers or analytics providers. The site makes no outbound network requests at runtime.'],
    ['Email and messaging','Password recovery and "contact theater" actions are previewed locally. No message is ever sent to any address or venue.'],
    ['Deleting your data','Removing the local database file erases every account, booking and saved movie created here.'],
  ]},
};
function legalPage(pathname){
  const page=LEGAL[pathname];
  layout(`<div class="shell legal"><p class="eyebrow">Fandango Policies</p><h1>${esc(page.title)}</h1><p>${esc(page.intro)}</p><p class="card-meta">Last updated August 2026</p>
  ${page.sections.map(([h,c])=>`<section><h2>${esc(h)}</h2><p>${esc(c)}</p></section>`).join('')}
  <div class="legal-links"><a href="/policies/terms-of-use" data-link>Terms of Use</a><a href="/policies/privacy-policy" data-link>Privacy Policy</a><a href="/account/register" data-link>Back to sign up</a><a href="/help" data-link>Help Center</a></div></div>`);
}
function notFound(){
  layout(`<div class="shell not-found"><div class="ticket-stub">404</div><h1>That page missed the show.</h1><p>The link may have changed, but movies and showtimes are still available.</p><div><a class="primary" href="/movies" data-link>Browse Movies</a><a href="/theaters" data-link>Theaters Near You</a><a href="/help" data-link>Visit Help Center</a></div></div>`);
}

/* ---------- wiring ---------- */
function bindGlobal(){
  root.querySelectorAll('[data-link]').forEach(link=>link.addEventListener('click',event=>{if(event.button===0&&!event.ctrlKey&&!event.metaKey){event.preventDefault();go(link.getAttribute('href'));}}));
  root.querySelector('[data-search-form]')?.addEventListener('submit',event=>{event.preventDefault();const q=new FormData(event.currentTarget).get('q');go(`/movies?q=${encodeURIComponent(q)}`);});
  root.querySelectorAll('[data-favorite]').forEach(button=>button.addEventListener('click',async()=>{try{const result=await api(`/api/favorites/${button.dataset.favorite}`,{method:'POST',body:'{}'});await refresh();notify(result.saved?'Saved to My Movies':'Removed from My Movies');render();}catch(err){notify(err.message);}}));
}

async function render(){
  if(!state.data) await refresh();
  const path=location.pathname;
  if(await navigationRoute(path)) return;
  if(path==='/'){home();return;}
  if(path==='/movies'||path==='/search'){await moviesPage();return;}
  if(path.startsWith('/movies/')){await moviePage(path.split('/')[2]);return;}
  if(path==='/theaters'){await theatersPage();return;}
  if(path.startsWith('/theaters/')){await theatersPage(path.split('/')[2]);return;}
  if(path==='/tickets'){ticketsPage();return;}
  if(path==='/tickets/seats'){seatMap();return;}
  if(path==='/checkout'){checkout();return;}
  if(path==='/confirmation'){confirmation();return;}
  if(path==='/account/login'){authPage('login');return;}
  if(path==='/account/register'){authPage('register');return;}
  if(path==='/account/recover'){authPage('recover');return;}
  if(path==='/account/bookings'){account('bookings');return;}
  if(path==='/favorites'){account('favorites');return;}
  if(path==='/account'){account();return;}
  if(path==='/help'){help();return;}
  if(path==='/offers'){offersPage();return;}
  if(LEGAL[path]){legalPage(path);return;}
  notFound();
}

window.addEventListener('popstate',render);
render();
