// Stage 07 — worker decode → columnar TypedArrays (the round-payload contract).
import { describe, it, expect } from 'vitest';
import { decodeRound } from '../src/decode.js';

function sampleRound() {
  const p = (steamid, name, over) => ({
    steamid, name, X: 10, Y: 20, yaw: 90, health: 100, armor_value: 100, balance: 800,
    flash_duration: 0, has_defuser: false, has_helmet: true, is_walking: false,
    active_weapon_name: 'ak47', team_name: 't', inventory: [], ...over,
  });
  return {
    meta: { winner: 't', T_score: 1, CT_score: 0 },
    smokes: [{ entity_id: 5, start_tick: 148, end_tick: 160, X: 170, Y: 45 }],
    infernos: [{ entity_id: 9, start_tick: 200, end_tick: 260, X: 1, Y: 2 }],
    kills: {},
    ticks: {
      100: {
        players: [
          p('1', 'alice', { team_name: 't', inventory: ['C4'] }),
          p('2', 'bob', { team_name: 'ct', health: 50, armor_value: 0, balance: 200, flash_duration: 2, has_defuser: true, has_helmet: false, is_walking: true, active_weapon_name: 'awp' }),
        ],
        weapon_fires: [{ player_steamid: '1', player_X: 10, player_Y: 20, player_yaw: 90, weapon: 'ak47' }],
        bomb: null,
        grenades: [{ entity_id: 5, grenade_type: 'smoke', X: 12, Y: 22, tick: 100, thrower_steamid: '1' }],
      },
      105: {
        players: [p('1', 'alice'), p('2', 'bob', { team_name: 'ct' })],
        bomb: { X: 5, Y: 6, planted_ticks: 3 },
        grenades: [{ entity_id: 5, grenade_type: 'smoke', X: 14, Y: 24, tick: 105, thrower_steamid: '1' }],
        weapon_fires: [],
      },
    },
  };
}

describe('decodeRound', () => {
  it('returns null on empty/invalid input', () => {
    expect(decodeRound(null)).toBe(null);
    expect(decodeRound({ ticks: {} })).toBe(null);
  });

  it('builds columnar player arrays with a stable slot order', () => {
    const { result } = decodeRound(sampleRound());
    const pl = result.players;
    expect(pl.count).toBe(2);
    expect(pl.steamids).toEqual(['1', '2']);
    expect(pl.names).toEqual(['alice', 'bob']);
    // T=2 ticks × P=2 players
    expect(pl.X.length).toBe(4);
    expect(pl.X).toBeInstanceOf(Float32Array);
    // team encoding: 1 = t, 0 = ct
    expect(pl.teams[0]).toBe(1);
    expect(pl.teams[1]).toBe(0);
    // C4 in inventory → inventoryMask bit0
    expect(pl.inventoryMask[0] & 1).toBe(1);
    expect(pl.inventoryMask[1] & 1).toBe(0);
    // booleans + values from tick 100
    expect(pl.health[1]).toBe(50);
    expect(pl.hasDefuser[1]).toBe(1);
    expect(pl.isWalking[1]).toBe(1);
  });

  it('builds a deduplicated weapon table indexed from the players', () => {
    const { result } = decodeRound(sampleRound());
    expect(result.players.weapons[0]).toBe('');     // slot 0 = no weapon
    expect(result.players.weapons).toContain('ak47');
    expect(result.players.weapons).toContain('awp');
  });

  it('captures sparse bomb + weapon-fire entries by tick index', () => {
    const { result } = decodeRound(sampleRound());
    // bomb only present at tick 105 → tick index 1
    expect(Array.from(result.bomb.tickIndex)).toEqual([1]);
    expect(result.bomb.plantedTicks[0]).toBe(3);
    // one weapon fire at tick 100 → index 0, attributed to player slot 0
    expect(Array.from(result.weaponFires.tickIndex)).toEqual([0]);
    expect(result.weaponFires.playerIdx[0]).toBe(0);
  });

  it('assembles one grenade per entity with its trajectory + passes smokes/infernos', () => {
    const { result } = decodeRound(sampleRound());
    const g = result.grenades[5];
    expect(g.grenade_type).toBe('smoke');
    expect(g.trajectory.length).toBe(2);   // seen at tick 100 and 105
    expect(g.throwTick).toBe(100);
    expect(g.tick).toBe(105);
    expect(result.smokes.length).toBe(1);
    expect(result.infernos.length).toBe(1);
  });

  it('lists ArrayBuffers for zero-copy transfer', () => {
    const { transferables } = decodeRound(sampleRound());
    expect(transferables.length).toBeGreaterThan(10);
    for (const b of transferables) expect(b).toBeInstanceOf(ArrayBuffer);
  });

  it('tolerates a mid-round roster change (union of steamids, Stage 11)', () => {
    const p = (steamid, name, over) => ({
      steamid, name, X: 0, Y: 0, yaw: 0, health: 100, armor_value: 0, balance: 0,
      flash_duration: 0, has_defuser: false, has_helmet: false, is_walking: false,
      active_weapon_name: '', team_name: 't', inventory: [], kills_total: 0,
      deaths_total: 0, assists_total: 0, ...over,
    });
    const round = {
      meta: {}, smokes: [], infernos: [], kills: {},
      ticks: {
        100: { players: [p('1', 'alice')], weapon_fires: [], bomb: null, grenades: [] },
        105: { players: [p('1', 'alice'), p('2', 'bob')], weapon_fires: [], bomb: null, grenades: [] },
      },
    };
    const { result } = decodeRound(round);
    const pl = result.players;
    expect(pl.count).toBe(2);                 // union, not just the first tick's roster
    expect(pl.steamids).toEqual(['1', '2']);
    // bob (slot 1) is absent at tick 0 → default health 0 (not drawn); present at tick 1
    expect(pl.health[0 * 2 + 1]).toBe(0);
    expect(pl.health[1 * 2 + 1]).toBe(100);
  });
});
