(()=>{
 const frame=document.querySelector('.service-shell iframe');if(!frame)return;
 window.addEventListener('message',event=>{
  if(event.source!==frame.contentWindow||event.origin!==location.origin)return;
  if(event.data?.type==='service-height'&&Number.isFinite(event.data.height))frame.style.height=Math.min(100000,Math.max(400,event.data.height))+'px';
 });
})();
