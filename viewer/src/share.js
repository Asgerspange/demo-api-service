// Shareable deep-links (Stage 17 §17.1). Encode the exact moment — demo + round + tick (+ followed
// player) — into a compact string the viewer restores on load. Both a UX feature and the cheapest
// distribution lever ("share this clutch" spreads embeds). Pure + self-contained so it's unit-tested
// and host sites can build links server-side.

const KEYS = { d: 'demoId', r: 'round', t: 'tick', f: 'follow' };
const NUM = new Set(['demoId', 'round', 'tick']);

// state → "d=12&r=5&t=1840&f=765..." (omits absent fields). Read back with decodeShareState.
export function encodeShareState(state) {
  const parts = [];
  for (const [short, full] of Object.entries(KEYS)) {
    const v = state?.[full];
    if (v === undefined || v === null || v === '') continue;
    parts.push(`${short}=${encodeURIComponent(v)}`);
  }
  return parts.join('&');
}

export function decodeShareState(str) {
  const out = {};
  if (!str) return out;
  // tolerate a leading '#', '?', or a '…#csdv=' / '…?csdv=' wrapper
  let s = String(str).replace(/^[#?]/, '');
  const m = s.match(/(?:^|[#?&])csdv=([^#&]*)/);
  if (m) s = decodeURIComponent(m[1]);
  for (const pair of s.split('&')) {
    const [k, v] = pair.split('=');
    const full = KEYS[k];
    if (!full || v === undefined) continue;
    const val = decodeURIComponent(v);
    out[full] = NUM.has(full) ? Number(val) : val;
  }
  return out;
}

// Build a shareable URL by putting the state under a `#csdv=` fragment (keeps it off the server,
// survives copy/paste, and doesn't collide with the host page's own query/hash params).
export function buildShareUrl(baseUrl, state) {
  const enc = encodeShareState(state);
  const base = String(baseUrl || '').replace(/#.*$/, '');
  return enc ? `${base}#csdv=${encodeURIComponent(enc)}` : base;
}

// Pull a share state out of a full location string (or its hash), if any.
export function shareStateFromLocation(href) {
  const hash = String(href || '').match(/#(.*)$/)?.[1] || '';
  return decodeShareState(hash);
}
