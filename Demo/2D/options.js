const SERVER_TICK_RATE = 64;
const TOTAL_ROUND_DURATION = 115; // seconds
const GRENADE_ACTIVATION_TICKS = 104; // No souce, looks about right
const FLASH_ACTIVATION_TICKS = GRENADE_ACTIVATION_TICKS;
const SMOKE_LINGER_TICKS = 18 * SERVER_TICK_RATE; // 18 seconds

const SMOKE_RADIUS = 144;
const INFERNO_RADIUS = 128;
const GRENADE_EXPLOSION_RADIUS = 144; // Idfk, again no source.
const FLASH_RADIUS = 144; // Just using random numbers at this point
const C4_DELAY = 40; // seconds
const C4_DELAY_TICKS = C4_DELAY * SERVER_TICK_RATE;

const FEED_LINGER_SECONDS = 10;
const MAX_ZOOM = 3;
const MIN_ZOOM = 0.1;
const BULLET_FADE_TICKS = 12;
const GRENADE_TRAJECTORY_FADE_TICKS = 128;
const FLASH_FADE_TICKS = 12;
const NADE_FADE_TICKS = 12;
const UTILITIES = [
    'High Explosive Grenade',
    'Smoke Grenade',
    'Flashbang',
    'Decoy Grenade',
    'Molotov',
    'Incendiary Grenade',
    'Zeus x27',
    'Defuser',
];

const PISTOLS = [
    'CZ75-Auto', 'Desert-Eagle', 'Dual-Berettas', 'Five-SeveN', 
    'Glock-18', 'P2000', 'P250', 'R8-Revolver', 'Tec-9', 'USP-S'
];

export {
    SERVER_TICK_RATE,
    TOTAL_ROUND_DURATION,
    GRENADE_ACTIVATION_TICKS,
    FLASH_ACTIVATION_TICKS,
    SMOKE_RADIUS,
    INFERNO_RADIUS,
    GRENADE_EXPLOSION_RADIUS,
    FLASH_RADIUS,
    FEED_LINGER_SECONDS,
    MAX_ZOOM,
    MIN_ZOOM,
    BULLET_FADE_TICKS,
    GRENADE_TRAJECTORY_FADE_TICKS,
    FLASH_FADE_TICKS,
    NADE_FADE_TICKS,
    SMOKE_LINGER_TICKS,
    C4_DELAY,
    C4_DELAY_TICKS,
    UTILITIES,
    PISTOLS,
};
