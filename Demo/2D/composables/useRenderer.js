import { ref, watch } from 'vue';
import { convertFloatToHexOpacity } from '@/helpers';
import { getTickView } from './useRoundData';
import {
  SERVER_TICK_RATE,
  INFERNO_RADIUS,
  SMOKE_RADIUS,
  GRENADE_EXPLOSION_RADIUS,
  FLASH_RADIUS,
  GRENADE_ACTIVATION_TICKS,
  FLASH_ACTIVATION_TICKS,
  BULLET_FADE_TICKS,
  GRENADE_TRAJECTORY_FADE_TICKS,
  SMOKE_LINGER_TICKS,
  C4_DELAY_TICKS,
} from '../options';

// ─── Icon image cache ─────────────────────────────────────────────────────────
const iconImgCache = {};
function getIconImage(url) {
  if (!iconImgCache[url]) {
    const img = new Image();
    img.src = url;
    iconImgCache[url] = img;
  }
  return iconImgCache[url];
}

// ─── Path2D cache ─────────────────────────────────────────────────────────────
const path2DCache = {};
function getPath2D(svgString) {
  if (!path2DCache[svgString]) path2DCache[svgString] = new Path2D(svgString);
  return path2DCache[svgString];
}

// ─── Precomputed static paths ─────────────────────────────────────────────────
const ARROW_PATH  = new Path2D('M 6 -7.44 a 9.6 9.6 180 0 0 -6 -2.16 a 9.6 9.6 180 0 0 0 19.2 a 9.6 9.6 180 0 0 6 -2.16 l 9.84 -7.44 z');
const CIRCLE_PATH = new Path2D('M 0 0 m -10 0 a 10 10 90 1 0 20 0 a 10 10 90 1 0 -20 0');

const TEAM_COLORS = { ct: '#7a9bcb', t: '#d1c185' };
function getTeamColor(team) { return TEAM_COLORS[team] ?? '#808080'; }
function getPlayerIconUrl(team) {
  return team === 'ct'
    ? 'https://csstrats.b-cdn.net/icons/ct_player.svg'
    : 'https://csstrats.b-cdn.net/icons/t_player.svg';
}

const PLAYER_FONT       = 'bold 14px "Bai Jamjuree", sans-serif';
const PLAYER_FONT_SMALL = 'bold 10px "Bai Jamjuree", sans-serif';
const BOMB_FONT         = 'bold 6px Bai Jamjuree';
// Compact, low-profile name labels — small rounded pills instead of big slabs.
const PLAYER_LABEL_FONT       = '600 11px "Bai Jamjuree", sans-serif';
const PLAYER_LABEL_FONT_SMALL = '600 9px "Bai Jamjuree", sans-serif';

const HOVER_DIM_ALPHA = 0.2;

