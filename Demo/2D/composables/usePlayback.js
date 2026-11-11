import { ref, computed } from 'vue';
import { SERVER_TICK_RATE } from '../options';

export function usePlayback({
  currentTickIndex, firstPlayableTickIndex,
  currentRound, round, demoRounds, rounds, loadingRounds, allowPlay, loadRound,
  viewingMultipleRounds, multiRoundTickIndex, multiRoundTickNumbers,
  render,
  demoId, externalId,
}) {
  const playing       = ref(false);
  const playbackSpeed = ref(1);
  const lastTickTime  = ref(0);
  let   rafHandle     = null;

  const tickRate = computed(() => SERVER_TICK_RATE / (1 / playbackSpeed.value));

  const SPEED_CYCLE = { 1: 2, 2: 4, 4: 0.25, 0.25: 0.5, 0.5: 1 };

  function togglePlaybackSpeed() {
    const wasPlaying = playing.value;
    if (wasPlaying) pauseDemo();
    playbackSpeed.value = SPEED_CYCLE[playbackSpeed.value] ?? 1;
    if (wasPlaying) setTimeout(playDemo, 0);
  }

  function togglePlayback() { playing.value ? pauseDemo() : playDemo(); }

  function playDemo() {
    if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
    playing.value  = true;
    lastTickTime.value = performance.now();

    const animate = (now) => {
      if (!playing.value) return;
      const delta       = now - lastTickTime.value;
      const tickInterval= 1000 / tickRate.value;
      const toAdvance   = Math.min(Math.floor(delta / tickInterval), 8);

      if (toAdvance > 0) {
        lastTickTime.value = now - (delta % tickInterval);
        for (let i = 0; i < toAdvance; i++) {
          if (!_advance()) { pauseDemo(); return; }
        }
        render(true);
      }

      rafHandle = requestAnimationFrame(animate);
    };
    rafHandle = requestAnimationFrame(animate);
  }

  function pauseDemo() {
    playing.value = false;
    if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null; }
  }

  function _advance() {
    if (viewingMultipleRounds.value) {
      if (multiRoundTickIndex.value < multiRoundTickNumbers.value.length - 1) {
        multiRoundTickIndex.value++;
        return true;
      }
      return false;
    }

    const tickNumbers = round.value?.tickNumbers || [];
    const maxTick     = tickNumbers.length - 1;

    // FIX: If the round has no ticks yet, wait for data instead of skipping to next round
    if (tickNumbers.length === 0) return false;

    const nextKey = `${demoId.value}_${currentRound.value + 1}`;
    if (
      currentRound.value < demoRounds.value.length &&
      !rounds.value[nextKey] &&
      !loadingRounds.value.has(nextKey)
    ) {
      loadRound(externalId.value, demoId.value, currentRound.value + 1, true);
    }

    if (currentTickIndex.value < maxTick) {
      if (currentTickIndex.value < firstPlayableTickIndex.value) {
        currentTickIndex.value = firstPlayableTickIndex.value;
      } else {
        currentTickIndex.value++;
      }
      return true;
    }

    // End of round — only auto-advance if we've actually finished playing the current data
    if (currentRound.value < demoRounds.value.length) {
      if (rounds.value[nextKey] && !loadingRounds.value.has(nextKey)) {
        currentRound.value++;
        currentTickIndex.value = firstPlayableTickIndex.value;
        return true;
      }
    }
    return false;
  }

  return { playing, playbackSpeed, togglePlayback, togglePlaybackSpeed, playDemo, pauseDemo };
}