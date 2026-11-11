/**
 * useMultiDemo
 * Manages compare-rounds / compare-demos feature.
 */
import { ref, computed } from 'vue';
import { SERVER_TICK_RATE, TOTAL_ROUND_DURATION } from '../options';

export function useMultiDemo({ rounds, loadRound, allowPlay, setPinnedRoundKeys }) {

  // ─── Loaded extra demos ───────────────────────────────────────────────────
  const loadedDemos = ref(new Map());

  async function addDemo(externalId) {
    const id = String(externalId);
    if (loadedDemos.value.has(id)) return;
    try {
      const res  = await fetch(`/api/demos/${id}`);
      const data = await res.json();
      loadedDemos.value = new Map(loadedDemos.value).set(id, {
        externalId: id,
        id:     data.id,
        name:   data.name ?? id,
        rounds: data.rounds ?? [],
      });
    } catch (e) {
      console.error('Failed to load demo metadata:', e);
    }
  }

  function removeDemo(externalId) {
    const id   = String(externalId);
    const next = new Map(loadedDemos.value);
    next.delete(id);
    loadedDemos.value    = next;
    selectedRounds.value = selectedRounds.value.filter(r => r.externalId !== id);
  }

  // ─── Round selection ──────────────────────────────────────────────────────
  const selectedRounds = ref([]);
  const multiRoundMode = ref(false);

  function toggleMultiRoundMode() {
    multiRoundMode.value = !multiRoundMode.value;
    if (!multiRoundMode.value) selectedRounds.value = [];
  }

  function isRoundSelected(externalId, roundIndex) {
    return selectedRounds.value.some(
      r => r.externalId === String(externalId) && r.roundIndex === roundIndex
    );
  }

  function toggleRoundSelection(externalId, demoId, demoName, roundIndex) {
    const eid = String(externalId);
    const idx = selectedRounds.value.findIndex(
      r => r.externalId === eid && r.roundIndex === roundIndex
    );
    if (idx === -1) selectedRounds.value.push({ externalId: eid, demoId, demoName, roundIndex });
    else selectedRounds.value.splice(idx, 1);
  }

  // ─── Active comparison state ──────────────────────────────────────────────
  const viewingMultipleRounds = ref(false);
  const activeRounds          = ref([]);
  const multiRoundTickIndex   = ref(0);
  const multiRoundTickNumbers = ref([]);

  const multiRoundSecondsRemaining = computed(() => {
    if (!multiRoundTickNumbers.value.length) return 115;
    const relativeTick = multiRoundTickNumbers.value[multiRoundTickIndex.value] ?? 0;
    return Math.max(0, TOTAL_ROUND_DURATION - relativeTick / SERVER_TICK_RATE);
  });

  // ─── Filters ──────────────────────────────────────────────────────────────
  const teamFilter   = ref('both');
  const playerFilter = ref(null);
  const weaponFilter = ref(null);
  const showUtil     = ref(true);

  function setTeamFilter(v)   { teamFilter.value   = v; }
  function setPlayerFilter(v) { playerFilter.value = v; }
  function setShowUtil(v)     { showUtil.value      = v; }

  // ─── Player list for filter UI ────────────────────────────────────────────
  const multiRoundPlayers = computed(() => {
    const seen = new Map();
    for (const r of activeRounds.value) {
      const data = rounds.value?.[`${r.demoId}_${r.roundIndex}`];
      if (!data?.players) continue;
      const { steamids, names, teams, count } = data.players;
      for (let s = 0; s < count; s++) {
        const steamid = steamids[s];
        if (!seen.has(steamid)) {
          seen.set(steamid, {
            steamid,
            name:      names[s] || steamid,
            team_name: teams[s] === 0 ? 'ct' : 't',
          });
        }
      }
    }
    return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
  });

  // ─── Apply ────────────────────────────────────────────────────────────────
  async function applyMultiRoundView() {
    if (!selectedRounds.value.length) return;
    multiRoundMode.value        = false;
    viewingMultipleRounds.value = true;

    activeRounds.value = [...selectedRounds.value].sort((a, b) =>
      a.demoId !== b.demoId
        ? String(a.demoId).localeCompare(String(b.demoId))
        : a.roundIndex - b.roundIndex
    );

    // ── PIN all active round keys BEFORE loading ──────────────────────────
    // Without this, each worker completion calls evictOldRounds(MAX=5) and
    // throws away all but the last 5 rounds, even though they just loaded.
    const pinnedKeys = activeRounds.value.map(r => `${r.demoId}_${r.roundIndex}`);
    setPinnedRoundKeys?.(pinnedKeys);

    // Evict rounds not in the active set (frees memory from prior browsing)
    const keep    = new Set(pinnedKeys);
    const pruned  = {};
    for (const k of Object.keys(rounds.value ?? {})) {
      if (keep.has(k)) pruned[k] = rounds.value[k];
    }
    rounds.value = pruned;

    allowPlay.value = false;
    await Promise.all(
      activeRounds.value.map(r => loadRound(r.externalId, r.demoId, r.roundIndex, true))
    );

    // Build unified relative tick timeline
    let maxDuration = 0;
    for (const r of activeRounds.value) {
      const data = rounds.value?.[`${r.demoId}_${r.roundIndex}`];
      if (!data) continue;
      const freezeEnd = data.meta?.freeze_end ?? 0;
      const lastTick  = data.tickNumbers[data.tickNumbers.length - 1] ?? 0;
      maxDuration = Math.max(maxDuration, lastTick - freezeEnd);
    }

    multiRoundTickNumbers.value = Array.from({ length: Math.ceil(maxDuration) + 1 }, (_, i) => i);
    multiRoundTickIndex.value   = 0;
    allowPlay.value             = true;
  }

  function exitMultiRoundView() {
    viewingMultipleRounds.value = false;
    activeRounds.value          = [];
    multiRoundTickIndex.value   = 0;
    multiRoundTickNumbers.value = [];
    // Unpin so normal LRU eviction resumes
    setPinnedRoundKeys?.([]);
    teamFilter.value   = 'both';
    playerFilter.value = null;
    showUtil.value     = true;
  }

  // ─── Per-round tick resolution ────────────────────────────────────────────
  function getTickIndexForRound(demoId, roundIndex) {
    const data = rounds.value?.[`${demoId}_${roundIndex}`];
    if (!data?.tickNumbers?.length) return 0;

    const freezeEnd      = data.meta?.freeze_end ?? 0;
    const relativeOffset = multiRoundTickNumbers.value[multiRoundTickIndex.value] ?? 0;
    const targetTick     = freezeEnd + relativeOffset;
    const ticks          = data.tickNumbers;

    let lo = 0, hi = ticks.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (ticks[mid] < targetTick) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0 && Math.abs(ticks[lo - 1] - targetTick) <= Math.abs(ticks[lo] - targetTick)) lo--;
    return lo;
  }

  // ─── Colour helpers ───────────────────────────────────────────────────────
  function getRoundColor(index, total, alpha = 1) {
    const hue = (index * 137.508) % 360;
    return `hsla(${hue}, 70%, 60%, ${alpha})`;
  }

  function getActiveRoundColor(demoId, roundIndex) {
    const idx = activeRounds.value.findIndex(
      r => r.demoId === demoId && r.roundIndex === roundIndex
    );
    return idx === -1 ? 'hsla(0,0%,50%,1)' : getRoundColor(idx, activeRounds.value.length);
  }

  return {
    loadedDemos, addDemo, removeDemo,
    selectedRounds, multiRoundMode,
    toggleMultiRoundMode, isRoundSelected, toggleRoundSelection,
    viewingMultipleRounds, activeRounds,
    multiRoundTickIndex, multiRoundTickNumbers, multiRoundSecondsRemaining,
    applyMultiRoundView, exitMultiRoundView,
    getTickIndexForRound,
    teamFilter, playerFilter, weaponFilter, showUtil,
    setTeamFilter, setPlayerFilter, setShowUtil,
    multiRoundPlayers,
    getRoundColor, getActiveRoundColor,
  };
}