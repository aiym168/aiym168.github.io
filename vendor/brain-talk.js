/* Site brain voice: arrival greeting, click-to-intro, live heartbeat / countdown.
   All lines are real DOM text rendered by build.py; this only reveals them.
   Reduced motion (OS or "减少动态") → text appears instantly, no auto-advance. */
(function () {
  var root = document.documentElement;
  function reduced() { return root.classList.contains('reduce-motion') || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
  function api() { return window.__brainAPI || null; }
  function talk(on) { var a = api(); if (a && a.setTalking) a.setTalking(on); var c = document.getElementById('brain-core'); if (c) c.classList.toggle('talking', !!on); }
  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // ---- typewriter (visual span is aria-hidden; screen readers get the full sentence once via the live region)
  var typing = null;
  function typeInto(el, text, done) {
    if (typing) { clearTimeout(typing.t); typing = null; }
    if (reduced()) { el.textContent = text; if (done) done(); return; }
    var i = 0; el.textContent = ''; el.classList.add('typing'); talk(true);
    typing = { t: 0 };
    (function step() {
      i += 1; el.textContent = text.slice(0, i);
      if (i >= text.length) { el.classList.remove('typing'); typing = null; talk(false); if (done) done(); return; }
      var ch = text.charAt(i - 1);
      typing.t = setTimeout(step, /[，。？！：；…]/.test(ch) ? 230 : 42);
    })();
  }
  function announce(core, text) { var lr = core.querySelector('[data-bc-live]'); if (lr) lr.textContent = text; }

  function initCountdown(core) {
    var out = core.querySelectorAll('[data-bc-count]'); if (!out.length) return;
    var next = Date.parse(core.getAttribute('data-next') || '');
    if (!next) return;
    function tick() {
      var s = Math.round((next - Date.now()) / 1000), txt;
      if (s > 0) txt = pad(Math.floor(s / 60)) + ':' + pad(s % 60);
      else txt = '正在自动更新';
      for (var k = 0; k < out.length; k++) out[k].textContent = txt;
    }
    tick(); setInterval(tick, 1000);
    core._setNext = function (iso, label) { var t = Date.parse(iso); if (t) { next = t; var n = core.querySelectorAll('[data-bc-next]'); for (var k = 0; k < n.length; k++) n[k].textContent = label; tick(); } };
  }

  // refresh "last heartbeat / next update" from the same status file the update page uses (page may be cached)
  function refreshStatus(core) {
    var url = core.getAttribute('data-status'); if (!url || !window.fetch) return;
    fetch(url + '?t=' + Math.floor(Date.now() / 60000), { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (!d || !d.last_update) return;
      var cur = core.getAttribute('data-last-label') || '';
      var last = String(d.last_update).slice(0, 16), nxt = String(d.next_update || '').slice(0, 16);
      if (last > cur) {
        var l = core.querySelectorAll('[data-bc-last]'); for (var k = 0; k < l.length; k++) l[k].textContent = last.slice(11, 16);
        core.setAttribute('data-last-label', last);
      }
      if (nxt && nxt > (core.getAttribute('data-next-label') || '') && core._setNext) {
        core.setAttribute('data-next-label', nxt);
        core._setNext(nxt.replace(' ', 'T') + ':00+08:00', nxt.slice(11, 16));
      }
    }).catch(function () {});
  }

  function initVoice(core) {
    var say = core.querySelector('[data-bc-say]');
    var greet = [].slice.call(core.querySelectorAll('[data-bc-greet]'));
    var list = core.querySelector('[data-bc-intro-list]');
    var beats = list ? [].slice.call(list.querySelectorAll('[data-beat]')) : [];
    var idle = [].slice.call(core.querySelectorAll('[data-bc-idle]')).map(function (e) { return e.textContent; });
    var stage = core.querySelector('.brain-stage');
    var greetBox = core.querySelector('[data-bc-greetbox]');
    var introBox = core.querySelector('[data-bc-introbox]');
    var dots = core.querySelector('[data-bc-dots]');
    var mode = 'greet', beat = -1, adv = 0, idleT = 0, idleI = 0;

    beats.forEach(function (b) { b._text = (b.querySelector('p') || b).textContent; });
    greet.forEach(function (g) { g._text = g.textContent; });
    if (dots) dots.innerHTML = beats.map(function (_, i) { return '<i data-dot="' + i + '"></i>'; }).join('');

    function playGreeting() {
      var i = 0;
      announce(core, greet.map(function (g) { return g._text; }).join(' '));
      greet.forEach(function (g) { g.textContent = ''; });
      (function nextLine() {
        if (mode !== 'greet' || i >= greet.length) { core.classList.add('greeted'); return; }
        var g = greet[i++]; setTimeout(function () { typeInto(g, g._text, nextLine); }, i === 1 ? 0 : 260);
      })();
    }
    function showBeat(n) {
      clearTimeout(adv);
      if (n >= beats.length) { endIntro(); return; }
      beat = n;
      beats.forEach(function (b, k) { b.hidden = k !== n; b.classList.toggle('on', k === n); });
      if (dots) [].forEach.call(dots.children, function (d, k) { d.className = k < n ? 'done' : (k === n ? 'on' : ''); });
      var b = beats[n], p = b.querySelector('p');
      announce(core, (b.querySelector('.bc-k') || {}).textContent + '：' + b._text);
      b.classList.remove('typed'); var A = api(); if (A && A.surge && n) A.surge(false);
      typeInto(p, b._text, function () {
        b.classList.add('typed');
        if (!reduced() && n < beats.length - 1) adv = setTimeout(function () { showBeat(n + 1); }, 2600 + b._text.length * 45);
      });
    }
    function startIntro() {
      if (mode === 'intro') { showBeat(beat + 1); return; }
      mode = 'intro'; clearInterval(idleT); clearTimeout(adv);
      if (typing) { clearTimeout(typing.t); typing = null; }
      greet.forEach(function (g) { g.textContent = g._text; g.classList.remove('typing'); });
      core.classList.add('intro'); if (greetBox) greetBox.hidden = true; if (introBox) introBox.hidden = false;
      var a = api(); if (a && a.triggerShockwave && !reduced()) { /* stage click already fires it */ }
      showBeat(0);
      var nx = core.querySelector('[data-bc-next-btn]'); if (nx) nx.focus({ preventScroll: true });
    }
    function endIntro() {
      clearTimeout(adv); if (typing) { clearTimeout(typing.t); typing = null; talk(false); }
      beats.forEach(function (b) { var p = b.querySelector('p'); if (p) p.textContent = b._text; });
      mode = 'idle'; core.classList.remove('intro'); core.classList.add('greeted', 'idle');
      if (introBox) introBox.hidden = true; if (greetBox) greetBox.hidden = false;
      greet.forEach(function (g) { g.textContent = g._text; });
      startIdle();
    }
    function startIdle() {
      clearInterval(idleT);
      if (!say || !idle.length) return;
      var show = function () { var t = idle[idleI++ % idle.length]; if (reduced()) say.textContent = t; else typeInto(say, t); };
      show();
      if (!reduced()) idleT = setInterval(function () { if (mode === 'idle' && !document.hidden) show(); }, 9000);
    }

    core.addEventListener('click', function (e) {
      var t = e.target.closest ? e.target.closest('[data-bc-act]') : null;
      if (!t) return;
      var act = t.getAttribute('data-bc-act');
      if (act === 'intro') { e.preventDefault(); startIntro(); }
      else if (act === 'next') { e.preventDefault(); if (typing) { clearTimeout(typing.t); typing = null; talk(false); var b = beats[beat]; b.querySelector('p').textContent = b._text; b.classList.add('typed'); } else showBeat(beat + 1); }
      else if (act === 'skip') { e.preventDefault(); endIntro(); }
      else if (act === 'later') { e.preventDefault(); mode = 'idle'; if (typing) { clearTimeout(typing.t); typing = null; talk(false); } greet.forEach(function (g) { g.textContent = g._text; }); core.classList.add('greeted', 'idle'); startIdle(); }
    });
    if (stage) {
      stage.addEventListener('click', function () { if (mode !== 'intro') startIntro(); });
      stage.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); var a = api(); if (a && a.triggerShockwave) a.triggerShockwave(); startIntro(); } });
    }

    // arrival: start talking as soon as the brain is on screen
    var started = false;
    function arrive() {
      if (started) return; started = true; core.classList.add('awake'); setTimeout(playGreeting, reduced() ? 0 : 700);
      var tries = 0; (function look() { var a = api(); if (a && a.notice) a.notice(); else if (++tries < 25) setTimeout(look, 200); })();
    }
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (en) { if (en[0].isIntersecting) { io.disconnect(); arrive(); } }, { threshold: 0.25 });
      io.observe(core);
    } else arrive();
  }

  function boot() {
    var core = document.getElementById('brain-core'); if (!core) return;
    core.classList.add('js'); core.classList.remove('nojs');
    var list = core.querySelector('[data-bc-intro-list]');
    if (list) [].forEach.call(list.querySelectorAll('[data-beat]'), function (b, i) { b.hidden = i !== 0; });
    var ib = core.querySelector('[data-bc-introbox]'); if (ib) ib.hidden = true;
    initCountdown(core); refreshStatus(core);
    if (core.getAttribute('data-voice') === 'on') initVoice(core);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
