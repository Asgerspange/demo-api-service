// Stage 17 — viewer UX pure modules: deep-links, timers, killfeed, i18n, version negotiation.
import { describe, it, expect } from 'vitest';
import { buildShareUrl, decodeShareState, encodeShareState, shareStateFromLocation } from '../src/share.js';
import { DEFAULTS, defuseState, formatClock, roundPhase } from '../src/timers.js';
import { buildKillfeed, visibleKills } from '../src/killfeed.js';
import { DEFAULT_STRINGS, makeI18n } from '../src/i18n.js';
import { BUNDLE_VERSION, negotiatePayloadVersion } from '../src/version.js';

describe('share deep-links (§17.1)', () => {
  it('round-trips demo + round + tick + follow', () => {
    const state = { demoId: 12, round: 5, tick: 1840, follow: '76561190000000001' };
    const enc = encodeShareState(state);
    expect(decodeShareState(enc)).toEqual(state);
  });

  it('omits absent fields and coerces numbers', () => {
    const enc = encodeShareState({ demoId: 3, round: 1 });
    expect(enc).toBe('d=3&r=1');
    const back = decodeShareState(enc);
    expect(back).toEqual({ demoId: 3, round: 1 });
    expect(typeof back.demoId).toBe('number');
  });

  it('builds + reads a #csdv= fragment URL, ignoring the host page query', () => {
    const url = buildShareUrl('https://news.example/match/42?utm=x', { demoId: 7, round: 2, tick: 99 });
    expect(url).toContain('#csdv=');
    expect(shareStateFromLocation(url)).toEqual({ demoId: 7, round: 2, tick: 99 });
  });

  it('decodes a wrapped csdv param even amid other hash keys', () => {
    expect(decodeShareState('#foo=1&csdv=' + encodeURIComponent('d=9&r=3'))).toEqual({ demoId: 9, round: 3 });
  });
});

describe('timers (§17.3)', () => {
  it('formats a clock', () => {
    expect(formatClock(115)).toBe('1:55');
    expect(formatClock(5)).toBe('0:05');
    expect(formatClock(-3)).toBe('0:00');
  });

  it('counts down freezetime, live round, and the bomb fuse', () => {
    const meta = { freeze_end: 64 * 20 }; // freezetime ends at 20s
    // during freeze
    expect(roundPhase(64 * 5, meta).phase).toBe('freeze');
    // live, 10s in → 1:45 left of 1:55
    const live = roundPhase(64 * 30, meta);
    expect(live.phase).toBe('live');
    expect(live.label).toBe('1:45');
    // planted → 40s fuse, 8s elapsed → 0:32
    const planted = roundPhase(64 * 60, meta, { planted: 64 * 8 });
    expect(planted.phase).toBe('planted');
    expect(planted.label).toBe('0:32');
  });

  it('round time hits 0:00 when it runs out', () => {
    const p = roundPhase(64 * 1000, { freeze_end: 0 });
    expect(p.phase).toBe('over');
    expect(p.secondsRemaining).toBe(0);
  });

  it('defuse state machine: starts on adjacency, 5s with kit, clears when CT leaves', () => {
    const tr = DEFAULTS.tickRate;
    let st = null;
    st = defuseState(st, { planted: true, ctAdjacent: true, hasKit: true, tickNumber: 100, tickRate: tr });
    expect(st.active).toBe(true);
    expect(st.secondsRemaining).toBeCloseTo(5, 5);
    // ~2.5s later
    st = defuseState(st, { planted: true, ctAdjacent: true, hasKit: true, tickNumber: 100 + tr * 2.5, tickRate: tr });
    expect(st.secondsRemaining).toBeCloseTo(2.5, 1);
    // CT leaves → defuse cancels
    st = defuseState(st, { planted: true, ctAdjacent: false, hasKit: true, tickNumber: 200, tickRate: tr });
    expect(st.active).toBe(false);
  });

  it('defuse without a kit is 10s', () => {
    const st = defuseState(null, { planted: true, ctAdjacent: true, hasKit: false, tickNumber: 0, tickRate: 64 });
    expect(st.secondsRemaining).toBeCloseTo(10, 5);
  });
});

describe('killfeed (§17.3)', () => {
  const kills = {
    300: [{ attacker_name: 'alice', attacker_side: 'TERRORIST', victim_name: 'bob',
            victim_side: 'CT', weapon: 'AK-47', headshot: true }],
    450: [{ attacker_name: 'cara', attacker_side: 'CT', victim_name: 'dan',
            victim_side: 'TERRORIST', weapon: 'AWP', headshot: false }],
  };

  it('normalizes records and sorts by tick', () => {
    const feed = buildKillfeed(kills);
    expect(feed.map((k) => k.tick)).toEqual([300, 450]);
    expect(feed[0]).toMatchObject({ attacker: 'alice', attackerSide: 't', victim: 'bob',
      victimSide: 'ct', weapon: 'AK-47', headshot: true });
  });

  it('shows only kills up to the current tick, newest first, within the window', () => {
    const feed = buildKillfeed(kills);
    expect(visibleKills(feed, 200, {})).toEqual([]);            // before any kill
    expect(visibleKills(feed, 460, {}).map((k) => k.victim)).toEqual(['dan', 'bob']); // newest first
    // a tight window drops the old kill
    expect(visibleKills(feed, 460, { windowTicks: 20 }).map((k) => k.victim)).toEqual(['dan']);
  });

  it('flags a suicide/bomb death as selfKill', () => {
    const feed = buildKillfeed({ 10: [{ victim_name: 'x', weapon: 'world' }] });
    expect(feed[0].selfKill).toBe(true);
  });
});

describe('i18n (§17.4)', () => {
  it('returns defaults and interpolates params', () => {
    const t = makeI18n();
    expect(t('play')).toBe(DEFAULT_STRINGS.play);
    expect(t('round', { n: 7 })).toBe('Round 7');
  });

  it('lets a host override any string (localization)', () => {
    const t = makeI18n({ play: 'Lire', round: 'Manche {n}' });
    expect(t('play')).toBe('Lire');
    expect(t('round', { n: 3 })).toBe('Manche 3');
  });
});

describe('payload-version negotiation (§17.5)', () => {
  it('accepts a supported version with no warning', () => {
    expect(negotiatePayloadVersion(1)).toEqual({ ok: true, warn: false, sunset: null, message: '' });
  });

  it('warns (but still decodes) a deprecated version near sunset', () => {
    const neg = negotiatePayloadVersion(1, { supported: [1, 2], deprecated: { 1: '2027-01-01' } });
    expect(neg.ok).toBe(true);
    expect(neg.warn).toBe(true);
    expect(neg.message).toContain('2027-01-01');
  });

  it('refuses a version this bundle cannot decode (too new) with a clear message', () => {
    const neg = negotiatePayloadVersion(9, { supported: [1] });
    expect(neg.ok).toBe(false);
    expect(neg.message).toContain('Update');
  });

  it('exposes a bundle version', () => {
    expect(typeof BUNDLE_VERSION).toBe('string');
  });
});
