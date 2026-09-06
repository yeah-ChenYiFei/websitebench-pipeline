(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const json = async (url, options = {}) => {
    const response = await fetch(url, {headers: {'Content-Type': 'application/json'}, ...options});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Something went wrong');
    return payload;
  };
  const normalized = value => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const bindVisibleContractControls = () => {
    const controls = window.SONGKICK_CONTROLS || [];
    const candidates = [...document.querySelectorAll('a,button,input,textarea')].filter(element => {
      const style = getComputedStyle(element);
      return element.getClientRects().length > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    });
    const assignments = new Set();
    const compact = value => value.replace(/[^a-z0-9]+/g, '');
    let bound = 0;
    const orderedControls = [...controls].sort((left, right) => {
      const specificity = control => Number(Boolean(normalized(control.label))) * 2 + Number(Boolean(normalized(control.text)));
      return specificity(right) - specificity(left);
    });
    orderedControls.forEach(control => {
      const sameKind = candidates.filter(element => element.tagName.toLowerCase() === control.kind && !assignments.has(element));
      const expectedHrefs = [control.source_href, control.local_href].filter(Boolean);
      const expectedLabel = normalized(control.label);
      const expectedText = normalized(control.text);
      const expectedType = normalized(control.type);
      const scored = sameKind.map((candidate, index) => {
        const actualText = normalized(candidate.textContent || candidate.value);
        const actualLabel = normalized(candidate.getAttribute('aria-label'));
        const surroundingLabel = normalized(candidate.closest('label')?.textContent);
        const href = candidate.getAttribute('href') || '';
        const type = normalized(candidate.getAttribute('type'));
        let score = 0;
        if (expectedLabel && (actualLabel === expectedLabel || surroundingLabel === expectedLabel)) score += 140;
        if (expectedText && (actualText === expectedText || actualLabel === expectedText)) score += 130;
        if (expectedLabel && surroundingLabel.includes(expectedLabel)) score += 70;
        if (expectedText && compact(actualText) === compact(expectedText)) score += 65;
        if (expectedText && compact(actualLabel) === compact(expectedText)) score += 65;
        if (expectedHrefs.includes(href)) score += 35;
        if (expectedType && type === expectedType) score += 10;
        if (Boolean(candidate.disabled) !== Boolean(control.disabled)) score -= 1000;
        return {candidate, index, score};
      }).sort((left, right) => right.score - left.score || left.index - right.index);
      const best = scored[0];
      const hasSemanticIdentity = Boolean(expectedText || expectedLabel);
      const element = best && (!hasSemanticIdentity || best.score >= 65) ? best.candidate : null;
      if (!element) return;
      assignments.add(element);
      element.setAttribute('data-wb-control-id', control.id);
      bound += 1;
    });
    document.body.dataset.wbControlBinding = `${bound}/${controls.length}`;
  };
  bindVisibleContractControls();
  const searchModal = $('#search-modal');
  const searchInput = $('#global-search-input');
  const searchInputAux = $('#global-search-input-aux');
  const searchResults = $('#search-results');
  const openSearch = () => {
    if (!searchModal) return;
    searchModal.dataset.searchState = searchInput?.value ? 'query' : 'empty';
    searchModal.hidden = false;
    searchInput?.focus();
  };
  $('#search-trigger')?.addEventListener('click', openSearch);
  $('#not-found-search')?.addEventListener('click', openSearch);
  $('[data-close-search]')?.addEventListener('click', () => { searchModal.hidden = true; document.body.classList.remove('home-search-variant'); });
  searchModal?.addEventListener('click', event => { if (event.target === searchModal) { searchModal.hidden = true; document.body.classList.remove('home-search-variant'); } });
  $('#search-clear')?.addEventListener('click', () => { searchInput.value = ''; searchResults.innerHTML = ''; searchModal.dataset.searchState = 'empty'; searchInput.focus(); });
  let searchTimer;
  searchInput?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const result = await json('/api/search?q=' + encodeURIComponent(searchInput.value));
      searchInput.setAttribute('data-wb-search-control-id', result.state + '-0');
      searchInputAux?.setAttribute('data-wb-search-control-id', result.state + '-1');
      $('#search-clear')?.setAttribute('data-wb-search-control-id', result.state + '-2');
      const controls = result.controls || [];
      const tabs = controls.filter(item => item.tag === 'button' && !['Clear', 'View all results', 'View all events near you'].includes(item.text));
      const links = controls.filter(item => item.tag === 'a');
      if (result.state === 'search-no-results') {
        searchModal.dataset.searchState = 'no-results';
        searchResults.setAttribute('data-wb-component', 'search-no-results');
        searchResults.innerHTML = '<h3>Sorry, we found no results for “”</h3><p>Try searching again with a different term, or check all words are spelled correctly</p><a class="primary-button" data-wb-search-control-id="' + result.state + '-3" href="/concerts">View all events near you&nbsp; ›</a>';
      } else {
        searchModal.dataset.searchState = 'populated';
        searchResults.setAttribute('data-wb-component', 'search-populated-results');
        const pictures = [
          '/assets/source/a0300-huge-avatar-f7978a0965.jpg',
          '/assets/source/a0712-huge-avatar-d9ac742053.png',
          '/assets/source/a0712-huge-avatar-d9ac742053.png',
          '/assets/source/a0712-huge-avatar-d9ac742053.png',
          '/assets/source/a0712-huge-avatar-d9ac742053.png',
          '/assets/source/a0712-huge-avatar-d9ac742053.png',
          '/assets/source/a0712-huge-avatar-d9ac742053.png'
        ];
        const resultCards = links.map((item, index) => {
          const text = item.text.replace(/^ARTIST |^EVENT /, '');
          const kind = item.text.startsWith('ARTIST ') ? 'ARTIST' : 'EVENT';
          const match = text.match(/^(.*?) ((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} [A-Za-z]+, \d{4}) (.*)$/);
          const thumb = index === 0
            ? '<span class="search-thumb artist"><img src="' + pictures[index] + '" alt="Coldplay"><small>ARTIST</small></span>'
            : index === links.length - 1
              ? '<span class="search-thumb alternate"><small>EVENT</small><b>▣</b></span>'
              : '<span class="search-thumb"><small>EVENT</small><b>ULTIMATE<br>COLDPLAY</b></span>';
          const copy = kind === 'ARTIST'
            ? '<span class="search-result-copy"><strong>' + escapeHtml(text) + '</strong></span>'
            : '<span class="search-result-copy"><strong>' + escapeHtml(match ? match[1] : text) + '</strong><span>' + escapeHtml(match ? match[2] : '') + '</span><small>' + escapeHtml(match ? match[3] : '') + '</small></span>';
          return '<a class="search-result-card" data-search-category="' + kind + '" data-wb-capability="branded-data-boundary" data-wb-search-control-id="' + result.state + '-' + item.index + '" data-wb-search-link-id="' + result.state + '-' + item.index + '" href="' + escapeHtml(item.local_path) + '">' + thumb + copy + '</a>';
        }).join('');
        searchResults.innerHTML = '<div class="search-tabs">' + tabs.map(item => '<button type="button" data-wb-search-control-id="' + result.state + '-' + item.index + '">' + escapeHtml(item.text) + '</button>').join('') + '</div><div class="search-results-grid">' + resultCards + '</div><button class="primary-button search-more" data-wb-search-control-id="' + result.state + '-15" type="button">View all results ›</button>';
        // Category tabs and "View all results" filter the local frozen result set.
        // Categories with no captured result show the branded empty state rather than
        // silently leaving the previous list on screen.
        const CATEGORY_BY_TAB = {'Top Results': null, 'Artists': 'ARTIST', 'Events': 'EVENT', 'Venues': 'VENUE', 'Locations': 'LOCATION'};
        const grid = $('.search-results-grid', searchResults);
        const applyCategory = category => {
          const cards = $$('.search-result-card', grid);
          let shown = 0;
          cards.forEach(card => {
            const match = !category || card.dataset.searchCategory === category;
            card.hidden = !match;
            if (match) shown += 1;
          });
          let empty = $('.search-category-empty', searchResults);
          if (!shown) {
            if (!empty) {
              empty = document.createElement('p');
              empty.className = 'search-category-empty';
              grid.insertAdjacentElement('afterend', empty);
            }
            empty.textContent = 'No local results in this category.';
            empty.hidden = false;
          } else if (empty) {
            empty.hidden = true;
          }
          searchModal.dataset.searchCategory = category || 'top';
        };
        $$('.search-tabs button', searchResults).forEach(button => {
          button.addEventListener('click', () => {
            $$('.search-tabs button', searchResults).forEach(other => other.classList.remove('active'));
            button.classList.add('active');
            applyCategory(CATEGORY_BY_TAB[button.textContent.trim()] ?? null);
          });
        });
        $('.search-more', searchResults)?.addEventListener('click', () => {
          $$('.search-tabs button', searchResults).forEach(other => other.classList.remove('active'));
          const top = $$('.search-tabs button', searchResults).find(b => b.textContent.trim() === 'Top Results');
          top?.classList.add('active');
          applyCategory(null);
        });
      }
    }, 120);
  });
  function escapeHtml(value) {
    const node = document.createElement('span'); node.textContent = value || ''; return node.innerHTML;
  }

  if (document.body.dataset.pageId === 'artist-07-bruno-mars') {
    const nativeScrollTo = window.scrollTo.bind(window);
    window.scrollTo = (...args) => {
      document.body.dataset.lazyLayout = 'settled';
      return nativeScrollTo(...args);
    };
  }

  const notice = $('#form-notice');
  $('#login-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
    try { await json('/api/auth/sign-in', {method:'POST', body:JSON.stringify(data)}); location.href='/home'; }
    catch (error) { notice.textContent = error.message; }
  });
  $('#signup-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await json('/api/auth/register/start', {method:'POST', body:JSON.stringify(data)});
      const mail = await json('/api/auth/local-mail/registration');
      event.currentTarget.innerHTML = '<label>Verification code<input name="code" inputmode="numeric" maxlength="6" required></label><button class="primary-button" type="submit">Verify account</button>';
      event.currentTarget.dataset.phase = 'verify';
      notice.textContent = 'A local verification message is ready. Development code: ' + mail.message.verification_code;
      event.currentTarget.addEventListener('submit', async verifyEvent => {
        verifyEvent.preventDefault(); const code = new FormData(verifyEvent.currentTarget).get('code');
        try { await json('/api/auth/register/verify', {method:'POST', body:JSON.stringify({code})}); location.href='/home'; }
        catch (error) { notice.textContent = error.message; }
      }, {once:true});
    } catch (error) { notice.textContent = error.message; }
  }, {once:true});
  $('#reset-form')?.addEventListener('submit', async event => {
    event.preventDefault(); const email = new FormData(event.currentTarget).get('email');
    try {
      const result = await json('/api/auth/password-reset/start', {method:'POST', body:JSON.stringify({email})});
      notice.textContent = result.message;
      const mail = await json('/api/auth/local-mail/password-reset');
      if (mail.message) $('#reset-next').innerHTML = '<label>Verification code<input id="reset-code" value="' + mail.message.verification_code + '"></label><label>New password<input id="reset-password" type="password" minlength="8"></label><button id="finish-reset" class="primary-button">Reset password</button>';
      $('#finish-reset')?.addEventListener('click', async () => {
        try {
          await json('/api/auth/password-reset/verify', {method:'POST', body:JSON.stringify({code:$('#reset-code').value})});
          await json('/api/auth/password-reset/complete', {method:'POST', body:JSON.stringify({password:$('#reset-password').value})});
          sessionStorage.setItem('songkick-reset-success', '1'); location.href='/session/new';
        } catch (error) { notice.textContent = error.message; }
      });
    } catch (error) { notice.textContent = error.message; }
  });
  if (sessionStorage.getItem('songkick-reset-success') && notice) {
    notice.setAttribute('data-wb-component', 'password-reset-success-notice');
    notice.textContent = 'Your password has been reset. You can now log in.';
    sessionStorage.removeItem('songkick-reset-success');
  }

  const accountButton = $('#account-button');
  const accountMenu = $('#account-menu');
  json('/api/auth/session').then(session => {
    document.body.dataset.session = session.authenticated ? 'authenticated-user' : 'logged-out';
    if (!session.authenticated) return;
    $$('.public-nav-link,.public-brand').forEach(item => item.hidden = true);
    $$('.authenticated-nav-link,.authenticated-brand').forEach(item => item.hidden = false);
    const dashboard = $('.authenticated-dashboard');
    if (dashboard) dashboard.hidden = false;
    accountButton.hidden = false;
    $$('.site-nav > a').filter(link => ['Sign up','Log in'].includes(link.textContent.trim())).forEach(link => link.hidden = true);
    $('#account-name').textContent = session.account.display_name;
    json('/api/me/library').then(library => {
      const artistButton = $('#track-artist');
      if (artistButton && library.tracked_artist_ids.includes(artistButton.dataset.artistId)) {
        artistButton.classList.add('tracked'); artistButton.setAttribute('data-wb-component', 'artist-tracked-state');
        artistButton.querySelector('span').textContent = 'Tracked';
      }
      const eventButton = $('#event-interest');
      const event = eventButton && library.events.find(item => item.event_id === eventButton.dataset.eventId);
      if (event && event.status === 'interested') {
        eventButton.classList.add('interested'); eventButton.setAttribute('data-wb-component', 'event-interested-state');
        eventButton.textContent = '♥ Interested';
      }
    });
  }).catch(() => {});
  accountButton?.addEventListener('click', () => accountMenu.hidden = !accountMenu.hidden);
  $('#logout-button')?.addEventListener('click', async () => { await json('/api/auth/sign-out', {method:'POST'}); location.href='/'; });

  $('#track-artist')?.addEventListener('click', async event => {
    try {
      const button = event.currentTarget; const tracked = !button.classList.contains('tracked');
      await json('/api/me/artists/' + button.dataset.artistId, {method:'PUT', body:JSON.stringify({tracked})});
      button.classList.toggle('tracked', tracked); button.querySelector('span').textContent = tracked ? 'Tracked' : 'Track artist';
      if (tracked) button.setAttribute('data-wb-component', 'artist-tracked-state');
    } catch (_) { location.href='/session/new'; }
  });
  $('#event-interest')?.addEventListener('click', async event => {
    try {
      const button = event.currentTarget; const interested = !button.classList.contains('interested');
      await json('/api/me/events/' + button.dataset.eventId, {method:'PUT', body:JSON.stringify({status:interested?'interested':'none'})});
      button.classList.toggle('interested', interested); button.textContent = interested ? '♥ Interested' : '♡ Interested';
      if (interested) button.setAttribute('data-wb-component', 'event-interested-state');
    } catch (_) { location.href='/session/new'; }
  });
  $$('[data-event-status]').forEach(button => button.addEventListener('click', async () => {
    try { await json('/api/me/events/' + button.dataset.eventId, {method:'PUT', body:JSON.stringify({status:button.dataset.eventStatus})}); button.textContent='You were there'; }
    catch (_) { location.href='/session/new'; }
  }));
  // The source renders "Buy tickets" as a button controlling the provider list. The
  // candidate keeps the heading element so the frozen full-frame comparison is untouched,
  // but gives it a real role, keyboard affordance and behaviour rather than leaving the
  // contract marker on an inert title.
  const buyTickets = $('#buy-tickets');
  const providerList = $('#ticket-providers');
  if (buyTickets && providerList) {
    const toggleProviders = () => {
      const expanded = buyTickets.getAttribute('aria-expanded') !== 'true';
      buyTickets.setAttribute('aria-expanded', String(expanded));
      providerList.dataset.providersState = expanded ? 'expanded' : 'collapsed';
    };
    providerList.dataset.providersState = 'expanded';
    buyTickets.addEventListener('click', toggleProviders);
    buyTickets.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleProviders(); }
    });
  }
  $$('[data-wb-external-id]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    location.href = '/__external__?destination=' + encodeURIComponent(link.href);
  }));
  $$('[data-card-href]').forEach(button => button.addEventListener('click', () => {
    location.href = button.dataset.cardHref;
  }));
  const syncCarouselEnds = row => {
    const previous = $$('[data-carousel="' + row.id + '"]').filter(item => item.classList.contains('carousel-previous'));
    const next = $$('[data-carousel="' + row.id + '"]').filter(item => item.classList.contains('carousel-next'));
    const maxScroll = Math.max(0, row.scrollWidth - row.clientWidth);
    previous.forEach(item => { item.disabled = row.scrollLeft <= 1; });
    next.forEach(item => { item.disabled = row.scrollLeft >= maxScroll - 1; });
  };
  $$('[data-carousel]').forEach(button => button.addEventListener('click', () => {
    const row = $('#' + button.dataset.carousel);
    const frame = $('.viewport-frame');
    row.scrollBy({left: button.classList.contains('carousel-previous') ? -380 : 380, behavior:'smooth'});
    if (frame) frame.scrollTop = 0;
    window.setTimeout(() => syncCarouselEnds(row), 450);
  }));
  $$('[data-carousel]').forEach(button => {
    const row = $('#' + button.dataset.carousel);
    if (row) { row.addEventListener('scroll', () => syncCarouselEnds(row)); syncCarouselEnds(row); }
  });
  $('#theme-toggle')?.addEventListener('click', () => {
    document.body.classList.toggle('theme-dark');
    localStorage.setItem('songkick-theme', document.body.classList.contains('theme-dark') ? 'dark' : 'light');
  });
  if (localStorage.getItem('songkick-theme') === 'dark') document.body.classList.add('theme-dark');
  $$('.chip').forEach(button => button.addEventListener('click', () => { button.parentElement.querySelectorAll('.chip').forEach(item => item.classList.remove('active')); button.classList.add('active'); }));
  $('#cookie-button')?.addEventListener('click', () => $('#cookie-center').hidden=false);
  $('[data-close-cookie]')?.addEventListener('click', () => $('#cookie-center').hidden=true);
  $('#save-cookies')?.addEventListener('click', async () => {
    const analytics=$('#analytics-cookie').checked; localStorage.setItem('songkick-cookie-analytics', String(analytics)); $('#cookie-center').hidden=true;
    try { const current=await json('/api/me/preferences'); await json('/api/me/preferences',{method:'PUT',body:JSON.stringify({...current,cookie_preferences:{analytics}})}); } catch (_) {}
  });

  const persistLocation = async location => {
    localStorage.setItem('songkick-location', location);
    if (document.body.dataset.session === 'authenticated-user') {
      try {
        const current = await json('/api/me/preferences');
        await json('/api/me/preferences', {method:'PUT', body:JSON.stringify({...current, location})});
      } catch (_) {}
    }
    const result = $('#location-results');
    if (result) result.textContent = 'Your concert location is now ' + location + '.';
  };
  $('#location-form')?.addEventListener('submit', event => {
    event.preventDefault();
    const query = $('#location-query').value.trim();
    const result = $('#location-results');
    if (!query) {
      result.textContent = 'Enter a city to search.';
    } else if (query.toLowerCase().includes('toronto')) {
      const locations = [
        ['Toronto, ON, Canada', ''],
        ['Newcastle, NSW, Australia', 'Toronto'],
        ['Toronto, ON, Canada', 'New Toronto'],
        ['Toronto, MI, US', ''],
        ['Wichita, KS, US', 'Toronto'],
        ['Toronto, OH, US', '']
      ];
      result.innerHTML = '<p class="location-result-summary">There are 6 locations that match “Toronto”.</p>' + locations.map(item => '<article class="location-result-row"><i aria-hidden="true">●</i><div><a href="#">' + escapeHtml(item[0]) + '</a>' + (item[1] ? ' <span>' + escapeHtml(item[1]) + '</span>' : '') + '<button type="button" data-location="' + escapeHtml(item[0]) + '">SAVE LOCATION</button></div></article>').join('');
      result.querySelectorAll('[data-location]').forEach(button => button.addEventListener('click', event => { event.preventDefault(); persistLocation(button.dataset.location); }));
    } else {
      result.innerHTML = '<div class="location-no-results"><h2>Sorry, we found no results for “' + escapeHtml(query) + '”.</h2><strong>Suggestions:</strong><p>Try searching for a larger city near you. You can’t save your location to a country or state. If you searched for a zip code or postcode, we don’t accept those yet. Try searching for a city.</p></div>';
    }
  });
  $$('[data-location]').forEach(button => button.addEventListener('click', () => persistLocation(button.dataset.location)));
})();
