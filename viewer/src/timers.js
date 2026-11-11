// In-viewer timers (Stage 17 §17.3) — map tick → in-game clock: round time, the 40s bomb fuse,
// and the 5/10s defuse. Pure functions so the math is unit-tested; the viewer renders the labels
// into a small HUD. Defaults match CS2 (competitive): 1:55 round, 20s freeze, 40s C4, 10s/5s defuse.

export const DEFAULTS = {
  tickRate: 64,
  roundSeconds: 115, // 1:55 live round time (after freezetime)
  freezeSeconds: 20,
  bombSeconds: 40,
  defuseSeconds: 10,
  defuseWithKitSeconds: 5,
};

export function formatClock(seconds) {
  const s = Math.max(0, Math.ceil(seconds));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

// Round phase + remaining time from the current tick. `planted` is the bomb's planted_ticks at this
// tick (>=0 once planted, else null). Returns { phase, secondsRemaining, label }.
export function roundPhase(tickNumber, meta, opts = {}) {
  const o = { ...DEFAULTS, ...opts };
  const freezeEnd = Number(meta?.freeze_end ?? meta?.start ?? 0);

  // Bomb planted → the 40s C4 fuse takes over the clock.
  if (typeof opts.planted === 'number' && opts.planted >= 0) {
    const remaining = o.bombSeconds - opts.planted / o.tickRate;
    return { phase: 'planted', secondsRemaining: remaining, label: formatClock(remaining) };
  }
  // Before the round goes live → freezetime countdown.
  if (freezeEnd && tickNumber < freezeEnd) {
    const remaining = Math.min(o.freezeSeconds, (freezeEnd - tickNumber) / o.tickRate);
    return { phase: 'freeze', secondsRemaining: remaining, label: formatClock(remaining) };
  }
  // Live round time.
  const elapsed = (tickNumber - freezeEnd) / o.tickRate;
  const remaining = o.roundSeconds - elapsed;
  if (remaining <= 0) return { phase: 'over', secondsRemaining: 0, label: '0:00' };
  return { phase: 'live', secondsRemaining: remaining, label: formatClock(remaining) };
}

// Defuse countdown state machine (§17.3). The payload has no "defuse started" event, so we derive
// it: while an alive CT is adjacent to the planted bomb, a defuse is in progress; the duration is
// 5s with a kit else 10s. Call each tick with the previous state; returns the new state + remaining.
//
//   prev:    the last state returned (or null)
//   ctx:     { planted: bool, ctAdjacent: bool, hasKit: bool, tickNumber, tickRate, opts }
export function defuseState(prev, ctx) {
  const o = { ...DEFAULTS, ...(ctx.opts || {}) };
  if (!ctx.planted || !ctx.ctAdjacent) {
    return { active: false, startTick: null, hasKit: false, secondsRemaining: null };
  }
  // (re)start when not already defusing, or the kit assumption changed
  const total = ctx.hasKit ? o.defuseWithKitSeconds : o.defuseSeconds;
  const start = prev && prev.active && prev.hasKit === ctx.hasKit && prev.startTick != null
    ? prev.startTick
    : ctx.tickNumber;
  const elapsed = (ctx.tickNumber - start) / o.tickRate;
  const remaining = Math.max(0, total - elapsed);
  return { active: true, startTick: start, hasKit: ctx.hasKit, secondsRemaining: remaining };
}
