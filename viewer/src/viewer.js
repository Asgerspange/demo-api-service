// The embeddable viewer instance: wires metadata → radar → worker round-loading → renderer →
// playback + controls, behind the documented init/instance API (Stage 07 §7.2). Talks to the
// Stage 06 contract; branches on clientKey (direct vs proxy). Memory-disciplined: holds at
// most MAX_CACHED_ROUNDS decoded rounds and frees the rest on round change (§7.3).

import { DEFAULT_THEME, SERVER_TICK_RATE } from './constants.js';
import { Renderer } from './renderer.js';
import { createDecodeWorker } from './worker.js';
import { buildShareUrl, decodeShareState, shareStateFromLocation } from './share.js';
import { makeI18n } from './i18n.js';
import { defuseState, formatClock, roundPhase } from './timers.js';
import { buildKillfeed, visibleKills } from './killfeed.js';
import { BUNDLE_VERSION, negotiatePayloadVersion } from './version.js';

const MAX_CACHED_ROUNDS = 2;
// World-unit radius for the "a CT is on the bomb" defuse heuristic (no defuse-start event exists).
const DEFUSE_ADJ_WORLD = 80;
const KILLFEED_WINDOW_TICKS = 8 * SERVER_TICK_RATE; // a kill lingers ~8s in the feed

export class Viewer {
  constructor(opts) {
    this.opts = opts || {};
    this.el = typeof this.opts.el === 'string' ? document.querySelector(this.opts.el) : this.opts.el;
    if (!this.el) throw new Error('CSDemoViewer: `el` not found');
    this.apiBase = (this.opts.apiBase || '').replace(/\/$/, '');
    this.demoId = this.opts.demoId;
    this.clientKey = this.opts.clientKey || null;
    this.theme = { ...DEFAULT_THEME, ...(this.opts.theme || {}) };
    this.hooks = this.opts.hooks || {};
    this.speed = this.opts.speed || 1;
    // Start each round at the end of freezetime (like HLTV match replays) instead of tick 0.
    this.skipFreezetime = !!this.opts.skipFreezetime;
    // When a round finishes, automatically load + play the next round.
    this.autoAdvance = !!this.opts.autoAdvance;
    // In-viewer scoreboard overlay (default on; toggleable like autoplay).
    this.showScoreboard = this.opts.scoreboard !== false && this.theme.showHud !== false;
    // Localizable labels (§17.4) — host can pass `labels` (or theme.i18n) to translate every string.
    this.i18n = makeI18n(this.opts.labels || this.theme.i18n);
    // Timers (§17.3) — round/bomb clock tuning (tickrate etc. overridable per demo).
    this.timerOpts = { tickRate: SERVER_TICK_RATE, ...(this.opts.timers || {}) };
    this.showTimer = this.theme.showTimer !== false;
    this.showKillfeed = this.theme.showKillfeed !== false;

    // Deep-link restore (§17.1): an explicit `share` string always wins; reading `#csdv=…` from the
    // page URL is what `deepLink: false` disables (host wants to control the entry point itself).
    const fromLocation = this.opts.deepLink === false || typeof location === 'undefined'
      ? {} : shareStateFromLocation(location.href);
    // `share` is the inner state string (what's after `#csdv=`); decodeShareState handles either form.
    const fromShare = this.opts.share ? decodeShareState(this.opts.share) : {};
    const link = { ...fromLocation, ...fromShare };

    this.meta = null;
    this.roundIndex = this.opts.round || link.round || 0;
    this._initialTick = this.opts.tick ?? link.tick ?? null;   // restored after the round loads
    this.follow = this.opts.follow || link.follow || null;     // followed player's steamid
    this.rounds = new Map();          // roundIndex → decoded result (bounded)
    this.tickIndex = 0;
    this._tickFloat = 0;
    this._playing = false;
    this._raf = null;
    this._destroyed = false;
    this._listeners = [];
    this._killfeed = [];              // normalized kill events for the current round
    this._defuse = null;              // defuse-countdown state machine (timers.defuseState)

    this._buildDom();
    this.renderer = new Renderer(this.canvas, this.theme);
    this.worker = createDecodeWorker();
    this.worker.onmessage = (e) => this._onRoundDecoded(e.data);
    this._pending = null;

    this._ro = new ResizeObserver(() => { this.renderer.resize(); this._render(); });
    this._ro.observe(this.el);

    this._start();
  }

