// Public entry: the `CSDemoViewer` API (script-tag global + ESM) and the `<cs-demoviewer>`
// Web Component. The component renders into a shadow root so the host site's CSS can't leak in
// or out (Stage 07 §7.1).

import { Viewer } from './viewer.js';

export const CSDemoViewer = {
  init(opts) {
    const viewer = new Viewer(opts);
    return viewer.publicApi();
  },
  Viewer,
};

// ── <cs-demoviewer demo-id api-base client-key round autoplay speed> ──────────
class CSDemoViewerElement extends HTMLElement {
  connectedCallback() {
    if (this._viewer) return;
    const shadow = this.attachShadow({ mode: 'open' });
    const host = document.createElement('div');
    host.style.width = '100%';
    host.style.height = '100%';
    shadow.appendChild(host);
    if (!this.style.display) this.style.display = 'block';

    let theme = {};
    const themeAttr = this.getAttribute('theme');
    if (themeAttr) { try { theme = JSON.parse(themeAttr); } catch { /* ignore bad theme json */ } }

    this._viewer = new Viewer({
      el: host,
      demoId: Number(this.getAttribute('demo-id')),
      apiBase: this.getAttribute('api-base') || '',
      clientKey: this.getAttribute('client-key') || null,
      round: Number(this.getAttribute('round') || 0),
      autoplay: this.hasAttribute('autoplay'),
      skipFreezetime: this.hasAttribute('skip-freezetime'),
      autoAdvance: this.hasAttribute('auto-advance'),
      scoreboard: this.getAttribute('scoreboard') !== 'false',
      speed: Number(this.getAttribute('speed') || 1),
      theme,
    });
  }

  disconnectedCallback() {
    this._viewer?.destroy();
    this._viewer = null;
  }
}

if (typeof customElements !== 'undefined' && !customElements.get('cs-demoviewer')) {
  customElements.define('cs-demoviewer', CSDemoViewerElement);
}

// Attach the global for the UMD/IIFE script-tag build.
if (typeof window !== 'undefined') window.CSDemoViewer = CSDemoViewer;

export default CSDemoViewer;
