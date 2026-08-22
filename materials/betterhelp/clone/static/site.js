(() => {
  const banner = document.querySelector('[data-close-cookie]');
  if (banner) banner.addEventListener('click', () => document.querySelector('#cookie-banner')?.remove());
  document.querySelectorAll('[data-open-sharing]').forEach((button) => button.addEventListener('click', () => {
    const bannerEl = document.querySelector('#cookie-banner');
    if (bannerEl) bannerEl.insertAdjacentHTML('beforeend', '<div class="sharing-popover" role="dialog"><strong>Sharing settings</strong><p>Review your privacy and sharing preferences.</p><button data-dismiss-sharing>Close</button></div>');
    document.querySelector('[data-dismiss-sharing]')?.addEventListener('click', () => document.querySelector('.sharing-popover')?.remove());
  }));
  const toggle = document.querySelector('[data-menu-toggle]');
  toggle?.addEventListener('click', () => { const nav = document.querySelector('.main-nav'); const open = nav?.classList.toggle('is-open'); toggle.setAttribute('aria-expanded', String(Boolean(open))); });
  document.querySelector('[data-google-login]')?.addEventListener('click', () => {
    const note = document.querySelector('[data-provider-note]');
    if (note) note.hidden = false;
    document.querySelector('#emailInput')?.focus();
  });
  const firstFaq = document.querySelector('.faq-list details');
  if (firstFaq) {
    const syncFaqViewport = () => { firstFaq.open = window.innerWidth > 560; };
    syncFaqViewport();
    window.addEventListener('resize', syncFaqViewport);
  }
  const quotes = [
    ['“I feel heard and supported every time we talk.”', '— BetterHelp member'],
    ['“The flexibility of online therapy made it possible for me to start.”', '— BetterHelp member'],
    ['“My therapist gives me tools I can use every day.”', '— BetterHelp member'],
  ]; let current = 0;
  const quote = document.querySelector('[data-quote]'); const author = document.querySelector('[data-author]');
  const loginDots = [...document.querySelectorAll('[data-login-dot]')];
  const render = () => { if (quote && author) { quote.textContent = quotes[current][0]; author.textContent = quotes[current][1]; loginDots.forEach((dot, index) => dot.classList.toggle('active', index === current)); } };
  document.querySelector('[data-next]')?.addEventListener('click', () => { current = (current + 1) % quotes.length; render(); });
  document.querySelector('[data-prev]')?.addEventListener('click', () => { current = (current + quotes.length - 1) % quotes.length; render(); });
  loginDots.forEach((dot) => dot.addEventListener('click', () => { current = Number(dot.dataset.loginDot); render(); }));
  document.querySelector('[data-load-more]')?.addEventListener('click', (event) => { event.currentTarget.textContent = 'All reviews loaded'; event.currentTarget.disabled = true; });
  const adviceSlides = [
    'How can I refresh my routine this spring if I’m feeling mentally drained?',
    'How does stress affect the body?',
    'What is the mind body connection and how can you cultivate it?',
  ];
  const adviceTitle = document.querySelector('[data-advice-title]');
  const adviceStatus = document.querySelector('[data-advice-status]');
  const adviceDots = [...document.querySelectorAll('[data-advice-dot]')];
  let adviceIndex = 0;
  const renderAdvice = () => {
    if (!adviceTitle) return;
    adviceTitle.textContent = adviceSlides[adviceIndex];
    if (adviceStatus) adviceStatus.textContent = `Advice slide ${adviceIndex + 1} of ${adviceSlides.length}`;
    adviceDots.forEach((dot, index) => dot.classList.toggle('active', index === adviceIndex));
  };
  document.querySelector('[data-advice-next]')?.addEventListener('click', () => { adviceIndex = (adviceIndex + 1) % adviceSlides.length; renderAdvice(); });
  document.querySelector('[data-advice-prev]')?.addEventListener('click', () => { adviceIndex = (adviceIndex + adviceSlides.length - 1) % adviceSlides.length; renderAdvice(); });
  adviceDots.forEach((dot) => dot.addEventListener('click', () => { adviceIndex = Number(dot.dataset.adviceDot); renderAdvice(); }));
})();