  // ── DOM / controls ───────────────────────────────────────────────────────
  _buildDom() {
    this.root = document.createElement('div');
    this.root.classList.add('csdv-scope');
    Object.assign(this.root.style, {
      position: 'relative', width: '100%', height: '100%', minHeight: '320px',
      background: this.theme.background, font: this.theme.font, color: '#fff',
      overflow: 'hidden', userSelect: 'none',
    });
    this.canvas = document.createElement('canvas');
    // touchAction:none → we own pan/pinch gestures (no browser scroll/zoom hijack) on mobile (§17.2).
    Object.assign(this.canvas.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block', cursor: 'grab', touchAction: 'none' });
    this.root.appendChild(this.canvas);

    // In-viewer scoreboard overlay (a crisp DOM strip across the top).
    this.scoreboardEl = document.createElement('div');
    this.scoreboardEl.className = 'csdv-sb';
    this.root.appendChild(this.scoreboardEl);

    // Round/bomb/defuse timer (top-center) + killfeed (top-right) — §17.3.
    this.timerEl = document.createElement('div');
    this.timerEl.className = 'csdv-timer';
    this.root.appendChild(this.timerEl);
    this.killfeedEl = document.createElement('div');
    this.killfeedEl.className = 'csdv-kf';
    this.root.appendChild(this.killfeedEl);

    this.msg = document.createElement('div');
    Object.assign(this.msg.style, {
      position: 'absolute', inset: '0', display: 'none', alignItems: 'center',
      justifyContent: 'center', textAlign: 'center', padding: '1em', font: this.theme.font,
    });
    this.root.appendChild(this.msg);

    this.bar = document.createElement('div');
    this.bar.className = 'csdv-bar csdv-bar-wrap';
    Object.assign(this.bar.style, {
      position: 'absolute', left: '0', right: '0', bottom: '0', display: 'flex',
      gap: '8px', alignItems: 'center', padding: '6px 8px',
      // Definite height + border-box so the 24px controls (play/round/timeline/…) are fully shown
      // instead of being clipped at the container's bottom edge (overflow:hidden).
      minHeight: '40px', boxSizing: 'border-box',
      background: this.theme.controlBg, font: this.theme.font, color: this.theme.controlColor,
    });
    this.root.appendChild(this.bar);
    this._buildControls();

    // Keyboard operability (§17.4): focusable root + space/arrows/round-step + ARIA on the region.
    this.root.tabIndex = 0;
    this.root.setAttribute('role', 'application');
    this.root.setAttribute('aria-label', 'CS2 2D demo viewer');
    this._on(this.root, 'keydown', (e) => this._onKey(e));

    this.el.appendChild(this.root);
    this._injectStyles();
    this._addCanvasInteractions();
    // Re-fit the canvas when entering/leaving fullscreen.
    this._on(document, 'fullscreenchange', () => { this.renderer.resize?.(); this._render(); });
  }

  // Layout-only stylesheet for the scoreboard overlay, scoped to `.csdv-scope` and injected
  // into this viewer's root node (document or the web component's shadow root). Colors stay
  // inline (themeable); this only handles structure so it can't clash with the host site.
  _injectStyles() {
    const rootNode = this.root.getRootNode();
    const host = rootNode === document ? document.head : rootNode;
    if (!host || host.querySelector?.('style[data-csdv]')) return;
    // Strip spans the box (left/right 8px) and the two teams flex to share the width, so the
    // chips shrink to fit instead of overflowing — fits any viewer/fullscreen size.
    const css = `
      .csdv-scope .csdv-sb{position:absolute;top:8px;left:8px;right:8px;display:flex;
        align-items:flex-start;justify-content:space-between;gap:8px;pointer-events:none;z-index:5;}
      .csdv-scope .csdv-team{flex:1 1 0;min-width:0;display:flex;gap:3px;}
      .csdv-scope .csdv-team.csdv-r{justify-content:flex-end;}
      .csdv-scope .csdv-chip{flex:0 1 54px;min-width:0;border-top:2px solid #888;border-radius:3px;padding:2px 5px 3px;}
      .csdv-scope .csdv-top{display:flex;justify-content:space-between;gap:4px;align-items:baseline;}
      .csdv-scope .csdv-nm{font:600 10px system-ui,sans-serif;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
      .csdv-scope .csdv-hp{font:10px system-ui,sans-serif;color:#cbd2dd;flex:0 0 auto;}
      .csdv-scope .csdv-bar{height:3px;background:rgba(255,255,255,.16);border-radius:2px;margin-top:2px;overflow:hidden;}
      .csdv-scope .csdv-bar i{display:block;height:100%;}
      .csdv-scope .csdv-dead{opacity:.4;}
      .csdv-scope .csdv-score{flex:0 0 auto;font:800 18px system-ui,sans-serif;white-space:nowrap;align-self:center;}
      .csdv-scope .csdv-timer{position:absolute;top:34px;left:50%;transform:translateX(-50%);
        font:800 16px system-ui,sans-serif;letter-spacing:.5px;padding:2px 10px;border-radius:4px;
        background:rgba(0,0,0,.5);pointer-events:none;z-index:6;display:none;}
      .csdv-scope .csdv-timer.csdv-bomb{color:#ff7043;}
      .csdv-scope .csdv-timer .csdv-sub{font:600 10px system-ui,sans-serif;opacity:.85;margin-left:6px;}
      .csdv-scope .csdv-kf{position:absolute;top:34px;right:8px;display:flex;flex-direction:column;
        gap:3px;align-items:flex-end;pointer-events:none;z-index:6;}
      .csdv-scope .csdv-kf-row{font:600 11px system-ui,sans-serif;background:rgba(0,0,0,.5);
        padding:2px 7px;border-radius:3px;white-space:nowrap;display:flex;gap:5px;align-items:center;}
      .csdv-scope .csdv-kf-hs{font-size:9px;opacity:.9;}
      /* Mobile / narrow: let the control bar wrap and grow tap targets (§17.2). */
      .csdv-scope .csdv-bar-wrap{flex-wrap:wrap;}
      @media (max-width:480px){
        .csdv-scope .csdv-bar button,.csdv-scope .csdv-bar select{min-height:32px;min-width:32px;}
        .csdv-scope .csdv-timer{font-size:14px;}
      }`;
    const style = document.createElement('style');
    style.setAttribute('data-csdv', '');
    style.textContent = css;
    host.appendChild(style);
  }

  _buildControls() {
    const ctrls = this.theme.controls || [];
    const mk = (tag, props, style) => { const e = document.createElement(tag); Object.assign(e, props); Object.assign(e.style, style || {}); return e; };

    const T = this.i18n;
    if (ctrls.includes('play')) {
      this.playBtn = mk('button', { textContent: '▶', title: T('play') },
        { cursor: 'pointer', background: this.theme.accent, color: '#000', border: 'none', borderRadius: '3px', width: '28px', height: '24px' });
      this.playBtn.setAttribute('aria-label', T('play'));
      this._on(this.playBtn, 'click', () => (this._playing ? this.pause() : this.play()));
      this.bar.appendChild(this.playBtn);
    }
    if (ctrls.includes('round')) {
      this.roundSel = mk('select', { title: T('roundSelect') }, { background: '#1b1d22', color: '#fff', border: '1px solid #333', borderRadius: '3px' });
      this.roundSel.setAttribute('aria-label', T('roundSelect'));
      this._on(this.roundSel, 'change', () => this.setRound(Number(this.roundSel.value)));
      this.bar.appendChild(this.roundSel);
    }
    if (ctrls.includes('timeline')) {
      this.timeline = mk('input', { type: 'range', min: 0, max: 0, value: 0, title: T('timeline') }, { flex: '1', cursor: 'pointer', minWidth: '80px' });
      this.timeline.setAttribute('aria-label', T('timeline'));
      this._on(this.timeline, 'input', () => { this.pause(); this.seek(Number(this.timeline.value)); });
      this.bar.appendChild(this.timeline);
    }
    if (ctrls.includes('speed')) {
      this.speedSel = mk('select', { title: T('speed') }, { background: '#1b1d22', color: '#fff', border: '1px solid #333', borderRadius: '3px' });
      this.speedSel.setAttribute('aria-label', T('speed'));
      for (const s of [0.5, 1, 2, 4]) { const o = document.createElement('option'); o.value = String(s); o.textContent = s + '×'; if (s === this.speed) o.selected = true; this.speedSel.appendChild(o); }
      this._on(this.speedSel, 'change', () => this.setSpeed(Number(this.speedSel.value)));
      this.bar.appendChild(this.speedSel);
    }
    const ghost = (icon, label, fn) => {
      const b = mk('button', { textContent: icon, title: label },
        { cursor: 'pointer', background: 'transparent', color: this.theme.controlColor,
          border: `1px solid ${this.theme.controlColor}`, borderRadius: '3px', width: '28px', height: '24px' });
      b.setAttribute('aria-label', label);
      this._on(b, 'click', fn);
      this.bar.appendChild(b);
      return b;
    };
    if (ctrls.includes('scoreboard')) this.sbBtn = ghost('▦', T('scoreboard'), () => this.setScoreboard(!this.showScoreboard));
    if (ctrls.includes('share')) this.shareBtn = ghost('S', T('share'), () => this._copyShareLink());
    if (ctrls.includes('fullscreen')) this.fsBtn = ghost('⛶', T('fullscreen'), () => this.fullscreen());
  }

  // ── keyboard (§17.4) ────────────────────────────────────────────────────────
  _onKey(e) {
    const step = SERVER_TICK_RATE; // 1 second
    const idxs = (this.meta?.rounds || []).map((r) => r.round_index);
    const pos = idxs.indexOf(this.roundIndex);
    switch (e.key) {
      case ' ': case 'k': e.preventDefault(); this._playing ? this.pause() : this.play(); break;
      case 'ArrowLeft': e.preventDefault(); this.pause(); this.seek(this.tickIndex - step); break;
      case 'ArrowRight': e.preventDefault(); this.pause(); this.seek(this.tickIndex + step); break;
      case 'ArrowUp': case '.': if (pos >= 0 && pos < idxs.length - 1) { e.preventDefault(); this.setRound(idxs[pos + 1]); } break;
      case 'ArrowDown': case ',': if (pos > 0) { e.preventDefault(); this.setRound(idxs[pos - 1]); } break;
      case 'f': this.fullscreen(); break;
      default: break;
    }
  }

  // Copy a deep-link to the current moment + fire the host hook (§17.1).
  async _copyShareLink() {
    const url = this.shareUrl();
    try { await navigator.clipboard?.writeText(url); } catch { /* clipboard may be blocked */ }
    if (this.shareBtn) { const t = this.shareBtn.textContent; this.shareBtn.textContent = '✓'; setTimeout(() => { if (this.shareBtn) this.shareBtn.textContent = t; }, 1200); }
    this.hooks.onShare?.(url, this._shareState());
  }

  _shareState() {
    return { demoId: this.demoId, round: this.roundIndex,
             tick: this.round?.tickNumbers?.[this.tickIndex], follow: this.follow || undefined };
  }

  shareUrl() {
    const base = typeof location !== 'undefined' ? location.href : '';
    return buildShareUrl(base, this._shareState());
  }

  fullscreen() {
    if (document.fullscreenElement === this.root) document.exitFullscreen?.();
    else this.root.requestFullscreen?.();
  }

  // Unified mouse + touch via Pointer Events (§17.2): 1-pointer drag = pan, 2-pointer = pinch-zoom,
  // wheel = zoom, double-tap/click = reset. touch-action:none lets us own the gestures on phones.
  _addCanvasInteractions() {
    const pts = new Map();   // pointerId → {x, y}
    let dragging = false, lx = 0, ly = 0, pinchDist = 0;
    const dist = () => { const [a, b] = [...pts.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
    const center = () => { const [a, b] = [...pts.values()]; return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; };

    this._on(this.canvas, 'wheel', (e) => { e.preventDefault(); const r = this.canvas.getBoundingClientRect(); this.renderer.zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.1 : 0.9); this._render(); }, { passive: false });
    this._on(this.canvas, 'pointerdown', (e) => {
      this.canvas.setPointerCapture?.(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 1) { dragging = true; lx = e.clientX; ly = e.clientY; this.canvas.style.cursor = 'grabbing'; }
      else if (pts.size === 2) { dragging = false; pinchDist = dist(); }
    });
    this._on(this.canvas, 'pointermove', (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size >= 2) {
        const d = dist();
        if (pinchDist > 0) { const r = this.canvas.getBoundingClientRect(); const c = center(); this.renderer.zoomAt(c.x - r.left, c.y - r.top, d / pinchDist); this._render(); }
        pinchDist = d;
      } else if (dragging) { this.renderer.pan(e.clientX - lx, e.clientY - ly); lx = e.clientX; ly = e.clientY; this._render(); }
    });
    const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinchDist = 0; if (pts.size === 0) { dragging = false; this.canvas.style.cursor = 'grab'; } };
    this._on(this.canvas, 'pointerup', up);
    this._on(this.canvas, 'pointercancel', up);
    this._on(this.canvas, 'dblclick', () => { this.renderer.resetView(); this._render(); });
  }

