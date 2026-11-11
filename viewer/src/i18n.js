// i18n label dictionary (Stage 17 §17.4). No hardcoded English in the UI — every user-visible
// string comes from here so host sites can localize via `theme.i18n` / the `labels` init option.
// Pure + tiny; `makeI18n(overrides)` returns a `t(key, params)` lookup with `{placeholder}` interp.

export const DEFAULT_STRINGS = {
  processing: 'Demo is processing…',
  loadingRound: 'Loading round {round}…',
  rateLimited: 'Rate limited — retrying…',
  unsupportedMap: 'Map “{map}” isn’t supported yet (no radar calibration).',
  roundLoadFailed: 'Round failed to load.',
  authError: 'Authentication / origin error.',
  loadFailed: 'Failed to load demo.',
  notReady: 'Demo is still processing — try again shortly.',
  outdatedViewer: 'This viewer is out of date for this demo; some features may be missing.',
  round: 'Round {n}',
  // control labels / ARIA
  play: 'Play',
  pause: 'Pause',
  roundSelect: 'Select round',
  timeline: 'Timeline',
  speed: 'Playback speed',
  scoreboard: 'Toggle scoreboard',
  fullscreen: 'Fullscreen',
  share: 'Copy share link',
  shareCopied: 'Link copied',
  bomb: 'Bomb',
  defusing: 'Defusing',
};

export function makeI18n(overrides) {
  const dict = { ...DEFAULT_STRINGS, ...(overrides || {}) };
  return (key, params) => {
    let s = dict[key] ?? key;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        s = s.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
      }
    }
    return s;
  };
}
