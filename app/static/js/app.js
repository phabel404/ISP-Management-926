/* SambiraPandoraBox client behavior */
(function () {
  // ---- theme handling (cookie-based, server renders data-theme too)
  var html = document.documentElement;
  function applyTheme(mode) {
    var t = mode || 'system';
    var dark = t === 'dark' || (t === 'system' && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
    html.setAttribute('data-theme', dark ? 'dark' : 'light');
    html.setAttribute('data-theme-mode', t);
  }
  window.spbSetTheme = function (mode) {
    applyTheme(mode);
    var f = document.createElement('form');
    f.method = 'post'; f.action = '/theme';
    var i = document.createElement('input');
    i.name = 'mode'; i.value = mode; f.appendChild(i);
    document.body.appendChild(f); f.submit();
  };
  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(html.getAttribute('data-theme-mode') || 'system');
    if (html.getAttribute('data-compact') === '1') html.setAttribute('data-compact', '1');

    // hamburger
    var hb = document.querySelector('.hamburger');
    if (hb) hb.addEventListener('click', function () { document.body.classList.toggle('sb-open'); });
    document.querySelectorAll('.side-nav a').forEach(function (a) {
      a.addEventListener('click', function(){ document.body.classList.remove('sb-open'); });
    });

    // toasts from flash cookie (server puts them in #flash-data JSON)
    var fd = document.getElementById('flash-data');
    if (fd) { try { toast(JSON.parse(fd.textContent)); } catch (e) {} }

    // confirm dialogs for destructive forms
    document.querySelectorAll('form[data-confirm]').forEach(function (f) {
      f.addEventListener('submit', function (ev) {
        ev.preventDefault();
        openConfirm(f.getAttribute('data-confirm-title') || 'Konfirmasi',
                    f.getAttribute('data-confirm'),
                    function () { f.submit(); });
      });
    });

    // busy indicator on submit / navigation
    document.querySelectorAll('form[method=post]').forEach(function (f) {
      f.addEventListener('submit', function () { setTimeout(function(){ html.classList.add('busy'); }, 50); });
    });
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[href]');
      if (a && !a.download && !a.target && a.href.indexOf('#') !== 0 && a.getAttribute('href').indexOf('javascript') !== 0) {
        setTimeout(function(){ html.classList.add('busy'); }, 50);
      }
    });
    window.addEventListener('pageshow', function () { html.classList.remove('busy'); });

    // auto-submit filter selects
    document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
      el.addEventListener('change', function () { el.form && el.form.submit(); });
    });

    // modal dialogs (generic: <dialog id="dlg-x"> + buttons with data-dialog)
    document.querySelectorAll('[data-dialog]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        var dlg = document.getElementById(btn.getAttribute('data-dialog'));
        if (!dlg) return;
        if (btn.hasAttribute('data-fill')) {
          Object.keys(JSON.parse(btn.getAttribute('data-fill'))).forEach(function (k) {
            var inp = dlg.querySelector('[name="' + k + '"]');
            if (inp) inp.value = JSON.parse(btn.getAttribute('data-fill'))[k];
          });
        }
        dlg.showModal();
      });
    });
    document.querySelectorAll('dialog [data-close]').forEach(function (btn) {
      btn.addEventListener('click', function (e) { e.preventDefault(); btn.closest('dialog').close(); });
    });

    // simple bar charts from JSON script tags
    document.querySelectorAll('svg.chart[data-series]').forEach(drawChart);
  });

  function toast(obj) {
    if (!obj || !obj.m) return;
    var box = document.getElementById('toasts');
    if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
    var d = document.createElement('div');
    d.className = 'toast ' + (obj.k || 'ok');
    d.textContent = obj.m;
    box.appendChild(d);
    setTimeout(function () { d.style.opacity = '0'; d.style.transition = 'opacity .3s'; setTimeout(function(){ d.remove(); }, 320); }, 4200);
  }
  window.spbToast = toast;

  var _confirmCb = null;
  function openConfirm(title, msg, cb) {
    var dlg = document.getElementById('dlg-confirm');
    if (!dlg) { if (window.confirm(msg)) cb(); return; }
    dlg.querySelector('.bd').textContent = msg;
    dlg.querySelector('.hd').textContent = title;
    _confirmCb = cb;
    dlg.showModal();
  }
  window.spbConfirm = function (title, msg, cb) { openConfirm(title, msg, cb); };
  document.addEventListener('DOMContentLoaded', function () {
    var dlg = document.getElementById('dlg-confirm');
    if (dlg) dlg.querySelector('[data-yes]').addEventListener('click', function (e) {
      e.preventDefault(); dlg.close(); if (_confirmCb) { _confirmCb(); _confirmCb = null; }
    });
  });

  function drawChart(svg) {
    var data;
    try { data = JSON.parse(svg.getAttribute('data-series')); } catch (e) { return; }
    if (!data.length) { svg.outerHTML = '<div class="empty">Belum ada data untuk grafik.</div>'; return; }
    var W = 600, H = 150, P = 28, max = 0;
    data.forEach(function (d) { if (d.value > max) max = d.value; });
    if (max <= 0) max = 1;
    var bw = Math.min(56, (W - P * 2) / data.length * 0.6), gap = (W - P * 2) / data.length;
    var ns = 'http://www.w3.org/2000/svg';
    var axis = document.createElementNS(ns, 'line');
    axis.setAttribute('x1', P - 4); axis.setAttribute('x2', W - P + 4);
    axis.setAttribute('y1', H - P); axis.setAttribute('y2', H - P);
    axis.setAttribute('class', 'axis'); svg.appendChild(axis);
    data.forEach(function (d, i) {
      var h = Math.round((H - P - 14) * (d.value / max));
      var x = P + i * gap + (gap - bw) / 2, y = H - P - h;
      var r = document.createElementNS(ns, 'rect');
      r.setAttribute('x', x); r.setAttribute('y', y); r.setAttribute('width', bw);
      r.setAttribute('height', Math.max(h, 1)); r.setAttribute('rx', 2); r.setAttribute('class', 'bar');
      var ttl = document.createElementNS(ns, 'title');
      ttl.textContent = d.label + ': ' + (svg.getAttribute('data-fmt') === 'rp' ? fmtRp(d.value) : d.value);
      r.appendChild(ttl); svg.appendChild(r);
      var tx = document.createElementNS(ns, 'text');
      tx.setAttribute('x', x + bw / 2); tx.setAttribute('y', H - P + 12);
      tx.setAttribute('text-anchor', 'middle'); tx.textContent = d.label; svg.appendChild(tx);
      var vy = document.createElementNS(ns, 'text');
      vy.setAttribute('x', x + bw / 2); vy.setAttribute('y', y - 3);
      vy.setAttribute('text-anchor', 'middle');
      vy.textContent = svg.getAttribute('data-fmt') === 'rp' ? shortRp(d.value) : d.value;
      svg.appendChild(vy);
    });
  }
  function fmtRp(n){ return 'Rp' + Number(n).toLocaleString('id-ID'); }
  function shortRp(n){ n=Number(n); if(n>=1e9) return (n/1e9).toFixed(1).replace('.',',')+' Miliar'; if(n>=1e6) return Math.round(n/1e6)+' Jt'; if(n>=1e3) return Math.round(n/1e3)+' Rb'; return ''+n; }
})();
