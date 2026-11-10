/* AI大模型免费资源导航 · fx.js (v3) — calm background only.
   Removed in v3: count-up numbers, headline blur-in, scroll-blur reveals, per-second clock/countdown, parallax, tilt.
   Motion respects prefers-reduced-motion and the persistent "减少动态" toggle (html.reduce-motion). */
(function(){
  var root = document.documentElement;
  root.classList.add('js');
  var mobile = Math.min(window.innerWidth, window.innerHeight) < 720;
  function isReduced(){ return root.classList.contains('reduce-motion') || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }

  /* ---------- GLSL shader background (raw WebGL, no deps) ---------- */
  (function shaderBg(){
    var old = document.getElementById('fx-particles'); if (old) old.style.display = 'none';
    var cv = document.getElementById('fx-shader');
    if (!cv) { cv = document.createElement('canvas'); cv.id = 'fx-shader'; cv.setAttribute('aria-hidden','true'); document.body.insertBefore(cv, document.body.firstChild); }
    var gl = cv.getContext('webgl', {antialias:false, alpha:false, premultipliedAlpha:false});
    if (!gl) { cv.classList.add('no-gl'); return; }
    var vs = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
    var fs = [
      'precision mediump float;uniform vec2 r;uniform float t;uniform vec2 m;uniform float sc;',
      'float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}',
      'float n(vec2 p){vec2 i=floor(p),f=fract(p);vec2 u=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1,0)),u.x),mix(h(i+vec2(0,1)),h(i+vec2(1,1)),u.x),u.y);}',
      'float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}',
      'void main(){vec2 uv=gl_FragCoord.xy/r;vec2 p=(gl_FragCoord.xy-.5*r)/r.y;',
      'p.y+=sc*.35;float tt=t*.045;',
      'vec2 q=vec2(fbm(p*1.6+tt),fbm(p*1.6-tt+3.1));',
      'vec2 w=vec2(fbm(p*1.3+2.*q+vec2(1.7,9.2)+tt*1.3),fbm(p*1.3+2.*q+vec2(8.3,2.8)-tt));',
      'float f=fbm(p*1.2+2.4*w);',
      'vec3 bg=vec3(.010,.016,.040);',
      'vec3 c1=vec3(.36,.88,1.);vec3 c2=vec3(.65,.55,.98);vec3 c3=vec3(.37,.94,.75);',
      'vec3 col=bg;col=mix(col,c2*.5,smoothstep(.3,.95,f)*.65);',
      'col=mix(col,c1*.48,smoothstep(.45,1.,w.x)*.55);',
      'col+=c3*.10*smoothstep(.62,.95,q.y);',
      'float md=length(p-(m-.5)*vec2(r.x/r.y,1.));col+=c1*.10*exp(-md*md*5.);',
      'float vg=smoothstep(1.25,.25,length(uv-.5)*1.4);col*=.55+.45*vg;',
      'col*=.85;gl_FragColor=vec4(col,1.);}'
    ].join('\n');
    function sh(type, src){ var s=gl.createShader(type); gl.shaderSource(s,src); gl.compileShader(s); return s; }
    var pr = gl.createProgram(); gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { cv.classList.add('no-gl'); return; }
    gl.useProgram(pr);
    var b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,3,-1,-1,3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(pr,'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,2,gl.FLOAT,false,0,0);
    var uR=gl.getUniformLocation(pr,'r'), uT=gl.getUniformLocation(pr,'t'), uM=gl.getUniformLocation(pr,'m'), uS=gl.getUniformLocation(pr,'sc');
    var scale = mobile ? 0.35 : 0.5, mx=.5, my=.5, smx=.5, smy=.5;
    function size(){ cv.width = Math.max(2, Math.floor(innerWidth*scale)); cv.height = Math.max(2, Math.floor(innerHeight*scale)); gl.viewport(0,0,cv.width,cv.height); }
    size(); window.addEventListener('resize', size);
    window.addEventListener('pointermove', function(e){ mx=e.clientX/innerWidth; my=1-e.clientY/innerHeight; }, {passive:true});
    var t0 = performance.now(), last = 0;
    function draw(now){
      smx += (mx-smx)*.04; smy += (my-smy)*.04;
      var sc = Math.min(1, (window.scrollY||0) / Math.max(1, document.documentElement.scrollHeight - innerHeight));
      gl.uniform2f(uR, cv.width, cv.height); gl.uniform1f(uT, (now-t0)/1000 + 20.0); gl.uniform2f(uM, smx, smy); gl.uniform1f(uS, sc);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    draw(performance.now());
    (function loop(now){
      requestAnimationFrame(loop);
      if (isReduced() || document.hidden || now - last < 40) return; last = now; draw(now);
    })(performance.now());
    cv.classList.add('on');
  })();

  /* ---------- nav: solid background after scrolling ---------- */
  var nav = document.querySelector('.topnav');
  function onScroll(){ if (nav) nav.classList.toggle('scrolled', (window.scrollY||0) > 24); }
  window.addEventListener('scroll', onScroll, {passive:true}); onScroll();
})();

/* ---------- share buttons on cards and item pages: X / 微信 / 小红书 / link (text is built from the card itself) */
(function(){
  function txt(root, sel){ var e = root.querySelector(sel); return e ? e.textContent.replace(/\s+/g, ' ').trim() : ''; }
  function cut(s, n){ return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function copy(btn, t, okLabel){
    var old = btn.dataset.label || btn.textContent; btn.dataset.label = old;
    function done(){ btn.textContent = okLabel || '已复制'; btn.classList.add('done'); setTimeout(function(){ btn.textContent = old; btn.classList.remove('done'); }, 1600); }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(done, function(){ window.prompt('复制下面的文字：', t); });
    else window.prompt('复制下面的文字：', t);
  }
  document.addEventListener('click', function(ev){
    var btn = ev.target.closest && ev.target.closest('[data-share]'); if (!btn) return;
    var root = btn.closest('[data-share-url]'); if (!root) return;
    ev.preventDefault();
    var url = root.getAttribute('data-share-url'), title = txt(root, '[data-s-title]'), sum = txt(root, '[data-s-sum]'),
        st = txt(root, '[data-s-st]'), mod = txt(root, '[data-s-mod]'), how = txt(root, '[data-s-how]');
    var kind = btn.getAttribute('data-share');
    if (kind === 'x') {
      var t = cut(title, 70) + (st ? '｜' + st : '') + '\n' + cut(sum, 60);
      window.open('https://x.com/intent/post?text=' + encodeURIComponent(t) + '&url=' + encodeURIComponent(url), '_blank', 'noopener');
    } else if (kind === 'wx') {
      copy(btn, '【AI 羊毛】' + title + '\n' + cut(sum, 120) + (how ? '\n怎么领：' + cut(how, 80) : '') + (st ? '\n状态：' + st : '') + '\n详情：' + url);
    } else if (kind === 'xhs') {
      copy(btn, cut(title, 20) + '\n\n' + cut(sum, 150) + (how ? '\n\n怎么领：' + cut(how, 100) : '') + (st ? '\n状态：' + st + '（以官网为准）' : '') +
        '\n\n详情搜「AI大模型免费资源导航」\n\n#AI羊毛 #免费AI #大模型' + (mod ? ' #' + mod.replace(/[\s/·]+/g, '') : ''));
    } else {
      copy(btn, url, '链接已复制');
    }
  });
})();
