/**
 * useRoundData — columnar edition
 *
 * Round data is now stored as typed arrays (one buffer per field, spanning all
 * ticks × players) rather than per-tick JS objects.  This keeps one round at
 * ~2 MB of ArrayBuffer instead of ~50 MB of V8 heap.
 *
 * Public API is unchanged except:
 *   • currentTick  →  still a computed, returns a lightweight view object
 *                      assembled on-demand from the typed arrays
 *   • round.ticks  →  gone; use getTickView(round, tickIndex) instead
 *   • steamIdTeamLookup  →  derived from players.steamids / players.teams
 */
import { ref, computed, shallowRef } from 'vue';
import {
  SERVER_TICK_RATE,
  TOTAL_ROUND_DURATION,
  FEED_LINGER_SECONDS,
} from '../options';
  import RoundWorker from '@/Workers/RoundLoader.worker.js?worker';

// ─── LRU cache helpers ────────────────────────────────────────────────────────
const MAX_CACHED_ROUNDS = 5;

function evictOldRounds(roundsObj, pinnedKeys = new Set()) {
  const keys = Object.keys(roundsObj);
  if (keys.length <= MAX_CACHED_ROUNDS) return roundsObj;
  const keep = new Set();
  for (let i = keys.length - 1; i >= 0; i--) {
    if (pinnedKeys.has(keys[i]) || keep.size < MAX_CACHED_ROUNDS) keep.add(keys[i]);
  }
  const next = {};
  for (const k of keys) if (keep.has(k)) next[k] = roundsObj[k];
  return next;
}

// ─── Tick-view helper (exported so renderer can call it directly) ──────────────
/**
 * Assembles a lightweight plain-object "tick view" from the columnar arrays.
 * Called at most once per rendered frame — never inside a hot loop.
 *
 * Shape mirrors the old tick object so the renderer needs minimal changes:
 *   { players: [...], bomb: {...}|null, weapon_fires: [...] }
 */
export function getTickView(round, tickIndex) {
  if (!round?.tickNumbers?.length) return null;
  if (tickIndex < 0 || tickIndex >= round.tickNumbers.length) return null;

  const { players, bomb, weaponFires } = round;
  const P    = players.count;
  const base = tickIndex * P;

  // ── Players ────────────────────────────────────────────────────────────────
  const playerViews = [];
  for (let s = 0; s < P; s++) {
    const i = base + s;
    playerViews.push({
      steamid:            players.steamids[s],
      name:               players.names[s],
      team_name:          players.teams[i] === 0 ? 'ct' : 't',
      X:                  players.X[i],
      Y:                  players.Y[i],
      yaw:                players.yaw[i],
      health:             players.health[i],
      armor_value:        players.armor[i],
      balance:            players.balance[i],
      flash_duration:     players.flashDuration[i],
      has_defuser:        players.hasDefuser[i] === 1,
      has_helmet:         players.hasHelmet[i]  === 1,
      is_walking:         players.isWalking[i]  === 1,
      active_weapon_name: players.weapons[players.weaponIndex[i]] ?? '',
      // inventory: sparse mask — bit 0 = C4
      inventory: (players.inventoryMask[i] & 1) ? ['C4'] : [],
    });
  }

  // ── Bomb (binary search in sparse sorted tickIndex array) ─────────────────
  let bombView = null;
  if (bomb?.tickIndex?.length) {
    let lo = 0, hi = bomb.tickIndex.length - 1, found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if      (bomb.tickIndex[mid] === tickIndex) { found = mid; break; }
      else if (bomb.tickIndex[mid]  < tickIndex)    lo = mid + 1;
      else                                          hi = mid - 1;
    }
    if (found !== -1) {
      bombView = {
        X:             bomb.X[found],
        Y:             bomb.Y[found],
        planted_ticks: bomb.plantedTicks[found] === -1 ? null : bomb.plantedTicks[found],
      };
    }
  }

  // ── Weapon fires (linear scan — sparse, typically 0–3 entries per tick) ───
  const wfViews = [];
  if (weaponFires?.tickIndex?.length) {
    for (let j = 0; j < weaponFires.tickIndex.length; j++) {
      if (weaponFires.tickIndex[j] === tickIndex) {
        const pIdx = weaponFires.playerIdx[j];
        wfViews.push({
          player_steamid: players.steamids[pIdx] ?? '',
          player_X:       weaponFires.X[j],
          player_Y:       weaponFires.Y[j],
          player_yaw:     weaponFires.yaw[j],
        });
      }
    }
  }

  return { players: playerViews, bomb: bombView, weapon_fires: wfViews };
}

