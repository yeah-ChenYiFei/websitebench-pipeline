(() => {
  const menu = document.querySelector('.menu');
  const nav = document.querySelector('#primary-nav');
  if (menu && nav) {
    menu.addEventListener('click', () => {
      const open = menu.getAttribute('aria-expanded') === 'true';
      menu.setAttribute('aria-expanded', String(!open));
      nav.classList.toggle('nav-open', !open);
      menu.textContent = open ? '☰' : '×';
    });
  }
  document.querySelectorAll('.filters select').forEach((control) => {
    control.addEventListener('change', () => control.form?.requestSubmit());
  });
  document.querySelectorAll('[data-quantity]').forEach((button) => {
    button.addEventListener('click', () => {
      const input = button.parentElement?.querySelector('input[type="number"]');
      if (!input) return;
      const direction = button.dataset.quantity === 'increase' ? 1 : -1;
      const min = Number(input.min || 1);
      const max = Number(input.max || 20);
      input.value = String(Math.min(max, Math.max(min, Number(input.value || min) + direction)));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  document.querySelectorAll('#variant-select').forEach((select) => {
    const product = select.closest('.product-detail');
    const price = product?.querySelector('.price');
    const addButton = product?.querySelector('#add-to-bag');
    const hiddenPrice = select.form?.querySelector('input[name="display_price"]');
    const syncVariant = () => {
      const option = select.selectedOptions[0];
      if (!option) return;
      const rawPrice = option.dataset.price || '0.00';
      const numericPrice = Number(rawPrice);
      if (price) price.textContent = `$${Number.isInteger(numericPrice) ? numericPrice : numericPrice.toFixed(2)}`;
      if (hiddenPrice) hiddenPrice.value = rawPrice;
      if (addButton) addButton.disabled = option.dataset.available !== 'true';
    };
    select.addEventListener('change', syncVariant);
    syncVariant();
  });
  document.querySelectorAll('.pdp-thumbnails').forEach((gallery) => {
    const primary = gallery.closest('.gallery')?.querySelector('.product-primary');
    const thumbnails = Array.from(gallery.querySelectorAll('[data-gallery-src]'));
    if (!primary || !thumbnails.length) return;
    let current = Math.max(0, thumbnails.findIndex((item) => item.classList.contains('active')));
    const activate = (index) => {
      current = (index + thumbnails.length) % thumbnails.length;
      thumbnails.forEach((item, itemIndex) => {
        const active = itemIndex === current;
        item.classList.toggle('active', active);
        if (active) item.setAttribute('aria-current', 'true');
        else item.removeAttribute('aria-current');
      });
      primary.src = thumbnails[current].dataset.gallerySrc;
    };
    thumbnails.forEach((item, index) => item.addEventListener('click', () => activate(index)));
    gallery.querySelector('[data-gallery-direction="previous"]')?.addEventListener('click', () => activate(current - 1));
    gallery.querySelector('[data-gallery-direction="next"]')?.addEventListener('click', () => activate(current + 1));
  });
  document.querySelectorAll('[data-local-newsletter]').forEach((button) => {
    button.addEventListener('click', () => {
      const section = button.closest('.newsletter');
      const input = section?.querySelector('input[type="email"]');
      const status = section?.querySelector('.newsletter-status');
      if (!input || !status) return;
      const valid = /^[^@\s]+@example\.test$/i.test(input.value.trim());
      status.textContent = valid ? 'You are on the local list.' : 'Use an @example.test address.';
    });
  });
  document.querySelectorAll('[data-hero-carousel]').forEach((carousel) => {
    const image = carousel.querySelector('[data-hero-image]');
    const eyebrow = carousel.querySelector('[data-hero-eyebrow]');
    const heading = carousel.querySelector('[data-hero-heading]');
    const subtitle = carousel.querySelector('[data-hero-subtitle]');
    const link = carousel.querySelector('[data-hero-link]');
    const dots = Array.from(carousel.querySelectorAll('[data-hero-index]'));
    const slides = [
      { image: '/static/assets/home-hero-chantecaille.jpg', alt: 'Chantecaille beauty collection', eyebrow: '', heading: '15% Off Chantecaille', subtitle: '', href: '/collections/chantecaille', mode: 'split' },
      { image: '/static/assets/home-hero-m61-desktop.jpg', mobileImage: '/static/assets/home-hero-m61-mobile.jpg', alt: 'M-61 Perfect Collection', eyebrow: 'M-61', heading: 'Perfect for Fall', subtitle: "Soothe skin that's been stressed by summer with the Perfect Collection.", href: '/collections/m-61-perfect-collection', mode: 'promo' },
      { image: '/static/assets/home-hero-fall-desktop.jpg', mobileImage: '/static/assets/home-hero-fall-mobile.jpg', alt: 'Fall beauty routine', eyebrow: '', heading: 'Fall in Love', subtitle: 'New season = new routine. Explore the best in fall beauty!', href: '/collections/fall-beauty-must-haves', mode: 'split' },
    ];
    let current = 0;
    const activate = (index) => {
      current = (index + slides.length) % slides.length;
      const slide = slides[current];
      image.src = matchMedia('(max-width: 800px)').matches && slide.mobileImage ? slide.mobileImage : slide.image;
      image.alt = slide.alt;
      eyebrow.textContent = slide.eyebrow;
      eyebrow.hidden = !slide.eyebrow;
      heading.textContent = slide.heading;
      subtitle.textContent = slide.subtitle;
      subtitle.hidden = !slide.subtitle;
      link.href = slide.href;
      carousel.classList.toggle('hero-promo', slide.mode === 'promo');
      dots.forEach((dot, dotIndex) => {
        dot.classList.toggle('active', dotIndex === current);
        if (dotIndex === current) dot.setAttribute('aria-current', 'true');
        else dot.removeAttribute('aria-current');
      });
    };
    dots.forEach((dot, index) => dot.addEventListener('click', () => activate(index)));
    carousel.querySelector('[data-hero-direction="previous"]')?.addEventListener('click', () => activate(current - 1));
    carousel.querySelector('[data-hero-direction="next"]')?.addEventListener('click', () => activate(current + 1));
    const responsive = matchMedia('(max-width: 800px)');
    responsive.addEventListener?.('change', () => activate(current));
  });
  document.querySelectorAll('[data-brand-carousel]').forEach((carousel) => {
    const row = carousel.querySelector('.product-row');
    if (!row) return;
    carousel.querySelector('[data-brand-direction="previous"]')?.addEventListener('click', () => row.scrollBy({ left: -row.clientWidth * 0.8, behavior: 'smooth' }));
    carousel.querySelector('[data-brand-direction="next"]')?.addEventListener('click', () => row.scrollBy({ left: row.clientWidth * 0.8, behavior: 'smooth' }));
  });
})();
