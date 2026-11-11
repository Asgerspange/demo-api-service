// @vitest-environment jsdom
// Stage 15 §15.3 — viewer visual regression via deterministic draw-op transcripts.
//
// We render representative rounds through the real Renderer onto a recording canvas and snapshot
// the operation sequence. A calibration change (Stage 12: a map_ref whose pos/scale moved) shifts
// every player/utility pixel, and a render-logic change reorders/adds ops — both move the
// transcript, so the committed snapshot diff is the gate. Covers a simple map (dust2), an SVG
// radar path, and a multi-level map (nuke), plus the team-tinted smoke + molotov fire layers.
import { describe, it, expect } from 'vitest';
import { Renderer } from '../src/renderer.js';
import { decodeRound } from '../src/decode.js';
import { DEFAULT_THEME } from '../src/constants.js';
import { createRecordingCanvas, fakeRadar } from './helpers/recording-canvas.js';

// Real calibrations from the map_metadata seed (kept in sync with the API).
const MAP_REFS = {
  de_dust2: { name: 'de_dust2', pos_x: -2476, pos_y: 3239, scale: 4.4, rotate: 1, zoom: 1.1, levels: [] },
  de_mirage: { name: 'de_mirage', pos_x: -3230, pos_y: 1713, scale: 5, rotate: 0, zoom: 0, levels: [] },
  de_nuke: { name: 'de_nuke', pos_x: -3453, pos_y: 2887, scale: 7, rotate: null, zoom: null,
    levels: [{ name: 'default', altitude_max: 10000, altitude_min: -10000 }] },
};

function p(steamid, name, team, over) {
  return {
    steamid, name, X: 200, Y: 300, yaw: 45, health: 100, armor_value: 100, balance: 3000,
    flash_duration: 0, has_defuser: false, has_helmet: true, is_walking: false,
    active_weapon_name: 'AK-47', team_name: team, inventory: team === 't' ? ['C4'] : [],
    kills_total: 1, deaths_total: 0, assists_total: 0, ...over,
  };
}

// A round with two teams, a lingering team-tinted smoke, a detonated molotov (fire), a planted
// bomb, and a weapon fire — exercising every render layer at the snapshot tick (200).
function richRound() {
  return decodeRound({
    meta: { winner: 't', T_score: 1, CT_score: 0, freeze_end: 100, start: 100 },
    smokes: [{ entity_id: 5, start_tick: 110, end_tick: 400, X: 350, Y: -120, thrower_steamid: '1' }],
    infernos: [],
    kills: {},
    ticks: {
      100: {
        players: [p('1', 'alice', 't'), p('2', 'bob', 't', { X: -400, Y: 600 }),
          p('3', 'cara', 'ct', { X: 800, Y: -200 }), p('4', 'dan', 'ct', { X: 1000, Y: 100 })],
        weapon_fires: [{ player_steamid: '3', player_X: 800, player_Y: -200, player_yaw: 180, weapon: 'AK-47' }],
        bomb: null,
        grenades: [
          { entity_id: 5, grenade_type: 'smoke', X: 340, Y: -110, tick: 100, thrower_steamid: '1' },
          { entity_id: 7, grenade_type: 'molotov', X: 500, Y: 0, tick: 100, thrower_steamid: '1' },
        ],
      },
      130: {
        players: [p('1', 'alice', 't'), p('2', 'bob', 't', { X: -400, Y: 600 }),
          p('3', 'cara', 'ct', { X: 800, Y: -200 }), p('4', 'dan', 'ct', { X: 1000, Y: 100 })],
        weapon_fires: [],
        bomb: null,
        grenades: [{ entity_id: 7, grenade_type: 'molotov', X: 520, Y: 10, tick: 130, thrower_steamid: '1' }],
      },
      200: {
        players: [p('1', 'alice', 't', { X: 250 }), p('2', 'bob', 't', { X: -400, Y: 600, health: 0 }),
          p('3', 'cara', 'ct', { X: 800, Y: -200 }), p('4', 'dan', 'ct', { X: 1000, Y: 100, flash_duration: 2 })],
        weapon_fires: [],
        bomb: { X: 250, Y: 300, planted_ticks: 5 },
        grenades: [],
      },
    },
  }).result;
}

function renderTranscript(mapRef) {
  const { canvas, log } = createRecordingCanvas();
  const renderer = new Renderer(canvas, { ...DEFAULT_THEME });
  renderer.setMap(fakeRadar(mapRef.name), mapRef);
  renderer.setRound(richRound());
  log.length = 0;           // drop setup ops; snapshot only the frame
  renderer.draw(2);         // tick index 2 → tick 200
  return log;
}

describe('Renderer visual regression', () => {
  for (const name of Object.keys(MAP_REFS)) {
    it(`renders a stable frame for ${name}`, () => {
      expect(renderTranscript(MAP_REFS[name])).toMatchSnapshot();
    });
  }

  it('projects players differently per calibration (catches map_ref drift)', () => {
    const dust2 = renderTranscript(MAP_REFS.de_dust2).join('\n');
    const nuke = renderTranscript(MAP_REFS.de_nuke).join('\n');
    expect(dust2).not.toEqual(nuke); // same world coords, different calibration → different pixels
  });

  it('draws the radar image and skips the dead player', () => {
    const ops = renderTranscript(MAP_REFS.de_mirage);
    expect(ops.some((o) => o.startsWith('drawImage radar:de_mirage'))).toBe(true);
    // 4 players, one dead at the snapshot tick → name labels only for the 3 alive
    const names = ops.filter((o) => o.startsWith('fillText'));
    expect(names.length).toBe(3);
  });
});
