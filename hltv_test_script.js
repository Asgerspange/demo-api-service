
(async () => {
  const API = 'https://api.csstrats.dk';
  // Cache-bust while iterating so you always pull the freshly-published bundle (the CDN caches it
  // ~5 min). Drop the `?t=` once you're done testing.
  const VIEWER = 'https://demoviewer.b-cdn.net/viewer.js?t=' + Date.now();
  const KEY = 'pk_live_YOUR_CLIENT_KEY'; // client key allow-listed for *.hltv.org
  const SERVERKEY = 'sk_live_YOUR_SERVER_KEY';
  if (!window.CSDemoViewer) {
    await new Promise((ok, err) => { const s = document.createElement('script'); s.src = VIEWER;
      s.onload = ok; s.onerror = () => err(new Error('load ' + VIEWER)); document.head.appendChild(s); });
  }

  let demoId = 1;
  try { const r = await fetch(API + '/v1/demos?limit=1', { headers: { Authorization: 'Bearer ' + KEY } });
        const j = await r.json(); if (j.items?.[0]) demoId = j.items[0].id; } catch (e) {}

  // sample HLTV's live colors so the embed blends in
  const cs = (el) => el ? getComputedStyle(el) : null;
  const panel = document.querySelector('.standard-box') || document.querySelector('.contentCol') || document.body;
  const panelBg = '#e5e7ea';
  const textCol = cs(document.body).color || '#fff';
  const linkEl = document.querySelector('.contentCol a, a');
  const accent = (linkEl && cs(linkEl).color) || '#5e98d9';

  // build the embed using HLTV's own .standard-box look
  document.getElementById('csdv-inject')?.remove();
  const box = document.createElement('div');
  box.id = 'csdv-inject';
  box.className = 'standard-box';
  box.style.cssText = 'overflow:hidden;padding:0;margin-bottom:12px;';
  const head = document.createElement('div');
  head.innerHTML = '<span class="headline">2D Demo Replay</span>';
  head.style.cssText = `padding:10px 14px;border-bottom:1px solid rgba(128,128,128,.25);color:${textCol};`;
  const host = document.createElement('div');
  host.style.cssText = 'width:100%;height:600px;';
  box.append(head, host);

  // ── insert ABOVE the Highlights section (the .spoiler that wraps .highlights) ─
  const highlights = document.querySelector('.highlights');
  const anchor = highlights ? (highlights.closest('.spoiler') || highlights) : null;
  const teams = document.querySelector('.standard-box.teamsBox, .match-page, .teamsBox');
  const col = document.querySelector('.contentCol, .colCon, main');

  if (anchor?.parentNode) anchor.parentNode.insertBefore(box, anchor);                 // above Highlights
  else if (teams?.parentNode) teams.parentNode.insertBefore(box, teams.nextSibling);   // else under the score
  else if (col) col.insertBefore(box, col.firstChild);                                 // else top of content
  else document.body.insertBefore(box, document.body.firstChild);
  box.scrollIntoView({ behavior: 'smooth', block: 'center' });

  window.csdv = CSDemoViewer.init({
    el: host, apiBase: API, demoId, clientKey: KEY,
    skipFreezetime: true, autoplay: true, autoAdvance: true,
    theme: { background: panelBg, controlBg: 'rgba(0,0,0,0.45)', controlColor: textCol, accent },
    hooks: {
      onShare: (url) => console.log('[csdv] share link:', url),
      onDeprecation: (info) => console.warn('[csdv] payload deprecation:', info.message),
    },
  });
  
  console.log('[csdv] inlined demo', demoId, anchor ? 'above Highlights' : '(Highlights not found — fallback)');
  console.log('[csdv] try window.csdv.shareUrl() · window.csdv.setFollow(steamid) · keyboard: space/←→/↑↓');
})();