  _on(target, type, fn, opts) { target.addEventListener(type, fn, opts); this._listeners.push([target, type, fn, opts]); }

  _showMessage(text) { this.msg.textContent = text; this.msg.style.display = text ? 'flex' : 'none'; }

  // ── fetch + lifecycle ──────────────────────────────────────────────────────
  async _fetch(path) {
    const headers = this.clientKey ? { Authorization: `Bearer ${this.clientKey}` } : {};
    return fetch(this.apiBase + path, { headers, credentials: 'omit' });
  }

  async _start() {
    try {
      await this._loadMetadata();
      if (this._destroyed) return;
      // Payload-version negotiation + deprecation (§17.5): decode whatever the API declares, warn a
      // host pinned near end-of-life, and fail clearly if this bundle is too old for the format.
      const neg = negotiatePayloadVersion(this.meta.payload_version);
      if (neg.warn) {
        // eslint-disable-next-line no-console
        console.warn(`[CSDemoViewer ${BUNDLE_VERSION}] ${neg.message}`);
        this.hooks.onDeprecation?.(neg);
      }
      if (!neg.ok) {
        this._showMessage(this.i18n('outdatedViewer'));
        this.hooks.onError?.(new Error(neg.message));
        return;
      }
      // Unknown/unsupported map → clear neutral state, never a blank or crashed viewer (Stage 12).
      if (this.meta.map_supported === false || !this.meta.map_ref?.radar_url) {
        this._showMessage(this.i18n('unsupportedMap', { map: this.meta.map }));
        this.hooks.onError?.(new Error('unsupported map: ' + this.meta.map));
        return;
      }
      await this._loadRadar();
      if (this._destroyed) return;
      this._populateRounds();
      // Round indices come from the parser (awpy rounds start at 1), so don't assume 0 —
      // fall back to the first available round if the requested one isn't in the index.
      const idxs = (this.meta.rounds || []).map((r) => r.round_index);
      if (idxs.length && !idxs.includes(this.roundIndex)) this.roundIndex = idxs[0];
      await this.setRound(this.roundIndex);
      this._showMessage('');
      this.hooks.onReady?.(this.publicApi());
      if (this.opts.autoplay) this.play();
    } catch (err) {
      this._fail(err);
    }
  }

