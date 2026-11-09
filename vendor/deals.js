/* 全球优惠情报中心：搜索、按参与类型 / 核实程度筛选、排序（无依赖） */
(function () {
  var root = document.querySelector('[data-dl-root]');
  var list = document.querySelector('[data-dl-list]');
  if (!root || !list) return;
  root.classList.add('js-ready');
  var cards = Array.prototype.slice.call(list.querySelectorAll('.dl-card'));
  var q = root.querySelector('#dlq');
  var countEl = root.querySelector('[data-dl-count]');
  var clearBtn = root.querySelector('[data-dl-clear]');
  var sortSel = root.querySelector('[data-dl-sort]');
  var empty = document.querySelector('[data-dl-empty]');
  var sel = { tags: {}, ver: {} };
  function verKey(v) { return (v === 'verified' || v === 'official') ? v : 'pending'; }
  function apply() {
    var term = (q && q.value || '').trim().toLowerCase();
    var n = 0, any = term.length > 0;
    var tk = Object.keys(sel.tags), vk = Object.keys(sel.ver);
    if (tk.length || vk.length) any = true;
    cards.forEach(function (c) {
      var ok = true;
      if (term && (c.getAttribute('data-text') || '').toLowerCase().indexOf(term) < 0) ok = false;
      if (ok && tk.length) {
        var tags = (c.getAttribute('data-tags') || '').split(' ');
        ok = tk.some(function (t) { return tags.indexOf(t) >= 0; });
      }
      if (ok && vk.length) ok = vk.indexOf(verKey(c.getAttribute('data-ver'))) >= 0;
      c.hidden = !ok;
      if (ok) n++;
    });
    if (countEl) countEl.textContent = (any ? '筛选后 ' : '共 ') + n + ' 条';
    if (clearBtn) clearBtn.classList.toggle('hidden', !any);
    if (empty) empty.classList.toggle('hidden', n > 0);
  }
  root.addEventListener('click', function (e) {
    var b = e.target.closest('[data-dl-f]');
    if (!b) return;
    var f = b.getAttribute('data-dl-f'), v = b.getAttribute('data-v');
    var on = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (on) sel[f][v] = 1; else delete sel[f][v];
    apply();
  });
  if (q) q.addEventListener('input', apply);
  if (clearBtn) clearBtn.addEventListener('click', function () {
    sel = { tags: {}, ver: {} };
    if (q) q.value = '';
    root.querySelectorAll('[data-dl-f]').forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
    apply();
  });
  if (sortSel) sortSel.addEventListener('change', function () {
    var by = sortSel.value;
    cards.sort(function (a, b) {
      if (by === 'end') {
        var ea = a.getAttribute('data-end') || '9999', eb = b.getAttribute('data-end') || '9999';
        return ea < eb ? -1 : ea > eb ? 1 : 0;
      }
      return parseFloat(b.getAttribute('data-score')) - parseFloat(a.getAttribute('data-score'));
    });
    cards.forEach(function (c) { list.appendChild(c); });
  });
})();
