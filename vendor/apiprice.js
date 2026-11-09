/* 大模型 API 最低价榜：搜索、家族 / 服务商筛选、表头排序、展开全部报价 */
(function () {
  var t = document.querySelector('[data-ap-table]'), root = document.querySelector('[data-ap-root]');
  if (!t || !root) return;
  var bodies = Array.prototype.slice.call(t.querySelectorAll('tbody.ap-model'));
  var q = root.querySelector('#apq'), prov = root.querySelector('[data-ap-prov]'), cnt = root.querySelector('[data-ap-count]');
  var empty = document.querySelector('[data-ap-empty]'), fams = {};
  function apply() {
    var term = (q.value || '').trim().toLowerCase(), p = prov.value, fk = Object.keys(fams), n = 0;
    bodies.forEach(function (b) {
      var ok = (!term || (b.getAttribute('data-text') || '').toLowerCase().indexOf(term) >= 0) &&
        (!fk.length || fk.indexOf(b.getAttribute('data-fam')) >= 0) &&
        (!p || (' ' + b.getAttribute('data-prov') + ' ').indexOf(' ' + p + ' ') >= 0);
      b.hidden = !ok; if (ok) n++;
    });
    cnt.textContent = '共 ' + n + ' 个模型';
    if (empty) empty.classList.toggle('hidden', n > 0);
  }
  q.addEventListener('input', apply); prov.addEventListener('change', apply);
  root.addEventListener('click', function (e) {
    var c = e.target.closest('[data-ap-fam]'); if (!c) return;
    var f = c.getAttribute('data-ap-fam'), on = c.getAttribute('aria-pressed') !== 'true';
    c.setAttribute('aria-pressed', on ? 'true' : 'false'); if (on) fams[f] = 1; else delete fams[f]; apply();
  });
  t.addEventListener('click', function (e) {
    var tog = e.target.closest('.ap-tog');
    if (tog) {
      var sub = tog.closest('tbody').querySelector('.ap-sub'), open = sub.hidden;
      sub.hidden = !open; tog.setAttribute('aria-expanded', open ? 'true' : 'false'); return;
    }
    var th = e.target.closest('th[data-sort]'); if (!th) return;
    var k = th.getAttribute('data-sort'), dir = th.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc';
    if (!th.getAttribute('data-dir') && k === 'save') dir = 'desc';
    t.querySelectorAll('th[data-sort]').forEach(function (x) { x.removeAttribute('data-dir'); });
    th.setAttribute('data-dir', dir);
    bodies.sort(function (a, b) {
      var va = a.getAttribute('data-s-' + k), vb = b.getAttribute('data-s-' + k), r;
      if (k === 'model') r = va.localeCompare(vb); else r = parseFloat(va) - parseFloat(vb);
      return dir === 'asc' ? r : -r;
    });
    bodies.forEach(function (b) { t.appendChild(b); });
  });
})();