  async _loadMetadata(attempt = 0) {
    const resp = await this._fetch(`/v1/demos/${this.demoId}`);
    if (resp.status === 409) { // not ready → poll a few times
      this._showMessage(this.i18n('processing'));
      if (attempt < 20 && !this._destroyed) {
        await new Promise((r) => setTimeout(r, 3000));
        return this._loadMetadata(attempt + 1);
      }
      throw new Error('demo not ready');
    }
    if (resp.status === 429) { this._showMessage(this.i18n('rateLimited')); await new Promise((r) => setTimeout(r, (Number(resp.headers.get('Retry-After')) || 5) * 1000)); return this._loadMetadata(attempt + 1); }
    if (resp.status === 401 || resp.status === 403) throw new Error('authentication/origin error (' + resp.status + ')');
    if (!resp.ok) throw new Error('failed to load demo (' + resp.status + ')');
    this.meta = await resp.json();
  }

  async _loadRadar() {
    const url = this.meta?.map_ref?.radar_url;
    if (!url) throw new Error('no radar for map ' + this.meta?.map);
    const src = url.startsWith('/') ? 'https://csstrats.b-cdn.net' + url : url;
    const img = await new Promise((resolve, reject) => {
      const im = new Image();
      im.crossOrigin = 'anonymous';
      im.onload = () => resolve(im);
      im.onerror = () => reject(new Error('radar image failed to load: ' + src));
      im.src = src;
    });
    this.renderer.setMap(img, this.meta.map_ref);
  }

