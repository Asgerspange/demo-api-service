// Killfeed (Stage 17 §17.3). The data is already in the per-round payload (`kills`, keyed by tick),
// so we just normalize + select. Pure functions → unit-tested; the viewer renders the rows.

// kills (tick-keyed map of full kill records) → a flat, tick-sorted list of normalized events.
export function buildKillfeed(kills) {
  if (!kills || typeof kills !== 'object') return [];
  const events = [];
  for (const [tick, list] of Object.entries(kills)) {
    for (const k of list || []) {
      events.push({
        tick: Number(tick),
        attacker: k.attacker_name ?? '',
        attackerSide: side(k.attacker_side),
        victim: k.victim_name ?? '',
        victimSide: side(k.victim_side),
        weapon: k.weapon ?? '',
        headshot: !!k.headshot,
        noscope: !!k.noscope,
        // a suicide / bomb death has no real attacker
        selfKill: !k.attacker_name || k.attacker_name === k.victim_name,
      });
    }
  }
  events.sort((a, b) => a.tick - b.tick);
  return events;
}

function side(s) {
  const v = String(s ?? '').toLowerCase();
  if (v === 'ct' || v === 'counter-terrorist' || v === 'counterterrorist') return 'ct';
  if (v === 't' || v === 'terrorist' || v === 'terrorists') return 't';
  return null;
}

// The rows to show at `tickNumber`: kills that have happened, most recent first, within `windowTicks`
// of now (so the feed fades as in-game), capped at `max`. `windowTicks <= 0` keeps all prior kills.
export function visibleKills(events, tickNumber, { windowTicks = 0, max = 5 } = {}) {
  const out = [];
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.tick > tickNumber) continue;
    if (windowTicks > 0 && tickNumber - e.tick > windowTicks) break; // older than the window
    out.push(e);
    if (out.length >= max) break;
  }
  return out;
}
