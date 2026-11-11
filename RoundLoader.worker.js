import { FLASH_FADE_TICKS } from "../PagesNew/Demo/2D/options";

const loadRound = async (demoId, roundIndex = 0, version = 1, baseUrl = '') => {
    try {
        const fetchUrl = baseUrl 
            ? new URL(`/api/demo-chunk?demo_id=${demoId}&round_index=${roundIndex}`, baseUrl).href
            : `/api/demo-chunk?demo_id=${demoId}&round_index=${roundIndex}`;

        // 3. Fetch using the absolute URL
        const response = await fetch(fetchUrl);

        const data = await response.json();
const sortedTicks = Object.keys(data.ticks).map(Number).sort((a, b) => a - b);
    if (!response.ok || sortedTicks.length === 0) {
      console.error('RoundLoader: empty or error response', data.error);
      return null;
    }

    const T = sortedTicks.length;

    // ─── 1. Build player index from first tick that has players ──────────────
    // Player order can theoretically vary tick-to-tick, so we fix a canonical
    // slot order from the first populated tick and maintain it throughout.
    let canonicalPlayers = null;
    for (const t of sortedTicks) {
      const ps = data.ticks[t].players;
      if (ps?.length) { canonicalPlayers = ps; break; }
    }
    if (!canonicalPlayers) canonicalPlayers = [];

    const P             = canonicalPlayers.length;          // players per tick
    const steamids      = canonicalPlayers.map(p => p.steamid);
    const names         = canonicalPlayers.map(p => p.name);
    // steamid → fixed slot index, used when a tick lists players in a different order
    const slotByStead   = Object.fromEntries(steamids.map((s, i) => [s, i]));

    // Build deduplicated weapon name table
    const weaponSet  = new Set();
    for (const t of sortedTicks) {
      const ps = data.ticks[t].players;
      if (!ps) continue;
      for (const p of ps) if (p.active_weapon_name) weaponSet.add(p.active_weapon_name);
    }
    const weapons    = ['', ...weaponSet];                  // index 0 = "no weapon"
    const weaponIdx  = Object.fromEntries(weapons.map((w, i) => [w, i]));

    // ─── 2. Allocate player columns ───────────────────────────────────────────
    const col = {
      X:             new Float32Array(T * P),
      Y:             new Float32Array(T * P),
      yaw:           new Int16Array(T * P),
      health:        new Uint8Array(T * P),
      armor:         new Uint8Array(T * P),
      balance:       new Float32Array(T * P),
      flashDuration: new Float32Array(T * P),
      hasDefuser:    new Uint8Array(T * P),   // 0 | 1
      hasHelmet:     new Uint8Array(T * P),
      isWalking:     new Uint8Array(T * P),
      weaponIndex:   new Uint8Array(T * P),   // index into weapons[]
      inventoryMask: new Uint8Array(T * P),   // bit0 = C4
      teams:         new Uint8Array(T * P),   // 0 = ct, 1 = t
    };

    // ─── 3. Sparse bomb columns (one entry per tick that has bomb) ────────────
    const bombTickIndices = [];
    const bombX = [], bombY = [], bombPlanted = [];

    // ─── 4. Sparse weapon-fire columns ───────────────────────────────────────
    const wfTickIndices = [], wfPlayerIdx = [], wfX = [], wfY = [], wfYaw = [];

    // ─── 5. Grenade processing (same logic as before, kept in worker) ─────────
    const grenadeMap         = {};   // entity_id → grenade object (one per entity)
    const grenadeTrajectories = {};
    const firstSeen          = {};
    const lastSeen           = {};
    const flashes            = {};

    // Pass A — grenade trajectories & timing
    for (const tickNum of sortedTicks) {
      const tick = data.ticks[tickNum];
      if (!tick.grenades) continue;
      for (const g of tick.grenades) {
        const id = g.entity_id;
        if (!grenadeTrajectories[id]) {
          grenadeTrajectories[id] = [];
          firstSeen[id]           = tickNum;
        }
        grenadeTrajectories[id].push({ X: g.X, Y: g.Y, tick: tickNum });
        lastSeen[id] = tickNum;
        if (g.grenade_type === 'flashbang') flashes[id] = g;
      }
    }

    // Build the final grenade map (one object per entity_id)
    for (const tickNum of sortedTicks) {
      const tick = data.ticks[tickNum];
      if (!tick.grenades) continue;
      for (const g of tick.grenades) {
        const id = g.entity_id;
        if (!grenadeMap[id]) {
          grenadeMap[id] = {
            entity_id:     id,
            grenade_type:  g.grenade_type,
            X:             g.X,
            Y:             g.Y,
            thrower_steamid: g.thrower_steamid,
            trajectory:    grenadeTrajectories[id],
            throwTick:     firstSeen[id],
            tick:          lastSeen[id],
          };
        }
      }
    }

    // Flashbang persistent effect entries (appended to grenadeMap with synthetic ids)
    for (const flash of Object.values(flashes)) {
      const explosionTick = lastSeen[flash.entity_id];
      for (let i = 1; i <= FLASH_FADE_TICKS; i++) {
        const syntheticId = `${flash.entity_id}_flash_${i}`;
        grenadeMap[syntheticId] = {
          entity_id:      syntheticId,
          grenade_type:   'flashbang',
          X:              flash.X,
          Y:              flash.Y,
          thrower_steamid: flash.thrower_steamid,
          trajectory:     grenadeTrajectories[flash.entity_id],
          throwTick:      firstSeen[flash.entity_id],
          tick:           explosionTick + i,
          isEffectOnly:   true,
          // absolute tick number of the effect frame
          effectAtTick:   explosionTick + i,
        };
      }
    }

    // ─── 6. Fill columnar arrays tick by tick ─────────────────────────────────
    for (let ti = 0; ti < T; ti++) {
      const tickNum = sortedTicks[ti];
      const tick    = data.ticks[tickNum];
      const base    = ti * P;

      // Players
      if (tick.players) {
        for (const p of tick.players) {
          const slot = slotByStead[p.steamid];
          if (slot === undefined) continue;          // unexpected new player — skip
          const i = base + slot;
          col.X[i]             = p.X;
          col.Y[i]             = p.Y;
          col.yaw[i]           = Math.round(p.yaw);
          col.health[i]        = p.health;
          col.armor[i]         = p.armor_value;
          col.balance[i]       = p.balance;
          col.flashDuration[i] = p.flash_duration;
          col.hasDefuser[i]    = p.has_defuser ? 1 : 0;
          col.hasHelmet[i]     = p.has_helmet  ? 1 : 0;
          col.isWalking[i]     = p.is_walking  ? 1 : 0;
          col.weaponIndex[i]   = weaponIdx[p.active_weapon_name] ?? 0;
          col.teams[i]         = p.team_name === 'ct' ? 0 : 1;
          // Inventory mask: bit 0 = C4
          col.inventoryMask[i] = (p.inventory?.includes('C4') ? 1 : 0);
        }
      }

      // Bomb (sparse)
      if (tick.bomb) {
        bombTickIndices.push(ti);
        bombX.push(tick.bomb.X);
        bombY.push(tick.bomb.Y);
        bombPlanted.push(tick.bomb.planted_ticks ?? -1);
      }

      // Weapon fires (sparse)
      if (tick.weapon_fires) {
        for (const wf of tick.weapon_fires) {
          const pIdx = slotByStead[wf.player_steamid] ?? 255;
          wfTickIndices.push(ti);
          wfPlayerIdx.push(pIdx);
          wfX.push(wf.player_X);
          wfY.push(wf.player_Y);
          wfYaw.push(Math.round(wf.player_yaw));
        }
      }
    }

    // ─── 7. Assemble the transferable result ─────────────────────────────────
    const tickNumbers = new Int32Array(sortedTicks);

    const bombCount = bombTickIndices.length;
    const bomb = {
      tickIndex:    new Uint16Array(bombTickIndices),
      X:            new Float32Array(bombX),
      Y:            new Float32Array(bombY),
      plantedTicks: new Int16Array(bombPlanted),
    };

    const wfCount = wfTickIndices.length;
    const weaponFires = {
      tickIndex: new Uint16Array(wfTickIndices),
      playerIdx: new Uint8Array(wfPlayerIdx),
      X:         new Float32Array(wfX),
      Y:         new Float32Array(wfY),
      yaw:       new Int16Array(wfYaw),
    };

    // Collect all ArrayBuffers for zero-copy transfer
    const transferables = [
      tickNumbers.buffer,
      col.X.buffer, col.Y.buffer, col.yaw.buffer,
      col.health.buffer, col.armor.buffer, col.balance.buffer,
      col.flashDuration.buffer, col.hasDefuser.buffer, col.hasHelmet.buffer,
      col.isWalking.buffer, col.weaponIndex.buffer, col.inventoryMask.buffer,
      col.teams.buffer,
      bomb.tickIndex.buffer, bomb.X.buffer, bomb.Y.buffer, bomb.plantedTicks.buffer,
      weaponFires.tickIndex.buffer, weaponFires.playerIdx.buffer,
      weaponFires.X.buffer, weaponFires.Y.buffer, weaponFires.yaw.buffer,
    ];

    const result = {
      // ── Columnar player data ──────────────────────────────────────────────
      players: {
        count:   P,
        steamids,          // string[] — not transferable but tiny
        names,
        weapons,           // deduplicated weapon name table
        ...col,            // all TypedArrays
      },

      // ── Sparse bomb & weapon-fire data ───────────────────────────────────
      bomb,
      weaponFires,

      // ── Grenades: one object per entity, keyed by entity_id ──────────────
      // (plain object, not a Map, so it survives structured clone)
      grenades: grenadeMap,

      // ── Round-level data (unchanged from before) ──────────────────────────
      tickNumbers,
      meta:   data.meta,
      smokes: data.smokes,
      kills:  data.kills,
    };

    return { result, transferables };

  } catch (err) {
    console.error('RoundLoader: fetch/parse error', err);
    return null;
  }
};

onmessage = async (e) => {
    const { demoId, roundIndex, version, baseUrl } = e.data;
    postMessage(await loadRound(demoId, roundIndex, version, baseUrl));
};