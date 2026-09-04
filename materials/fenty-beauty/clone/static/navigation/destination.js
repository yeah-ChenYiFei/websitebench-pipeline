import {a as swiper} from './theme/vendor-swiper.Da1fQJcj.min.js';
import './theme/mega-menu.Czt_VZjk.min.js';
import './theme/core-accordion.BUHJZ9sG.min.js';
import './theme/core-carousel.B9osNzbQ.min.js';
import './theme/multi-panel-content.d_x8vGY7.min.js';
import './theme/read-more-toggle.CAYwWotP.min.js';
import './theme/fluid-flex-experience.BK4ySirr.min.js';
import './theme/before-after-steps.Bulbci8e.min.js';
import './theme/split-image-slider.BKWpu36R.min.js';
import {initializeCollections} from './collection.js';

swiper.register();
const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
const saved = new Set(JSON.parse(localStorage.getItem('fenty-home-saved') || '[]'));
let activeDialog, previousFocus;
const videos = fetch('/static/navigation/videos.json').then(r => r.json());
class LocalFavorite extends HTMLElement {
  connectedCallback() {
    this.setAttribute('role','button');this.tabIndex = 0;
    this.setAttribute('aria-pressed',String(saved.has(this.dataset.productId)));
    if (!this.querySelector('svg')) this.innerHTML = '<svg width="24" height="24" aria-hidden="true"><use href="/static/assets/home-20260904/source-icons.svg#icon-wishlist"></use></svg>';
  }
}
if (!customElements.get('rivo-favorite-button')) customElements.define('rivo-favorite-button',LocalFavorite);
if (!customElements.get('rivo-wishlist-button')) customElements.define('rivo-wishlist-button',class extends LocalFavorite {});

function closeDialog() {
  if (!activeDialog) return;
  activeDialog.classList.remove('local-dialog-open');
  activeDialog.setAttribute('aria-hidden', 'true');
  $$('video', activeDialog).forEach(v => v.pause());
  activeDialog = null;
  document.body.classList.remove('local-dialog-visible');
  previousFocus?.focus();
}
function openDialog(dialog) {
  closeDialog();previousFocus = document.activeElement;activeDialog = dialog;
  dialog.removeAttribute('cloak');dialog.classList.add('local-dialog-open');
  dialog.setAttribute('role', 'dialog');dialog.setAttribute('aria-modal', 'true');dialog.setAttribute('aria-hidden', 'false');
  if (!$('[data-local-close]', dialog)) {
    const close = document.createElement('button');
    close.dataset.localClose = '';close.className = 'local-dialog-close';close.ariaLabel = 'Close';close.textContent = '×';
    dialog.prepend(close);
  }
  document.body.classList.add('local-dialog-visible');
  $('button,input,a[href]', dialog)?.focus();
}
function notice(text) {
  let status = $('#local-feedback');
  if (!status) {status = document.createElement('div');status.id = 'local-feedback';status.setAttribute('role', 'status');document.body.append(status);}
  status.textContent = text;status.hidden = false;
  clearTimeout(notice.timer);notice.timer = setTimeout(() => status.hidden = true, 6500);
}

class LocalDeferredMedia extends HTMLElement {
  connectedCallback() {
    if (!this.hasAttribute('playing')) this.setAttribute('playing','false');
    if (this.getAttribute('autoplay') !== 'true') return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) {this.play();observer.disconnect();}
    });
    observer.observe(this);
  }
  async play() {
    let media = $('video', this);
    if (!media) {
      const template = $('template', this);
      if (template) {this.append(template.content.cloneNode(true));media = $('video', this);}
    }
    if (!media) {
      const frame = $('[data-source-frame]', this), id = frame?.dataset.sourceFrame.match(/vimeo.com\/video\/(\d+)/)?.[1];
      const source = id && (await videos)[id];
      if (source) {
        media = document.createElement('video');media.src = source;
        media.className = 'absolute inset-0 w-full h-full object-contain bg-black';media.playsInline = true;
        const poster = $('img', this);if (poster) media.poster = poster.currentSrc;
        this.append(media);
      }
    }
    if (media) {
      media.controls = this.getAttribute('controls') !== 'false' && !$('[play-toggle]',this);media.muted = this.getAttribute('muted') === 'true';media.loop = this.getAttribute('loop') === 'true';
      this.setAttribute('loaded','true');this.setAttribute('playing','true');
      media.play().catch(() => {});$('[play-toggle]',this)?.setAttribute('aria-label','Pause video');
    }
    else notice('This video uses an online player that is unavailable in this local preview.');
  }
  pause() { $('video', this)?.pause();this.setAttribute('playing','false');$('[play-toggle]',this)?.setAttribute('aria-label','Play video'); }
}
if (!customElements.get('deferred-media')) customElements.define('deferred-media', LocalDeferredMedia);

