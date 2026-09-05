'use strict';
(() => {
 const root=document.querySelector('[data-pdp]');if(!root)return;
 const $=s=>root.querySelector(s),$$=s=>[...root.querySelectorAll(s)];
 const data=JSON.parse($('#pdp-data').textContent),dialog=$('.pdp-lightbox');let images=data.images,index=0,returnFocus,reviewPhoto=false;
 const status=message=>{$('[data-pdp-status]').textContent=message;};
 function showImage(i){index=(i+images.length)%images.length;$('.pdp-enlarge img').src='/static/assets/'+images[index];$$('[data-gallery-index]').forEach((b,n)=>b.setAttribute('aria-pressed',String(n===index)));if(dialog.open&&!reviewPhoto){$('.pdp-lightbox>img').src='/static/assets/'+images[index];$('[data-light-counter]').textContent=`${index+1} / ${images.length}`;}}
 function bindThumbs(){$$('[data-gallery-index]').forEach(b=>b.addEventListener('click',()=>showImage(Number(b.dataset.galleryIndex))));}
 bindThumbs();$('[data-gallery-next]').addEventListener('click',()=>showImage(index+1));
 function openImage(trigger,url){returnFocus=trigger;reviewPhoto=Boolean(url);$('.pdp-lightbox>img').src=url||$('.pdp-enlarge img').src;$$('[data-light-step]').forEach(b=>b.hidden=reviewPhoto||images.length<2);$('[data-light-counter]').textContent=reviewPhoto?'Customer photo':`${index+1} / ${images.length}`;dialog.showModal();}
 $$('[data-zoom]').forEach(b=>b.addEventListener('click',()=>openImage(b)));
 $$('[data-review-image]').forEach(b=>b.addEventListener('click',()=>openImage(b,'/static/assets/'+b.dataset.reviewImage)));
 $('[data-zoom-close]').addEventListener('click',()=>dialog.close());dialog.addEventListener('close',()=>returnFocus?.focus());dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
 $$('[data-light-step]').forEach(b=>b.addEventListener('click',()=>showImage(index+Number(b.dataset.lightStep))));dialog.addEventListener('keydown',e=>{if(!reviewPhoto&&['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();showImage(index+(e.key==='ArrowRight'?1:-1));}});
 $('[data-pdp-share]').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(location.href);status('Product link copied');const b=$('[data-pdp-share]');b.setAttribute('aria-label','Product link copied');}catch{status('Copy the product link from your address bar.');}});
 function chooseVariant(){
  const keys=$$('[data-criterion]:checked').map(x=>x.value);const entry=Object.entries(data.variants).find(([,v])=>keys.length===v.keys.length&&keys.every(k=>v.keys.includes(k)));
  const available=Boolean(entry?.[1].available);$('[data-pdp-add]').disabled=!available;$('[data-variant-status]').textContent=available?'':'This combination is unavailable in the captured selection.';$('[data-variant-id]').value=available?entry[0]:'';
  $$('[data-criterion]:checked').forEach(input=>{root.querySelector(`[data-criterion-label="${input.dataset.criterion}"]`).textContent=input.closest('label').querySelector('span').textContent;});
  if(!entry)return;
  const [id,v]=entry;$('[data-price]').textContent=new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(v.price/100);
  $$('[data-criterion]').forEach(input=>{const others=keys.filter(k=>!k.startsWith(input.dataset.criterion+'-'));input.disabled=!Object.values(data.variants).some(candidate=>candidate.available&&candidate.keys.includes(input.value)&&(!input.dataset.criterion.includes('size')||others.every(k=>candidate.keys.includes(k))));});
  const format=n=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n/100);
  if($('[data-pdp-was]')){$('[data-pdp-was]').hidden=!v.was||v.was<=v.price;$('[data-pdp-was]').textContent=format(v.was);}
  if($('[data-pdp-saving]')){$('[data-pdp-saving]').hidden=!v.was||v.was<=v.price;$('[data-pdp-saving]').textContent='You save '+format(v.was-v.price);}
  const url=new URL(location.href);url.searchParams.set('option',id);history.replaceState(null,'',url);
  if(v.images.length){images=v.images;const rail=$('.pdp-thumbnails');rail.replaceChildren();images.forEach((image,i)=>{const b=document.createElement('button');b.type='button';b.className='pdp-thumb';b.dataset.galleryIndex=i;b.setAttribute('aria-label',`View image ${i+1}`);const img=document.createElement('img');img.src='/static/assets/'+image;img.alt=`Product view ${i+1}`;b.append(img);rail.append(b);});bindThumbs();showImage(0);$('[data-gallery-next]').hidden=images.length<2;}
 }
 $$('[data-criterion]').forEach(input=>input.addEventListener('change',chooseVariant));if($('[data-criterion]'))chooseVariant();
 const reviewRows=$$('.pdp-review');let reviewLimit=3;
 function filterReviews(){const rating=$('[data-review-filter]').value,sort=$('[data-review-sort]').value;const sorted=reviewRows.slice();if(sort==='newest')sorted.sort((a,b)=>Date.parse(b.dataset.reviewDate)-Date.parse(a.dataset.reviewDate));if(sort==='high'||sort==='low')sorted.sort((a,b)=>(Number(a.dataset.reviewRating)-Number(b.dataset.reviewRating))*(sort==='high'?-1:1));sorted.forEach(row=>{row.hidden=Boolean(rating&&row.dataset.reviewRating!==rating);$('[data-review-list]').append(row);});const matches=sorted.filter(r=>!r.hidden),count=Math.min(matches.length,reviewLimit);matches.slice(reviewLimit).forEach(row=>row.hidden=true);if($('[data-reviews-more]'))$('[data-reviews-more]').hidden=matches.length<=reviewLimit;$('[data-review-count]').textContent=count?`Showing ${count} captured review${count===1?'':'s'}`:'No captured reviews match this rating. Choose All ratings to reset.';}
 $('[data-reviews-more]')?.addEventListener('click',()=>{reviewLimit=reviewRows.length;filterReviews();});
 if(reviewRows.length){$('[data-review-filter]').addEventListener('change',filterReviews);$('[data-review-sort]').addEventListener('change',filterReviews);filterReviews();}
 $$('[data-review-stars]').forEach(b=>b.addEventListener('click',()=>{if(!$('[data-review-filter]'))return;$('[data-review-filter]').value=b.dataset.reviewStars;filterReviews();$('[data-review-count]').scrollIntoView({block:'center',behavior:'smooth'});}));
})();