  _populateRounds() {
    if (!this.roundSel) return;
    this.roundSel.innerHTML = '';
    for (const r of this.meta.rounds || []) {
      const o = document.createElement('option');
      o.value = String(r.round_index);
      o.textContent = this.i18n('round', { n: r.round_index });
      this.roundSel.appendChild(o);
    }
  }

  _fail(err) {
    this._showMessage('⚠ ' + (err?.message || err));
    // eslint-disable-next-line no-console
    console.error('CSDemoViewer:', err);
    this.hooks.onError?.(err);
  }

  // ── rounds ─────────────────────────────────────────────────────────────────
  setRound(index) {
    this.roundIndex = index;
    if (this.roundSel) this.roundSel.value = String(index);
    this.tickIndex = 0; this._tickFloat = 0;
    if (this.rounds.has(index)) { this._applyRound(this.rounds.get(index)); return Promise.resolve(); }
    this._showMessage(this.i18n('loadingRound', { round: index }));
    return new Promise((resolve) => {
      this._pending = { index, resolve };
      const cdn = this.meta?.cdn;
      // With a CDN token, the worker fetches the payload straight from the edge (no key needed);
      // otherwise it goes through the API round endpoint with the client key (Stage 13).
      this.worker.postMessage({
        url: this._roundUrl(index),
        clientKey: cdn ? null : this.clientKey,
      });
    });
  }

