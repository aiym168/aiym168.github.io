/* Loads the decorative WebGL brain. Reduced motion (OS or the "减少动态" toggle) → static frame, not removal. */
(function(){
  function ready(fn){
    if(document.readyState==='complete') fn();
    else window.addEventListener('load', fn, {once:true});
  }
  function fallback(el, base){
    var f=document.createElement('script');
    f.src=base+'brain-fallback.js';
    f.onload=function(){ if(window.mountBrainFallback) window.mountBrainFallback(el); };
    document.head.appendChild(f);
  }
  function boot(){
    var el=document.getElementById('brain-hero');
    if(!el) return;
    var base=el.getAttribute('data-vendor')||'vendor/';
    var start=function(){
      var probe=document.createElement('canvas');
      var gl=probe.getContext('webgl')||probe.getContext('experimental-webgl');
      if(!gl){ fallback(el, base); return; }
      import(new URL(base+'brain-hero.js', document.baseURI).href).then(function(mod){
        if(!(mod&&mod.mountBrainHero&&mod.mountBrainHero(el))) fallback(el, base);
      }).catch(function(){ fallback(el, base); });
    };
    if('requestIdleCallback' in window) requestIdleCallback(start, {timeout:900});
    else setTimeout(start, 250);
  }
  ready(boot);
})();