// ─── Composable ───────────────────────────────────────────────────────────────
export function useRoundData({ demoId, demoRounds, version, externalId }) {
  const rounds           = shallowRef({});
  const currentRound     = ref(1);
  const currentTickIndex = ref(0);
  const allowPlay        = ref(false);
  const loadingRounds    = ref(new Set());
  const pinnedRoundKeys  = ref(new Set());

  // Empty sentinel — avoids null-checks throughout
  const EMPTY_ROUND = {
    players: {
      count: 0, steamids: [], names: [], weapons: [],
      X: new Float32Array(0), Y: new Float32Array(0),
      yaw: new Int16Array(0), health: new Uint8Array(0),
      armor: new Uint8Array(0), balance: new Float32Array(0),
      flashDuration: new Float32Array(0), hasDefuser: new Uint8Array(0),
      hasHelmet: new Uint8Array(0), isWalking: new Uint8Array(0),
      weaponIndex: new Uint8Array(0), inventoryMask: new Uint8Array(0),
      teams: new Uint8Array(0),
    },
    bomb: {
      tickIndex: new Uint16Array(0), X: new Float32Array(0),
      Y: new Float32Array(0), plantedTicks: new Int16Array(0),
    },
    weaponFires: {
      tickIndex: new Uint16Array(0), playerIdx: new Uint8Array(0),
      X: new Float32Array(0), Y: new Float32Array(0), yaw: new Int16Array(0),
    },
    grenades:    {},
    tickNumbers: new Int32Array(0),
    meta: {}, smokes: [], kills: {},
  };

  const round = computed(() => {
    const key = `${demoId.value}_${currentRound.value}`;
    return rounds.value?.[key] ?? EMPTY_ROUND;
  });

  // ── Tick index helpers ────────────────────────────────────────────────────
  const firstPlayableTickIndex = computed(() => {
    const ticks     = round.value?.tickNumbers;
    const freezeEnd = round.value?.meta?.freeze_end ?? 0;
    if (!ticks?.length || !freezeEnd) return 0;
    let lo = 0, hi = ticks.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (ticks[mid] < freezeEnd) lo = mid + 1;
      else hi = mid;
    }
    return Math.min(lo, Math.max(0, ticks.length - 2));
  });

  // playableRound only needs tickNumbers sliced — used by the Slider component
  const playableRound = computed(() => {
    const fi = firstPlayableTickIndex.value;
    if (!round.value?.tickNumbers?.length || fi === 0) return round.value;
    return { ...round.value, tickNumbers: round.value.tickNumbers.slice(fi) };
  });

