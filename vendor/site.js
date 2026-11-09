/* AI大模型免费资源导航 · site.js (v3): nav, 减少动态 toggle, search + filters + sort, quick search over /api/latest.json. */
(function(){
  var root = document.documentElement;
  var KEY = 'ai168-reduce';
  function $(s, el){ return (el||document).querySelector(s); }
  function $all(s, el){ return Array.prototype.slice.call((el||document).querySelectorAll(s)); }
  var brand = document.querySelector('.brand-mini');
  var base = (document.body && document.body.getAttribute('data-base')) || (brand && brand.getAttribute('href')) || './';
  if (base.slice(-1) !== '/') base += '/';

  /* ---------- 减少动态 (persistent) ---------- */
  function setReduce(on){
    root.classList.toggle('reduce-motion', on);
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch(e) {}
    $all('[data-reduce-toggle]').forEach(function(b){ b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.querySelector('b') && (b.querySelector('b').textContent = on ? '开' : '关'); });
    try { window.dispatchEvent(new Event('ai168:reduce-motion')); } catch(e) {}
  }
  $all('[data-reduce-toggle]').forEach(function(b){
    b.addEventListener('click', function(){ setReduce(!root.classList.contains('reduce-motion')); });
  });
  setReduce(root.classList.contains('reduce-motion'));

  /* ---------- hamburger nav (≤768px) ---------- */
  var nav = $('.topnav'), tog = $('.nav-toggle');
  if (nav && tog) {
    tog.addEventListener('click', function(){
      var open = !nav.classList.contains('open');
      nav.classList.toggle('open', open); tog.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    $all('.navlinks a', nav).forEach(function(a){ a.addEventListener('click', function(){ nav.classList.remove('open'); tog.setAttribute('aria-expanded','false'); }); });
  }

  /* ---------- filters / search / sort (home + module pages) ---------- */
  var fr = $('[data-filter-root]');
  var q = $('#q');
  function initFilters(){
    if (!fr) return;
    var list = $('[data-list]', fr) || $('[data-list]');
    if (!list) return;
    var cards = $all('.card[data-id]', list);
    var order = cards.slice();
    var active = {};
    var countEl = $('#f-count'), emptyEl = $('#f-empty'), moreBtn = $('#f-more');
    var limit = parseInt(list.getAttribute('data-limit') || '0', 10), expanded = !limit;
    var sortSel = $('#f-sort');
    function matches(c, t){
      for (var k in active) {
        if (!active[k] || !active[k].length) continue;
        var v = c.getAttribute('data-' + k) || '';
        if (active[k].indexOf(v) < 0) return false;
      }
      if (t) {
        var hay = (c.getAttribute('data-text') || '').toLowerCase();
        var parts = t.split(/\s+/);
        for (var i = 0; i < parts.length; i++) if (parts[i] && hay.indexOf(parts[i]) < 0) return false;
      }
      return true;
    }
    function sortCards(){
      var mode = sortSel ? sortSel.value : 'default';
      var arr = order.slice();
      if (mode === 'pub') arr.sort(function(a,b){ return (b.getAttribute('data-pub')||'').localeCompare(a.getAttribute('data-pub')||''); });
      if (mode === 'exp') arr.sort(function(a,b){
        var x = a.getAttribute('data-exp') || '9999', y = b.getAttribute('data-exp') || '9999'; return x.localeCompare(y); });
      arr.forEach(function(c){ list.appendChild(c); });
      return arr;
    }
    function apply(){
      var t = (q && q.value || '').trim().toLowerCase();
      var arr = sortCards(), shown = 0, visible = 0;
      var filtering = !!t || Object.keys(active).some(function(k){ return active[k] && active[k].length; });
      arr.forEach(function(c){
        var ok = matches(c, t);
        if (ok) shown++;
        var hideByLimit = ok && !expanded && !filtering && shown > limit;
        c.classList.toggle('hidden', !ok || hideByLimit);
        if (ok && !hideByLimit) visible++;
      });
      if (countEl) countEl.textContent = filtering ? ('筛选结果 ' + shown + ' / ' + cards.length + ' 条') : ('共 ' + cards.length + ' 条');
      if (emptyEl) emptyEl.classList.toggle('hidden', shown > 0);
      if (moreBtn) moreBtn.classList.toggle('hidden', expanded || filtering || shown <= limit);
      var clr = $('#f-clear'); if (clr) clr.classList.toggle('hidden', !filtering);
    }
    $all('[data-f]', fr).forEach(function(btn){
      btn.addEventListener('click', function(){
        var k = btn.getAttribute('data-f'), v = btn.getAttribute('data-v');
        var arr = active[k] || (active[k] = []);
        var i = arr.indexOf(v);
        if (i >= 0) arr.splice(i, 1); else arr.push(v);
        btn.setAttribute('aria-pressed', i >= 0 ? 'false' : 'true');
        apply();
      });
    });
    var clr = $('#f-clear');
    if (clr) clr.addEventListener('click', function(){
      active = {}; if (q) q.value = '';
      $all('[data-f]', fr).forEach(function(b){ b.setAttribute('aria-pressed','false'); });
      apply();
    });
    if (moreBtn) moreBtn.addEventListener('click', function(){ expanded = true; apply(); });
    if (sortSel) sortSel.addEventListener('change', apply);
    if (q) {
      q.addEventListener('input', apply);
      var form = q.form; if (form) form.addEventListener('submit', function(e){ e.preventDefault(); apply(); var s = $('#search'); if (s && s.scrollIntoView) s.scrollIntoView({behavior: root.classList.contains('reduce-motion') ? 'auto' : 'smooth'}); });
      try { var u = new URLSearchParams(location.search).get('q'); if (u) { q.value = u; } } catch(e) {}
    }
    fr.classList.add('js-ready');
    apply();
  }
  initFilters();

  /* ---------- quick search overlay (pages without a list): reads /api/latest.json ---------- */
  var box = null, data = null;
  function openQuick(){
    if (!box) {
      box = document.createElement('div'); box.id = 'quick-search'; box.setAttribute('role','dialog'); box.setAttribute('aria-label','搜索免费资源');
      box.innerHTML = '<div class="qs-box"><input id="qs-input" type="search" placeholder="搜索免费资源：如 Gemini、免费 GPU、免绑卡…" autocomplete="off"/><div id="qs-results" class="qs-results"><div class="qs-empty">正在载入数据…</div></div><div class="qs-foot">数据来自 <code>api/latest.json</code> · Esc 关闭</div></div>';
      document.body.appendChild(box);
      box.addEventListener('click', function(e){ if (e.target === box) closeQuick(); });
      var inp = $('#qs-input', box), res = $('#qs-results', box);
      function render(){
        if (!data) return;
        var t = (inp.value || '').trim().toLowerCase();
        var rows = data.filter(function(it){ var h = (it.title + ' ' + it.summary + ' ' + (it.module_name||'') + ' ' + (it.source||'')).toLowerCase(); return !t || t.split(/\s+/).every(function(p){ return h.indexOf(p) >= 0; }); }).slice(0, 30);
        res.innerHTML = rows.length ? rows.map(function(it){
          var a = document.createElement('a'); a.className = 'qs-item'; a.href = base + (it.path || '');
          a.innerHTML = '<b></b><small></small>'; a.firstChild.textContent = it.title; a.lastChild.textContent = (it.module_name || '') + ' · ' + (it.status_label || '');
          return a.outerHTML; }).join('') : '<div class="qs-empty">没有匹配的条目</div>';
      }
      inp.addEventListener('input', render);
      fetch(base + 'api/latest.json', {cache: 'no-cache'}).then(function(r){ return r.json(); }).then(function(j){ data = j.items || []; render(); })
        .catch(function(){ res.innerHTML = '<div class="qs-empty">数据载入失败，请返回首页搜索</div>'; });
    }
    box.classList.add('open'); setTimeout(function(){ var i = $('#qs-input'); i && i.focus(); }, 30);
  }
  function closeQuick(){ if (box) box.classList.remove('open'); }
  function openSearch(e){
    if (q && fr) { if (e) e.preventDefault(); q.focus(); if (q.scrollIntoView) q.scrollIntoView({block:'center', behavior: root.classList.contains('reduce-motion') ? 'auto' : 'smooth'}); return; }
    if (e) e.preventDefault(); openQuick();
  }
  $all('[data-search-open]').forEach(function(b){ b.addEventListener('click', openSearch); });
  document.addEventListener('keydown', function(e){
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openSearch(); }
    else if (e.key === '/' && !/input|textarea|select/i.test((document.activeElement||{}).tagName||'')) { e.preventDefault(); openSearch(); }
    else if (e.key === 'Escape') closeQuick();
  });

  /* ---------- copy buttons ---------- */
  $all('.copy-btn').forEach(function(btn){
    btn.addEventListener('click', function(){
      var t = btn.getAttribute('data-copy') || '';
      (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function(){ btn.textContent = '已复制'; setTimeout(function(){ btn.textContent = '复制'; }, 1200); }, function(){ btn.textContent = '请手动复制'; });
    });
  });
})();
