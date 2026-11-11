
// ── metastack.gg test script ─────────────────────────────────────────────────
// Paste into the devtools console on any app.metastack.gg page (desktop layout).
// Adds a "2D Viewer" entry to their icon rail, and a full viewer page styled like
// their own pages: charcoal cards, blue accent, rounded-lg, outline buttons.
// The built-in viewer chrome is disabled (theme.controls: []) — every control on
// the page (play, timeline, rounds, speed, share, scoreboard) is custom, driven
// through the instance API + hooks.
(async () => {
  const API = 'https://api.csstrats.dk';
  // Cache-bust while iterating so you always pull the freshly-published bundle (the CDN caches it
  // ~5 min). Drop the `?t=` once you're done testing.
  const VIEWER = 'https://demoviewer.b-cdn.net/viewer.js?t=' + Date.now();
  const KEY = 'pk_live_YOUR_CLIENT_KEY'; // must be allow-listed for *.metastack.gg

  // metastack's CSP blocks third-party <script src>, but allows 'unsafe-eval' — and the demos
  // CDN serves the bundle with ACAO:* — so fetch the source and eval it instead.
  if (!window.CSDemoViewer) {
    try {
      const r = await fetch(VIEWER);
      if (!r.ok) throw new Error('http ' + r.status);
      (0, eval)(await r.text());
    } catch (e) {
      console.error(
        '[csdv] could not load the bundle — metastack\'s connect-src CSP blocks it.\n' +
        'Strip the CSP via DevTools Local Overrides:\n' +
        '  1. DevTools → Network → reload → select the top document request (metastack.gg)\n' +
        '  2. Response Headers → pencil icon ("Override headers") → pick a local overrides folder\n' +
        '  3. Set content-security-policy to an empty value, reload, re-paste this script\n' +
        '(Undo later in Sources → Overrides.)', e);
      return;
    }
  }

  // Same CSP likely blocks the viewer's blob-URL decode worker (blob: isn't in script-src).
  // Probe once; if blocked, shim blob workers to run on the main thread via 'unsafe-eval'.
  try {
    const u = URL.createObjectURL(new Blob([''], { type: 'application/javascript' }));
    new Worker(u).terminate(); URL.revokeObjectURL(u);
  } catch {
    const Native = window.Worker;
    window.Worker = function (url, opts) {
      if (!String(url).startsWith('blob:')) return new Native(url, opts);
      const shim = { onmessage: null, __blobUrl: url, terminate() {} };
      const post = (msg) => Promise.resolve().then(() => shim.onmessage?.({ data: msg }));
      const ready = fetch(url).then((r) => r.text())
        .then((src) => new Function('postMessage', `let onmessage;\n${src}\n;return onmessage;`)(post));
      shim.postMessage = (msg) => { ready.then((h) => h?.({ data: msg })); };
      return shim;
    };
    console.log('[csdv] blob workers blocked by CSP — decoding rounds on the main thread');
  }

  // ── sample metastack's live palette (their compiled Tailwind includes these) ─
  const probe = (cls, prop) => {
    const el = document.createElement('div'); el.className = cls;
    el.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none;';
    document.body.appendChild(el);
    const val = getComputedStyle(el)[prop]; el.remove();
    return val && val !== 'rgba(0, 0, 0, 0)' && val !== 'rgb(0, 0, 0)' ? val : null;
  };
  const CHARCOAL   = probe('bg-charcoal', 'backgroundColor')   || '#26282d';
  const BLACKOLIVE = probe('bg-blackOlive', 'backgroundColor') || '#3a3d42';
  const BLUE       = probe('bg-blue', 'backgroundColor')       || '#2f7df6';
  const MIST       = probe('!text-silverMist', 'color')        || '#a9aeb4';
  const CT_COL = '#5b9ded', T_COL = '#e6c15c';

  // ── fetch the demo list (feeds the demo picker; first item = initial demo) ──
  let demos = [];
  try { const r = await fetch(API + '/v1/demos?limit=50', { headers: { Authorization: 'Bearer ' + KEY } });
        demos = (await r.json()).items || []; } catch (e) { console.warn('[csdv] demo list failed', e); }
  let demoId = demos[0]?.id ?? 1;

  // ── tear down a previous run ─────────────────────────────────────────────────
  clearInterval(window.csdvms?._pulse);
  window.csdvms?._navObs?.disconnect?.();
  window.csdvms?.viewer?.destroy?.();
  document.getElementById('csdv-ms-page')?.remove();
  document.getElementById('csdv-ms-style')?.remove();
  document.querySelectorAll('.csdv-ms-navitem').forEach((n) => n.remove());

  // ── shared styles (timeline slider, scrollbars, pills) ───────────────────────
  const style = document.createElement('style');
  style.id = 'csdv-ms-style';
  style.textContent = `
    #csdv-ms-page{scrollbar-width:thin;scrollbar-color:${BLACKOLIVE} transparent;}
    #csdv-ms-page ::-webkit-scrollbar{height:6px;width:6px}
    #csdv-ms-page ::-webkit-scrollbar-thumb{background:${BLACKOLIVE};border-radius:3px}
    #csdv-ms-page input[type=range]{-webkit-appearance:none;appearance:none;height:6px;border-radius:3px;
      background:${BLACKOLIVE};outline:none;cursor:pointer;margin:0;}
    #csdv-ms-page input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
      width:14px;height:14px;border-radius:50%;background:${BLUE};border:none;
      box-shadow:0 0 0 3px rgba(255,255,255,.08);}
    #csdv-ms-page input[type=range]::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
      background:${BLUE};border:none;}
    .csdv-ms-btn{transition:background .1s;font-weight:500;font-size:15px;border-radius:8px;
      border:1px solid ${BLUE};background:#000;color:#fff;height:40px;padding:0 20px;cursor:pointer;
      display:inline-flex;align-items:center;gap:8px;white-space:nowrap;}
    .csdv-ms-btn:hover{background:${CHARCOAL};}
    .csdv-ms-icon{border:none;background:transparent;color:#fff;width:40px;height:40px;border-radius:8px;
      cursor:pointer;display:inline-flex;align-items:center;justify-content:center;transition:background .1s;}
    .csdv-ms-icon:hover{background:${CHARCOAL};}
    .csdv-ms-pill{min-width:30px;height:30px;border-radius:6px;border:none;background:${CHARCOAL};
      color:${MIST};font-size:12px;font-weight:500;cursor:pointer;transition:background .1s;
      border-top:2px solid transparent;}
    .csdv-ms-pill:hover{background:${BLACKOLIVE};}
    .csdv-ms-pill.active{background:${BLUE};color:#fff;}
    .csdv-ms-speed{border:none;background:transparent;color:${MIST};border-radius:6px;height:28px;
      padding:0 10px;font-size:13px;font-weight:500;cursor:pointer;}
    .csdv-ms-speed.active{background:${BLUE};color:#fff;}
    .csdv-ms-row{display:grid;grid-template-columns:16px 1fr 64px 34px 58px 1fr 44px;gap:8px;align-items:center;
      padding:7px 12px;border-radius:8px;font-size:13px;cursor:pointer;transition:background .1s;}
    .csdv-ms-row:hover{background:${BLACKOLIVE};}
    .csdv-ms-row.dead{opacity:.45;}
    .csdv-ms-row.followed{outline:1px solid ${BLUE};}
    .csdv-ms-hpbar{height:4px;border-radius:2px;background:${BLACKOLIVE};overflow:hidden;}
    .csdv-ms-hpbar i{display:block;height:100%;border-radius:2px;}
    .csdv-ms-select{background:${CHARCOAL};color:#fff;border:1px solid transparent;border-radius:8px;
      height:40px;padding:0 12px;font-size:15px;cursor:pointer;outline:none;max-width:260px;}
    /* fullscreen takes the whole card, so the control bar (play/timeline/speed) comes along */
    #csdv-ms-card:fullscreen{display:flex;flex-direction:column;background:#000;border-radius:0;}
    #csdv-ms-card:fullscreen #csdv-ms-host{flex:1;min-height:0;height:auto !important;}
  `;
  document.head.appendChild(style);

  // ── sidebar entry (matches their <li>/<a> markup + classes exactly) ──────────
  const NAV_A_CLS = 'flex h-full flex-col items-center justify-center gap-3 rounded-lg py-4 leading-none transition duration-100 active:bg-blackOlive hover:bg-charcoal';
  const navIcon = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 384 384">
    <circle cx="192" cy="192" r="170" fill="none" stroke="#fff" stroke-width="30"/>
    <path fill="#fff" d="M150 112 274 192 150 272Zm0 0"/></svg>`;
  let pageOpen = false;
  const injectNav = () => {
    document.querySelectorAll('aside nav[aria-label="Main navigation"]').forEach((nav) => {
      const ul = nav.querySelector('ul[role="menubar"]');
      if (!ul || ul.querySelector('.csdv-ms-navitem')) return;
      const li = document.createElement('li');
      li.className = 'relative w-[68px] csdv-ms-navitem';
      const a = document.createElement('a');
      a.href = '#2d-viewer';
      a.className = NAV_A_CLS + (pageOpen ? ' bg-charcoal' : '');
      a.innerHTML = navIcon + '2D Viewer';
      a.addEventListener('click', (e) => { e.preventDefault(); openPage(); });
      li.appendChild(a);
      ul.appendChild(li);
    });
  };
  injectNav();
  // their React router re-renders the sidebar on route change and drops injected nodes — re-inject
  const navObs = new MutationObserver(() => {
    if (!document.querySelector('.csdv-ms-navitem')) queueMicrotask(injectNav);
  });
  navObs.observe(document.body, { childList: true, subtree: true });
  const setActive = (on) => {
    pageOpen = on;
    document.querySelectorAll('.csdv-ms-navitem a').forEach((a) => {
      a.classList.toggle('bg-charcoal', on);
      a.classList.toggle('hover:bg-charcoal', !on);
    });
  };
  // leaving via any other nav link closes our page (their router swaps content underneath)
  document.addEventListener('click', (e) => {
    const a = e.target.closest?.('aside nav a');
    if (a && !a.closest('.csdv-ms-navitem')) closePage();
  }, true);

  // ── the viewer page: fixed overlay right of the 84px rail, below the 80px header
  const page = document.createElement('div');
  page.id = 'csdv-ms-page';
  page.style.cssText = `position:fixed;top:80px;left:84px;right:0;bottom:0;z-index:55;display:none;
    background:#000;color:#fff;overflow-y:auto;font-size:15px;`;
  page.innerHTML = `
    <div style="max-width:1668px;margin:0 auto;padding:32px 28px 56px;">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:24px;">
        <div>
          <h1 style="font-size:22px;font-weight:600;margin:0;">2D Viewer</h1>
          <p id="csdv-ms-sub" style="margin:4px 0 0;color:${MIST};font-size:13px;">loading…</p>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <select id="csdv-ms-demo" class="csdv-ms-select" title="Demo"></select>
          <button id="csdv-ms-share" class="csdv-ms-btn">
            <svg width="18" height="18" viewBox="0 0 384 384"><path fill="#fff" d="m230.36 26.36-78.048 78.05c-.152.149-.246.332-.394.485 19.227-2.801 38.98-.88 57.289 6.257L262.18 58.18c17.55-17.547 46.09-17.547 63.64 0 17.547 17.55 17.547 46.093 0 63.64-2.992 2.993-82.562 82.563-78.05 78.047-17.688 17.692-46.708 16.934-63.641 0-8.77-8.77-23.047-8.77-31.816 0l-13.665 13.664c3.79 6.438 8.137 12.633 13.665 18.16 33.328 33.329 90.699 35.993 126.792.395.153-.152.332-.246.485-.395l78.05-78.05c35.145-35.149 35.145-92.133 0-127.282-35.148-35.144-92.132-35.144-127.28 0m0 0"/><path fill="#fff" d="M174.965 272.676 121.82 325.82c-17.547 17.547-46.09 17.547-63.636 0-17.551-17.55-17.551-46.09 0-63.64l78.218-78.22c17.688-17.687 46.707-16.933 63.641 0 8.77 8.77 23.047 8.77 31.816 0l13.66-13.66c-3.785-6.437-8.132-12.632-13.66-18.16-33.265-33.269-90.593-36.097-126.793-.394-.152.149-.332.242-.484.395l-78.223 78.218c-35.144 35.149-35.144 92.133 0 127.282 35.149 35.144 92.133 35.144 127.282 0l78.218-78.223c.153-.148.246-.328.395-.484-19.227 2.8-38.98.882-57.29-6.258m0 0"/></svg>
            <span>Share</span>
          </button>
          <button id="csdv-ms-fs" class="csdv-ms-btn" style="padding:0 14px;" title="Fullscreen">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>
          </button>
        </div>
      </div>

      <div style="display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap;">
        <!-- left: viewer card + custom control bar (the card is what goes fullscreen) -->
        <div id="csdv-ms-card" style="flex:1 1 60%;min-width:520px;background:${CHARCOAL};border-radius:12px;overflow:hidden;">
          <!-- height caps to the viewport so the control bar below stays on screen (radar letterboxes) -->
          <div id="csdv-ms-host" style="width:100%;height:clamp(420px, calc(100vh - 300px), 940px);background:#000;"></div>
          <div style="display:flex;align-items:center;gap:12px;padding:12px 16px;">
            <button id="csdv-ms-play" class="csdv-ms-icon" style="background:${BLUE};border-radius:50%;" title="Play/Pause">
              <svg id="csdv-ms-playico" width="16" height="16" viewBox="0 0 16 16"><path fill="#fff" d="M4 2l10 6-10 6z"/></svg>
            </button>
            <button id="csdv-ms-prev" class="csdv-ms-icon" style="width:32px;height:32px;font-size:18px;" title="Previous round">‹</button>
            <button id="csdv-ms-next" class="csdv-ms-icon" style="width:32px;height:32px;font-size:18px;" title="Next round">›</button>
            <span id="csdv-ms-clock" style="font-size:13px;color:${MIST};min-width:44px;text-align:center;font-variant-numeric:tabular-nums;">0:00</span>
            <input id="csdv-ms-tl" type="range" min="0" max="0" value="0" style="flex:1;">
            <div style="display:flex;background:${CHARCOAL};border:1px solid ${BLACKOLIVE};border-radius:8px;padding:2px;gap:2px;">
              ${[0.5, 1, 2, 4].map((s) => `<button class="csdv-ms-speed${s === 1 ? ' active' : ''}" data-speed="${s}">${s}×</button>`).join('')}
            </div>
          </div>
        </div>

        <!-- right: score, rounds, live scoreboard -->
        <div style="flex:1 1 32%;min-width:380px;display:flex;flex-direction:column;gap:16px;">
          <div style="background:${CHARCOAL};border-radius:12px;padding:16px 20px;">
            <div id="csdv-ms-score" style="display:flex;align-items:baseline;justify-content:center;gap:14px;font-size:26px;font-weight:700;">
              <span style="color:${CT_COL};">CT 0</span><span style="color:${MIST};font-size:18px;">:</span><span style="color:${T_COL};">0 T</span>
            </div>
            <div id="csdv-ms-rounds" style="display:flex;flex-wrap:wrap;gap:4px;justify-content:center;margin-top:14px;"></div>
          </div>
          <div style="background:${CHARCOAL};border-radius:12px;padding:12px 8px;">
            <div id="csdv-ms-ct"></div>
            <div style="height:1px;background:${BLACKOLIVE};margin:8px 12px;"></div>
            <div id="csdv-ms-t"></div>
            <p style="margin:10px 12px 2px;color:${MIST};font-size:11px;">Click a player to follow them on the map.</p>
          </div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(page);
  const $ = (id) => document.getElementById(id);

  const openPage = () => { page.style.display = 'block'; setActive(true); if (!window.csdvms.viewer) boot(demoId); };
  const closePage = () => { page.style.display = 'none'; setActive(false); };

  // ── demo picker ──────────────────────────────────────────────────────────────
  const demoSel = $('csdv-ms-demo');
  demoSel.innerHTML = demos.length
    ? demos.map((d) => `<option value="${d.id}">${(d.name || d.map || 'demo').replace(/</g, '&lt;')} · ${d.map ?? ''} (#${d.id})</option>`).join('')
    : `<option value="${demoId}">demo #${demoId}</option>`;
  demoSel.addEventListener('change', () => { demoId = Number(demoSel.value); boot(demoId); });

  // ── custom controls, wired through the instance API + hooks ─────────────────
  const TICKRATE = 64; // tick indices advance at the server tick rate (see viewer _onKey: 64 ≈ 1 s)
  const tl = $('csdv-ms-tl'), clock = $('csdv-ms-clock'), playIco = $('csdv-ms-playico');
  let v = null, playing = false, scrubbing = false, lastHud = 0;

  const fmt = (ticks) => { const s = Math.max(0, Math.round(ticks / TICKRATE)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  const paintTl = () => { const p = tl.max > 0 ? (tl.value / tl.max) * 100 : 0;
    tl.style.background = `linear-gradient(to right, ${BLUE} ${p}%, ${BLACKOLIVE} ${p}%)`; };
  const setPlaying = (on) => { playing = on;
    playIco.innerHTML = on ? '<path fill="#fff" d="M3 2h3.5v12H3zM9.5 2H13v12H9.5z"/>' : '<path fill="#fff" d="M4 2l10 6-10 6z"/>'; };

  $('csdv-ms-play').addEventListener('click', () => { playing ? v?.pause() : v?.play(); setPlaying(!playing); });
  $('csdv-ms-prev').addEventListener('click', () => stepRound(-1));
  $('csdv-ms-next').addEventListener('click', () => stepRound(1));
  // fullscreen the whole card (viewer + control bar) — not just the canvas — so the timeline
  // slider and speed controls stay usable; the killfeed lives inside the host and comes along.
  const card = $('csdv-ms-card');
  const toggleFs = () => (document.fullscreenElement === card ? document.exitFullscreen() : card.requestFullscreen());
  $('csdv-ms-fs').addEventListener('click', toggleFs);
  // hijack the viewer's own 'f' shortcut (capture beats its root-level listener)
  page.addEventListener('keydown', (e) => {
    if (e.key === 'f') { e.preventDefault(); e.stopPropagation(); toggleFs(); }
  }, true);
  // windowed: our side-panel HUD · fullscreen: the viewer's built-in scoreboard strip for score context
  document.addEventListener('fullscreenchange', () => v?.setScoreboard(document.fullscreenElement === card));
  $('csdv-ms-share').addEventListener('click', async (e) => {
    const span = e.currentTarget.querySelector('span');
    const url = v?.shareUrl(); if (!url) return;
    try { await navigator.clipboard.writeText(url); } catch {}
    span.textContent = 'Copied!';
    setTimeout(() => { span.textContent = 'Share'; }, 1200);
    console.log('[csdv] share link:', url);
  });
  page.querySelectorAll('.csdv-ms-speed').forEach((b) => b.addEventListener('click', () => {
    v?.setSpeed(Number(b.dataset.speed));
    page.querySelectorAll('.csdv-ms-speed').forEach((x) => x.classList.toggle('active', x === b));
  }));
  tl.addEventListener('pointerdown', () => { scrubbing = true; });
  tl.addEventListener('pointerup', () => { scrubbing = false; });
  tl.addEventListener('input', () => { v?.pause(); setPlaying(false); v?.seek(Number(tl.value)); paintTl(); });

  const roundIdxs = () => (v?.meta?.rounds || []).map((r) => r.round_index);
  const findRound = (i) => (v?.meta?.rounds || []).find((r) => r.round_index === i);
  const stepRound = (d) => { const idxs = roundIdxs(), p = idxs.indexOf(v?.roundIndex);
    if (p + d >= 0 && p + d < idxs.length) v.setRound(idxs[p + d]); };

  // ── right panel: round strip + score ─────────────────────────────────────────
  const buildRounds = () => {
    $('csdv-ms-rounds').innerHTML = (v.meta.rounds || []).map((r) => {
      const w = r.meta?.winner, col = w === 'ct' ? CT_COL : w === 't' ? T_COL : 'transparent';
      return `<button class="csdv-ms-pill" data-round="${r.round_index}" style="border-top-color:${col};" title="Round ${r.round_index} — ${w ? w.toUpperCase() + ' win' : '?'}">${r.round_index}</button>`;
    }).join('');
    $('csdv-ms-rounds').querySelectorAll('button').forEach((b) =>
      b.addEventListener('click', () => v.setRound(Number(b.dataset.round))));
  };
  const syncRound = (idx) => {
    $('csdv-ms-rounds').querySelectorAll('button').forEach((b) =>
      b.classList.toggle('active', Number(b.dataset.round) === idx));
    const m = findRound(idx)?.meta || {};
    $('csdv-ms-score').innerHTML =
      `<span style="color:${CT_COL};">CT ${m.CT_score ?? 0}</span>` +
      `<span style="color:${MIST};font-size:18px;">:</span>` +
      `<span style="color:${T_COL};">${m.T_score ?? 0} T</span>`;
    tl.max = String(Math.max(0, (m.n_ticks || 1) - 1));
    tl.value = '0'; clock.textContent = fmt(0); paintTl();
  };

  // ── right panel: live scoreboard from v.snapshot(), throttled to ~4 Hz ───────
  const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const hpCol = (hp) => (hp > 50 ? '#6ab04c' : hp > 20 ? '#e0b341' : '#c0392b');
  const renderHud = () => {
    const snap = v?.snapshot(); if (!snap) return;
    const row = (p) => {
      const col = p.team === 'ct' ? CT_COL : T_COL;
      return `<div class="csdv-ms-row${p.alive ? '' : ' dead'}${v.followedId === p.steamid ? ' followed' : ''}" data-sid="${p.steamid}">
        <span style="width:8px;height:8px;border-radius:2px;background:${col};"></span>
        <span style="color:#fff;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(p.name)}${p.hasC4 ? ' <span style="color:' + T_COL + '">●</span>' : ''}${p.flashed ? ' ⚡' : ''}</span>
        <span class="csdv-ms-hpbar"><i style="width:${p.alive ? p.health : 0}%;background:${hpCol(p.health)};"></i></span>
        <span style="text-align:right;font-variant-numeric:tabular-nums;">${p.alive ? p.health : '☠'}</span>
        <span style="color:#6ab04c;text-align:right;font-variant-numeric:tabular-nums;">$${p.money}</span>
        <span style="color:${MIST};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(p.weapon)}</span>
        <span style="color:${MIST};text-align:right;font-variant-numeric:tabular-nums;">${p.kills}-${p.deaths}</span>
      </div>`;
    };
    $('csdv-ms-ct').innerHTML = snap.players.filter((p) => p.team === 'ct').map(row).join('');
    $('csdv-ms-t').innerHTML = snap.players.filter((p) => p.team === 't').map(row).join('');
  };
  page.addEventListener('click', (e) => {
    const r = e.target.closest?.('.csdv-ms-row'); if (!r || !v) return;
    v.followedId = v.followedId === r.dataset.sid ? null : r.dataset.sid;
    v.setFollow(v.followedId); renderHud();
  });

  // ── boot / re-boot the viewer for a demo ─────────────────────────────────────
  function boot(id) {
    window.csdvms.viewer?.destroy();
    setPlaying(true);
    v = window.csdvms.viewer = CSDemoViewer.init({
      el: $('csdv-ms-host'), apiBase: API, demoId: id, clientKey: KEY,
      skipFreezetime: true, autoplay: true, autoAdvance: true, scoreboard: false,
      theme: {
        background: '#000', accent: BLUE, ctColor: CT_COL, tColor: T_COL,
        controlBg: 'transparent', controlColor: '#fff', followColor: BLUE,
        showKillfeed: true, showTimer: true, // in-canvas killfeed + round timer (windowed & fullscreen)
        controls: [],                       // no built-in chrome — the page owns the controls
      },
      hooks: {
        onReady: () => {
          $('csdv-ms-sub').textContent = `${v.meta.name || ''} · ${v.meta.map} · ${v.meta.round_count} rounds`;
          buildRounds(); syncRound(v.roundIndex); renderHud();
        },
        onRoundChange: (idx) => { syncRound(idx); renderHud(); },
        onTick: (tickIndex) => {
          if (!scrubbing) {
            if (tickIndex > Number(tl.max)) tl.max = String(tickIndex);
            tl.value = String(tickIndex); paintTl();
          }
          clock.textContent = fmt(tickIndex);
          const now = performance.now();
          if (now - lastHud > 250) { lastHud = now; renderHud(); }
        },
        onError: (err) => { $('csdv-ms-sub').textContent = '⚠ ' + err.message; console.error('[csdv]', err); },
        onShare: (url) => console.log('[csdv] share link:', url),
        onDeprecation: (info) => console.warn('[csdv] payload deprecation:', info.message),
      },
    });
    // the keyboard (space) can toggle playback behind our back — poll tick motion to keep the button honest
    clearInterval(window.csdvms._pulse);
    let lastTick = -1;
    window.csdvms._pulse = setInterval(() => {
      if (!v) return;
      const t = v.tickIndex; setPlaying(t !== lastTick); lastTick = t;
    }, 600);
  }

  window.csdvms = { open: () => openPage(), close: closePage, get viewer() { return v; }, set viewer(x) { v = x; }, _pulse: null, _navObs: navObs };
  openPage();
  console.log('[csdv] metastack page injected — sidebar "2D Viewer" toggles it · window.csdvms.{open,close,viewer}');
})();
