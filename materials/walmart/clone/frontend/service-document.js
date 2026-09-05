(()=>{
 const source=document.body.dataset.serviceSource,dialog=document.getElementById('service-action-dialog');
 let lastHeight=0;
 const resize=()=>{const height=Math.ceil(document.body.getBoundingClientRect().height);if(height!==lastHeight){lastHeight=height;parent.postMessage({type:'service-height',height},location.origin);}};
 new ResizeObserver(resize).observe(document.body);window.addEventListener('load',resize);document.fonts.ready.then(resize);
 const official=(title,href=source)=>{dialog.querySelector('[data-service-action-title]').textContent=title;dialog.querySelector('.service-continue').href=href;dialog.showModal();};
 const slickMove=(slider,index)=>{const slides=[...slider.querySelectorAll('.slick-track > .slick-slide:not(.slick-cloned)')],track=slider.querySelector('.slick-track');if(!slides.length||!track)return;index=(index+slides.length)%slides.length;slider.dataset.localSlide=index;track.style.transform=`translate3d(${-slides[index].offsetLeft}px,0,0)`;slides.forEach((slide,i)=>{slide.classList.toggle('slick-current',i===index);slide.classList.toggle('slick-active',i===index);slide.setAttribute('aria-hidden',String(i!==index));});slider.querySelectorAll('.slick-dots li').forEach((dot,i)=>{dot.classList.toggle('slick-active',i===index);dot.querySelector('button')?.setAttribute('aria-current',String(i===index));});};
 document.addEventListener('submit',e=>{e.preventDefault();official('Continue on the official website');});
 document.addEventListener('click',e=>{
  const close=e.target.closest('[data-service-close]');if(close){dialog.close();return;}
  const privateField=e.target.closest('[data-private-field]');if(privateField){official('Sign in securely on Walmart.com');return;}
  const button=e.target.closest('button');if(!button)return;
  if(button.matches('.nav-item-more')){const item=button.closest('.nav-item'),menu=item.querySelector('.dropdown-menu'),open=button.getAttribute('aria-expanded')!=='true';document.querySelectorAll('.dropdown-menu.show').forEach(x=>x.classList.remove('show'));menu?.classList.toggle('show',open);button.setAttribute('aria-expanded',String(open));return;}
  if(button.matches('[data-toggle="collapse"]')){const panel=document.querySelector(button.dataset.target);if(panel){const open=!panel.classList.contains('show');panel.classList.toggle('show',open);button.setAttribute('aria-expanded',String(open));}return;}
  const slider=button.closest('.slick-slider');if(slider){const index=Number(slider.dataset.localSlide||0);if(button.closest('.slick-dots'))slickMove(slider,[...button.closest('ul').children].indexOf(button.parentElement));else if(button.matches('.slick-prev,.slick-next'))slickMove(slider,index+(button.matches('.slick-prev')?-1:1));else if(button.matches('.slick-autoplay-toggle-button')){button.classList.toggle('paused');button.setAttribute('aria-pressed',String(button.classList.contains('paused')));}return;}
  if(button.hasAttribute('data-service-accordion')){const panel=button.closest('.expand-collapse-section').querySelector('[data-service-answer]');const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));panel.hidden=!open;const icon=button.querySelector('i');if(icon)icon.className=icon.className.replace(open?'ChevronDown':'ChevronUp',open?'ChevronUp':'ChevronDown');return;}
  if(button.hasAttribute('data-service-carousel')){let section=button.parentElement,track;while(section&&section!==document.body&&!track){track=[...section.querySelectorAll('ul,[role="list"],div')].find(x=>x.scrollWidth>x.clientWidth+40&&/auto|scroll|hidden/.test(getComputedStyle(x).overflowX));section=section.parentElement;}if(track)track.scrollBy({left:track.clientWidth*.85*Number(button.dataset.serviceCarousel),behavior:'smooth'});return;}
  if(button.dataset.serviceLink){const target=button.dataset.serviceLink;if(target.startsWith('/'))parent.location.assign(target);else official('View this item on Walmart.com',target);return;}
  if(button.dataset.serviceAction){official(button.dataset.serviceAction);}
 });
})();
