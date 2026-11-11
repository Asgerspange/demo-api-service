// Framework-free canvas renderer — de-Vue'd from Demo/2D/composables/useRenderer.js.
//
// The UTILITY rendering (smokes, infernos, HE/molotov/flash explosions, grenade-in-flight
// trajectories) is ported VERBATIM from the Vue renderer's single-round path so it looks
// pixel-identical. Everything else (team colors, marker SVGs, weapon icons, HUD, name labels,
// sizes, toggles) is driven by the theme so each tenant can fully restyle the viewer.
//
// Draws in radar-image pixel space under a view transform (fit + pan/zoom), DPR-aware.

import { makeWorldToImage, worldLenToImage } from './scales.js';
import {
  SMOKE_RADIUS, INFERNO_RADIUS, GRENADE_EXPLOSION_RADIUS, FLASH_RADIUS,
  GRENADE_ACTIVATION_TICKS, FLASH_ACTIVATION_TICKS, BULLET_FADE_TICKS,
  GRENADE_TRAJECTORY_FADE_TICKS, SMOKE_LINGER_TICKS, C4_DELAY_TICKS, SERVER_TICK_RATE,
  RADAR_SIZE, WEAPON_FILE, GRENADE_FILE,
} from './constants.js';

const _imgCache = {};
function loadImage(url) {
  if (!_imgCache[url]) {
    const im = new Image();
    im.crossOrigin = 'anonymous';
    im.src = url;
    _imgCache[url] = im;
  }
  return _imgCache[url];
}

// 0..1 → 2-digit hex alpha (port of helpers.convertFloatToHexOpacity).
function hexOpacity(o) {
  return Math.round(Math.max(0, Math.min(1, o)) * 255).toString(16).padStart(2, '0');
}