const playableTickIndex = computed({
    get: () => currentTickIndex.value - firstPlayableTickIndex.value,
    set: (v) => { currentTickIndex.value = v + firstPlayableTickIndex.value; }
});

  // currentTick: assembled on demand from typed arrays
  const currentTick = computed(() => getTickView(round.value, currentTickIndex.value));

  function tickToSecondsRemaining(t) {
    if (!round.value.meta) return null;
    const start = Math.max(0, round.value.meta.start ?? 0, round.value.meta.freeze_end ?? 0);
    return Math.max(0, TOTAL_ROUND_DURATION - Math.max(0, (t - start) / SERVER_TICK_RATE));
  }

 const secondsRemaining = computed(() => {
    const tickNum = round.value?.tickNumbers?.[currentTickIndex.value] ?? 0;
    return tickToSecondsRemaining(tickNum);
});

  // ── Kill feed ─────────────────────────────────────────────────────────────
  const currentEvents = computed(() => {
    if (!currentTickIndex.value) return [];
    const ticks = round.value?.tickNumbers;
    const kills = round.value?.kills;
    if (!ticks?.length || !kills) return [];
    const startIndex = Math.max(0, currentTickIndex.value - FEED_LINGER_SECONDS * SERVER_TICK_RATE);
    const endIndex   = Math.min(currentTickIndex.value, ticks.length);
    const events = [], shown = new Set();
    for (let i = startIndex; i < endIndex; i++) {
      const tick = ticks[i];
      if (!(tick in kills)) continue;
      events.push(...kills[tick].filter(k => !shown.has(k.victim_steamid)));
      kills[tick].forEach(k => shown.add(k.victim_steamid));
    }
    return events;
  });

  // steamIdTeamLookup — built from the fixed player roster (slot 0 of first tick)
  const steamIdTeamLookup = computed(() => {
    const { steamids, teams, count } = round.value.players;
    if (!count) return {};
    const lookup = {};
    for (let s = 0; s < count; s++) {
      lookup[steamids[s]] = teams[s] === 0 ? 'ct' : 't';
    }
    return lookup;
  });

  // ── Round tab helpers (logic unchanged) ───────────────────────────────────
  const roundTabSeparators = computed(() => {
    const r    = demoRounds.value;
    const seps = new Array(r.length).fill(false);
    const halfwayPoints = [[24,12,12],[30,15,15],[36,18,18],[42,21,21],[48,24,24]];
    for (let i = 1; i < r.length; i++) {
      const prev = r[i - 1], cur = r[i];
      const ctDiff = Math.abs((cur.meta?.CT_score ?? 0) - (prev.meta?.CT_score ?? 0));
      const tDiff  = Math.abs((cur.meta?.T_score  ?? 0) - (prev.meta?.T_score  ?? 0));
      const isHalf = halfwayPoints.some(([idx, ct, t]) =>
        i === idx && prev.meta?.CT_score === ct && prev.meta?.T_score === t
      );
      seps[i] = ctDiff > 1 || tDiff > 1 || isHalf;
    }
    return seps;
  });

  const roundTabSideSwapped = computed(() => {
    const r       = demoRounds.value;
    const swapped = new Array(r.length).fill(false);
    let lastSideChangeIndex = 0;
    for (let i = 1; i < r.length; i++) {
      const prev = r[i - 1], prevPrev = r[i - 2];
      if (prevPrev) {
        const ctDiff = Math.abs((prev.meta?.CT_score ?? 0) - (prevPrev.meta?.CT_score ?? 0));
        const tDiff  = Math.abs((prev.meta?.T_score  ?? 0) - (prevPrev.meta?.T_score  ?? 0));
        if (ctDiff > 1 || tDiff > 1) lastSideChangeIndex = i - 1;
      }
      swapped[i] = lastSideChangeIndex > 0 && i >= lastSideChangeIndex;
    }
    return swapped;
  });

  // ── loadRound ─────────────────────────────────────────────────────────────
  const lastLoadedRoundKey = ref(null);
  const loadRoundDebounce  = ref(null);

  function setPinnedRoundKeys(keys) { pinnedRoundKeys.value = new Set(keys); }

  async function loadRound(demoPubId, demoIntId, roundIndex, background = false) {
    const roundKey = `${demoIntId}_${roundIndex}`;

    if (!background) {
      const url = new URL(window.location);
      url.searchParams.set('round', roundIndex);
      window.history.replaceState({}, '', url);
    }

    if (!background && lastLoadedRoundKey.value === roundKey && currentRound.value === roundIndex) return;
    if (loadRoundDebounce.value) { clearTimeout(loadRoundDebounce.value); loadRoundDebounce.value = null; }

    if (loadingRounds.value.has(roundKey)) {
      return new Promise(resolve => {
        const check = setInterval(() => {
          if (!loadingRounds.value.has(roundKey)) { clearInterval(check); resolve(); }
        }, 100);
      });
    }

    if (!background) {
      allowPlay.value        = false;
      lastLoadedRoundKey.value = roundKey;
      const next = {};
      if (rounds.value[roundKey]) next[roundKey] = rounds.value[roundKey];
      rounds.value           = next;
      currentRound.value     = roundIndex;
      currentTickIndex.value = 0;
    }

    return new Promise(resolve => {
      if (rounds.value[roundKey] && rounds.value[roundKey] !== EMPTY_ROUND) {
        if (!background) {
          currentRound.value     = roundIndex;
          currentTickIndex.value = 0;
          allowPlay.value        = true;
        }
        resolve(); return;
      }

      loadingRounds.value.add(roundKey);
      const withPlaceholder = { ...rounds.value, [roundKey]: EMPTY_ROUND };
      rounds.value = evictOldRounds(withPlaceholder, pinnedRoundKeys.value);

      const env = import.meta.env.VITE_APP_ENV;
      let worker;

      // 2. Implement the Cross-Origin Dev Workaround
      if (import.meta.env.DEV) {
        // Construct the URL to the worker on the Vite dev server
        const workerUrl = new URL('@/Workers/RoundLoader.worker.js', import.meta.url).href;
        
        // Create a local blob that imports the remote module
        const blob = new Blob([`import "${workerUrl}";`], { type: 'application/javascript' });
        
        // Instantiate the worker using the local blob URL
        worker = new Worker(URL.createObjectURL(blob), { type: 'module' });
      } else {
        // Production behavior (Assuming your build process outputs them to the same origin)
        worker = new Worker(new URL('@/Workers/RoundLoader.worker.js', import.meta.url), { type: 'module' });
      }

      worker.onmessage = (event) => {
    if (event.data?.result) {                              // ✅ unwrap
        const withRound = { ...rounds.value, [roundKey]: event.data.result };
        rounds.value = evictOldRounds(withRound, pinnedRoundKeys.value);
    }
    loadingRounds.value.delete(roundKey);
    if (!background) allowPlay.value = true;
    resolve(); worker.terminate();
};
      worker.onerror = (err) => {
        console.error('RoundLoader worker error:', err);
        loadingRounds.value.delete(roundKey);
        if (!background) allowPlay.value = true;
        resolve(); worker.terminate();
      };
      worker.postMessage({ demoId: demoPubId, roundIndex, version: version.value ?? 1.0, baseUrl: window.location.origin });
    });
  }

  return {
    rounds,
    currentRound,
    currentTickIndex,
    allowPlay,
    loadingRounds,
    round,
    firstPlayableTickIndex,
    playableRound,
    playableTickIndex,
    currentTick,
    currentEvents,
    secondsRemaining,
    steamIdTeamLookup,
    tickToSecondsRemaining,
    roundTabSeparators,
    roundTabSideSwapped,
    loadRound,
    setPinnedRoundKeys,
  };
}