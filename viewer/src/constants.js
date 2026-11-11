// Stage 07 — viewer constants. Ported from the old Demo/2D/options.js (stats-related
// entries dropped). Tick math assumes a 64-tick payload (matches the parser output).

// Radar coordinate space. The world→radar calibration (map_ref pos/scale) targets a SQUARE
// 1024px radar (matches the API's calibration), so the radar image is drawn at exactly this size —
// never the SVG/PNG's own intrinsic size, which for SVGs can be 0 or non-square and would leave the
// radar covering only part of the playfield while the player overlay sits in full 1024px space.
export const RADAR_SIZE = 1024;

// Verbatim from Demo/2D/options.js — the utility renderer is ported exactly, so these must match.
export const SERVER_TICK_RATE = 64;
export const SMOKE_LINGER_TICKS = 18 * SERVER_TICK_RATE; // 18 s
export const SMOKE_RADIUS = 144;        // world units
export const INFERNO_RADIUS = 128;
export const GRENADE_EXPLOSION_RADIUS = 144;
export const FLASH_RADIUS = 144;
export const GRENADE_ACTIVATION_TICKS = 104;
export const FLASH_ACTIVATION_TICKS = GRENADE_ACTIVATION_TICKS;
export const BULLET_FADE_TICKS = 12;
export const GRENADE_TRAJECTORY_FADE_TICKS = 128;
export const FLASH_FADE_TICKS = 12;
export const C4_DELAY_TICKS = 40 * SERVER_TICK_RATE; // 40 s fuse

// CDN that hosts the radar + icon + weapon SVGs (same assets as the production demoviewer).
export const ASSET_BASE = 'https://csstrats.b-cdn.net';
export const playerIconUrl = (team) =>
  `${ASSET_BASE}/icons/${team === 'ct' ? 'ct_player' : 't_player'}.svg`;

// CS2 display weapon name → /weapons/<file>.svg (the held-weapon icon drawn by each player).
export const WEAPON_FILE = {
  'AK-47': 'ak47', AUG: 'aug', AWP: 'awp_white', 'PP-Bizon': 'bizon', 'CZ75-Auto': 'cz',
  'Desert Eagle': 'deagle', 'Dual Berettas': 'dualberettas', FAMAS: 'famas',
  'Five-SeveN': 'fiveseven', G3SG1: 'g3sg1', 'Galil AR': 'galil', 'Glock-18': 'glock',
  M249: 'm249', 'M4A1-S': 'm4a1', M4A4: 'm4a4', 'MAC-10': 'mac10', 'MAG-7': 'mag7',
  'MP5-SD': 'mp5', MP7: 'mp7', MP9: 'mp9', Negev: 'negev', Nova: 'nova', 'P2000': 'p2000',
  P250: 'p250', P90: 'p90', 'R8 Revolver': 'r8', 'Sawed-Off': 'sawedoff', 'SCAR-20': 'scar20',
  'SG 553': 'sg553', 'SSG 08': 'ssg08', 'Tec-9': 'tec9', 'UMP-45': 'ump45', 'USP-S': 'usps',
  XM1014: 'xm', 'Zeus x27': 'zeus', 'HE Grenade': 'he', Flashbang: 'flashbang',
  'Smoke Grenade': 'smoke', 'Decoy Grenade': 'decoy', Molotov: 'molotov',
  'Incendiary Grenade': 'inc',
};
// normalized grenade_type → /weapons/<file>.svg (the in-flight projectile icon).
export const GRENADE_FILE = {
  smoke: 'smoke', he_grenade: 'he', flashbang: 'flashbang', molotov: 'molotov',
  incendiary: 'inc', decoy_grenade: 'decoy', decoy: 'decoy',
};

// Default theme — EVERY visual is overridable per tenant via the `theme` init option.
// A tenant can recolor teams, swap the player marker SVGs for their own, retint the chrome,
// resize markers/labels, toggle any layer, choose the control set, and place/recolor the HUD.
export const DEFAULT_THEME = {
  // ── palette ────────────────────────────────────────────────────────────────
  accent: '#f5a623',           // scoreline / active controls
  ctColor: '#7a9bcb',          // CT team color (markers, smoke tint, tracers, scoreboard)
  tColor: '#d1c185',           // T team color
  background: '#0e0f12',       // canvas + container background
  bombColor: '#cd6133',        // C4 carrier ring + planted ring + bomb fallback
  // ── chrome / controls ───────────────────────────────────────────────────────
  controlBg: 'rgba(0,0,0,0.55)',
  controlColor: '#ffffff',
  font: '12px system-ui, sans-serif',
  // ── assets (tenants can host their own marker/weapon SVGs) ───────────────────
  assetBase: ASSET_BASE,
  ctIconUrl: `${ASSET_BASE}/icons/ct_player.svg`,
  tIconUrl: `${ASSET_BASE}/icons/t_player.svg`,
  // ── sizes ────────────────────────────────────────────────────────────────────
  radarOpacity: 1,
  playerIconSize: 26,          // image-pixel width of the player marker
  weaponIconSize: 11,          // image-pixel width of the held-weapon icon beside a player
  nameFontSize: 11,
  // ── name labels ───────────────────────────────────────────────────────────────
  nameColor: 'team',           // 'team' = use team color, or any CSS color string
  nameBg: 'rgba(0,0,0,0.55)',
  // ── in-canvas HUD scoreboard ────────────────────────────────────────────────
  hudBg: 'rgba(0,0,0,0.38)',
  hudColor: '#ffffff',
  hudMutedColor: '#9aa3b2',
  hudDeadColor: '#888888',
  hudMoneyColor: '#6ab04c',
  scoreboard: 'sides',         // 'sides' (CT left / T right) | 'off'
  // ── layer toggles ─────────────────────────────────────────────────────────────
  showWeaponFire: true,
  showGrenades: true,
  showSmokes: true,
  showWeapons: true,           // held-weapon icon beside each player
  showNames: true,
  showHud: true,
  showTimer: true,             // round/bomb/defuse clock (Stage 17 §17.3)
  showKillfeed: true,          // in-viewer killfeed (Stage 17 §17.3)
  tracerFromTeam: true,        // tracer color follows shooter's team (else accent)
  followColor: '#ffd54f',      // highlight ring on a followed player (deep-link, §17.1)
  // ── controls present (order preserved) ──────────────────────────────────────
  // Scoreboard visibility is configured in code (`scoreboard` option / api.setScoreboard),
  // not via a player button — add 'scoreboard' here only if a tenant wants a UI toggle.
  controls: ['play', 'timeline', 'round', 'speed', 'share', 'fullscreen'],
};