  _roundUrl(index) {
    const cdn = this.meta?.cdn;
    if (cdn) {
      const key = `${this.demoId}/v${this.meta.payload_version}/round-${index}.bin`;
      return `${cdn.base}/${key}?token=${encodeURIComponent(cdn.token)}`
        + `&expires=${cdn.expires}&token_path=${encodeURIComponent(cdn.token_path)}`;
    }
    return `${this.apiBase}/v1/demos/${this.demoId}/rounds/${index}`;
  }

  _onRoundDecoded(data) {
    if (this._destroyed) return;
    const pending = this._pending; this._pending = null;
    if (!data || data.error) { this._fail(new Error('round load failed: ' + (data?.error || 'unknown'))); pending?.resolve(); return; }
    const index = pending ? pending.index : this.roundIndex;
    this.rounds.set(index, data.result);
    // Evict oldest beyond the cache cap → free buffers (memory discipline §7.3).
    while (this.rounds.size > MAX_CACHED_ROUNDS) {
      const oldest = this.rounds.keys().next().value;
      if (oldest === index) break;
      this.rounds.delete(oldest);
    }
    if (index === this.roundIndex) this._applyRound(data.result);
    pending?.resolve();
  }

  _applyRound(round) {
    this.round = round;
    this.renderer.setRound(round);
    this.renderer.setFollow?.(this.follow);
    this._killfeed = buildKillfeed(round.kills);   // §17.3 killfeed for this round
    this._defuse = null;
    const T = round.tickNumbers.length;
    this.tickIndex = this.skipFreezetime ? this._freezeEndIndex(round) : 0;
    // Deep-link: restore the exact tick once, on the round it was captured in (§17.1).
    if (this._initialTick != null) {
      this.tickIndex = this._tickIndexForNumber(round, this._initialTick);
      this._initialTick = null;
    }
    this._tickFloat = 0;
    if (this.timeline) { this.timeline.max = String(Math.max(0, T - 1)); this.timeline.value = String(this.tickIndex); }
    this._showMessage('');
    this.hooks.onRoundChange?.(this.roundIndex, this.meta?.rounds?.[this.roundIndex]?.meta);
    this._render();
  }

  // First tick index at/after freezetime ends (max of start, freeze_end from round meta).
  _freezeEndIndex(round) {
    return this._tickIndexForNumber(round,
      Math.max(Number(round.meta?.start) || 0, Number(round.meta?.freeze_end) || 0));
  }

