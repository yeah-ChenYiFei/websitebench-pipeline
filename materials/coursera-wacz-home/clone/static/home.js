import { createPromoState } from './promo-state.js';


const promoRegion = document.querySelector('[data-promo-region]');
const promoGrid = promoRegion?.querySelector('.promo-grid');
const promoCards = [...document.querySelectorAll('[data-promo-card]')];
const promoDots = [...document.querySelectorAll('[data-promo-dot]')];
const promoStatus = document.querySelector('[data-promo-status]');

if (promoRegion && promoGrid && promoCards.length > 0) {
  const promoState = createPromoState({
    itemCount: promoCards.length,
    visibleCount: 2,
    onChange: ({ index, visibleIndexes }) => {
      const visibleSet = new Set(visibleIndexes);
      const hiddenIndexes = promoCards
        .map((_, cardIndex) => cardIndex)
        .filter((cardIndex) => !visibleSet.has(cardIndex));

      for (const cardIndex of [...visibleIndexes, ...hiddenIndexes]) {
        const card = promoCards[cardIndex];
        const visible = visibleSet.has(cardIndex);
        card.hidden = !visible;
        card.setAttribute('aria-hidden', String(!visible));
        promoGrid.append(card);
      }

      promoDots.forEach((dot, dotIndex) => {
        const current = dotIndex === index;
        dot.classList.toggle('is-current', current);
        if (current) {
          dot.setAttribute('aria-current', 'true');
        } else {
          dot.removeAttribute('aria-current');
        }
      });

      if (promoStatus) {
        const labels = visibleIndexes.map((cardIndex) => cardIndex + 1).join(' and ');
        promoStatus.textContent = `Displaying items ${labels} of ${promoCards.length}.`;
      }
    },
  });

  document.querySelector('[data-promo-next]')?.addEventListener('click', () => promoState.next());
  document.querySelector('[data-promo-prev]')?.addEventListener('click', () => promoState.previous());
  promoDots.forEach((dot) => {
    dot.addEventListener('click', () => promoState.goTo(Number(dot.dataset.promoDot)));
  });
  promoRegion.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      promoState.next();
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      promoState.previous();
    }
  });
}


const exploreToggle = document.querySelector('[data-explore-toggle]');
const exploreMenu = document.querySelector('#explore-menu');
exploreToggle?.addEventListener('click', () => {
  const expanded = exploreToggle.getAttribute('aria-expanded') === 'true';
  exploreToggle.setAttribute('aria-expanded', String(!expanded));
  exploreMenu.hidden = expanded;
});


const archiveNotice = document.querySelector('[data-archive-notice]');
const showArchiveBoundary = () => {
  archiveNotice.textContent = 'The supplied archive contains the homepage only. This action stays in the offline reconstruction.';
  archiveNotice.hidden = false;
};

document.querySelectorAll('[data-archive-boundary]').forEach((control) => {
  control.addEventListener('click', (event) => {
    event.preventDefault();
    showArchiveBoundary();
  });
});
document.querySelector('[data-archive-search]')?.addEventListener('submit', (event) => {
  event.preventDefault();
  showArchiveBoundary();
});


const cookieDialog = document.querySelector('[data-cookie-dialog]');
document.querySelector('[data-cookie-open]')?.addEventListener('click', () => {
  cookieDialog.showModal();
});
document.querySelectorAll('[data-cookie-close]').forEach((control) => {
  control.addEventListener('click', () => cookieDialog.close());
});