export function useRenderer({
  getCanvases, toWorldCoords, toGameCoords,
  mapPosition, cachedImage,
  refreshMapPixelCacheIfNeeded, getPixelCache,
  round, currentTickIndex, currentTick, steamIdTeamLookup,
  mapMetadata,
  getWeapon,
  viewingMultipleRounds, activeRounds, rounds,
  multiRoundTickIndex,
  teamFilter, playerFilter, weaponFilter, showUtil, checkWeaponFilter,
  getRoundColor,
  hoveredPlayer,
}) {

  // ─── Single-round grenade / explosion state ───────────────────────────────
  const activeExplosions    = ref([]);
  const processedExplosions = new Set();
  const lastTickNumber      = ref(0);
  const roundGrenades       = ref(new Map());

  // ─── Player hit-test boxes (game coords) — rebuilt every render ────────────
  // Consumed by the Viewer's hover handler to resolve which player is under
  // the cursor. Entry: { steamid, team, X, Y, roundKey } (roundKey null = single).
  const playerHitboxes = ref([]);

  watch(
    () => round.value?.tickNumbers,
    () => {
      const src = round.value?.grenades ?? {};
      roundGrenades.value = new Map(Object.entries(src));
      activeExplosions.value = [];
      processedExplosions.clear();
      lastTickNumber.value = 0;
    },
    { immediate: true },
  );

  // ─── Per-round explosion state for multiround ─────────────────────────────
  // Keyed by roundKey → { active[], processed: Set, lastTick }
  const multiRoundExplosions = {};

  function _getMultiRoundExplosionState(roundKey) {
    if (!multiRoundExplosions[roundKey]) {
      multiRoundExplosions[roundKey] = { active: [], processed: new Set(), lastTick: -1 };
    }
    return multiRoundExplosions[roundKey];
  }

  function clearMultiRoundState() {
    for (const k of Object.keys(multiRoundExplosions)) delete multiRoundExplosions[k];
  }

  // ─── RAF dispatcher ────────────────────────────────────────────────────────
  let rafHandle = null;

  function render(skipRAF = false) {
    if (skipRAF) {
      viewingMultipleRounds.value ? renderMultiRound() : renderSingleRound();
      return;
    }
    if (rafHandle) cancelAnimationFrame(rafHandle);
    rafHandle = requestAnimationFrame(() => {
      viewingMultipleRounds.value ? renderMultiRound() : renderSingleRound();
      rafHandle = null;
    });
  }

  function cancelRender() {
    if (rafHandle) { cancelAnimationFrame(rafHandle); rafHandle = null; }
  }

  // ─── Map layer (only redrawn on pan/zoom/resize) ──────────────────────────
  let _lastMapX = null, _lastMapY = null, _lastMapScale = null;

  function _redrawMapIfNeeded(mapCanvas, mapCtx) {
    const { x, y, scale } = mapPosition.value;
    if (x === _lastMapX && y === _lastMapY && scale === _lastMapScale) return;
    _lastMapX = x; _lastMapY = y; _lastMapScale = scale;
    mapCtx.setTransform(1, 0, 0, 1, 0, 0);
    mapCtx.clearRect(0, 0, mapCanvas.width, mapCanvas.height);
    mapCtx.setTransform(scale, 0, 0, scale, x, y);
    mapCtx.drawImage(cachedImage.value, 0, 0);
    refreshMapPixelCacheIfNeeded(mapCanvas, mapCtx);
  }

  // ─── Single-round render ──────────────────────────────────────────────────
  function renderSingleRound() {
    const currentTickNumber = round.value?.tickNumbers?.[currentTickIndex.value];
    const { mapCanvas, mapCtx, ctx } = getCanvases();
    if (!mapCanvas || !cachedImage.value) return;

    const meta            = mapMetadata.value;
    const infernoRadius   = INFERNO_RADIUS           / meta.scale;
    const smokeRadius     = SMOKE_RADIUS             / meta.scale;
    const explosionRadius = GRENADE_EXPLOSION_RADIUS / meta.scale;
    const flashRadius     = FLASH_RADIUS             / meta.scale;

    const topLeft     = toWorldCoords(-mapCanvas.width * 2, -mapCanvas.height * 2);
    const bottomRight = toWorldCoords( mapCanvas.width * 2,  mapCanvas.height * 2);
    const clearW = bottomRight.x - topLeft.x, clearH = bottomRight.y - topLeft.y;

    _redrawMapIfNeeded(mapCanvas, mapCtx);

    ctx.setTransform(mapPosition.value.scale, 0, 0, mapPosition.value.scale, mapPosition.value.x, mapPosition.value.y);
    ctx.clearRect(topLeft.x, topLeft.y, clearW, clearH);

    if (!currentTick.value) { playerHitboxes.value = []; return; }

    const hitboxes = [];
    _drawPlayers(ctx, currentTick.value.players, hitboxes);
    playerHitboxes.value = hitboxes;
    _drawBulletTracers(ctx, mapCanvas, currentTickNumber);
    _drawBomb(ctx, currentTick.value.bomb);
    _updateAndDrawExplosions(ctx, currentTickNumber, infernoRadius, explosionRadius, flashRadius);
    _drawSmokes(ctx, currentTickNumber, smokeRadius);
    _drawInfernos(ctx, currentTickNumber, infernoRadius);
  }

  // ─── Multi-round render ───────────────────────────────────────────────────
  function renderMultiRound() {
    const { mapCanvas, mapCtx, ctx } = getCanvases();
    if (!mapCanvas || !cachedImage.value) return;

    const meta            = mapMetadata.value;
    const smokeRadius     = SMOKE_RADIUS             / meta.scale;
    const infernoRadius   = INFERNO_RADIUS           / meta.scale;
    const explosionRadius = GRENADE_EXPLOSION_RADIUS / meta.scale;
    const flashRadius     = FLASH_RADIUS             / meta.scale;

    const topLeft     = toWorldCoords(-mapCanvas.width * 2, -mapCanvas.height * 2);
    const bottomRight = toWorldCoords( mapCanvas.width * 2,  mapCanvas.height * 2);
    const clearW = bottomRight.x - topLeft.x, clearH = bottomRight.y - topLeft.y;

    mapCtx.clearRect(topLeft.x, topLeft.y, clearW, clearH);
    mapCtx.setTransform(mapPosition.value.scale, 0, 0, mapPosition.value.scale, mapPosition.value.x, mapPosition.value.y);
    mapCtx.drawImage(cachedImage.value, 0, 0);

    ctx.setTransform(mapPosition.value.scale, 0, 0, mapPosition.value.scale, mapPosition.value.x, mapPosition.value.y);
    ctx.clearRect(topLeft.x, topLeft.y, clearW, clearH);

    const relativeOffset = multiRoundTickIndex.value;

    const hov      = hoveredPlayer?.value ?? null;
    const hitboxes = [];

    activeRounds.value.forEach((roundObj, roundIdx) => {
      const roundKey  = `${roundObj.demoId}_${roundObj.roundIndex}`;
      const roundData = rounds.value[roundKey];
      if (!roundData) return;

      const roundColor = getRoundColor(roundIdx, activeRounds.value.length);
      const freezeEnd  = roundData.meta?.freeze_end ?? 0;
      const actualTick = freezeEnd + relativeOffset;
      const ticks      = roundData.tickNumbers;
      if (!ticks?.length) return;

      // Binary search for nearest tick index
      let lo = 0, hi = ticks.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (ticks[mid] < actualTick) lo = mid + 1;
        else hi = mid;
      }
      if (lo > 0 && Math.abs(ticks[lo - 1] - actualTick) < Math.abs(ticks[lo] - actualTick)) lo--;
      if (lo >= ticks.length) return;

      const currentTickNo = ticks[lo];
      const tick          = getTickView(roundData, lo);
      if (!tick) return;

      // Build steamid→team lookup for this round (for grenade thrower filtering)
      const roundTeamLookup = {};
      if (roundData.players?.count) {
        const { steamids, teams, count } = roundData.players;
        for (let s = 0; s < count; s++) {
          roundTeamLookup[steamids[s]] = teams[s] === 0 ? 'ct' : 't';
        }
      }

      // ── Players ────────────────────────────────────────────────────────────
      ctx.save();
      tick.players.forEach((player) => {
        if (!player || player.health <= 0) return;
        if (teamFilter.value !== 'both' && player.team_name !== teamFilter.value) return;
        if (playerFilter.value?.length && !playerFilter.value.includes(player.steamid)) return;
        if (weaponFilter.value && !checkWeaponFilter(player.active_weapon_name, weaponFilter.value)) return;

        hitboxes.push({ steamid: player.steamid, team: player.team_name, X: player.X, Y: player.Y, roundKey });

        // Hover focus: dim everyone outside the hovered player's round + team.
        const isHovered  = hov && hov.roundKey === roundKey && player.steamid === hov.steamid;
        const isTeammate = hov && !isHovered && hov.roundKey === roundKey && player.team_name === hov.team;
        const isDimmed   = hov && !isHovered && !isTeammate;

        const { x, y } = toGameCoords(player.X, player.Y);
        ctx.save();
        ctx.translate(x, y);
        if (isDimmed) ctx.globalAlpha = HOVER_DIM_ALPHA;

        // Weapon icon
        const weapon = getWeapon(player.active_weapon_name);
        if (weapon?.svg_path) {
          ctx.save();
          ctx.fillStyle = roundColor;
          ctx.scale(0.3, 0.3);
          ctx.translate(50, -35);
          ctx.fill(getPath2D(weapon.svg_path));
          ctx.restore();
        }

        // Compact name + round-tag pill
        _drawMultiRoundNameLabel(ctx, player.name, `R${roundObj.roundIndex}`, roundColor);

        // Direction arrow (rotated — isolated so the ring below stays upright)
        ctx.save();
        ctx.rotate((-player.yaw * Math.PI) / 180);
        ctx.shadowBlur  = 8;
        ctx.shadowColor = roundColor;
        ctx.fillStyle   = roundColor;
        ctx.fill(ARROW_PATH);
        ctx.restore();

        if (isHovered || isTeammate) _drawHighlightRing(ctx, isHovered, roundColor);

        ctx.restore();
      });
      ctx.restore();

      // ── Utility ────────────────────────────────────────────────────────────
      if (showUtil?.value !== false) {
        _drawMultiRoundUtil(
          ctx, roundData, roundKey, currentTickNo, roundColor,
          roundTeamLookup, smokeRadius, infernoRadius, explosionRadius, flashRadius
        );
      }
    });

    playerHitboxes.value = hitboxes;
  }

  // ─── Multiround utility renderer ──────────────────────────────────────────
  // Mirrors single-round logic but:
  //   • Per-round explosion state (multiRoundExplosions[roundKey])
  //   • Half-opacity on all visuals
  //   • Round colour dashed ring on smokes/infernos to identify the round
  //   • Player/team filter applied to grenade throwers

  function _grenadePassesFilter(throwerSteamid, roundTeamLookup) {
    if (teamFilter.value !== 'both') {
      const side = roundTeamLookup[throwerSteamid];
      if (side && side !== teamFilter.value) return false;
    }
    if (playerFilter.value?.length) {
      if (!playerFilter.value.includes(throwerSteamid)) return false;
    }
    return true;
  }

  function _normalizeGrenadeType(g) {
    switch (g.grenade_type) {
      case 'smoke': case 'CSmokeGrenadeProjectile': case 'CSmokeGrenade':
        g.grenade_type = 'smoke_grenade'; break;
      case 'CMolotovProjectile': case 'CMolotovGrenade': case 'CIncendiaryGrenade':
        g.grenade_type = 'molotov'; break;
      case 'CFlashbang': case 'CFlashbangProjectile':
        g.grenade_type = 'flashbang'; break;
      case 'CHEGrenade': case 'CHEGrenadeProjectile':
        g.grenade_type = 'he_grenade'; break;
    }
  }

  function _drawMultiRoundUtil(
    ctx, roundData, roundKey, currentTickNo, roundColor,
    roundTeamLookup, smokeRadius, infernoRadius, explosionRadius, flashRadius
  ) {
    if (!roundData) return;

    // ── Smokes ──────────────────────────────────────────────────────────────
    if (roundData.smokes?.length) {
      roundData.smokes.forEach((smoke) => {
        if (!_grenadePassesFilter(smoke.thrower_steamid, roundTeamLookup)) return;

        const ticksSince = currentTickNo - smoke.start_tick;
        if (ticksSince < 0 || ticksSince > SMOKE_LINGER_TICKS) return;

        const { x, y } = toGameCoords(smoke.X, smoke.Y);
        const EXPAND    = 30;
        let curR        = smokeRadius;
        if (ticksSince < EXPAND) curR *= 1 - Math.pow(1 - ticksSince / EXPAND, 3);

        const progress  = ticksSince / SMOKE_LINGER_TICKS;
        const baseAlpha = (progress > 0.7 ? 1 - (progress - 0.7) / 0.3 : 1) * 0.45;

        const seed  = (Math.round(smoke.X) * 7 + Math.round(smoke.Y) * 13) | 0;
        const drift = ticksSince * 0.018;

        ctx.save();
        ctx.translate(x, y);
        ctx.beginPath();
        ctx.arc(0, 0, curR * 1.05, 0, Math.PI * 2);
        ctx.clip();

        const baseGrad = ctx.createRadialGradient(0, 0, curR * 0.05, 0, 0, curR);
        baseGrad.addColorStop(0,   `rgba(170,170,170,${baseAlpha * 0.55})`);
        baseGrad.addColorStop(0.6, `rgba(150,150,150,${baseAlpha * 0.35})`);
        baseGrad.addColorStop(1,   `rgba(140,140,140,0)`);
        ctx.fillStyle = baseGrad;
        ctx.beginPath();
        ctx.arc(0, 0, curR, 0, Math.PI * 2);
        ctx.fill();

        for (let i = 0; i < 7; i++) {
          const angle  = _seededRand(seed, i) * Math.PI * 2 + drift * (0.4 + _seededRand(seed, i + 50) * 0.6);
          const dist   = _seededRand(seed, i + 20) * curR * 0.55;
          const bR     = curR * (0.38 + _seededRand(seed, i + 40) * 0.34);
          const bAlpha = baseAlpha * (0.28 + _seededRand(seed, i + 60) * 0.28);
          const bx     = Math.cos(angle) * dist;
          const by     = Math.sin(angle) * dist;
          ctx.save();
          ctx.translate(bx, by);
          const bg = ctx.createRadialGradient(0, 0, 0, 0, 0, bR);
          bg.addColorStop(0,   `rgba(190,190,190,${bAlpha})`);
          bg.addColorStop(0.5, `rgba(165,165,165,${bAlpha * 0.7})`);
          bg.addColorStop(1,   `rgba(140,140,140,0)`);
          ctx.fillStyle = bg;
          ctx.beginPath();
          ctx.arc(0, 0, bR, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
        ctx.restore();

        // Round-colour dashed ring to identify which round this belongs to
        ctx.save();
        ctx.strokeStyle = roundColor;
        ctx.lineWidth   = 2;
        ctx.globalAlpha = 0.7;
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.arc(x, y, curR * 0.95, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
        ctx.restore();
      });
    }

    // ── Infernos ─────────────────────────────────────────────────────────────
    if (roundData.infernos?.length) {
      roundData.infernos.forEach((inferno) => {
        if (!_grenadePassesFilter(inferno.thrower_steamid, roundTeamLookup)) return;
        if (currentTickNo < inferno.start_tick || currentTickNo > inferno.end_tick) return;

        const { x, y } = toGameCoords(inferno.X, inferno.Y);
        ctx.save();
        ctx.translate(x, y);
        ctx.globalAlpha = 0.55;

        const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, infernoRadius);
        grad.addColorStop(0,    'rgba(255,220,80,0.9)');
        grad.addColorStop(0.35, 'rgba(255,120,0,0.8)');
        grad.addColorStop(0.7,  'rgba(200,40,0,0.5)');
        grad.addColorStop(1,    'rgba(150,20,0,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(0, 0, infernoRadius, 0, Math.PI * 2);
        ctx.fill();

        ctx.globalAlpha = 0.65;
        ctx.strokeStyle = roundColor;
        ctx.lineWidth   = 2;
        ctx.setLineDash([5, 3]);
        ctx.beginPath();
        ctx.arc(0, 0, infernoRadius * 0.9, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
        ctx.restore();
      });
    }

    // ── Grenade projectiles + HE/flash/molotov explosions ────────────────────
    const grenades = roundData.grenades ?? {};
    if (!Object.keys(grenades).length) return;

    const state = _getMultiRoundExplosionState(roundKey);

    // Rewind when scrubbing backward
    if (currentTickNo < state.lastTick) {
      state.processed.clear();
      state.active = [];
    }
    state.lastTick = currentTickNo;

    for (const grenade of Object.values(grenades)) {
      _normalizeGrenadeType(grenade);
      const type = grenade.grenade_type;
      if (!['he_grenade', 'flashbang', 'molotov', 'incendiary_grenade', 'smoke_grenade'].includes(type)) continue;
      if (!_grenadePassesFilter(grenade.thrower_steamid, roundTeamLookup)) continue;

      const isSmoke   = type === 'smoke_grenade';
      const isFlash   = type === 'flashbang';
      const isMolotov = type === 'molotov' || type === 'incendiary_grenade';

      const detonTick = (isMolotov || isSmoke)
        ? grenade.tick
        : grenade.throwTick + (isFlash ? FLASH_ACTIVATION_TICKS : GRENADE_ACTIVATION_TICKS);

      if (currentTickNo < grenade.throwTick) continue;

      // In-flight trajectory
      if (!grenade.isEffectOnly && currentTickNo < detonTick && grenade.trajectory?.length) {
        _drawMultiRoundGrenadeInFlight(ctx, grenade, currentTickNo, roundColor);
      }

      // Register explosion (skip smoke — handled by smokes/infernos above)
      if (!isSmoke && !grenade.isEffectOnly) {
        if (currentTickNo >= detonTick && !state.processed.has(grenade.entity_id)) {
          state.processed.add(grenade.entity_id);
          const traj    = grenade.trajectory;
          const landPos = traj?.length ? traj[traj.length - 1] : grenade;
          state.active.push({
            entity_id: grenade.entity_id,
            type,
            startTick: detonTick,
            X: landPos.X,
            Y: landPos.Y,
          });
        }
      }
    }

    // Draw explosions for this round at reduced opacity
    for (let i = state.active.length - 1; i >= 0; i--) {
      const exp        = state.active[i];
      const ticksSince = currentTickNo - exp.startTick;
      const duration   = exp.type === 'he_grenade' ? 64
                       : exp.type === 'molotov' || exp.type === 'incendiary_grenade' ? 448
                       : 45;

      if (ticksSince > duration || ticksSince < 0) {
        state.active.splice(i, 1);
        if (ticksSince < 0) state.processed.delete(exp.entity_id);
        continue;
      }

      const { x, y } = toGameCoords(exp.X, exp.Y);
      ctx.save();
      ctx.globalAlpha = 0.55;
      _drawExplosion(ctx, exp, ticksSince, duration, x, y, currentTickNo, infernoRadius, explosionRadius, flashRadius);
      ctx.restore();
    }
  }

  // In-flight grenade for multiround — coloured by round, not by team
  function _drawMultiRoundGrenadeInFlight(ctx, grenade, currentTickNo, roundColor) {
    const traj = grenade.trajectory;
    if (!traj?.length) return;

    const totalTicks = grenade.tick - grenade.throwTick;
    const elapsed    = currentTickNo - grenade.throwTick;
    const progress   = totalTicks > 0 ? Math.min(1, elapsed / totalTicks) : 1;
    const currentIdx = Math.floor(progress * (traj.length - 1));
    const fadeStart  = Math.max(1, currentIdx - GRENADE_TRAJECTORY_FADE_TICKS);

    ctx.save();
    for (let ti = fadeStart; ti <= currentIdx; ti++) {
      const prev    = toGameCoords(traj[ti - 1].X, traj[ti - 1].Y);
      const curr    = toGameCoords(traj[ti].X,     traj[ti].Y);
      const opacity = (1 - (currentIdx - ti) / GRENADE_TRAJECTORY_FADE_TICKS) * 0.7;
      ctx.globalAlpha  = opacity;
      ctx.beginPath();
      ctx.moveTo(prev.x, prev.y);
      ctx.lineTo(curr.x, curr.y);
      ctx.strokeStyle  = roundColor;
      ctx.lineWidth    = 1.5;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.restore();

    const pt = traj[currentIdx];
    if (pt) {
      const { x, y } = toGameCoords(pt.X, pt.Y);
      ctx.save();
      ctx.globalAlpha = 0.85;
      ctx.fillStyle   = roundColor;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.restore();
    }
  }

  // ─── Player drawing ───────────────────────────────────────────────────────
  function _drawPlayers(ctx, players, hitboxes) {
    // Hover focus is only honoured while the hovered player is present + alive.
    const hov = hoveredPlayer?.value ?? null;
    const hovValid = hov && (hov.roundKey ?? null) === null &&
      players.some(p => p && p.health > 0 && p.steamid === hov.steamid);
    const effHov = hovValid ? hov : null;

    players.forEach((player) => {
      if (!player || player.health <= 0) return;
      const { x, y } = toGameCoords(player.X, player.Y);
      const teamColor = getTeamColor(player.team_name);

      if (hitboxes) {
        hitboxes.push({ steamid: player.steamid, team: player.team_name, X: player.X, Y: player.Y, roundKey: null });
      }

      const isHovered  = effHov && player.steamid === effHov.steamid;
      const isTeammate = effHov && !isHovered && player.team_name === effHov.team;
      const isDimmed   = effHov && !isHovered && !isTeammate;

      ctx.save();
      ctx.translate(x, y);
      if (isDimmed) ctx.globalAlpha = HOVER_DIM_ALPHA;

      const weapon = getWeapon(player.active_weapon_name);
      if (weapon?.svg_path) {
        ctx.save();
        ctx.fillStyle = teamColor;
        ctx.scale(0.3, 0.3);
        ctx.translate(50, -35);
        ctx.fill(getPath2D(weapon.svg_path));
        ctx.restore();
      }

      _drawNameLabel(ctx, player.name, teamColor);

      const iconImg = getIconImage(getPlayerIconUrl(player.team_name));
      if (iconImg.complete) {
        ctx.save();
        ctx.rotate((-player.yaw * Math.PI) / 180 - Math.PI / 2);
        const targetW = 26, ar = iconImg.naturalHeight / iconImg.naturalWidth;
        ctx.drawImage(iconImg, -targetW / 2, -(targetW * ar) / 2, targetW, targetW * ar);
        ctx.restore();
      }

      if (player.inventory?.includes('C4')) {
        const c4 = getWeapon('c4');
        if (c4?.svg_path) {
          ctx.save();
          ctx.fillStyle = '#cd6133';
          ctx.scale(0.25, 0.25);
          ctx.translate(-20, -20);
          ctx.fill(getPath2D(c4.svg_path));
          ctx.restore();
        }
      }

      if (isHovered || isTeammate) _drawHighlightRing(ctx, isHovered, teamColor);

      ctx.restore();
    });
  }

  // Compact rounded name pill — small and low-profile instead of a big slab.
  function _drawNameLabel(ctx, name, color) {
    ctx.save();
    ctx.font = PLAYER_LABEL_FONT;
    const nameW  = ctx.measureText(name).width;
    const padX   = 5, labelH = 15, labelY = -32;
    const boxW   = nameW + padX * 2;
    ctx.fillStyle = 'rgba(0,0,0,0.55)';
    ctx.beginPath();
    ctx.roundRect(-boxW / 2, labelY, boxW, labelH, 4);
    ctx.fill();
    ctx.fillStyle    = color;
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(name, 0, labelY + labelH / 2 + 0.5);
    ctx.restore();
  }

  // Compact name + round-tag pill for multiround compare.
  function _drawMultiRoundNameLabel(ctx, name, tag, roundColor) {
    ctx.save();
    ctx.font = PLAYER_LABEL_FONT;
    const nameW = ctx.measureText(name).width;
    ctx.font = PLAYER_LABEL_FONT_SMALL;
    const tagW  = ctx.measureText(tag).width;
    const gap = 5, padX = 5, labelH = 15, labelY = -33;
    const boxW = nameW + tagW + gap + padX * 2;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.beginPath();
    ctx.roundRect(-boxW / 2, labelY, boxW, labelH, 4);
    ctx.fill();
    const midY = labelY + labelH / 2 + 0.5;
    ctx.textBaseline = 'middle';
    ctx.textAlign    = 'left';
    ctx.font      = PLAYER_LABEL_FONT;
    ctx.fillStyle = '#ffffff';
    ctx.fillText(name, -boxW / 2 + padX, midY);
    ctx.font      = PLAYER_LABEL_FONT_SMALL;
    ctx.fillStyle = roundColor;
    ctx.fillText(tag, -boxW / 2 + padX + nameW + gap, midY);
    ctx.restore();
  }

  // Ring around the hovered player (strong, white) or its teammates (team tint).
  function _drawHighlightRing(ctx, strong, color) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(0, 0, strong ? 17 : 14, 0, Math.PI * 2);
    ctx.strokeStyle = strong ? '#ffffff' : color;
    ctx.lineWidth   = strong ? 2 : 1.5;
    ctx.globalAlpha = strong ? 0.95 : 0.7;
    ctx.stroke();
    ctx.restore();
  }

  // ─── Bullet tracers ───────────────────────────────────────────────────────
  function _drawBulletTracers(ctx, mapCanvas, currentTickNumber) {
    const pixelCache = getPixelCache();
    for (let i = 0; i < BULLET_FADE_TICKS && currentTickIndex.value - i >= 0; i++) {
      const tickData = getTickView(round.value, currentTickIndex.value - i);
      if (!tickData?.weapon_fires) continue;
      tickData.weapon_fires.forEach((wf) => {
        const { x, y }  = toGameCoords(wf.player_X, wf.player_Y);
        const teamColor  = getTeamColor(steamIdTeamLookup.value[wf.player_steamid] ?? 't');
        const angle      = (-wf.player_yaw * Math.PI) / 180;
        const cosA = Math.cos(angle), sinA = Math.sin(angle);
        const maxDist    = 2000;
        let finalDist    = maxDist;
        if (pixelCache) {
          for (let d = 15; d < maxDist; d += 2) {
            const px = Math.floor((x + d * cosA) * mapPosition.value.scale + mapPosition.value.x);
            const py = Math.floor((y + d * sinA) * mapPosition.value.scale + mapPosition.value.y);
            if (px >= 0 && px < mapCanvas.width && py >= 0 && py < mapCanvas.height) {
              const idx = (py * mapCanvas.width + px) * 4;
              if (pixelCache[idx] > 250 && pixelCache[idx + 1] > 250 && pixelCache[idx + 2] > 250) {
                finalDist = d; break;
              }
            }
          }
        }
        ctx.save();
        ctx.translate(x, y);
        ctx.strokeStyle = teamColor + convertFloatToHexOpacity(1 - i / BULLET_FADE_TICKS);
        ctx.lineWidth   = 1;
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(finalDist * cosA, finalDist * sinA);
        ctx.stroke();
        ctx.restore();
      });
    }
  }

  // ─── Bomb ─────────────────────────────────────────────────────────────────
  function _drawBomb(ctx, bomb) {
    if (!bomb) return;
    const { x, y } = toGameCoords(bomb.X, bomb.Y);
    const c4 = getWeapon('c4');
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(0.25, 0.25);
    ctx.translate(-20, -20);
    ctx.fillStyle = '#cd6133';
    if (c4?.svg_path) ctx.fill(getPath2D(c4.svg_path));
    ctx.restore();

    if (bomb.planted_ticks !== null) {
      const remaining  = (C4_DELAY_TICKS - bomb.planted_ticks) / SERVER_TICK_RATE;
      const percentage = remaining / 40;
      ctx.save();
      ctx.translate(x, y);
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fill(CIRCLE_PATH);
      ctx.beginPath();
      ctx.arc(0, 0, 10, -Math.PI / 2, -Math.PI / 2 + percentage * 2 * Math.PI, false);
      ctx.strokeStyle = 'rgba(255,255,255,0.4)';
      ctx.lineWidth   = 1.5;
      ctx.stroke();
      ctx.fillStyle    = 'rgba(255,255,255,1)';
      ctx.font         = BOMB_FONT;
      ctx.textAlign    = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(remaining.toFixed(1), 0, 0);
      ctx.restore();
    }
  }

  // ─── Explosions (single-round) ────────────────────────────────────────────
  function _updateAndDrawExplosions(ctx, currentTickNumber, infernoRadius, explosionRadius, flashRadius) {
    if (currentTickNumber === undefined) return;

    if (currentTickNumber < lastTickNumber.value) {
      processedExplosions.clear();
      activeExplosions.value = [];
    }
    lastTickNumber.value = currentTickNumber;

    for (const grenade of roundGrenades.value.values()) {
      switch (grenade.grenade_type) {
        case 'smoke': case 'CSmokeGrenadeProjectile': case 'CSmokeGrenade':
          grenade.grenade_type = 'smoke_grenade'; break;
        case 'CMolotovProjectile': case 'CMolotovGrenade': case 'CIncendiaryGrenade':
          grenade.grenade_type = 'molotov'; break;
        case 'CFlashbang': case 'CFlashbangProjectile':
          grenade.grenade_type = 'flashbang'; break;
        case 'CHEGrenade': case 'CHEGrenadeProjectile':
          grenade.grenade_type = 'he_grenade'; break;
        default: break;
      }

      const type = grenade.grenade_type;
      if (!['he_grenade', 'flashbang', 'molotov', 'incendiary_grenade', 'smoke_grenade'].includes(type)) continue;

      const isSmoke   = type === 'smoke_grenade';
      const isFlash   = type === 'flashbang';
      const isMolotov = type === 'molotov' || type === 'incendiary_grenade';

      const detonTick = (isMolotov || isSmoke)
        ? grenade.tick
        : grenade.throwTick + (isFlash ? FLASH_ACTIVATION_TICKS : GRENADE_ACTIVATION_TICKS);

      if (currentTickNumber < grenade.throwTick) continue;

      if (!grenade.isEffectOnly && currentTickNumber < detonTick && grenade.trajectory?.length) {
        _drawGrenadeInFlight(ctx, grenade, currentTickNumber);
      }

      if (!isSmoke && !grenade.isEffectOnly) {
        if (currentTickNumber >= detonTick && !processedExplosions.has(grenade.entity_id)) {
          processedExplosions.add(grenade.entity_id);
          const traj    = grenade.trajectory;
          const landPos = traj?.length ? traj[traj.length - 1] : grenade;
          activeExplosions.value.push({
            entity_id: grenade.entity_id,
            type,
            startTick: detonTick,
            X: landPos.X,
            Y: landPos.Y,
          });
        }
      }
    }

    for (let i = activeExplosions.value.length - 1; i >= 0; i--) {
      const exp        = activeExplosions.value[i];
      const ticksSince = currentTickNumber - exp.startTick;
      const duration   = exp.type === 'he_grenade' ? 64
                       : exp.type === 'molotov' || exp.type === 'incendiary_grenade' ? 448
                       : 45;

      if (ticksSince > duration || ticksSince < 0) {
        activeExplosions.value.splice(i, 1);
        if (ticksSince < 0) processedExplosions.delete(exp.entity_id);
        continue;
      }

      const { x, y } = toGameCoords(exp.X, exp.Y);
      _drawExplosion(ctx, exp, ticksSince, duration, x, y, currentTickNumber, infernoRadius, explosionRadius, flashRadius);
    }
  }

  function _drawGrenadeInFlight(ctx, grenade, currentTickNumber) {
    const traj = grenade.trajectory;
    if (!traj?.length) return;
    const totalTicks = grenade.tick - grenade.throwTick;
    const elapsed    = currentTickNumber - grenade.throwTick;
    const progress   = totalTicks > 0 ? Math.min(1, elapsed / totalTicks) : 1;
    const currentIdx = Math.floor(progress * (traj.length - 1));
    const throwerTeam = steamIdTeamLookup.value[grenade.thrower_steamid];

    const fadeStart = Math.max(1, currentIdx - GRENADE_TRAJECTORY_FADE_TICKS);
    ctx.save();
    for (let ti = fadeStart; ti <= currentIdx; ti++) {
      const prev    = toGameCoords(traj[ti - 1].X, traj[ti - 1].Y);
      const curr    = toGameCoords(traj[ti].X,     traj[ti].Y);
      const opacity = 1 - (currentIdx - ti) / GRENADE_TRAJECTORY_FADE_TICKS;
      ctx.beginPath();
      ctx.moveTo(prev.x, prev.y);
      ctx.lineTo(curr.x, curr.y);
      ctx.strokeStyle = getTeamColor(throwerTeam) + convertFloatToHexOpacity(opacity);
      ctx.lineWidth   = 1;
      ctx.stroke();
    }
    ctx.restore();

    const { x, y } = toGameCoords(traj[currentIdx].X, traj[currentIdx].Y);
    const weaponKey = grenade.grenade_type === 'he_grenade' ? 'he-grenade'
                    : grenade.grenade_type === 'smoke_grenade' ? 'smoke-grenade'
                    : grenade.grenade_type === 'flashbang'     ? 'flashbang'
                    : 'molotov';
    const w = getWeapon(weaponKey);
    if (w?.svg_path) {
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(0.3, 0.3);
      ctx.translate(-25, -25);
      ctx.fillStyle = getTeamColor(throwerTeam);
      ctx.fill(getPath2D(w.svg_path));
      ctx.restore();
    }
  }

  function _drawExplosion(ctx, exp, ticksSince, duration, x, y, currentTickNumber, infernoRadius, explosionRadius, flashRadius) {
    const progress = ticksSince / duration;
    const opacity  = progress > 0.8 ? 1 - (progress - 0.8) / 0.2 : 1;
    ctx.save();
    ctx.translate(x, y);

    if (exp.type === 'he_grenade') {
      const radius = Math.max(2, explosionRadius * (1 - Math.pow(1 - progress, 4)));
      ctx.shadowBlur  = 20 * (1 - progress);
      ctx.shadowColor = progress < 0.2 ? 'white' : 'rgba(255,100,0,1)';
      const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
      grad.addColorStop(0,   `rgba(255,255,255,${opacity})`);
      grad.addColorStop(0.2, `rgba(255,230,0,${opacity})`);
      grad.addColorStop(0.5, `rgba(255,100,0,${opacity * 0.7})`);
      grad.addColorStop(1,   `rgba(150,20,0,0)`);
      ctx.fillStyle = grad;
      for (let j = 0; j < 5; j++) {
        const angle = (j * Math.PI * 2) / 5;
        ctx.beginPath();
        ctx.arc(Math.cos(angle) * radius * 0.15, Math.sin(angle) * radius * 0.15, radius * 0.8, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (exp.type === 'molotov' || exp.type === 'incendiary_grenade') {
      const seed = exp.entity_id;
      ctx.shadowBlur  = 20;
      ctx.shadowColor = `rgba(200,30,0,${0.5 * opacity})`;
      for (let j = 0; j < 75; j++) {
        ctx.save();
        const angle     = (j * 137.5) * (Math.PI / 180);
        const dist      = Math.sqrt(Math.abs(Math.sin(seed + j))) * infernoRadius;
        const liftSpeed = 0.4 + Math.abs(Math.cos(j * seed)) * 0.6;
        const lift      = ((currentTickNumber + j * 7) % 45) * liftSpeed;
        const drift     = Math.sin(currentTickNumber * 0.05 + j) * 4;
        ctx.translate(Math.cos(angle) * dist + drift, Math.sin(angle) * dist - lift);
        const cr = Math.sin(seed * j + j);
        let pColor;
        if (cr > 0.95)      pColor = `rgba(255,200,50,${opacity})`;
        else if (cr > 0.6)  pColor = `rgba(255,120,0,${opacity})`;
        else if (cr < -0.4) pColor = `rgba(180,0,0,${opacity * 0.6})`;
        else                pColor = `rgba(255,60,0,${opacity * 0.8})`;
        const flicker = Math.sin(currentTickNumber * 0.15 + j) * 2;
        const pSize   = Math.max(1, (8 + flicker) * (1 - lift / 50));
        const grad    = ctx.createRadialGradient(0, 0, 0, 0, 0, pSize);
        grad.addColorStop(0, pColor);
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(0, 0, pSize, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    } else {
      // Flashbang
      const radius = Math.max(2, flashRadius * (1 - Math.pow(1 - progress, 3)));
      ctx.shadowBlur  = 35 * opacity;
      ctx.shadowColor = 'white';
      const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
      grad.addColorStop(0, `rgba(255,255,255,${opacity})`);
      grad.addColorStop(1, `rgba(255,255,255,0)`);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  // ─── Seeded RNG for stable smoke blob positions ────────────────────────────
  function _seededRand(seed, n) {
    let h = (seed ^ (n * 2654435761)) >>> 0;
    h = Math.imul(h ^ (h >>> 16), 0x45d9f3b) >>> 0;
    h = Math.imul(h ^ (h >>> 16), 0x45d9f3b) >>> 0;
    return (h >>> 0) / 0xffffffff;
  }

  // ─── Smokes (single-round) ────────────────────────────────────────────────
  function _drawSmokes(ctx, currentTickNumber, smokeRadius) {
    if (!round.value?.smokes?.length) return;
    round.value.smokes.forEach((smoke) => {
      const ticksSince = currentTickNumber - smoke.start_tick;
      if (ticksSince < 0 || ticksSince > SMOKE_LINGER_TICKS) return;

      const { x, y } = toGameCoords(smoke.X, smoke.Y);
      const hex = getTeamColor(steamIdTeamLookup.value[smoke.thrower_steamid]) || '#808080';
      const r   = parseInt(hex.slice(1, 3), 16);
      const g   = parseInt(hex.slice(3, 5), 16);
      const b   = parseInt(hex.slice(5, 7), 16);
      const tR  = Math.floor((r + 160) / 2);
      const tG  = Math.floor((g + 160) / 2);
      const tB  = Math.floor((b + 160) / 2);

      const EXPAND = 30;
      let curR = smokeRadius;
      if (ticksSince < EXPAND) curR *= 1 - Math.pow(1 - ticksSince / EXPAND, 3);

      const progress  = ticksSince / SMOKE_LINGER_TICKS;
      const baseAlpha = progress > 0.7 ? 0.72 * (1 - (progress - 0.7) / 0.3) : 0.72;
      const seed      = (Math.round(smoke.X) * 7 + Math.round(smoke.Y) * 13) | 0;
      const drift     = ticksSince * 0.018;

      ctx.save();
      ctx.translate(x, y);
      ctx.beginPath();
      ctx.arc(0, 0, curR * 1.05, 0, Math.PI * 2);
      ctx.clip();

      const baseGrad = ctx.createRadialGradient(0, 0, curR * 0.05, 0, 0, curR);
      baseGrad.addColorStop(0,   `rgba(${tR - 15},${tG - 15},${tB - 15},${baseAlpha * 0.55})`);
      baseGrad.addColorStop(0.6, `rgba(${tR - 10},${tG - 10},${tB - 10},${baseAlpha * 0.35})`);
      baseGrad.addColorStop(1,   `rgba(${tR},${tG},${tB},0)`);
      ctx.fillStyle = baseGrad;
      ctx.beginPath();
      ctx.arc(0, 0, curR, 0, Math.PI * 2);
      ctx.fill();

      for (let i = 0; i < 9; i++) {
        const angle  = _seededRand(seed, i) * Math.PI * 2 + drift * (0.4 + _seededRand(seed, i + 50) * 0.6);
        const dist   = _seededRand(seed, i + 20) * curR * 0.55;
        const bR     = curR * (0.38 + _seededRand(seed, i + 40) * 0.34);
        const bAlpha = baseAlpha * (0.28 + _seededRand(seed, i + 60) * 0.28);
        const bxOff  = Math.cos(angle) * dist;
        const byOff  = Math.sin(angle) * dist;
        const scaleY = 0.72 + _seededRand(seed, i + 80) * 0.36;
        ctx.save();
        ctx.translate(bxOff, byOff);
        ctx.scale(1, scaleY);
        const bg = ctx.createRadialGradient(0, 0, 0, 0, 0, bR);
        bg.addColorStop(0,    `rgba(${tR + 18},${tG + 18},${tB + 18},${bAlpha})`);
        bg.addColorStop(0.45, `rgba(${tR +  8},${tG +  8},${tB +  8},${bAlpha * 0.75})`);
        bg.addColorStop(0.8,  `rgba(${tR},${tG},${tB},${bAlpha * 0.3})`);
        bg.addColorStop(1,    `rgba(${tR},${tG},${tB},0)`);
        ctx.fillStyle = bg;
        ctx.beginPath();
        ctx.arc(0, 0, bR, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      const hlGrad = ctx.createRadialGradient(-curR * 0.12, -curR * 0.15, 0, 0, 0, curR * 0.55);
      hlGrad.addColorStop(0,   `rgba(255,255,255,${baseAlpha * 0.22})`);
      hlGrad.addColorStop(0.5, `rgba(255,255,255,${baseAlpha * 0.06})`);
      hlGrad.addColorStop(1,   `rgba(255,255,255,0)`);
      ctx.fillStyle = hlGrad;
      ctx.beginPath();
      ctx.arc(0, 0, curR * 0.7, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore();
    });
  }

  // ─── Infernos (single-round) ──────────────────────────────────────────────
  function _drawInfernos(ctx, currentTickNumber, infernoRadius) {
    if (!round.value?.infernos?.length) return;
    round.value.infernos.forEach((inferno) => {
      if (currentTickNumber < inferno.start_tick || currentTickNumber > inferno.end_tick) return;
      const { x, y } = toGameCoords(inferno.X, inferno.Y);
      ctx.save();
      ctx.translate(x, y);
      const numParticles = 8;
      for (let j = 0; j < numParticles; j++) {
        const startAngle = ((j / numParticles) * Math.PI * 2) + currentTickNumber * 0.01;
        const endAngle   = startAngle + (Math.PI * 2) / numParticles * 0.8;
        ctx.beginPath();
        ctx.arc(0, 0, infernoRadius, startAngle, endAngle, false);
        ctx.strokeStyle = '#ff4400cc';
        ctx.lineWidth   = 1.5;
        ctx.stroke();
      }
      ctx.restore();
    });
  }

  return {
    render,
    cancelRender,
    renderSingleRound,
    renderMultiRound,
    roundGrenades,
    activeExplosions,
    getTeamColor,
    clearMultiRoundState,
    playerHitboxes,
  };
}