$$('swiper-container').forEach(container => {
  if (container.closest('swiper-thumbnails')) {
    Object.assign(container, {direction:innerWidth >= 1024 ? 'vertical' : 'horizontal',slidesPerView:'auto',freeMode:true,watchSlidesProgress:true});
  } else if (container.closest('swiper-product-gallery')) {
    Object.assign(container, {slidesPerView:'auto',on:{slideChange(s) {s.slides.forEach(slide => $$('video',slide).forEach(v => v.pause()));}}});
  }
  if (!container.swiper) container.initialize();
});
$$('swiper-thumbnails swiper-slide').forEach((slide, index) => slide.addEventListener('click', () => {
  $('swiper-product-gallery swiper-container')?.swiper?.slideTo(index);
}));

function save(button) {
  const holder = button.closest('rivo-favorite-button,rivo-wishlist-button');
  const id = holder?.dataset.productId || holder?.getAttribute('product-id') || $('main-product')?.getAttribute('product-id') || location.pathname;
  saved.has(id) ? saved.delete(id) : saved.add(id);
  localStorage.setItem('fenty-home-saved', JSON.stringify([...saved]));
  button.setAttribute('aria-pressed', String(saved.has(id)));
  notice(saved.has(id) ? 'Saved to your local favorites.' : 'Removed from your local favorites.');
}
document.addEventListener('click', event => {
  const target = event.target.closest('button,a,rivo-favorite-button,rivo-wishlist-button');
  if (!target) return;
  if (target.hasAttribute('data-local-close')) return closeDialog();
  const toggle = target.closest('dialog-toggle');
  if (toggle) {
    const dialog = document.getElementById(toggle.getAttribute('modal-id'));
    if (dialog) {event.preventDefault();openDialog(dialog);return;}
  }
  if (target.closest('rivo-favorite-button,rivo-wishlist-button')) {event.preventDefault();save(target);return;}
  if (target.hasAttribute('data-continue') && target.closest('shade-finder-options')) {
    event.preventDefault();notice('Shade matching requires the online camera or matching service, which is unavailable in this local preview.');return;
  }
  if (target.closest('quantity-input')) {
    const parent = target.closest('quantity-input'), input = $('input', parent);
    if (input) input.value = Math.min(Number(parent.getAttribute('max') || 5), Math.max(1, Number(input.value) + (target.name === 'minus' ? -1 : 1)));
  }
  const media = target.closest('deferred-media');
  if (media) {
    event.preventDefault();
    if (target.hasAttribute('volume-toggle')) {
      const muted = media.getAttribute('muted') !== 'true';media.setAttribute('muted',String(muted));
      if ($('video',media)) $('video',media).muted = muted;else media.play();
    } else if (target.hasAttribute('play-toggle') && media.getAttribute('playing') === 'true') media.pause();
    else media.play();
  }
  if (target.hasAttribute('data-zoom-trigger')) {
    const box = target.closest('[data-zoom-container]'), image = $('[data-zoom-image]', box);
    const zoomed = box.toggleAttribute('data-zoomed');
    image.style.transform = zoomed ? 'scale(2.5)' : '';
    target.ariaLabel = zoomed ? 'Zoom out' : 'Zoom';
  }
  if (target.closest('quick-shop-toggle')) {
    const card = target.closest('.product-card');
    const url = target.closest('quick-shop-toggle').getAttribute('product-url') || $('a[href*="/products/"]', card || target.parentElement)?.href;
    if (url) {event.preventDefault();location.assign(url);}
  }
});
document.addEventListener('change', event => {
  const target = event.target;
  if (target.matches('input[name="shade-finder-option"]')) $('[data-continue]', target.closest('shade-finder-options'))?.removeAttribute('disabled');
  const option = target.matches('select') ? target.selectedOptions[0] : target;
  if (option?.hasAttribute('data-product-url') && !target.closest('fluid-flex-form')) location.assign(option.getAttribute('data-product-url'));
  else if (option?.dataset.variantId && target.closest('variant-picker')) location.assign(`${location.pathname}?variant=${option.dataset.variantId}`);
  if (target.matches('fluid-flex-form select[name="shade"]') && option?.dataset.bottleSrc) {
    const bottle = $('[data-ffe-bottle] img');
    if (bottle) {bottle.removeAttribute('srcset');bottle.src = option.dataset.bottleSrc;}
  }
});
document.addEventListener('input', event => {
  if (!event.target.matches('[data-ffe-field="name"]')) return;
  const label = $('[data-ffe-bottle-label-name]');
  if (label) label.textContent = event.target.value.trim() || label.dataset.default || '';
});
$$('fluid-flex-form [data-ffe-field],fluid-flex-form select[name="shade"]').forEach(input => input.required = true);
document.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.target;
  if (!form.reportValidity()) return;
  if ((form.dataset.sourceAction || '').includes('/cart/add')) {
    notice('Local preview: this item was selected. No purchase or payment has been submitted.');
  } else notice('Preview only: your information has not been sent.');
});
document.addEventListener('keydown', event => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('rivo-favorite-button,rivo-wishlist-button')) {event.preventDefault();save(event.target);}
  if (event.key === 'Escape') {
    closeDialog();
    $$('mega-menu').forEach(menu => menu.activeElement = undefined);
    $$('[data-zoom-image]').forEach(image => image.style.transform = '');
  }
  if (event.key === 'Tab' && activeDialog) {
    const items = $$('button,a[href],input,select,textarea', activeDialog).filter(e => e.getClientRects().length);
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) {event.preventDefault();last?.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault();first?.focus();}
  }
});
const updateHeader = () => {
  const header = $('#main-header');
  if (header) document.documentElement.style.setProperty('--header-height', `${header.offsetHeight}px`);
};
updateHeader();window.addEventListener('resize', updateHeader);
initializeCollections(closeDialog);

