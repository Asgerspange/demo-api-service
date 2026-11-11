// Round payload (gzipped-JSON, decoded by the browser) → columnar TypedArrays, with buffers
// listed for zero-copy transfer out of the worker. Ported near-verbatim from the proven
// RoundLoader.worker.js; the only additions are `infernos` passthrough and being a pure
// function (no fetch) so it can be unit-tested AND stringified into the inlined worker.
//
// IMPORTANT: this function must stay SELF-CONTAINED (no module-scope references) — it is
// serialized via `.toString()` into the Web Worker blob. Keep constants inline.

export function decodeRound(data) {
  const FLASH_FADE_TICKS = 12;
  if (!data || !data.ticks) return null;

  const sortedTicks = Object.keys(data.ticks).map(Number).sort((a, b) => a - b);
  const T = sortedTicks.length;
  if (T === 0) return null;

  // Build the steamid→slot map from the UNION of every player seen this round, in first-seen
  // order — NOT just the first tick. Rosters change mid-round on disconnect/reconnect/sub
  // (Stage 11 §11.1.5); keying strictly by steamid over the union means a player who joins late
  // still gets a slot (and a player who leaves just stops filling theirs → health 0 → not drawn).
  const steamids = [];
  const names = [];
  const slotBySteam = {};
  for (const t of sortedTicks) {
    const ps = data.ticks[t].players;
    if (!ps) continue;
    for (const p of ps) {
      if (slotBySteam[p.steamid] === undefined) {
        slotBySteam[p.steamid] = steamids.length;
        steamids.push(p.steamid);
        names.push(p.name);
      }
    }
  }
  const P = steamids.length;

  const weaponSet = new Set();
  for (const t of sortedTicks) {
    const ps = data.ticks[t].players;
    if (!ps) continue;
    for (const p of ps) if (p.active_weapon_name) weaponSet.add(p.active_weapon_name);
  }
  const weapons = ['', ...weaponSet];
  const weaponIdx = Object.fromEntries(weapons.map((w, i) => [w, i]));

  const col = {
    X: new Float32Array(T * P),
    Y: new Float32Array(T * P),
    yaw: new Int16Array(T * P),
    health: new Uint8Array(T * P),
    armor: new Uint8Array(T * P),
    balance: new Float32Array(T * P),
    flashDuration: new Float32Array(T * P),
    hasDefuser: new Uint8Array(T * P),
    hasHelmet: new Uint8Array(T * P),
    isWalking: new Uint8Array(T * P),
    weaponIndex: new Uint8Array(T * P),
    inventoryMask: new Uint8Array(T * P), // bit0 = C4
    teams: new Uint8Array(T * P),         // 0 = ct, 1 = t
    kills: new Uint16Array(T * P),
    deaths: new Uint16Array(T * P),
    assists: new Uint16Array(T * P),
  };

  const bombTickIndices = [], bombX = [], bombY = [], bombPlanted = [];
  const wfTickIndices = [], wfPlayerIdx = [], wfX = [], wfY = [], wfYaw = [];

  // Grenade trajectories & timing.
  const trajectories = {}, firstSeen = {}, lastSeen = {}, flashes = {};
  for (const tickNum of sortedTicks) {
    const tick = data.ticks[tickNum];
    if (!tick.grenades) continue;
    for (const g of tick.grenades) {
      const id = g.entity_id;
      if (!trajectories[id]) { trajectories[id] = []; firstSeen[id] = tickNum; }
      trajectories[id].push({ X: g.X, Y: g.Y, tick: tickNum });
      lastSeen[id] = tickNum;
      if (g.grenade_type === 'flashbang') flashes[id] = g;
    }
  }
  const grenadeMap = {};
  for (const tickNum of sortedTicks) {
    const tick = data.ticks[tickNum];
    if (!tick.grenades) continue;
    for (const g of tick.grenades) {
      const id = g.entity_id;
      if (!grenadeMap[id]) {
        grenadeMap[id] = {
          entity_id: id, grenade_type: g.grenade_type, X: g.X, Y: g.Y,
          thrower_steamid: g.thrower_steamid, trajectory: trajectories[id],
          throwTick: firstSeen[id], tick: lastSeen[id],
        };
      }
    }
  }
  for (const flash of Object.values(flashes)) {
    const explosionTick = lastSeen[flash.entity_id];
    for (let i = 1; i <= FLASH_FADE_TICKS; i++) {
      grenadeMap[`${flash.entity_id}_flash_${i}`] = {
        entity_id: `${flash.entity_id}_flash_${i}`, grenade_type: 'flashbang',
        X: flash.X, Y: flash.Y, thrower_steamid: flash.thrower_steamid,
        trajectory: trajectories[flash.entity_id], throwTick: firstSeen[flash.entity_id],
        tick: explosionTick + i, isEffectOnly: true, effectAtTick: explosionTick + i,
      };
    }
  }

  for (let ti = 0; ti < T; ti++) {
    const tickNum = sortedTicks[ti];
    const tick = data.ticks[tickNum];
    const base = ti * P;
    if (tick.players) {
      for (const p of tick.players) {
        const slot = slotBySteam[p.steamid];
        if (slot === undefined) continue;
        const i = base + slot;
        col.X[i] = p.X;
        col.Y[i] = p.Y;
        col.yaw[i] = Math.round(p.yaw);
        col.health[i] = p.health;
        col.armor[i] = p.armor_value;
        col.balance[i] = p.balance;
        col.flashDuration[i] = p.flash_duration;
        col.hasDefuser[i] = p.has_defuser ? 1 : 0;
        col.hasHelmet[i] = p.has_helmet ? 1 : 0;
        col.isWalking[i] = p.is_walking ? 1 : 0;
        col.weaponIndex[i] = weaponIdx[p.active_weapon_name] ?? 0;
        col.teams[i] = p.team_name === 'ct' ? 0 : 1;
        col.inventoryMask[i] = (p.inventory && p.inventory.includes('C4')) ? 1 : 0;
        col.kills[i] = p.kills_total || 0;
        col.deaths[i] = p.deaths_total || 0;
        col.assists[i] = p.assists_total || 0;
      }
    }
    if (tick.bomb) {
      bombTickIndices.push(ti);
      bombX.push(tick.bomb.X);
      bombY.push(tick.bomb.Y);
      bombPlanted.push(tick.bomb.planted_ticks ?? -1);
    }
    if (tick.weapon_fires) {
      for (const wf of tick.weapon_fires) {
        wfTickIndices.push(ti);
        wfPlayerIdx.push(slotBySteam[wf.player_steamid] ?? 255);
        wfX.push(wf.player_X);
        wfY.push(wf.player_Y);
        wfYaw.push(Math.round(wf.player_yaw));
      }
    }
  }

  const tickNumbers = new Int32Array(sortedTicks);
  const bomb = {
    tickIndex: new Uint16Array(bombTickIndices),
    X: new Float32Array(bombX),
    Y: new Float32Array(bombY),
    plantedTicks: new Int16Array(bombPlanted),
  };
  const weaponFires = {
    tickIndex: new Uint16Array(wfTickIndices),
    playerIdx: new Uint8Array(wfPlayerIdx),
    X: new Float32Array(wfX),
    Y: new Float32Array(wfY),
    yaw: new Int16Array(wfYaw),
  };

  const transferables = [
    tickNumbers.buffer, col.X.buffer, col.Y.buffer, col.yaw.buffer, col.health.buffer,
    col.armor.buffer, col.balance.buffer, col.flashDuration.buffer, col.hasDefuser.buffer,
    col.hasHelmet.buffer, col.isWalking.buffer, col.weaponIndex.buffer,
    col.inventoryMask.buffer, col.teams.buffer, col.kills.buffer, col.deaths.buffer,
    col.assists.buffer, bomb.tickIndex.buffer, bomb.X.buffer,
    bomb.Y.buffer, bomb.plantedTicks.buffer, weaponFires.tickIndex.buffer,
    weaponFires.playerIdx.buffer, weaponFires.X.buffer, weaponFires.Y.buffer,
    weaponFires.yaw.buffer,
  ];

  const result = {
    players: { count: P, steamids, names, weapons, ...col },
    bomb, weaponFires, grenades: grenadeMap,
    tickNumbers, meta: data.meta, smokes: data.smokes || [], infernos: data.infernos || [],
    kills: data.kills,
  };
  return { result, transferables };
}
