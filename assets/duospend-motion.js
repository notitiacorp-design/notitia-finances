/* ============================================================
   DUOSPEND — mouvements courts (app complète)
   Léger, sans dépendance : compteurs sobres liés aux événements
   'duospend:state', assagissement des confettis (palette maison).
   Tout est neutralisé par prefers-reduced-motion.
   ============================================================ */
(function(){
  'use strict';
  if(window.__duoMotion) return;
  window.__duoMotion = 1;

  var mq = (window.matchMedia && typeof window.matchMedia === 'function')
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;
  var rm = !!(mq && mq.matches);
  if(mq){
    var onRm = function(){ rm = !!mq.matches; };
    try { mq.addEventListener ? mq.addEventListener('change', onRm) : mq.addListener(onRm); } catch(e){}
  }

  /* ---------- compteurs d'argent (520 ms, une seule fois par valeur) ---------- */
  var CU_SEL = '#totalDisplay,#qtotal,#jtotal,#bsSpent,#bsRemain,#bsCaps,#proTotal,.bs-value,.person-amount,.donut-center-total';
  function parseMoney(t){
    var m = String(t == null ? '' : t).match(/^([^\d]*)([\d][\d\s\u00a0\u202f.,]*)([^\d]*)$/);
    if(!m) return null;
    var pre = m[1], mid = m[2], post = m[3];
    // l'espace (ou insécable) avant le symbole € a été absorbé dans mid : le rendre au suffixe
    var trail = mid.match(/[\s\u00a0\u202f]+$/);
    if(trail && post){ post = trail[0] + post; mid = mid.slice(0, mid.length - trail[0].length); }
    var raw = mid.replace(/[\s\u00a0\u202f]/g, '');
    var dec = /[.,]\d\d$/.test(raw);
    var v = parseFloat(raw.replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.'));
    if(!isFinite(v)) return null;
    return { pre: pre, post: post, v: v, dec: dec };
  }
  function fmt(x, dec){
    return x.toLocaleString('fr-FR', dec
      ? { minimumFractionDigits: 2, maximumFractionDigits: 2 }
      : { maximumFractionDigits: 2 });
  }
  function countUps(){
    if(rm) return;
    var els;
    try { els = document.querySelectorAll(CU_SEL); } catch(e){ return; }
    Array.prototype.forEach.call(els, function(el){
      try {
        if(el.closest && el.closest('#chatThread, .tx-list, .import-card')) return;
        var info = parseMoney((el.textContent || '').trim());
        if(!info) return;
        var to = info.v;
        var from = Number(el.getAttribute('data-cu-from'));
        if(!isFinite(from)) from = to;
        el.setAttribute('data-cu-from', String(to));
        if(from === to) return;
        var t0 = -1, dur = 520;
        var tok = ++cuSeq;
        el.__cuTok = tok;
        // filet : la valeur exacte est posée même si rAF gèle (onglet en arrière-plan)
        setTimeout(function(){
          if(el.__cuTok !== tok) return;
          el.textContent = info.pre + fmt(to, info.dec) + info.post;
        }, dur + 160);
        (function step(ts){
          if(el.__cuTok !== tok) return;
          if(t0 === -1) t0 = ts;
          var k = Math.min(1, (ts - t0) / dur), e = 1 - Math.pow(1 - k, 3);
          el.textContent = info.pre + fmt(from + (to - from) * e, info.dec) + info.post;
          if(k < 1) requestAnimationFrame(step);
          else el.textContent = info.pre + fmt(to, info.dec) + info.post;
        })(0);
      } catch(e){}
    });
  }
  var cuSeq = 0;
  document.addEventListener('duospend:state', function(){ requestAnimationFrame(countUps); });
  window.addEventListener('load', function(){ setTimeout(countUps, 320); });

  /* ---------- confettis assagis : palette maison, plafonnés, jamais en reduced-motion ---------- */
  (function wrapConfetti(){
    var tries = 0;
    var iv = setInterval(function(){
      if(window.confetti){
        clearInterval(iv);
        if(window.confetti.__duo) return;
        var base = window.confetti;
        var w = function(opts){
          if(rm) return;
          var o = Object.assign({}, opts || {});
          o.colors = ['#B18B4B', '#35212F', '#E6DED0', '#48745D'];
          o.particleCount = Math.min(Number(o.particleCount) || 12, 14);
          o.spread = Math.min(Number(o.spread) || 45, 55);
          o.disableForReducedMotion = true;
          try { base(o); } catch(e){}
        };
        w.__duo = 1;
        window.confetti = w;
      }
      if(++tries > 40) clearInterval(iv);
    }, 250);
  })();

  window.DuoMotion = {
    countUps: countUps,
    get reduced(){ return rm; }
  };
})();