$$('subscription-form').forEach(host => {
  host.innerHTML = `<form class="grid grid-cols-1 gap-sm" data-state="idle"><div class="grid grid-cols-1 gap-xs">${[['email','Email address','Email','Subscribe to email'],['phone','Phone number','Phone','Subscribe to SMS']].map(([name,placeholder,label,buttonLabel]) => `<div class="flex items-center rounded-sm border border-foreground"><label for="subscription-${name}" class="sr-only">${label}</label><input type="${name === 'email' ? 'email' : 'tel'}" id="subscription-${name}" name="${name}" class="min-w-0 flex-1 border-0 bg-transparent px-sm py-xs text-caption placeholder:text-foreground focus:ring-0 focus:outline-none disabled:opacity-50" placeholder="${placeholder}" autocomplete="${name === 'email' ? 'email' : 'tel'}"><button type="submit" data-submit-field="${name}" class="btn flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent disabled:opacity-50 md:focus-visible:outline-focus" aria-label="${buttonLabel}"><svg-icon src="icon-arrow" class="block h-4 w-4" aria-hidden="true"><svg><use href="/static/assets/home-20260904/source-icons.svg#icon-arrow"></use></svg></svg-icon></button></div>`).join('')}</div><p class="caption" role="status"></p></form>`;
  $('form',host).addEventListener('submit',event => {
    event.preventDefault();event.stopPropagation();
    const input = $(`[name="${event.submitter?.dataset.submitField || 'email'}"]`,host);
    const valid = input.name === 'email' ? /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value) : /^(1?\d{10})$/.test(input.value.replace(/\D/g,''));
    input.setCustomValidity(valid ? '' : `Please enter a valid ${input.name === 'email' ? 'email address' : 'phone number'}.`);
    if (input.reportValidity()) $('[role="status"]',host).textContent = 'Local preview: nothing was sent or subscribed.';
  });
  host.addEventListener('input',event => event.target.setCustomValidity?.(''));
});

$$('[data-source-contact-form]').forEach(template => {
  const host = template.parentElement, shadow = host.attachShadow({mode:'open'});
  const form = document.createElement('form');
  form.append(template.content.cloneNode(true));shadow.append(form);
  const send = $$('button', shadow).find(b => b.textContent.trim() === 'Send');
  if (send) {send.type = 'submit';send.disabled = false;}
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    let status = $('[role="status"]', shadow);
    if (!status) {status = document.createElement('p');status.setAttribute('role','status');form.append(status);}
    status.textContent = 'Local preview: your message and files have not been sent.';
  });
  shadow.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button?.textContent.includes('Attach Files')) $('input[type="file"]', shadow)?.click();
  });
});
