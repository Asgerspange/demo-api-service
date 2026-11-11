// @vitest-environment jsdom
// Stage 17 — instance-level wiring: a deep-link opens at the exact round+tick, and the timer +
// killfeed render. The worker/fetch/canvas/Image are stubbed so the real Viewer runs in jsdom.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Viewer } from '../src/viewer.js';
import { decodeRound } from '../src/decode.js';
import { createRecordingCanvas } from './helpers/recording-canvas.js';

const META = {
  id: 1, map: 'de_mirage', name: 'demo', status: 'ready', payload_version: 1,
  round_count: 1, duration_ticks: 5000, refs: [], players: [],
  rounds: [{ round_index: 1, meta: { freeze_end: 64 } }],
  map_ref: { name: 'de_mirage', pos_x: -3230, pos_y: 1713, scale: 5, rotate: 0, zoom: 0, radar_url: 'https://cdn/de_mirage.svg', levels: [] },
  map_supported: true, calibration_suspect: false, cdn: null,
};

function sampleRound() {
  const p = (steamid, name, over) => ({
    steamid, name, X: 100, Y: 100, yaw: 0, health: 100, armor_value: 100, balance: 800,
    flash_duration: 0, has_defuser: false, has_helmet: true, is_walking: false,
    active_weapon_name: 'AK-47', team_name: 't', inventory: [], kills_total: 0, deaths_total: 0, assists_total: 0, ...over,
  });
  return decodeRound({
    meta: { winner: 't', T_score: 1, CT_score: 0, freeze_end: 64, start: 64 },
    smokes: [], infernos: [],
    kills: { 103: [{ attacker_name: 'alice', attacker_side: 'TERRORIST', victim_name: 'bob',
                     victim_side: 'CT', weapon: 'AK-47', headshot: true }] },
    ticks: {
      100: { players: [p('1', 'alice'), p('2', 'bob', { team_name: 'ct' })], weapon_fires: [], bomb: null, grenades: [] },
      105: { players: [p('1', 'alice'), p('2', 'bob', { team_name: 'ct', health: 0 })], weapon_fires: [], bomb: null, grenades: [] },
    },
  }).result;
}

let decoded;

beforeEach(() => {
  decoded = sampleRound();
  // stub canvas 2D context
  HTMLCanvasElement.prototype.getContext = () => createRecordingCanvas().ctx;
  // stub the decode Worker — respond synchronously with the precomputed decoded round
  global.URL.createObjectURL = () => 'blob:fake';
  global.URL.revokeObjectURL = () => {};
  global.Worker = class {
    set onmessage(fn) { this._fn = fn; } get onmessage() { return this._fn; }
    postMessage() { this._fn?.({ data: { result: decoded } }); }
    terminate() {}
  };
  // stub Image so the radar "loads"
  global.Image = class { set src(_v) { queueMicrotask(() => this.onload?.()); } get naturalWidth() { return 1024; } get naturalHeight() { return 1024; } };
  // ResizeObserver isn't in jsdom
  global.ResizeObserver = class { observe() {} disconnect() {} };
  // metadata fetch
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => META, headers: { get: () => null } }));
});

afterEach(() => { vi.restoreAllMocks(); });

async function mount(opts) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const v = new Viewer({ el: host, apiBase: '', demoId: 1, ...opts });
  // let _start() resolve (metadata → radar microtask → round)
  await new Promise((r) => setTimeout(r, 5));
  return { v, host };
}

describe('Viewer deep-link + HUD wiring (§17.1/§17.3)', () => {
  it('a shared link opens at the exact round + tick', async () => {
    const { v } = await mount({ share: 'd=1&r=1&t=105', deepLink: false });
    const api = v.publicApi();
    expect(api.roundIndex).toBe(1);
    // tick 105 is index 1 in the round
    expect(v.round.tickNumbers[api.tickIndex]).toBe(105);
    v.destroy();
  });

  it('shareUrl reflects the current moment', async () => {
    const { v } = await mount({ round: 1, deepLink: false });
    const url = v.shareUrl();
    expect(url).toContain('#csdv=');
    expect(url).toContain('r%3D1'); // round=1 encoded
    v.destroy();
  });

  it('renders the round timer and the killfeed', async () => {
    const { v } = await mount({ round: 1, deepLink: false });
    v.seek(1); // tick 105 → after the kill at 103
    expect(v.timerEl.style.display).not.toBe('none');
    expect(v.timerEl.textContent).toMatch(/\d:\d\d/);          // a m:ss clock
    expect(v.killfeedEl.style.display).toBe('flex');
    expect(v.killfeedEl.textContent).toContain('alice');       // attacker in the feed
    expect(v.killfeedEl.textContent).toContain('bob');         // victim
    v.destroy();
  });

  it('follows a player (highlight carried in deep-links)', async () => {
    const { v } = await mount({ round: 1, follow: '1', deepLink: false });
    expect(v.follow).toBe('1');
    expect(v.renderer._follow).toBe('1');
    v.setFollow('2');
    expect(v.renderer._follow).toBe('2');
    v.destroy();
  });

  it('keyboard space toggles play/pause', async () => {
    const { v } = await mount({ round: 1, deepLink: false });
    expect(v._playing).toBe(false);
    v.root.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(v._playing).toBe(true);
    v.root.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(v._playing).toBe(false);
    v.destroy();
  });

  it('localizes strings via the labels option', async () => {
    const { v } = await mount({ round: 1, deepLink: false, labels: { round: 'Manche {n}' } });
    expect(v.roundSel.options[0].textContent).toBe('Manche 1');
    v.destroy();
  });
});
