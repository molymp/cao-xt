/**
 * Dorfkern Logo — animiertes SVG-Embed (Variante 1: horizontales Lockup)
 * =======================================================================
 *
 * Einbindung:
 *   <script src="dorfkern-logo.js" defer></script>
 *
 * Verwendung:
 *   <div data-dorfkern-logo></div>                          (auto)
 *   <div data-dorfkern-logo="mark"></div>                   (nur Marke)
 *   <div data-dorfkern-logo="vertical" data-theme="dark"
 *        data-size="140" data-tagline="Der Laden läuft">
 *   </div>
 *
 * Attribute (alle optional):
 *   data-dorfkern-logo   "horizontal" | "vertical" | "mark"    (default: "horizontal")
 *   data-theme           "light" | "dark" | "terracotta"       (default: "light")
 *   data-size            Höhe der Marke in px                  (default: 80)
 *   data-tagline         Tagline-Text, "" oder "false" = aus   (default: "Der Laden läuft")
 *   data-word            Wortmarke                             (default: "Dorfkern")
 *   data-dot             "true" | "false"  Terracotta-Punkt    (default: "true")
 *   data-autoplay        "true" | "false"                      (default: "true")
 *   data-loop            ms zwischen Wiederholungen, 0 = aus   (default: 0)
 *
 * Programmatisch:
 *   DorfkernLogo.mount(element, options)   → instance
 *   instance.play()                        → Animation neustarten
 *   instance.destroy()                     → Element leeren
 *   DorfkernLogo.mountAll()                → alle [data-dorfkern-logo] re-mounten
 */
