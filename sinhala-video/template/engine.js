// Deterministic scene engine. Python calls:
//   await init(data)   - build DOM for all scenes, wait for fonts, fit text
//   render(t)          - set every animated property for absolute time t (s)
//   checkLayout()      - report overlapping / overflowing elements per scene
// No CSS animations, transitions or timers are used: a frame depends on t only.
(function () {
  const { clamp, ease, back, bounce } = window.ANIM;
  let D = null, scenes = [], cues = [], els = {};

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // headline markup: words wrapped for the typewriter; *word* -> accent colour
  function headlineHTML(text) {
    return esc(text).split(/(\*[^*]+\*)/).map((part) => {
      const hl = /^\*[^*]+\*$/.test(part);
      const body = hl ? part.slice(1, -1) : part;
      return body.split(/(\s+)/).map((w) => (/^\s*$/.test(w) ? w :
        `<span class="w${hl ? ' hl' : ''}">${w}</span>`)).join('');
    }).join('');
  }

  function layoutMetrics() {
    const W = D.width, H = D.height, portrait = H > W;
    const u = Math.min(W, H) / 100;
    document.documentElement.style.setProperty('--u', u + 'px');
    const m = portrait
      ? { tagTop: 6 * u, tagFont: 3.3 * u, areaTop: 15 * u, areaBottom: 34 * u, subsBottom: 9 * u, subsFont: 4.6 * u,
          h1: 9.0 * u, sub: 5.3 * u, note: 4.3 * u, icon: 32 * u, src: 3.4 * u, btn: 5.2 * u }
      : { tagTop: 4.5 * u, tagFont: 2.8 * u, areaTop: 12 * u, areaBottom: 25 * u, subsBottom: 6.5 * u, subsFont: 4.0 * u,
          h1: 7.2 * u, sub: 4.2 * u, note: 3.4 * u, icon: 20 * u, src: 2.8 * u, btn: 4.2 * u };
    m.u = u; m.portrait = portrait;
    return m;
  }

  function lineCount(el) {
    const lh = parseFloat(getComputedStyle(el).lineHeight);
    return Math.round(el.getBoundingClientRect().height / lh);
  }

  // Shrink the headline until it is <= 5 lines, then shrink everything until it fits.
  function fit(sc, M, areaH) {
    const c = sc.content, h = sc.h1;
    const apply = (k, hk) => {
      h.style.fontSize = (M.h1 * hk) + 'px';
      if (sc.sub) sc.sub.style.fontSize = (M.sub * k) + 'px';
      if (sc.note) sc.note.style.fontSize = (M.note * k) + 'px';
      if (sc.icon) sc.icon.style.setProperty('--icon', (M.icon * k) + 'px');
      if (sc.final) { sc.src.style.fontSize = (M.src * k) + 'px'; sc.btn.style.fontSize = (M.btn * k) + 'px'; }
      c.style.gap = (3 * M.u * k) + 'px';
    };
    let hk = 1, k = 1;
    apply(k, hk);
    while (lineCount(h) > 5 && hk > 0.4) { hk *= 0.94; apply(k, hk); }
    const natural = () => Array.from(c.children).reduce((s, ch) => s + ch.getBoundingClientRect().height, 0)
      + parseFloat(c.style.gap) * (c.children.length - 1);
    while (natural() > areaH && k > 0.35) { k *= 0.95; hk *= 0.95; apply(k, hk); }
    sc.lines = lineCount(h);
    sc.scale = k;
    sc.hscale = hk;
  }

  window.init = async function (data) {
    D = data;
    const root = document.documentElement.style;
    for (const [k, v] of Object.entries(D.palette || {})) root.setProperty('--' + k, v);
    const M = layoutMetrics();
    els = {
      grid: document.getElementById('grid'), area: document.getElementById('area'),
      tag: document.getElementById('tag'), subs: document.querySelector('#subs span'),
      subsBox: document.getElementById('subs'), bar: document.getElementById('bar'),
      wipe: document.getElementById('wipebar'),
    };
    els.area.style.top = M.areaTop + 'px';
    els.area.style.bottom = M.areaBottom + 'px';
    els.tag.style.top = M.tagTop + 'px';
    els.tag.style.left = '5%';
    els.tag.style.fontSize = M.tagFont + 'px';
    els.tag.querySelector('span').textContent = D.channel_tag || '';
    els.tag.style.display = D.channel_tag ? 'flex' : 'none';
    els.subsBox.style.bottom = M.subsBottom + 'px';
    els.subs.style.fontSize = M.subsFont + 'px';

    await document.fonts.ready;
    // make sure every face we use is actually loaded before measuring
    await Promise.all(['400', '700', '800'].map((w) => document.fonts.load(`${w} 40px 'Noto Sans Sinhala'`, 'අ')));
    await Promise.all(['400', '700'].map((w) => document.fonts.load(`${w} 40px 'DejaVu Sans Local'`, 'A1')));

    scenes = D.scenes.map((s, i) => {
      const sec = document.createElement('section');
      sec.className = 'scene';
      const icon = s.icon && s.icon !== 'none' && window.ICONS[s.icon] ? s.icon : null;
      let html = '<div class="content">';
      if (icon) html += `<div class="icon">${window.ICONS[icon].build(s.icon_value)}</div>`;
      html += `<h1 class="headline">${headlineHTML(s.headline || '')}</h1>`;
      if (s.sub) html += `<p class="sub">${esc(s.sub)}</p>`;
      if (s.note) html += `<p class="note">${esc(s.note)}</p>`;
      if (s.is_last && (D.sources_text || D.subscribe_text)) {
        html += '<div class="final">';
        if (D.sources_text) html += `<div class="sources">${esc(D.sources_text)}</div>`;
        if (D.subscribe_text) html += `<div class="subscribe"><svg viewBox="0 0 24 24"><path d="M4 4 L20 12 L4 20z" fill="#fff"/></svg><span>${esc(D.subscribe_text)}</span></div>`;
        html += '</div>';
      }
      html += '</div>';
      sec.innerHTML = html;
      els.area.appendChild(sec);
      const q = (c) => sec.querySelector(c);
      const sc = Object.assign({}, s, {
        index: i, el: sec, content: q('.content'), iconEl: q('.icon'), icon: q('.icon'), iconKind: icon,
        svg: q('.icon svg'), h1: q('.headline'), words: Array.from(sec.querySelectorAll('.headline .w')),
        sub: q('.sub'), note: q('.note'), final: q('.final'), src: q('.sources'), btn: q('.subscribe'),
        end: s.start + s.dur,
      });
      sec.style.display = 'block';
      fit(sc, M, els.area.getBoundingClientRect().height);
      sec.style.display = 'none';
      return sc;
    });
    cues = D.cues || [];
    render(0);
    return scenes.map((s) => ({ lines: s.lines, scale: +s.scale.toFixed(3), hscale: +s.hscale.toFixed(3) }));
  };

  // ---- element entrance animations --------------------------------------------------
  function enter(el, kind, t, delay, M) {
    if (!el) return;
    const x = t - delay, a = ease(x / 0.7), u = M.u;
    let tf = '', op = clamp(x / 0.35);
    switch (kind) {
      case 'slide-left': tf = `translateX(${(1 - a) * 30 * u}px)`; break;
      case 'slide-right': tf = `translateX(${-(1 - a) * 30 * u}px)`; break;
      case 'zoom': tf = `scale(${(0.55 + 0.45 * back(x / 0.6)).toFixed(4)})`; break;
      case 'bounce': { // drop a short way + squash-free pop, so it never crosses neighbours
        const b = bounce(x / 0.9);
        tf = `translateY(${(-(1 - b) * 6 * u).toFixed(2)}px) scale(${(0.75 + 0.25 * b).toFixed(4)})`; op = clamp(x / 0.2); break;
      }
      default: tf = `translateY(${(1 - a) * 3 * u}px)`; op = a; // fade / typewriter blocks
    }
    el.style.opacity = op.toFixed(4);
    el.style.transform = tf;
  }

  function typewriter(sc, t, delay) {
    const n = sc.words.length, per = Math.min(0.16, 1.4 / Math.max(1, n));
    sc.words.forEach((w, k) => {
      const x = (t - delay - k * per) / 0.12;
      w.style.opacity = clamp(x).toFixed(3);
      // freshly typed word flashes in the accent colour
      w.style.color = x > 0 && x < 2.5 && !w.classList.contains('hl') ? 'var(--accent)' : '';
    });
    return delay + n * per + 0.12;
  }

  function animateScene(sc, lt, M) {
    const anim = sc.animation || 'fade';
    let after;
    if (sc.iconEl) {
      sc.iconEl.style.opacity = '1';
      window.ICONS[sc.iconKind].frame(sc.svg, lt, sc.icon_value);
    }
    if (anim === 'typewriter') {
      sc.h1.style.opacity = '1'; sc.h1.style.transform = '';
      after = typewriter(sc, lt, 0.2);
    } else {
      enter(sc.h1, anim, lt, 0.12, M);
      after = 0.45;
    }
    const subKind = anim === 'typewriter' || anim === 'zoom' || anim === 'bounce' ? 'fade' : anim;
    enter(sc.sub, subKind, lt, after, M);
    enter(sc.note, 'fade', lt, after + 0.25, M);
    if (sc.final) {
      enter(sc.src, 'fade', lt, after + 0.4, M);
      const b = lt - (after + 0.6);
      const pop = back(b / 0.5);
      // bounce every 2 s after it pops in
      const c = b > 0.8 ? (b - 0.8) % 2 : 9, hop = c < 0.6 ? Math.abs(Math.sin(c / 0.6 * Math.PI * 2)) * Math.exp(-c * 3) : 0;
      sc.btn.style.opacity = clamp(b / 0.15).toFixed(3);
      sc.btn.style.transform = `translateY(${(-hop * 3.5 * M.u).toFixed(2)}px) scale(${(0.3 + 0.7 * pop).toFixed(4)})`;
    }
    // slow push-in over the whole scene
    sc.content.style.transform = `scale(${(1 + 0.03 * clamp(lt / Math.max(sc.dur, 1))).toFixed(5)})`;
  }

  // ---- scene transitions ------------------------------------------------------------
  function setScene(sc, on, op = 1, tf = '', clip = '') {
    sc.el.style.display = on ? 'block' : 'none';
    if (!on) return;
    sc.el.style.opacity = op;
    sc.el.style.transform = tf;
    sc.el.style.clipPath = clip;
  }

  window.render = function (t) {
    const M = layoutMetrics();
    const T = D.transition;
    let cur = scenes.length - 1;
    for (let i = 0; i < scenes.length; i++) if (t < scenes[i].end) { cur = i; break; }
    els.wipe.style.display = 'none';
    scenes.forEach((s) => setScene(s, false));

    const sc = scenes[cur], lt = t - sc.start;
    const prev = cur > 0 ? scenes[cur - 1] : null;
    if (prev && lt < T) {
      const p = ease(lt / T), kind = sc.transition || 'fade';
      if (kind === 'wipe') {
        setScene(prev, true, 1, '', `inset(0 0 0 ${(p * 100).toFixed(3)}%)`);
        setScene(sc, true, 1, '', `inset(0 ${((1 - p) * 100).toFixed(3)}% 0 0)`);
        els.wipe.style.display = 'block';
        els.wipe.style.left = `calc(${(p * 100).toFixed(3)}% - ${0.6 * M.u}px)`;
      } else {
        // out-then-in (never two text layouts on screen at once): the old scene
        // leaves in the first half, the new one arrives in the second half
        const q = lt / T, out = clamp(1 - q * 2), inn = ease((q - 0.5) * 2);
        if (kind === 'zoom') {
          setScene(prev, true, out.toFixed(4), `scale(${(1 + 0.3 * (1 - out)).toFixed(4)})`);
          setScene(sc, true, inn.toFixed(4), `scale(${(0.85 + 0.15 * inn).toFixed(4)})`);
        } else {
          setScene(prev, true, out.toFixed(4));
          setScene(sc, true, inn.toFixed(4));
        }
      }
      animateScene(prev, t - prev.start, M);
    } else {
      setScene(sc, true);
    }
    // the very first scene fades up from black
    if (cur === 0) sc.el.style.opacity = clamp(t / 0.4).toFixed(4);
    animateScene(sc, lt, M);

    // persistent elements
    els.grid.style.transform = `translate(${(-(t * 6) % (8 * M.u)).toFixed(2)}px, ${(-(t * 3) % (8 * M.u)).toFixed(2)}px)`;
    const tg = ease(t / 0.6);
    els.tag.style.opacity = tg.toFixed(3);
    els.tag.style.transform = `translateX(${(-(1 - tg) * 6 * M.u).toFixed(2)}px)`;
    els.bar.style.width = (clamp(t / D.total) * 100).toFixed(4) + '%';

    let cue = null;
    for (const c of cues) if (t >= c.start && t < c.end) { cue = c; break; }
    if (cue) {
      els.subs.style.display = 'inline';
      if (els.subs.textContent !== cue.text) els.subs.textContent = cue.text;
      els.subs.style.opacity = clamp((t - cue.start) / 0.08).toFixed(3);
    } else {
      els.subs.style.display = 'none';
    }
  };

  // ---- layout QA ----------------------------------------------------------------------
  const box = (el) => { const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; };
  const hit = (a, b) => a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1;

  // Call after render(t) at a moment where the scene is settled.
  window.checkScene = function (i) {
    const sc = scenes[i], issues = [];
    const W = D.width, H = D.height;
    const parts = [['icon', sc.iconEl], ['headline', sc.h1], ['sub', sc.sub], ['note', sc.note], ['final', sc.final]]
      .filter(([, e]) => e).map(([n, e]) => [n, box(e)]);
    for (let a = 0; a < parts.length; a++)
      for (let b = a + 1; b < parts.length; b++)
        if (hit(parts[a][1], parts[b][1])) issues.push(`${parts[a][0]} overlaps ${parts[b][0]}`);
    const tag = box(els.tag), subsTop = H - parseFloat(els.subsBox.style.bottom) - 2 * parseFloat(els.subs.style.fontSize) * 1.45;
    for (const [n, r] of parts) {
      if (r.l < 0 || r.r > W || r.t < 0 || r.b > H) issues.push(`${n} is off-screen`);
      if (els.tag.style.display !== 'none' && hit(r, tag)) issues.push(`${n} overlaps channel tag`);
      if (r.b > subsTop) issues.push(`${n} reaches into the subtitle zone`);
    }
    if (sc.lines > 5) issues.push(`headline still ${sc.lines} lines`);
    return issues;
  };

  // Subtitle cues must fit in two lines.
  window.checkCues = function () {
    const issues = [];
    const prev = els.subs.textContent, disp = els.subs.style.display;
    els.subs.style.display = 'inline';
    for (const c of cues) {
      els.subs.textContent = c.text;
      const lines = els.subs.getClientRects().length;
      if (lines > 2) issues.push(`subtitle "${c.text}" wraps to ${lines} lines`);
    }
    els.subs.textContent = prev; els.subs.style.display = disp;
    return issues;
  };
})();