export class Renderer {
  constructor(canvas, theme) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.theme = theme;
    this.image = null;
    this.mapRef = null;
    this.round = null;
    this.toImg = makeWorldToImage(null);
    this.view = { scale: 1, x: 0, y: 0 };
    this._userZoomed = false;
    this._resetUtilState();
  }

  // Team color from the (themeable) palette.
  _tc(team) { return team === 'ct' ? this.theme.ctColor : team === 't' ? this.theme.tColor : '#808080'; }

  _resetUtilState() {
    this.activeExplosions = [];
    this.processedExplosions = new Set();
    this.lastTickNumber = 0;
    this._teamBySteam = {};
  }

  setTheme(theme) { this.theme = theme; }
  setFollow(steamid) { this._follow = steamid || null; }   // highlight a followed player (§17.1)
  setMap(image, mapRef) {
    this.image = image; this.mapRef = mapRef; this.toImg = makeWorldToImage(mapRef);
    this._userZoomed = false; this.resize();
  }

  setRound(round) {
    this.round = round;
    this._resetUtilState();
    if (round?.players?.count) {
      const { steamids, teams, count } = round.players;
      for (let s = 0; s < count; s++) this._teamBySteam[steamids[s]] = teams[s] === 0 ? 'ct' : 't';
    }
  }

  resize() {
    const dpr = self.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(rect.width)), h = Math.max(1, Math.round(rect.height));
    this.canvas.width = w * dpr; this.canvas.height = h * dpr;
    this._cssW = w; this._cssH = h; this._dpr = dpr;
    if (!this._userZoomed) this.fit();
  }

  fit() {
    if (!this.image) return;
    // Fit the fixed RADAR_SIZE×RADAR_SIZE calibration box (NOT the image's intrinsic size — an SVG
    // can report 0/non-square, which would mis-center the radar and leave it half off the edge).
    const iw = RADAR_SIZE, ih = RADAR_SIZE;
    const scale = Math.min(this._cssW / iw, this._cssH / ih);
    this.view = { scale, x: (this._cssW - iw * scale) / 2, y: (this._cssH - ih * scale) / 2 };
  }

  zoomAt(cssX, cssY, factor) {
    const s = Math.min(8, Math.max(0.05, this.view.scale * factor)), k = s / this.view.scale;
    this.view = { scale: s, x: cssX - (cssX - this.view.x) * k, y: cssY - (cssY - this.view.y) * k };
    this._userZoomed = true;
  }
  pan(dx, dy) { this.view = { scale: this.view.scale, x: this.view.x + dx, y: this.view.y + dy }; this._userZoomed = true; }
  resetView() { this._userZoomed = false; this.fit(); }

  _applyTransform() {
    const d = this._dpr, v = this.view;
    this.ctx.setTransform(d * v.scale, 0, 0, d * v.scale, d * v.x, d * v.y);
  }

  // Vue renderSingleRound draw order: players → tracers → bomb → explosions → smokes.
  draw(tickIndex) {
    const ctx = this.ctx, t = this.theme;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = t.background;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    if (!this.image || !this.round) return;

    this._applyTransform();
    ctx.imageSmoothingEnabled = true;
    ctx.globalAlpha = t.radarOpacity;
    // Draw the radar at the fixed calibration size so it exactly aligns with the player overlay
    // (which lives in RADAR_SIZE px space), regardless of the SVG/PNG's own intrinsic dimensions.
    ctx.drawImage(this.image, 0, 0, RADAR_SIZE, RADAR_SIZE);
    ctx.globalAlpha = 1;

    const scale = this.mapRef.scale || 1;
    const tickNum = this.round.tickNumbers[tickIndex];
    this._drawPlayers(tickIndex);
    if (t.showWeaponFire) this._drawBulletTracers(tickIndex);
    this._drawBomb(tickIndex);
    if (t.showGrenades) this._updateAndDrawExplosions(tickNum, INFERNO_RADIUS / scale, GRENADE_EXPLOSION_RADIUS / scale, FLASH_RADIUS / scale);
    if (t.showSmokes) this._drawSmokes(tickNum, SMOKE_RADIUS / scale);
    // The scoreboard is a crisp DOM overlay managed by the viewer (see Viewer._updateScoreboard).
  }

  // ─── Explosions (single-round) — ported verbatim ───────────────────────────
  _updateAndDrawExplosions(currentTickNumber, infernoRadius, explosionRadius, flashRadius) {
    if (currentTickNumber === undefined) return;

    if (currentTickNumber < this.lastTickNumber) {
      this.processedExplosions.clear();
      this.activeExplosions = [];
    }
    this.lastTickNumber = currentTickNumber;

    for (const grenade of Object.values(this.round.grenades || {})) {
      let type = grenade.grenade_type;
      if (type === 'smoke') type = 'smoke_grenade';
      if (!['he_grenade', 'flashbang', 'molotov', 'incendiary_grenade', 'smoke_grenade'].includes(type)) continue;

      const isSmoke = type === 'smoke_grenade';
      const isFlash = type === 'flashbang';
      const isMolotov = type === 'molotov' || type === 'incendiary_grenade';

      const detonTick = (isMolotov || isSmoke)
        ? grenade.tick
        : grenade.throwTick + (isFlash ? FLASH_ACTIVATION_TICKS : GRENADE_ACTIVATION_TICKS);

      if (currentTickNumber < grenade.throwTick) continue;

      if (!grenade.isEffectOnly && currentTickNumber < detonTick && grenade.trajectory?.length) {
        this._drawGrenadeInFlight(grenade, currentTickNumber);
      }

      if (!isSmoke && !grenade.isEffectOnly) {
        if (currentTickNumber >= detonTick && !this.processedExplosions.has(grenade.entity_id)) {
          this.processedExplosions.add(grenade.entity_id);
          const traj = grenade.trajectory;
          const landPos = traj?.length ? traj[traj.length - 1] : grenade;
          this.activeExplosions.push({ entity_id: grenade.entity_id, type, startTick: detonTick, X: landPos.X, Y: landPos.Y });
        }
      }
    }

    for (let i = this.activeExplosions.length - 1; i >= 0; i--) {
      const exp = this.activeExplosions[i];
      const ticksSince = currentTickNumber - exp.startTick;
      const duration = exp.type === 'he_grenade' ? 64
        : (exp.type === 'molotov' || exp.type === 'incendiary_grenade') ? 448 : 45;
      if (ticksSince > duration || ticksSince < 0) {
        this.activeExplosions.splice(i, 1);
        if (ticksSince < 0) this.processedExplosions.delete(exp.entity_id);
        continue;
      }
      const { x, y } = this.toImg(exp.X, exp.Y);
      this._drawExplosion(exp, ticksSince, duration, x, y, currentTickNumber, infernoRadius, explosionRadius, flashRadius);
    }
  }

  _drawGrenadeInFlight(grenade, currentTickNumber) {
    const ctx = this.ctx;
    const traj = grenade.trajectory;
    if (!traj?.length) return;
    const totalTicks = grenade.tick - grenade.throwTick;
    const elapsed = currentTickNumber - grenade.throwTick;
    const progress = totalTicks > 0 ? Math.min(1, elapsed / totalTicks) : 1;
    const currentIdx = Math.floor(progress * (traj.length - 1));
    const throwerTeam = this._teamBySteam[grenade.thrower_steamid];

    const fadeStart = Math.max(1, currentIdx - GRENADE_TRAJECTORY_FADE_TICKS);
    ctx.save();
    for (let ti = fadeStart; ti <= currentIdx; ti++) {
      const prev = this.toImg(traj[ti - 1].X, traj[ti - 1].Y);
      const curr = this.toImg(traj[ti].X, traj[ti].Y);
      const opacity = 1 - (currentIdx - ti) / GRENADE_TRAJECTORY_FADE_TICKS;
      ctx.beginPath();
      ctx.moveTo(prev.x, prev.y);
      ctx.lineTo(curr.x, curr.y);
      ctx.strokeStyle = this._tc(throwerTeam) + hexOpacity(opacity);
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();

    const { x, y } = this.toImg(traj[currentIdx].X, traj[currentIdx].Y);
    const file = GRENADE_FILE[grenade.grenade_type === 'smoke_grenade' ? 'smoke' : grenade.grenade_type];
    const icon = file && loadImage(`${this.theme.assetBase}/weapons/${file}.svg`);
    if (icon && icon.complete && icon.naturalWidth) {
      const w = 15, ar = icon.naturalHeight / icon.naturalWidth;
      ctx.drawImage(icon, x - w / 2, y - (w * ar) / 2, w, w * ar);
    } else {
      ctx.fillStyle = this._tc(throwerTeam);
      ctx.beginPath(); ctx.arc(x, y, 3.5, 0, Math.PI * 2); ctx.fill();
    }
  }

  _drawExplosion(exp, ticksSince, duration, x, y, currentTickNumber, infernoRadius, explosionRadius, flashRadius) {
    const ctx = this.ctx;
    const progress = ticksSince / duration;
    const opacity = progress > 0.8 ? 1 - (progress - 0.8) / 0.2 : 1;
    ctx.save();
    ctx.translate(x, y);

    if (exp.type === 'he_grenade') {
      const radius = Math.max(2, explosionRadius * (1 - Math.pow(1 - progress, 4)));
      ctx.shadowBlur = 20 * (1 - progress);
      ctx.shadowColor = progress < 0.2 ? 'white' : 'rgba(255,100,0,1)';
      const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
      grad.addColorStop(0, `rgba(255,255,255,${opacity})`);
      grad.addColorStop(0.2, `rgba(255,230,0,${opacity})`);
      grad.addColorStop(0.5, `rgba(255,100,0,${opacity * 0.7})`);
      grad.addColorStop(1, `rgba(150,20,0,0)`);
      ctx.fillStyle = grad;
      for (let j = 0; j < 5; j++) {
        const angle = (j * Math.PI * 2) / 5;
        ctx.beginPath();
        ctx.arc(Math.cos(angle) * radius * 0.15, Math.sin(angle) * radius * 0.15, radius * 0.8, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (exp.type === 'molotov' || exp.type === 'incendiary_grenade') {
      const seed = Number(exp.entity_id) || 0;
      ctx.shadowBlur = 20;
      ctx.shadowColor = `rgba(200,30,0,${0.5 * opacity})`;
      for (let j = 0; j < 75; j++) {
        ctx.save();
        const angle = (j * 137.5) * (Math.PI / 180);
        const dist = Math.sqrt(Math.abs(Math.sin(seed + j))) * infernoRadius;
        const liftSpeed = 0.4 + Math.abs(Math.cos(j * seed)) * 0.6;
        const lift = ((currentTickNumber + j * 7) % 45) * liftSpeed;
        const drift = Math.sin(currentTickNumber * 0.05 + j) * 4;
        ctx.translate(Math.cos(angle) * dist + drift, Math.sin(angle) * dist - lift);
        const cr = Math.sin(seed * j + j);
        let pColor;
        if (cr > 0.95) pColor = `rgba(255,200,50,${opacity})`;
        else if (cr > 0.6) pColor = `rgba(255,120,0,${opacity})`;
        else if (cr < -0.4) pColor = `rgba(180,0,0,${opacity * 0.6})`;
        else pColor = `rgba(255,60,0,${opacity * 0.8})`;
        const flicker = Math.sin(currentTickNumber * 0.15 + j) * 2;
        const pSize = Math.max(1, (8 + flicker) * (1 - lift / 50));
        const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, pSize);
        grad.addColorStop(0, pColor);
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(0, 0, pSize, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    } else {
      const radius = Math.max(2, flashRadius * (1 - Math.pow(1 - progress, 3)));
      ctx.shadowBlur = 35 * opacity;
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

  _seededRand(seed, n) {
    let h = (seed ^ (n * 2654435761)) >>> 0;
    h = Math.imul(h ^ (h >>> 16), 0x45d9f3b) >>> 0;
    h = Math.imul(h ^ (h >>> 16), 0x45d9f3b) >>> 0;
    return (h >>> 0) / 0xffffffff;
  }

  // ─── Smokes (single-round) — ported verbatim (team-tinted) ──────────────────
  _drawSmokes(currentTickNumber, smokeRadius) {
    const ctx = this.ctx;
    if (!this.round?.smokes?.length) return;
    this.round.smokes.forEach((smoke) => {
      const ticksSince = currentTickNumber - Number(smoke.start_tick);
      if (ticksSince < 0 || ticksSince > SMOKE_LINGER_TICKS) return;

      const { x, y } = this.toImg(smoke.X, smoke.Y);
      const hex = this._tc(this._teamBySteam[smoke.thrower_steamid]) || '#808080';
      const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
      const tR = Math.floor((r + 160) / 2), tG = Math.floor((g + 160) / 2), tB = Math.floor((b + 160) / 2);

      const EXPAND = 30;
      let curR = smokeRadius;
      if (ticksSince < EXPAND) curR *= 1 - Math.pow(1 - ticksSince / EXPAND, 3);

      const progress = ticksSince / SMOKE_LINGER_TICKS;
      const baseAlpha = progress > 0.7 ? 0.72 * (1 - (progress - 0.7) / 0.3) : 0.72;
      const seed = (Math.round(smoke.X) * 7 + Math.round(smoke.Y) * 13) | 0;
      const drift = ticksSince * 0.018;

      ctx.save();
      ctx.translate(x, y);
      ctx.beginPath();
      ctx.arc(0, 0, curR * 1.05, 0, Math.PI * 2);
      ctx.clip();

      const baseGrad = ctx.createRadialGradient(0, 0, curR * 0.05, 0, 0, curR);
      baseGrad.addColorStop(0, `rgba(${tR - 15},${tG - 15},${tB - 15},${baseAlpha * 0.55})`);
      baseGrad.addColorStop(0.6, `rgba(${tR - 10},${tG - 10},${tB - 10},${baseAlpha * 0.35})`);
      baseGrad.addColorStop(1, `rgba(${tR},${tG},${tB},0)`);
      ctx.fillStyle = baseGrad;
      ctx.beginPath();
      ctx.arc(0, 0, curR, 0, Math.PI * 2);
      ctx.fill();

      for (let i = 0; i < 9; i++) {
        const angle = this._seededRand(seed, i) * Math.PI * 2 + drift * (0.4 + this._seededRand(seed, i + 50) * 0.6);
        const dist = this._seededRand(seed, i + 20) * curR * 0.55;
        const bR = curR * (0.38 + this._seededRand(seed, i + 40) * 0.34);
        const bAlpha = baseAlpha * (0.28 + this._seededRand(seed, i + 60) * 0.28);
        const bxOff = Math.cos(angle) * dist, byOff = Math.sin(angle) * dist;
        const scaleY = 0.72 + this._seededRand(seed, i + 80) * 0.36;
        ctx.save();
        ctx.translate(bxOff, byOff);
        ctx.scale(1, scaleY);
        const bg = ctx.createRadialGradient(0, 0, 0, 0, 0, bR);
        bg.addColorStop(0, `rgba(${tR + 18},${tG + 18},${tB + 18},${bAlpha})`);
        bg.addColorStop(0.45, `rgba(${tR + 8},${tG + 8},${tB + 8},${bAlpha * 0.75})`);
        bg.addColorStop(0.8, `rgba(${tR},${tG},${tB},${bAlpha * 0.3})`);
        bg.addColorStop(1, `rgba(${tR},${tG},${tB},0)`);
        ctx.fillStyle = bg;
        ctx.beginPath();
        ctx.arc(0, 0, bR, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      const hlGrad = ctx.createRadialGradient(-curR * 0.12, -curR * 0.15, 0, 0, 0, curR * 0.55);
      hlGrad.addColorStop(0, `rgba(255,255,255,${baseAlpha * 0.22})`);
      hlGrad.addColorStop(0.5, `rgba(255,255,255,${baseAlpha * 0.06})`);
      hlGrad.addColorStop(1, `rgba(255,255,255,0)`);
      ctx.fillStyle = hlGrad;
      ctx.beginPath();
      ctx.arc(0, 0, curR * 0.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });
  }

  // ─── Bullet tracers ──────────────────────────────────────────────────────────
  _drawBulletTracers(tickIndex) {
    const wf = this.round.weaponFires;
    if (!wf || !wf.tickIndex.length) return;
    const ctx = this.ctx, teams = this.round.players.teams, P = this.round.players.count;
    for (let i = 0; i < wf.tickIndex.length; i++) {
      const dt = tickIndex - wf.tickIndex[i];
      if (dt < 0 || dt >= BULLET_FADE_TICKS) continue;
      const { x, y } = this.toImg(wf.X[i], wf.Y[i]);
      const slot = wf.playerIdx[i];
      const team = slot < P ? (teams[tickIndex * P + slot] === 0 ? 'ct' : 't') : 't';
      const color = this.theme.tracerFromTeam ? this._tc(team) : this.theme.accent;
      const angle = (-wf.yaw[i] * Math.PI) / 180;
      const len = worldLenToImage(this.mapRef, 2000);
      ctx.save();
      ctx.translate(x, y);
      ctx.strokeStyle = color + hexOpacity(1 - dt / BULLET_FADE_TICKS);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(Math.cos(angle) * len, Math.sin(angle) * len);
      ctx.stroke();
      ctx.restore();
    }
  }

  _drawBomb(tickIndex) {
    const b = this.round.bomb;
    if (!b || !b.tickIndex.length) return;
    let k = -1;
    for (let i = 0; i < b.tickIndex.length; i++) { if (b.tickIndex[i] <= tickIndex) k = i; else break; }
    if (k < 0) return;
    const { x, y } = this.toImg(b.X[k], b.Y[k]);
    const ctx = this.ctx;
    const icon = loadImage(`${this.theme.assetBase}/weapons/bomb.svg`);
    if (icon.complete && icon.naturalWidth) {
      const w = 14, ar = icon.naturalHeight / icon.naturalWidth;
      ctx.drawImage(icon, x - w / 2, y - (w * ar) / 2, w, w * ar);
    } else {
      ctx.fillStyle = this.theme.bombColor;
      ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
    }
    const planted = b.plantedTicks[k];
    if (planted >= 0) {
      const pct = (C4_DELAY_TICKS - planted) / SERVER_TICK_RATE / 40;
      ctx.save();
      ctx.translate(x, y);
      ctx.beginPath();
      ctx.arc(0, 0, 10, -Math.PI / 2, -Math.PI / 2 + pct * 2 * Math.PI, false);
      ctx.strokeStyle = this.theme.bombColor;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.restore();
    }
  }

  // ─── Players ──────────────────────────────────────────────────────────────────
  _drawPlayers(tickIndex) {
    const ctx = this.ctx, t = this.theme, pl = this.round.players;
    const P = pl.count, base = tickIndex * P;
    for (let s = 0; s < P; s++) {
      const i = base + s;
      if (pl.health[i] <= 0) continue;
      const { x, y } = this.toImg(pl.X[i], pl.Y[i]);
      const team = pl.teams[i] === 0 ? 'ct' : 't';
      const teamColor = this._tc(team);

      ctx.save();
      ctx.translate(x, y);

      if (t.showWeapons) {
        const wfile = WEAPON_FILE[pl.weapons[pl.weaponIndex[i]]];
        if (wfile) {
          const wi = loadImage(`${t.assetBase}/weapons/${wfile}.svg`);
          if (wi.complete && wi.naturalWidth) {
            const w = t.weaponIconSize, ar = wi.naturalHeight / wi.naturalWidth;
            ctx.drawImage(wi, w * 0.5, -w - 2, w, w * ar);
          }
        }
      }
      if (t.showNames) this._nameLabel(pl.names[s] || '', t.nameColor === 'team' ? teamColor : t.nameColor);

      const icon = loadImage(team === 'ct' ? t.ctIconUrl : t.tIconUrl);
      if (icon.complete && icon.naturalWidth) {
        ctx.save();
        ctx.rotate((-pl.yaw[i] * Math.PI) / 180 - Math.PI / 2);
        const w = t.playerIconSize, ar = icon.naturalHeight / icon.naturalWidth;
        ctx.drawImage(icon, -w / 2, -(w * ar) / 2, w, w * ar);
        ctx.restore();
      } else {
        ctx.fillStyle = teamColor;
        ctx.beginPath(); ctx.arc(0, 0, 7, 0, Math.PI * 2); ctx.fill();
      }

      if (pl.flashDuration[i] > 0.5) {
        ctx.fillStyle = `rgba(255,255,255,${Math.min(0.75, pl.flashDuration[i] / 5)})`;
        ctx.beginPath(); ctx.arc(0, 0, t.playerIconSize * 0.45, 0, Math.PI * 2); ctx.fill();
      }
      if (pl.inventoryMask[i] & 1) {
        ctx.strokeStyle = t.bombColor; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(0, 0, t.playerIconSize * 0.55, 0, Math.PI * 2); ctx.stroke();
      }
      if (this._follow && pl.steamids[s] === this._follow) {   // followed player highlight (§17.1)
        ctx.strokeStyle = t.followColor || '#ffd54f'; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.arc(0, 0, t.playerIconSize * 0.72, 0, Math.PI * 2); ctx.stroke();
      }
      ctx.restore();
    }
  }

  _nameLabel(name, color) {
    const ctx = this.ctx, t = this.theme;
    ctx.save();
    ctx.font = `600 ${t.nameFontSize}px system-ui, sans-serif`;
    const w = ctx.measureText(name).width, padX = 5, h = t.nameFontSize + 4, y = -(t.playerIconSize * 0.5 + h + 2);
    const boxW = w + padX * 2;
    ctx.fillStyle = t.nameBg;
    if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(-boxW / 2, y, boxW, h, 4); ctx.fill(); }
    else ctx.fillRect(-boxW / 2, y, boxW, h);
    ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(name, 0, y + h / 2 + 0.5);
    ctx.restore();
  }
}