(function (global) {
  'use strict';

  // ── Design-Tokens ───────────────────────────────────────────────────────
  const TOKENS = {
    ink:            '#141414',
    cream:          '#f2ede3',
    nightInk:       '#1b2027',
    terracotta:     '#b65c3a',
    terracottaLight:'#e08a66',
  };

  const THEMES = {
    light:      { bg: 'transparent',           fg: TOKENS.ink,    kern: TOKENS.terracotta,      muted: 'rgba(0,0,0,0.55)' },
    dark:       { bg: 'transparent',           fg: TOKENS.cream,  kern: TOKENS.terracottaLight, muted: 'rgba(242,237,227,0.6)' },
    terracotta: { bg: 'transparent',           fg: TOKENS.cream,  kern: TOKENS.cream,           muted: 'rgba(242,237,227,0.7)', dot: TOKENS.ink },
  };

  // Raster: 5×4 Punkte, Kreis-Maske Radius²≤4.8 um (2,1.5)
  const DOTS = (() => {
    const out = [];
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 5; c++) {
        const dx = c - 2, dy = r - 1.5;
        if (dx * dx + dy * dy > 4.8) continue;
        out.push({
          cx: 22 + c * 9,
          cy: 34 + r * 9,
          d: Math.hypot(dx, dy),
          center: r === 2 && c === 2,
        });
      }
    }
    out.sort((a, b) => a.d - b.d); // von innen nach außen
    return out;
  })();

  // Stellt sicher, dass das gemeinsame <style>-Tag nur einmal in <head> landet.
  let stylesInjected = false;
  function injectStyles() {
    if (stylesInjected || typeof document === 'undefined') return;
    stylesInjected = true;
    const css = `
      .dk-logo { display:inline-flex; align-items:center; gap: 0.55em; font-family: Fraunces, 'Times New Roman', serif; }
      .dk-logo.dk-vertical { flex-direction: column; gap: 0.45em; }
      .dk-logo .dk-word { font-weight: 500; letter-spacing: -0.02em; line-height: 1; color: inherit; display: inline-flex; align-items: baseline; }
      .dk-logo .dk-dot  { display: inline-block; width: 0.18em; height: 0.18em; border-radius: 50%; background: var(--dk-accent, #b65c3a); margin-left: 0.04em; transform: translateY(-0.02em); opacity: 0; }
      .dk-logo.dk-playing .dk-dot { animation: dk-dotpop 0.45s cubic-bezier(0.34,1.56,0.64,1) 2.4s forwards; }
      @keyframes dk-dotpop { 0% { opacity: 0; transform: translateY(-0.02em) scale(0); } 70% { opacity: 1; transform: translateY(-0.02em) scale(1.35); } 100% { opacity: 1; transform: translateY(-0.02em) scale(1); } }
      .dk-logo .dk-tagline { font: 500 0.62em/1 'JetBrains Mono', ui-monospace, monospace; letter-spacing: 0.22em; text-transform: uppercase; margin-top: 0.4em; }
      .dk-logo .dk-meta { display: flex; flex-direction: column; }
      .dk-logo.dk-vertical .dk-meta { align-items: center; }

      .dk-logo svg .dk-stroke { stroke-linecap: square; fill: none; stroke-width: 3.2; stroke-linejoin: miter; stroke-miterlimit: 6; }
      .dk-logo svg .dk-floor  { stroke-dasharray: 60; stroke-dashoffset: 60; }
      .dk-logo svg .dk-roof   { stroke-dasharray: 96; stroke-dashoffset: 96; }
      .dk-logo svg .dk-dot,
      .dk-logo svg .dk-core   { transform-origin: center; transform-box: fill-box; opacity: 0; }
      .dk-logo svg .dk-glow   { transform-origin: center; transform-box: fill-box; opacity: 0; }
      .dk-logo svg .dk-wordmark { opacity: 0; transform: translateY(4px); transition: none; }

      .dk-logo.dk-playing svg .dk-roof  { animation: dk-draw 1s cubic-bezier(0.2,0.9,0.3,1) 0.1s forwards; }
      .dk-logo.dk-playing svg .dk-floor { animation: dk-draw 0.6s cubic-bezier(0.2,0.9,0.3,1) 1.05s forwards; }
      .dk-logo.dk-playing svg .dk-dot   { animation: dk-pop 0.35s cubic-bezier(0.34,1.56,0.64,1) forwards; }
      .dk-logo.dk-playing svg .dk-core  { animation: dk-core 0.6s cubic-bezier(0.34,1.56,0.64,1) 2.2s forwards; }
      .dk-logo.dk-playing svg .dk-glow  { animation: dk-glow 1.4s ease-out 2.4s forwards; }
      .dk-logo.dk-playing .dk-wordmark  { animation: dk-fade 0.55s cubic-bezier(0.2,0.9,0.3,1) 1.25s forwards; }

      @keyframes dk-draw { to { stroke-dashoffset: 0; } }
      @keyframes dk-pop  {
        0%   { opacity: 0; transform: scale(0); }
        70%  { opacity: 1; transform: scale(1.25); }
        100% { opacity: 1; transform: scale(1); }
      }
      @keyframes dk-core {
        0%   { opacity: 0; transform: scale(0); }
        55%  { opacity: 1; transform: scale(1.5); }
        100% { opacity: 1; transform: scale(1); }
      }
      @keyframes dk-glow {
        0%   { opacity: 0.35; transform: scale(1); }
        100% { opacity: 0;    transform: scale(3.2); }
      }
      @keyframes dk-fade {
        to { opacity: 1; transform: translateY(0); }
      }

      @media (prefers-reduced-motion: reduce) {
        .dk-logo.dk-playing svg .dk-roof,
        .dk-logo.dk-playing svg .dk-floor,
        .dk-logo.dk-playing svg .dk-dot,
        .dk-logo.dk-playing svg .dk-core,
        .dk-logo.dk-playing svg .dk-glow,
        .dk-logo.dk-playing .dk-wordmark { animation: none !important; }
        .dk-logo svg .dk-roof,
        .dk-logo svg .dk-floor { stroke-dashoffset: 0; }
        .dk-logo svg .dk-dot,
        .dk-logo svg .dk-core  { opacity: 1; }
        .dk-logo .dk-wordmark  { opacity: 1; transform: none; }
      }
    `;
    const style = document.createElement('style');
    style.setAttribute('data-dorfkern-logo-styles', '');
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ── SVG-Builder ─────────────────────────────────────────────────────────
  function buildMarkSVG(size, theme) {
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(size));
    svg.setAttribute('viewBox', '0 0 80 80');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.color = theme.fg;
    svg.style.flex = '0 0 auto';

    // Dach + Traufen als EIN zusammenhängender Pfad
    // Start links an Traufen-Außenkante → First → rechts zur Traufen-Außenkante.
    // Keine Überlappung, saubere Miter-Joins.
    const roof = document.createElementNS(svgNS, 'path');
    roof.setAttribute('class', 'dk-stroke dk-roof');
    roof.setAttribute('d', 'M6 28 L 11 28 L 40 6.5 L 69 28 L 74 28');
    roof.setAttribute('stroke', 'currentColor');
    svg.appendChild(roof);

    // Punkte (inkl. Kern & Glow)
    DOTS.forEach((dot, i) => {
      if (dot.center) {
        const core = document.createElementNS(svgNS, 'circle');
        core.setAttribute('class', 'dk-core');
        core.setAttribute('cx', dot.cx);
        core.setAttribute('cy', dot.cy);
        core.setAttribute('r', '2.4');
        core.setAttribute('fill', theme.kern);
        svg.appendChild(core);

        const glow = document.createElementNS(svgNS, 'circle');
        glow.setAttribute('class', 'dk-glow');
        glow.setAttribute('cx', dot.cx);
        glow.setAttribute('cy', dot.cy);
        glow.setAttribute('r', '2.4');
        glow.setAttribute('fill', theme.kern);
        svg.appendChild(glow);
      } else {
        const c = document.createElementNS(svgNS, 'circle');
        c.setAttribute('class', 'dk-dot');
        c.setAttribute('cx', dot.cx);
        c.setAttribute('cy', dot.cy);
        c.setAttribute('r', '2.4');
        c.setAttribute('fill', 'currentColor');
        c.style.animationDelay = (1.5 + i * 0.07) + 's';
        svg.appendChild(c);
      }
    });

    // Boden
    const floor = document.createElementNS(svgNS, 'path');
    floor.setAttribute('class', 'dk-stroke dk-floor');
    floor.setAttribute('d', 'M10 72 L 70 72');
    floor.setAttribute('stroke', 'currentColor');
    svg.appendChild(floor);

    return svg;
  }

  // ── Instance ────────────────────────────────────────────────────────────
  function mount(el, opts) {
    if (!el) return null;
    injectStyles();

    const options = Object.assign(
      {
        variant:  el.getAttribute('data-dorfkern-logo') || 'horizontal',
        theme:    el.getAttribute('data-theme') || 'light',
        size:     parseFloat(el.getAttribute('data-size')) || 80,
        tagline:  el.hasAttribute('data-tagline') ? el.getAttribute('data-tagline') : 'Der Laden läuft',
        word:     el.getAttribute('data-word') || 'Dorfkern',
        dot:      el.getAttribute('data-dot') !== 'false',
        autoplay: el.getAttribute('data-autoplay') !== 'false',
        loop:     parseInt(el.getAttribute('data-loop') || '0', 10),
      },
      opts || {}
    );
    // "horizontal" wird in der Praxis als "horizontal" behandelt; sonstige Werte außer
    // vertical|mark fallen auf horizontal zurück.
    if (!['horizontal', 'vertical', 'mark'].includes(options.variant)) {
      options.variant = 'horizontal';
    }
    const theme = THEMES[options.theme] || THEMES.light;
    const showTagline = options.tagline && options.tagline !== 'false' && options.variant !== 'mark';
    const fontSize = options.size * 0.5; // Wortmarke skaliert an der Marken-Höhe

    // Root leeren
    while (el.firstChild) el.removeChild(el.firstChild);
    el.classList.add('dk-logo');
    el.classList.toggle('dk-vertical', options.variant === 'vertical');
    el.classList.toggle('dk-mark', options.variant === 'mark');
    el.style.color = theme.fg;

    // Marke
    const svg = buildMarkSVG(options.size, theme);
    el.appendChild(svg);

    // Wortmarke
    if (options.variant !== 'mark') {
      const meta = document.createElement('span');
      meta.className = 'dk-meta dk-wordmark';

      const word = document.createElement('span');
      word.className = 'dk-word';
      word.style.fontSize = fontSize + 'px';
      word.textContent = options.word;
      if (options.dot) {
        const dot = document.createElement('span');
        dot.className = 'dk-dot';
        dot.style.setProperty('--dk-accent', theme.dot || theme.kern);
        word.appendChild(dot);
      }
      meta.appendChild(word);

      if (showTagline) {
        const tl = document.createElement('span');
        tl.className = 'dk-tagline';
        tl.style.color = theme.muted;
        tl.style.fontSize = Math.max(9, fontSize * 0.28) + 'px';
        tl.textContent = options.tagline;
        meta.appendChild(tl);
      }
      el.appendChild(meta);
    }

    let loopTimer = null;

    function play() {
      el.classList.remove('dk-playing');
      // Reflow erzwingen, damit CSS-Animationen neu starten
      // eslint-disable-next-line no-unused-expressions
      void el.offsetWidth;
      el.classList.add('dk-playing');
      if (options.loop > 0) {
        clearTimeout(loopTimer);
        // Gesamtdauer ~3.6s + loop-Gap
        loopTimer = setTimeout(play, 3600 + options.loop);
      }
    }

    function destroy() {
      clearTimeout(loopTimer);
      while (el.firstChild) el.removeChild(el.firstChild);
      el.classList.remove('dk-logo', 'dk-vertical', 'dk-mark', 'dk-playing');
    }

    const instance = { el, options, play, destroy };

    if (options.autoplay) {
      // Auf Sichtbarkeit warten, damit die Animation nicht beim Scroll nach unten „verpasst" wird.
      if ('IntersectionObserver' in global) {
        const io = new IntersectionObserver((entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              play();
              io.disconnect();
            }
          });
        }, { threshold: 0.2 });
        io.observe(el);
      } else {
        play();
      }
    }

    el.__dorfkernLogo = instance;
    return instance;
  }

  function mountAll(root) {
    const scope = root || document;
    const nodes = scope.querySelectorAll('[data-dorfkern-logo]');
    const list = [];
    nodes.forEach((n) => {
      if (n.__dorfkernLogo) n.__dorfkernLogo.destroy();
      list.push(mount(n));
    });
    return list;
  }

  const api = { mount, mountAll, tokens: TOKENS };
  global.DorfkernLogo = api;

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => mountAll());
    } else {
      mountAll();
    }
  }
})(typeof window !== 'undefined' ? window : this);