  // First tick index whose tick number is >= `target` (binary search; tickNumbers is sorted).
  _tickIndexForNumber(round, target) {
    const tn = round.tickNumbers;
    let lo = 0, hi = tn.length - 1, idx = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (tn[mid] >= target) { idx = mid; hi = mid - 1; } else lo = mid + 1;
    }
    return idx;
  }

  // ── playback ────────────────────────────────────────────────────────────────
  play() {
    if (this._playing || !this.round) return;
    this._playing = true;
    if (this.playBtn) this.playBtn.textContent = '⏸';
    this._lastTs = null;
    this._raf = requestAnimationFrame((ts) => this._loop(ts));
  }

  pause() {
    this._playing = false;
    if (this.playBtn) this.playBtn.textContent = '▶';
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  _loop(ts) {
    if (!this._playing || this._destroyed) return;
    if (this._lastTs != null) {
      const dt = (ts - this._lastTs) / 1000;
      this._tickFloat += dt * SERVER_TICK_RATE * this.speed;
      const T = this.round.tickNumbers.length;
      let idx = this.tickIndex + Math.floor(this._tickFloat);
      if (this._tickFloat >= 1) this._tickFloat -= Math.floor(this._tickFloat);
      if (idx >= T - 1) {
        idx = T - 1; this.tickIndex = idx; this._render(); this.pause();
        if (this.autoAdvance) this._advanceRound();
        return;
      }
      if (idx !== this.tickIndex) { this.tickIndex = idx; this._render(); }
    }
    this._lastTs = ts;
    this._raf = requestAnimationFrame((t) => this._loop(t));
  }

  // Advance to the next round in the index (if any) and keep playing.
  _advanceRound() {
    const idxs = (this.meta?.rounds || []).map((r) => r.round_index);
    const pos = idxs.indexOf(this.roundIndex);
    if (pos < 0 || pos >= idxs.length - 1) return;       // last round → stop
    this.setRound(idxs[pos + 1]).then(() => { if (!this._destroyed) this.play(); });
  }

  seek(tickIndex) {
    if (!this.round) return;
    const T = this.round.tickNumbers.length;
    this.tickIndex = Math.max(0, Math.min(T - 1, tickIndex | 0));
    this._render();
  }

  setSpeed(x) { this.speed = x; if (this.speedSel) this.speedSel.value = String(x); }

  _render() {
    if (!this.round) return;
    this.renderer.draw(this.tickIndex);
    this._updateScoreboard();
    this._updateTimer();
    this._updateKillfeed();
    if (this.timeline && document.activeElement !== this.timeline) this.timeline.value = String(this.tickIndex);
    const tickNumber = this.round.tickNumbers[this.tickIndex];
    this.hooks.onTick?.(this.tickIndex, tickNumber);
    // Deep-link hook (§17.1): host can persist/share the exact moment as it plays.
    this.hooks.onTimestamp?.(this.roundIndex, tickNumber);
  }

  // ── timers + killfeed (§17.3) ────────────────────────────────────────────────
  // Bomb state at a tick index (mirrors the renderer's lookup): {X, Y, planted} or null.
  _bombAt(tickIndex) {
    const b = this.round.bomb;
    if (!b || !b.tickIndex.length) return null;
    let k = -1;
    for (let i = 0; i < b.tickIndex.length; i++) { if (b.tickIndex[i] <= tickIndex) k = i; else break; }
    if (k < 0) return null;
    return { X: b.X[k], Y: b.Y[k], planted: b.plantedTicks[k] };
  }

  // Heuristic: is an alive CT on the planted bomb (and do they carry a kit)? Drives the defuse clock.
  _defuseDetect(tickIndex, bomb) {
    const pl = this.round.players, P = pl.count, base = tickIndex * P;
    for (let s = 0; s < P; s++) {
      const i = base + s;
      if (pl.teams[i] !== 0 || pl.health[i] <= 0) continue;   // alive CT only
      if (Math.hypot(pl.X[i] - bomb.X, pl.Y[i] - bomb.Y) <= DEFUSE_ADJ_WORLD)
        return { adjacent: true, hasKit: !!pl.hasDefuser[i] };
    }
    return { adjacent: false, hasKit: false };
  }

  _updateTimer() {
    const el = this.timerEl;
    if (!el) return;
    if (!this.showTimer || !this.round) { el.style.display = 'none'; return; }
    const ti = this.tickIndex, tickNumber = this.round.tickNumbers[ti];
    const bomb = this._bombAt(ti);
    const planted = bomb && bomb.planted >= 0 ? bomb.planted : null;
    const phase = roundPhase(tickNumber, this.round.meta, { ...this.timerOpts, planted });

    let defuseLabel = '';
    if (planted != null) {
      const det = this._defuseDetect(ti, bomb);
      this._defuse = defuseState(this._defuse, {
        planted: true, ctAdjacent: det.adjacent, hasKit: det.hasKit,
        tickNumber, tickRate: this.timerOpts.tickRate, opts: this.timerOpts });
      if (this._defuse.active)
        defuseLabel = ` <span class="csdv-sub">${this.i18n('defusing')} ${formatClock(this._defuse.secondsRemaining)}</span>`;
    } else {
      this._defuse = null;
    }

    el.style.display = 'block';
    el.classList.toggle('csdv-bomb', phase.phase === 'planted');
    el.innerHTML = `${phase.phase === 'planted' ? '☢ ' : ''}${phase.label}${defuseLabel}`;
  }

  _updateKillfeed() {
    const el = this.killfeedEl;
    if (!el) return;
    if (!this.showKillfeed || !this.round) { el.style.display = 'none'; return; }
    const tickNumber = this.round.tickNumbers[this.tickIndex];
    const rows = visibleKills(this._killfeed, tickNumber, { windowTicks: KILLFEED_WINDOW_TICKS, max: 5 });
    if (!rows.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
    el.style.display = 'flex';
    const t = this.theme;
    const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    const col = (side) => (side === 'ct' ? t.ctColor : side === 't' ? t.tColor : t.hudMutedColor);
    el.innerHTML = rows.map((k) =>
      `<div class="csdv-kf-row">` +
      (k.selfKill ? '' : `<span style="color:${col(k.attackerSide)}">${esc(k.attacker)}</span>`) +
      `<span>${esc(k.weapon)}${k.headshot ? '<span class="csdv-kf-hs"> ⊙</span>' : ''}</span>` +
      `<span style="color:${col(k.victimSide)}">${esc(k.victim)}</span></div>`).join('');
  }

  // Follow a player by steamid (highlighted; carried in deep-links). null clears.
  setFollow(steamid) {
    this.follow = steamid || null;
    this.renderer.setFollow?.(this.follow);
    this._render();
  }

  setScoreboard(on) { this.showScoreboard = !!on; this._updateScoreboard(); }

  // Build the in-viewer scoreboard strip (CT chips · score · T chips) from the current tick.
  _updateScoreboard() {
    const el = this.scoreboardEl;
    if (!el) return;
    if (!this.showScoreboard || !this.round) { el.style.display = 'none'; return; }
    el.style.display = 'flex';
    const t = this.theme, m = this.round.meta || {}, snap = this._snapshot();
    if (!snap) return;
    const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    const hpColor = (hp) => (hp > 50 ? '#6ab04c' : hp > 20 ? '#e0b341' : '#c0392b');
    const chip = (p) => {
      const col = p.team === 'ct' ? t.ctColor : t.tColor;
      return `<div class="csdv-chip ${p.alive ? '' : 'csdv-dead'}" style="background:${t.hudBg};border-top-color:${col}">
        <div class="csdv-top"><span class="csdv-nm" style="color:${col}">${esc((p.name || '').slice(0, 8))}${p.hasC4 ? ' ●' : ''}</span><span class="csdv-hp">${p.alive ? p.health : '☠'}</span></div>
        <div class="csdv-bar"><i style="width:${p.alive ? p.health : 0}%;background:${hpColor(p.health)}"></i></div>
      </div>`;
    };
    const ct = snap.players.filter((p) => p.team === 'ct').map(chip).join('');
    const tt = snap.players.filter((p) => p.team === 't').map(chip).join('');
    el.innerHTML =
      `<div class="csdv-team">${ct}</div>` +
      `<div class="csdv-score"><span style="color:${t.ctColor}">${m.CT_score ?? 0}</span>` +
      `<span style="color:${t.hudMutedColor}"> : </span>` +
      `<span style="color:${t.tColor}">${m.T_score ?? 0}</span></div>` +
      `<div class="csdv-team csdv-r">${tt}</div>`;
  }

  // ── public API + teardown ────────────────────────────────────────────────────
  publicApi() {
    const self = this;
    return {
      play: () => self.play(), pause: () => self.pause(), seek: (t) => self.seek(t),
      setRound: (i) => self.setRound(i), setSpeed: (x) => self.setSpeed(x),
      destroy: () => self.destroy(), snapshot: (i) => self._snapshot(i),
      fullscreen: () => self.fullscreen(), setScoreboard: (on) => self.setScoreboard(on),
      // §17.1 deep-links + follow
      shareUrl: () => self.shareUrl(), setFollow: (sid) => self.setFollow(sid),
      get meta() { return self.meta; }, get tickIndex() { return self.tickIndex; },
      get roundIndex() { return self.roundIndex; },
    };
  }

  // Per-player state at a tick (current tick by default) — for host-side scoreboards/HUDs.
  _snapshot(tickIndex = this.tickIndex) {
    const r = this.round;
    if (!r) return null;
    const pl = r.players, P = pl.count, base = tickIndex * P;
    const players = [];
    for (let s = 0; s < P; s++) {
      const i = base + s;
      players.push({
        slot: s, steamid: pl.steamids[s], name: pl.names[s],
        team: pl.teams[i] === 0 ? 'ct' : 't',
        health: pl.health[i], armor: pl.armor[i], money: Math.round(pl.balance[i]),
        weapon: pl.weapons[pl.weaponIndex[i]] || '',
        kills: pl.kills[i], deaths: pl.deaths[i], assists: pl.assists[i],
        alive: pl.health[i] > 0, hasC4: !!(pl.inventoryMask[i] & 1),
        flashed: pl.flashDuration[i] > 0.5,
      });
    }
    return { tickIndex, tickNumber: r.tickNumbers[tickIndex], players };
  }

  destroy() {
    this._destroyed = true;
    this.pause();
    this._ro?.disconnect();
    for (const [t, type, fn, opts] of this._listeners) t.removeEventListener(type, fn, opts);
    this._listeners = [];
    if (this.worker) {
      this.worker.onmessage = null;
      this.worker.terminate();
      if (this.worker.__blobUrl) URL.revokeObjectURL(this.worker.__blobUrl);
      this.worker = null;
    }
    this.rounds.clear();
    this.round = null;
    if (this.root && this.root.parentNode) this.root.parentNode.removeChild(this.root);
  }
}
