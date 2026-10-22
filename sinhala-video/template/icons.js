// Inline SVG icons. Each icon has build(value) -> svg markup and frame(svg, t),
// which sets every animated attribute from the scene-local time t (seconds).
// Colours: currentColor = accent, var(--text) = foreground.
(function () {
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const ease = (x) => 1 - Math.pow(1 - clamp(x), 3);
  const back = (x) => { x = clamp(x); const c = 1.70158; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
  const bounce = (x) => {
    x = clamp(x); const n = 7.5625, d = 2.75;
    if (x < 1 / d) return n * x * x;
    if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75;
    if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375;
    return n * (x -= 2.625 / d) * x + 0.984375;
  };
  const $ = (svg, sel) => svg.querySelector(sel);
  const $$ = (svg, sel) => Array.from(svg.querySelectorAll(sel));
  const FG = 'var(--text)';

  // "1,250+" -> {pre:'', num:1250, dec:0, suf:'+', comma:true}
  function parseValue(v) {
    if (v === undefined || v === null || v === '') return null;
    const m = String(v).match(/^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/);
    if (!m) return { text: String(v) };
    const raw = m[2];
    return { pre: m[1], num: parseFloat(raw.replace(/,/g, '')), dec: (raw.split('.')[1] || '').length,
             suf: m[3], comma: raw.includes(',') };
  }
  function countText(p, k) {
    if (!p) return '';
    if (p.text !== undefined) return p.text;
    let n = (p.num * clamp(k)).toFixed(p.dec);
    if (p.comma) n = Number(n).toLocaleString('en-US', { minimumFractionDigits: p.dec, maximumFractionDigits: p.dec });
    return p.pre + n + p.suf;
  }
  const countLabel = (y) =>
    `<text class="count" x="100" y="${y}" text-anchor="middle" font-size="34" font-weight="800"
       fill="${FG}" font-family="DejaVu Sans Local, DejaVu Sans, sans-serif"></text>`;

  const ICONS = {
    pin: {
      build: () => `<svg viewBox="0 0 200 200">
        ${[0, 1, 2].map(() => `<ellipse class="ring" cx="100" cy="168" rx="40" ry="13" fill="none" stroke="currentColor" stroke-width="4"/>`).join('')}
        <ellipse cx="100" cy="168" rx="22" ry="7" fill="rgba(0,0,0,.45)"/>
        <g class="pin"><path d="M100 165 C 78 128 52 104 52 72 a48 48 0 0 1 96 0 c0 32 -26 56 -48 93z" fill="currentColor"/>
        <circle cx="100" cy="72" r="18" fill="${FG}"/></g></svg>`,
      frame(svg, t) {
        const drop = bounce(t / 0.8);
        $(svg, '.pin').setAttribute('transform', `translate(0 ${(-90 * (1 - drop)).toFixed(2)})`);
        $(svg, '.pin').style.opacity = clamp(t / 0.15);
        $$(svg, '.ring').forEach((r, k) => {
          const ph = t < 0.6 ? 0 : (((t - 0.6) / 1.5 + k / 3) % 1);
          const s = 0.3 + 1.7 * ph;
          r.setAttribute('transform', `translate(100 168) scale(${s.toFixed(3)}) translate(-100 -168)`);
          r.style.opacity = t < 0.6 ? 0 : (1 - ph) * 0.9;
        });
      },
    },

    people: {
      build: (v) => {
        const person = (cls, x, s) => `<g class="${cls}"><g transform="translate(${x} 0) scale(${s})">
          <circle cx="0" cy="62" r="20"/><path d="M-36 150 v-24 a36 36 0 0 1 72 0 v24z"/></g></g>`;
        return `<svg viewBox="0 0 200 200"><g fill="${FG}" opacity=".55">${person('pl', 46, .8)}${person('pr', 154, .8)}</g>
          <g fill="currentColor">${person('pc', 100, 1)}</g>${v ? countLabel(195) : ''}</svg>`;
      },
      frame(svg, t, v) {
        const a = ease((t - 0.15) / 0.6), c = back(t / 0.6);
        $(svg, '.pl').setAttribute('transform', `translate(${(-60 * (1 - a)).toFixed(2)} 0)`);
        $(svg, '.pr').setAttribute('transform', `translate(${(60 * (1 - a)).toFixed(2)} 0)`);
        $(svg, '.pl').style.opacity = a; $(svg, '.pr').style.opacity = a;
        $(svg, '.pc').setAttribute('transform', `translate(0 ${(40 * (1 - c)).toFixed(2)})`);
        $(svg, '.pc').style.opacity = clamp(t / 0.3);
        const lbl = $(svg, '.count');
        if (lbl) lbl.textContent = countText(parseValue(v), ease((t - 0.3) / 1.4));
      },
    },

    scale: {
      build: () => `<svg viewBox="0 0 200 200" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">
        <path d="M100 40 V175 M66 178 H134" stroke="${FG}"/><circle cx="100" cy="36" r="8" fill="currentColor" stroke="none"/>
        <g class="beam"><path d="M38 52 H162"/>
          <g class="panL"><path d="M38 52 L18 108 M38 52 L58 108 M12 108 h52 a26 20 0 0 1 -52 0z" fill="currentColor" fill-opacity=".25"/></g>
          <g class="panR"><path d="M162 52 L142 108 M162 52 L182 108 M136 108 h52 a26 20 0 0 1 -52 0z" fill="currentColor" fill-opacity=".25"/></g>
        </g></svg>`,
      frame(svg, t) {
        // settle from a big tilt into a gentle sway
        const settle = 22 * Math.exp(-t * 2.2) * Math.cos(t * 5);
        const ang = settle + 5 * Math.sin(t * 1.6) * clamp(t / 1.2);
        $(svg, '.beam').setAttribute('transform', `rotate(${ang.toFixed(2)} 100 52)`);
        // pans hang vertically: counter-rotate around their pivots
        $(svg, '.panL').setAttribute('transform', `rotate(${(-ang).toFixed(2)} 38 52)`);
        $(svg, '.panR').setAttribute('transform', `rotate(${(-ang).toFixed(2)} 162 52)`);
        svg.style.opacity = clamp(t / 0.3);
      },
    },

    calendar: {
      build: (v) => {
        let cells = '';
        for (let r = 0; r < 4; r++) for (let c = 0; c < 6; c++)
          cells += `<rect class="cell" x="${35 + c * 22.5}" y="${88 + r * 20}" width="16" height="13" rx="3"/>`;
        return `<svg viewBox="0 0 200 200">
          <rect x="22" y="34" width="156" height="152" rx="16" fill="rgba(255,255,255,.08)" stroke="${FG}" stroke-width="6"/>
          <path d="M22 50 a16 16 0 0 1 16 -16 h124 a16 16 0 0 1 16 16 v24 h-156z" fill="currentColor"/>
          <rect x="56" y="18" width="10" height="30" rx="5" fill="${FG}"/><rect x="134" y="18" width="10" height="30" rx="5" fill="${FG}"/>
          ${v ? `<text class="count" x="100" y="152" text-anchor="middle" font-size="60" font-weight="800" fill="${FG}"
                 font-family="DejaVu Sans Local, DejaVu Sans, sans-serif"></text>` : `<g class="cells">${cells}</g>`}</svg>`;
      },
      frame(svg, t, v) {
        const a = back(t / 0.5);
        svg.style.transform = `scale(${(0.6 + 0.4 * a).toFixed(3)})`;
        svg.style.opacity = clamp(t / 0.25);
        const lbl = $(svg, '.count');
        if (lbl) { lbl.textContent = countText(parseValue(v), ease((t - 0.3) / 1.3)); return; }
        const cells = $$(svg, '.cell'), n = cells.length;
        const filled = Math.floor(clamp((t - 0.3) / 1.4) * n);
        cells.forEach((c, k) => {
          c.setAttribute('fill', k < filled ? (k === filled - 1 || (filled === n && k === n - 1) ? 'currentColor' : FG) : 'rgba(255,255,255,.18)');
          c.setAttribute('fill-opacity', k < filled && k !== filled - 1 ? '.8' : '1');
        });
      },
    },

    globe: {
      build: () => `<svg viewBox="0 0 200 200" fill="none" stroke-linecap="round">
        <circle class="g arc" cx="100" cy="100" r="66" stroke="${FG}" stroke-width="6"/>
        <ellipse class="g arc" cx="100" cy="100" rx="66" ry="22" stroke="${FG}" stroke-width="4" opacity=".7"/>
        <path class="g arc" d="M38 72 H162 M38 128 H162" stroke="${FG}" stroke-width="4" opacity=".5"/>
        ${[0, 1, 2].map(() => `<ellipse class="mer" cx="100" cy="100" rx="66" ry="66" stroke="currentColor" stroke-width="5"/>`).join('')}
        <path class="orbit arc" d="M16 130 A92 40 -20 0 0 184 70" stroke="currentColor" stroke-width="5"/>
        <circle class="sat" r="8" fill="currentColor"/></svg>`,
      frame(svg, t) {
        $$(svg, '.arc').forEach((el, k) => {
          const len = el.getTotalLength();
          el.style.strokeDasharray = len;
          el.style.strokeDashoffset = (len * (1 - ease((t - k * 0.12) / 0.9))).toFixed(2);
        });
        const spin = t * 0.9;
        $$(svg, '.mer').forEach((m, k) => {
          const ph = spin + k * Math.PI / 3;
          m.setAttribute('rx', (66 * Math.abs(Math.cos(ph))).toFixed(2));
          m.style.opacity = clamp((t - 0.5) / 0.5) * (0.35 + 0.65 * Math.abs(Math.sin(ph)));
        });
        const orbit = $(svg, '.orbit'), len = orbit.getTotalLength();
        const p = orbit.getPointAtLength(len * ((t * 0.35) % 1));
        const sat = $(svg, '.sat');
        sat.setAttribute('cx', p.x.toFixed(2)); sat.setAttribute('cy', p.y.toFixed(2));
        sat.style.opacity = clamp((t - 0.9) / 0.3);
      },
    },

    phone: {
      build: () => `<svg viewBox="0 0 200 200" fill="none" stroke-linecap="round">
        ${[0, 1].map((k) => `<path class="wave" d="M${42 - k * 16} ${80 - k * 12} a${40 + k * 22} ${40 + k * 22} 0 0 0 0 ${40 + k * 24}" stroke="currentColor" stroke-width="6"/>
          <path class="wave" d="M${158 + k * 16} ${80 - k * 12} a${40 + k * 22} ${40 + k * 22} 0 0 1 0 ${40 + k * 24}" stroke="currentColor" stroke-width="6"/>`).join('')}
        <g class="body"><rect x="66" y="30" width="68" height="140" rx="14" fill="rgba(255,255,255,.08)" stroke="${FG}" stroke-width="6"/>
          <rect x="76" y="48" width="48" height="96" rx="5" fill="currentColor" fill-opacity=".35"/>
          <path d="M90 40 h20" stroke="${FG}" stroke-width="5"/><circle cx="100" cy="156" r="5" fill="${FG}"/></g></svg>`,
      frame(svg, t) {
        const a = ease(t / 0.6);
        // ring in bursts: shake for 0.6 s every 1.6 s
        const cyc = (t - 0.6) % 1.6, ringing = t > 0.6 && cyc < 0.6;
        const shake = ringing ? 7 * Math.sin(cyc * 50) * Math.sin(Math.PI * cyc / 0.6) : 0;
        $(svg, '.body').setAttribute('transform', `translate(0 ${(70 * (1 - a)).toFixed(2)}) rotate(${shake.toFixed(2)} 100 100)`);
        $(svg, '.body').style.opacity = a;
        $$(svg, '.wave').forEach((w, k) => {
          const ring = Math.floor(k / 2);
          w.style.opacity = ringing ? clamp(Math.sin(Math.PI * clamp((cyc - ring * 0.12) / 0.45))) : 0;
        });
      },
    },

    subscribe: {
      build: () => `<svg viewBox="0 0 200 200">
        <circle class="pulse" cx="100" cy="100" r="62" fill="none" stroke="currentColor" stroke-width="5"/>
        <g class="btn"><rect x="34" y="56" width="132" height="92" rx="24" fill="currentColor"/>
          <path d="M88 80 L124 102 L88 124z" fill="${FG}"/></g>
        <g class="bell" fill="${FG}"><path d="M160 22 a20 20 0 0 1 20 20 v14 l8 12 h-56 l8 -12 v-14 a20 20 0 0 1 20 -20z"/>
          <circle cx="160" cy="74" r="6"/></g></svg>`,
      frame(svg, t) {
        const a = back(t / 0.55);
        $(svg, '.btn').setAttribute('transform', `translate(100 102) scale(${(0.2 + 0.8 * a).toFixed(3)}) translate(-100 -102)`);
        $(svg, '.btn').style.opacity = clamp(t / 0.2);
        const c = (t - 0.6) % 2, sw = t > 0.6 ? 18 * Math.sin(c * 9) * Math.exp(-c * 2.2) : 0;
        $(svg, '.bell').setAttribute('transform', `rotate(${sw.toFixed(2)} 160 22)`);
        $(svg, '.bell').style.opacity = clamp((t - 0.4) / 0.2);
        const ph = t < 0.5 ? 0 : ((t - 0.5) / 1.4) % 1;
        const p = $(svg, '.pulse');
        p.setAttribute('transform', `translate(100 100) scale(${(1 + 0.45 * ph).toFixed(3)}) translate(-100 -100)`);
        p.style.opacity = t < 0.5 ? 0 : (1 - ph) * 0.8;
      },
    },
  };

  window.ICONS = ICONS;
  window.ANIM = { clamp, ease, back, bounce };
})();
