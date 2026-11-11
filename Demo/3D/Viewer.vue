<template>
  <Head :title="`3D Demo Viewer - CsStrats`" />
  <div class="cs2-viewer" ref="viewerContainer">
    <Transition name="fade">
      <div 
        class="cs2-loading" 
        v-if="isLoading" 
        :style="{ backgroundImage: `url('/threed/maps/images/${demoMap}_loading.png')` }"
      >
        <div class="loading-overlay"></div>
        <div class="loading-content justify-items-center">
          <img class="map-emblem" :src="`/threed/maps/images/${demoMap}_emblem.webp`" onerror="this.style.display='none'" />
          <div class="loading-text">
            <div class="map-name">{{ name }}</div>
            <div class="map-sub">{{ demoMap }}</div>
          </div>
          <div class="loading-bar-track">
            <div class="loading-bar-fill" :style="{ width: loadingProgress + '%' }"></div>
          </div>
          <div class="loading-status">{{ loadingStatus }}</div>
        </div>
      </div>
    </Transition>

    <div v-show="!isLoading" class="hud-layer">
      <div class="top-hud">
        <div class="team-avatars ct-side">
          <div
            v-for="p in uiState.ctPlayers"
            :key="p.name"
            class="avatar-slot"
            :class="{ dead: p.health <= 0, active: spectatingId === p.name }"
            @click.stop="startSpectating(p.name)"
          >
            <img :src="getPlayerImage(p)" v-if="p.health > 0" />
            <span v-else class="skull">💀</span>
            <div class="hp-bar-mini">
              <div class="fill" :style="{ width: p.health + '%' }"></div>
            </div>
          </div>
        </div>
        
        <div class="crosshair" v-if="spectatingId && !isFreeCam"></div>
        
        <div class="score-panel">
          <div class="score ct">{{ uiState.ctScore }}</div>
          <div class="timer" :class="{ 'red-text': isFreezeTime }">
            {{ formattedRoundTime }}
            <div class="round-num">Round {{ uiState.round }}</div>
          </div>
          <div class="score t">{{ uiState.tScore }}</div>
        </div>

        <div class="team-avatars t-side">
          <div
            v-for="p in uiState.tPlayers"
            :key="p.name"
            class="avatar-slot"
            :class="{ dead: p.health <= 0, active: spectatingId === p.name }"
            @click.stop="startSpectating(p.name)"
          >
            <img :src="getPlayerImage(p)" v-if="p.health > 0" />
            <span v-else class="skull">💀</span>
            <div class="hp-bar-mini">
              <div class="fill t-fill" :style="{ width: p.health + '%' }"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="radar-hud">
        <div class="radar-container">
          <img :src="'/images/demo/' + demoMap + '.svg'" class="radar-img" onerror="this.style.display='none'" />
          <canvas ref="radarCanvas" width="400" height="400"></canvas>
        </div>
      </div>

      <div class="spectator-card" v-if="spectatingId">
        <div class="spec-left">
          <div class="health-large"><span class="icon">✚</span> {{ getSpectatingPlayer()?.health || 0 }}</div>
          <div class="armor-large"><span class="icon">🛡️</span></div>
        </div>

        <div class="spec-center">
          <div class="spec-name">{{ spectatingId }}</div>
          <div class="spec-team-bar" :class="getSpectatingPlayer()?.team === 2 ? 't-bg' : 'ct-bg'"></div>
        </div>

        <div class="spec-right">
          <div class="ammo-large"><span class="mag">30</span><span class="reserve">/90</span></div>
          <div class="inventory-list">
            <template v-for="item in getSpectatingPlayer()?.inventory" :key="item">
              <svg
                v-if="getWeaponPath(item)"
                viewBox="0 0 120 50"
                class="inv-svg"
                :class="{ active: item === getSpectatingPlayer()?.activeWeaponRaw, nade: isGrenade(item) }"
              >
                <path :d="getWeaponPath(item)" fill="currentColor" />
              </svg>
            </template>
          </div>
        </div>
      </div>

      <div class="demo-controller">
        <div class="controller-glass">
          <button class="ctrl-btn main-play" @click="togglePause">{{ isPaused ? '▶' : '⏸' }}</button>

          <div class="scrubber-track">
            <div class="rounds-markers">
              <div
                v-for="r in roundRegistry"
                :key="r.roundNum"
                class="r-tick"
                :class="{ loaded: r.loaded }"
                :style="{ flex: r.tickCount }"
              ></div>
            </div>
            <input
              type="range"
              min="0"
              :max="totalGlobalTicks > 0 ? totalGlobalTicks - 1 : 0"
              v-model.number="scrubberIndex"
              @input="onSeek"
              class="native-scrubber"
            />
          </div>

          <div class="time-display">{{ formattedRoundTime }}</div>

          <div class="extra-controls">
            <button
              class="ctrl-icon"
              @click="showTrajectories = !showTrajectories"
              :class="{ active: showTrajectories }"
              title="Toggle Grenade Lines"
            >
              〰
            </button>
            <button class="ctrl-icon" @click="toggleFreecam" :class="{ active: isFreeCam }" title="Freecam">🎥</button>
            <button class="ctrl-icon" @click="toggleDebugPanel" :class="{ active: showDebugPanel }" title="Full Debugger">🐞</button>
          </div>
        </div>
      </div>

      <Transition name="fade">
        <div v-if="isBuffering" class="buffering-modal">
          <div class="spinner"></div>
          <div class="buffering-text">Loading Round {{ currentPlaybackState.round }}...</div>
        </div>
      </Transition>

      <Transition name="fade">
        <div v-if="showDebugPanel" class="full-debugger">
          <div class="debug-header">
            <div class="tabs">
              <button :class="{ active: debugTab === 'inspector' }" @click="debugTab = 'inspector'">Inspector</button>
              <button :class="{ active: debugTab === 'camera' }" @click="debugTab = 'camera'">Cam/Eye</button>
              <button :class="{ active: debugTab === 'visuals' }" @click="debugTab = 'visuals'">Visuals</button>
              <button :class="{ active: debugTab === 'anim' }" @click="initPreview(); debugTab = 'anim'">Animations</button>
            </div>
            <button class="close-debug" @click="showDebugPanel = false">✕</button>
          </div>

          <div class="debug-content">
            <div v-if="debugTab === 'inspector'" class="inspector-tab">
              <div class="stat-row title">Target: <span class="text-green">{{ spectatingId || 'Free Cam' }}</span></div>
              <div class="stat-group">
                <div class="lbl">Position</div>
                <div class="val text-mono">{{ debugState.pos.x.toFixed(1) }}, {{ debugState.pos.y.toFixed(1) }}, {{ debugState.pos.z.toFixed(1) }}</div>
              </div>
               <div class="stat-group">
                <div class="lbl">Rotation (Deg)</div>
                <div class="val text-mono">Y: {{ debugState.rot.y.toFixed(1) }}° | P: {{ debugState.rot.x.toFixed(1) }}°</div>
              </div>
               <div class="stat-group">
                <div class="lbl">Speed</div>
                <div class="val text-mono">{{ debugState.speed.toFixed(1) }} u/s</div>
              </div>
              <div class="stat-group">
                <div class="lbl">State</div>
                <div class="val">{{ debugState.state }}</div>
              </div>
               <div class="stat-group">
                <div class="lbl">Active Anim</div>
                <div class="val text-green">{{ debugState.animName }}</div>
              </div>
            </div>

            <div v-if="debugTab === 'camera'" class="camera-tab">
              <div class="control-group">
                <label>Eye Height Override</label>
                <input type="range" v-model.number="debugSettings.eyeHeightOffset" min="-50" max="50" step="1" />
                <div class="val-display">{{ debugSettings.eyeHeightOffset > 0 ? '+' : ''}}{{ debugSettings.eyeHeightOffset }} units</div>
              </div>
              <div class="control-group">
                <label>Cam Forward/Back Offset</label>
                <input type="range" v-model.number="debugSettings.camZOffset" min="-50" max="50" step="1" />
                <div class="val-display">{{ debugSettings.camZOffset }} units</div>
              </div>
              <div class="control-group">
                <label>Cam Pitch Offset</label>
                <input type="range" v-model.number="debugSettings.camPitchOffset" min="-90" max="90" step="1" />
                <div class="val-display">{{ debugSettings.camPitchOffset > 0 ? '+' : ''}}{{ debugSettings.camPitchOffset }}°</div>
              </div>
               <div class="control-group">
                <label>Pitch Influence (Spine)</label>
                <input type="range" v-model.number="debugSettings.pitchFactor" min="0" max="2" step="0.1" />
                <div class="val-display">{{ debugSettings.pitchFactor }}x</div>
              </div>
              <div class="info-box">
                <small>Actual Eye Height: {{ (debugState.isCrouched ? 46 : 64) + debugSettings.eyeHeightOffset }}</small>
              </div>
            </div>

            <div v-if="debugTab === 'visuals'" class="visuals-tab">
              <label class="toggle-row">
                <input type="checkbox" v-model="debugSettings.showSkeleton" />
                <span>Show Skeleton Helper</span>
              </label>
               <label class="toggle-row">
                <input type="checkbox" v-model="debugSettings.showEyeLevel" />
                <span>Show Eye Level Marker (Red)</span>
              </label>
              <label class="toggle-row">
                <input type="checkbox" v-model="debugSettings.showLookRay" />
                <span>Show Look Direction (Yellow)</span>
              </label>
               <label class="toggle-row">
                <input type="checkbox" v-model="debugSettings.wireframe" />
                <span>Wireframe Mode</span>
              </label>
            </div>

            <div v-if="debugTab === 'anim'" class="anim-debug-container">
              <div class="debug-lists">
                <div class="debug-column">
                  <h3>T Anims</h3>
                  <div class="anim-list-scroll">
                    <div
                      v-for="(name, i) in tAnimNames"
                      :key="'t' + i"
                      class="anim-name"
                      :class="{ active: previewName === name }"
                      @click="previewAnimation(name, 't')"
                    >
                      {{ name }}
                    </div>
                  </div>
                </div>
                <div class="debug-column">
                  <h3>CT Anims</h3>
                  <div class="anim-list-scroll">
                    <div
                      v-for="(name, i) in ctAnimNames"
                      :key="'ct' + i"
                      class="anim-name"
                      :class="{ active: previewName === name }"
                      @click="previewAnimation(name, 'ct')"
                    >
                      {{ name }}
                    </div>
                  </div>
                </div>
              </div>
              <div class="debug-preview">
                 <div ref="previewContainer" class="preview-canvas"></div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <div ref="canvasContainer" class="canvas-container"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, shallowRef, reactive, computed, nextTick, watch } from 'vue';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/addons/loaders/KTX2Loader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import getScale from '@/scales';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import { useRoute } from 'vue-router';
import useDemos from '@/composables/useDemos';
import useImages from '@/composables/useImages';

const route = useRoute();
const { Demos } = useDemos();
const { Images } = useImages();

const { data: _demo } = Demos.show(computed(() => route.params.id).value);
const { data: weaponImages } = Images.get('weapon');

const demoMap = computed(() => _demo.value?.map        ?? 'de_dust2');
const demoId  = computed(() => _demo.value?.id         ?? null);
const name    = computed(() => _demo.value?.name       ?? 'Demo');
const players = computed(() => _demo.value?.meta?.steamPlayers ?? []);
const weapons = computed(() => weaponImages.value      ?? []);

// --- HELPER: ASYNC YIELD ---
const yieldToMain = () => new Promise((resolve) => setTimeout(resolve, 0));

// --- CONSTANTS ---
const TICK_RATE = 64;
const TIME_PER_TICK = 1 / TICK_RATE;
const ESTIMATED_ROUND_TICKS = 135 * 64;
const ROUND_TIME_SECONDS = 115;
const MAX_TRACERS = 40;
const STAND_EYE_HEIGHT = 69; 
const CROUCH_EYE_HEIGHT = 46;

// --- REFS & STATE ---
const canvasContainer = ref(null);
const previewContainer = ref(null);
const isFreeCam = ref(false);
const isLoading = ref(true);
const loadingStatus = ref('Initializing Engine...');
const isPaused = ref(false);
const isBuffering = ref(false);
const loadingProgress = ref(0);
const showDebugPanel = ref(false);
const debugTab = ref('inspector');

// Debug State
const debugState = reactive({
  pos: { x: 0, y: 0, z: 0 },
  rot: { x: 0, y: 0 },
  speed: 0,
  state: 'Idle',
  animName: 'None',
  isCrouched: false
});

const debugSettings = reactive({
  eyeHeightOffset: 0,
  camZOffset: 0,
  camPitchOffset: 0,
  pitchFactor: 1.0,
  showSkeleton: false,
  showEyeLevel: false,
  showLookRay: false,
  wireframe: false
});

// Global Timeline State
const roundRegistry = ref([]);
const roundDataStore = new Map();
const scrubberIndex = ref(0);

const totalGlobalTicks = computed(() => {
  if (roundRegistry.value.length === 0) return 0;
  const last = roundRegistry.value[roundRegistry.value.length - 1];
  return last.startOffset + last.tickCount;
});

const currentPlaybackState = reactive({
  round: 1,
  tickInRound: 0,
});

const isFreezeTime = computed(() => {
  const roundInfo = roundRegistry.value.find((r) => r.roundNum === currentPlaybackState.round);
  if (!roundInfo || !roundInfo.loaded) return true;
  return currentPlaybackState.tickInRound < roundInfo.freezeEndTick;
});

const formattedRoundTime = computed(() => {
  const roundInfo = roundRegistry.value.find((r) => r.roundNum === currentPlaybackState.round);
  if (!roundInfo || !roundInfo.loaded) return '0:15';
  const currentTick = currentPlaybackState.tickInRound;
  const freezeEnd = roundInfo.freezeEndTick;
  let secondsRemaining;
  if (currentTick < freezeEnd) {
    const ticksLeft = freezeEnd - currentTick;
    secondsRemaining = Math.ceil(ticksLeft / TICK_RATE);
  } else {
    const ticksSinceStart = currentTick - freezeEnd;
    const secondsElapsed = ticksSinceStart / TICK_RATE;
    secondsRemaining = Math.ceil(ROUND_TIME_SECONDS - secondsElapsed);
  }
  if (secondsRemaining < 0) secondsRemaining = 0;
  const m = Math.floor(secondsRemaining / 60);
  const s = Math.floor(secondsRemaining % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
});

const showTrajectories = ref(true);
const spectatingId = ref(null);
const uiState = reactive({ ctPlayers: [], tPlayers: [], ctScore: 0, tScore: 0, round: 1 });

const tAnimNames = ref([]);
const ctAnimNames = ref([]);
const previewName = ref('');

// --- THREEJS STATE ---
let scene, camera, renderer;
let freeCamControls;
let mapGroup, playerGroup, effectsGroup, grenadeGroup, debugGroup;
let clock, animationId, raycaster, mouse;
let tModel = null;
let ctModel = null;
let tAnimations = [];
let ctAnimations = [];
let previewApp = { renderer: null, scene: null, camera: null, mixer: null, clock: new THREE.Clock(), controls: null, id: null, currentModel: null };

// Debug Helpers
let currentSkeletonHelper = null;
let lookRayArrow = null;

const camVelocity = new THREE.Vector3();
let tickAccumulator = 0;
const playerMeshes = {};
const roundGrenades = new Map();
const tracerPool = [];
let tracerPoolIndex = 0;
const moveState = { forward: false, backward: false, left: false, right: false, up: false, down: false, sprint: false };
const camParams = { flySpeed: 1000, sprintMultiplier: 3.0 };
const mapSettings = { x: 0, y: 0, z: 0, scale: 39.37 };
const _v1 = new THREE.Vector3();
const _lookTarget = new THREE.Vector3();

// --- ASSETS ---
const assets = {
  geo: {
    player: new THREE.CapsuleGeometry(10, 30, 4, 8),
    projectile: new THREE.SphereGeometry(4, 4, 4),
    smokeParticle: new THREE.SphereGeometry(70, 6, 6),
    fire: new THREE.CylinderGeometry(120, 120, 10, 8),
  },
  mat: {
    t: new THREE.MeshLambertMaterial({ color: 0xff4444 }),
    ct: new THREE.MeshLambertMaterial({ color: 0x44aaff }),
    dead: new THREE.MeshLambertMaterial({ color: 0x555555 }),
    smoke: new THREE.MeshLambertMaterial({ color: 0x555555, transparent: true, opacity: 0.6, depthWrite: false }),
    fire: new THREE.MeshBasicMaterial({ color: 0xff4400, transparent: true, opacity: 0.6, depthWrite: false }),
    grenade_flash: new THREE.MeshBasicMaterial({ color: 0xffffff }),
    grenade_smoke: new THREE.MeshBasicMaterial({ color: 0xaaaaaa }),
    grenade_fire: new THREE.MeshBasicMaterial({ color: 0xff5500 }),
    grenade_he: new THREE.MeshBasicMaterial({ color: 0x00ff00 }),
    grenade_decoy: new THREE.MeshBasicMaterial({ color: 0xff00ff }),
  },
};

function getPlayerImage(player) {
    const steamId = player.steamid || '';
    const foundPlayer = players.value.find(p => p.steamid === steamId);
    return foundPlayer?.avatarmedium || 'https://cdn-icons-png.flaticon.com/512/3135/3135715.png';
}

function getWeaponPath(itemName) {
  if(!weapons.value) return null;
  const name = itemName.toLowerCase().replace(/[^a-z0-9]/g, '');
  const w = weapons.value.find(x => x.name.toLowerCase().replace(/[^a-z0-9]/g, '') === name);
  return w ? w.svg_path : null;
}

function isGrenade(name) {
  const nades = ['flashbang', 'smokegrenade', 'hegrenade', 'molotov', 'incgrenade', 'decoy'];
  return nades.some((n) => name.includes(n));
}

function getGrenadeMat(type) {
  switch (type) {
    case 'flashbang': return assets.mat.grenade_flash;
    case 'smoke': return assets.mat.grenade_smoke;
    case 'molotov': case 'incendiary': return assets.mat.grenade_fire;
    case 'hegrenade': return assets.mat.grenade_he;
    case 'decoy': return assets.mat.grenade_decoy;
    default: return assets.mat.grenade_flash;
  }
}

// --- ANIMATION LOGIC ---
function determineWeaponCategory(weaponName) {
  if (!weaponName) return 'knife';
  const name = weaponName.toLowerCase();
  if (name.includes('knife') || name.includes('bayonet') || name.includes('karambit')) return 'knife';
  if (['glock', 'hkp2000', 'usp_silencer', 'p250', 'tec9', 'cz75', 'deagle', 'revolver', 'fiveseven', 'elite'].some((x) => name.includes(x))) return 'pistol';
  return 'rifle';
}

function getAnimNameForState(state, weaponCategory) {
  const suffix = weaponCategory === 'knife' ? 'knife' : weaponCategory === 'pistol' ? 'pistol' : 'rifle';
  switch (state) {
    case 'idle': return `idle_for_turns_stand_${suffix}`;
    case 'walk': return `walk_new_${suffix}_n`;
    case 'run': return `run_new_${suffix}_n`;
    case 'crouch_idle': return weaponCategory === 'knife' ? 'idle_for_turns_crouch_knife' : weaponCategory === 'pistol' ? 'idle_for_turns_crouch_pistol' : 'idle_for_turns_crouch_rifle';
    case 'crouch_move': return `crouch_new_${suffix}_n`;
    case 'death': return 'death_shoulder_a';
    default: return `idle_for_turns_stand_${suffix}`;
  }
}

function getPlayerState(speed, isCrouched) {
  if (isCrouched) {
    return speed > 10 ? 'crouch_move' : 'crouch_idle';
  } else {
    if (speed > 135) return 'run';
    if (speed > 5) return 'walk';
    return 'idle';
  }
}

// --- DEBUGGER FUNCTIONS ---
function toggleDebugPanel() {
  showDebugPanel.value = !showDebugPanel.value;
  if (!showDebugPanel.value) {
    // Cleanup preview if closing
    disposePreview();
  }
}

function createEyeMarker() {
  const group = new THREE.Group();
  const geo = new THREE.RingGeometry(15, 16, 32);
  geo.rotateX(-Math.PI / 2);
  const mat = new THREE.MeshBasicMaterial({ color: 0xff0000, depthTest: false, transparent: true, opacity: 0.3, side: THREE.DoubleSide });
  const ring = new THREE.Mesh(geo, mat);
  group.add(ring);

  const beadGeo = new THREE.SphereGeometry(2, 8, 8);
  const beadMat = new THREE.MeshBasicMaterial({ color: 0xff0000, depthTest: false });
  const bead = new THREE.Mesh(beadGeo, beadMat);
  bead.position.z = -50; // Forward in local space
  group.add(bead);
  
  return group;
}

function updateDebugVisuals(targetMesh) {
  if (!targetMesh || !debugSettings.showSkeleton) {
    if (currentSkeletonHelper) {
      debugGroup.remove(currentSkeletonHelper);
      currentSkeletonHelper = null;
    }
  } else if (debugSettings.showSkeleton) {
    if (!currentSkeletonHelper || currentSkeletonHelper.root !== targetMesh) {
      if (currentSkeletonHelper) debugGroup.remove(currentSkeletonHelper);
      currentSkeletonHelper = new THREE.SkeletonHelper(targetMesh);
      debugGroup.add(currentSkeletonHelper);
    }
    // THREE.SkeletonHelper automatically updates during the render pass via updateMatrixWorld
  }

  // Eye Level Markers (ALL Players)
  Object.values(playerMeshes).forEach(mesh => {
    if (!debugSettings.showEyeLevel) {
      if (mesh.userData.eyeMarker) mesh.userData.eyeMarker.visible = false;
      return;
    }

    if (!mesh.userData.eyeMarker) {
      const marker = createEyeMarker();
      mesh.add(marker);
      mesh.userData.eyeMarker = marker;
    }
    
    mesh.userData.eyeMarker.visible = true;
    const eyeH = (mesh.userData.currentEyeHeight || 64) + debugSettings.eyeHeightOffset;
    mesh.userData.eyeMarker.position.set(0, eyeH, 0);
  });

  // Look Ray (Target Only)
  if (!debugSettings.showLookRay) {
    if (lookRayArrow) lookRayArrow.visible = false;
  } else if (targetMesh) {
     if (!lookRayArrow) {
       lookRayArrow = new THREE.ArrowHelper(new THREE.Vector3(0,0,1), new THREE.Vector3(), 50, 0xffff00);
       debugGroup.add(lookRayArrow);
     }
     lookRayArrow.visible = true;
     const eyeH = (targetMesh.userData.currentEyeHeight || 64) + debugSettings.eyeHeightOffset;
     const start = targetMesh.position.clone();
     start.y += eyeH;
     lookRayArrow.position.copy(start);
     
     const yaw = THREE.MathUtils.degToRad(targetMesh.userData.rawRotY || 0);
     const finalPitchDeg = (targetMesh.userData.rawRotX || 0) + debugSettings.camPitchOffset;
     const pitch = THREE.MathUtils.degToRad(finalPitchDeg);
     
     const dir = new THREE.Vector3(
        Math.cos(yaw) * Math.cos(pitch),
        -Math.sin(pitch),
        -Math.sin(yaw) * Math.cos(pitch)
     ).normalize();
     lookRayArrow.setDirection(dir);
     lookRayArrow.setLength(300);
  }

  // Wireframe toggle
  scene.traverse(obj => {
      if (obj.isMesh && obj.userData.isModel) {
          obj.material.wireframe = debugSettings.wireframe;
          if (obj.children) {
              obj.children.forEach(c => {
                   if(c.isSkinnedMesh) c.material.wireframe = debugSettings.wireframe;
              })
          }
      }
  });
}

// --- PREVIEW SYSTEM ---
function initPreview() {
  if (!previewContainer.value || previewApp.renderer) return;
  const w = previewContainer.value.clientWidth || 300;
  const h = previewContainer.value.clientHeight || 300;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x222222);
  const grid = new THREE.GridHelper(200, 10);
  scene.add(grid);

  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000);
  camera.position.set(0, 50, 150);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(w, h);
  previewContainer.value.appendChild(renderer.domElement);

  const light = new THREE.AmbientLight(0xffffff, 2);
  scene.add(light);
  const dirLight = new THREE.DirectionalLight(0xffffff, 1);
  dirLight.position.set(50, 100, 50);
  scene.add(dirLight);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 40, 0);
  controls.update();

  previewApp = { renderer, scene, camera, mixer: null, clock: new THREE.Clock(), controls, id: null, currentModel: null };
  animatePreview();
}

function animatePreview() {
  if (!previewApp.renderer || !showDebugPanel.value) return;
  previewApp.id = requestAnimationFrame(animatePreview);
  const delta = previewApp.clock.getDelta();
  if (previewApp.mixer) previewApp.mixer.update(delta);
  previewApp.controls.update();
  previewApp.renderer.render(previewApp.scene, previewApp.camera);
}

function disposePreview() {
  if (previewApp.id) cancelAnimationFrame(previewApp.id);
  if (previewApp.renderer) {
    previewApp.renderer.dispose();
    if(previewApp.renderer.domElement.parentNode) previewApp.renderer.domElement.parentNode.removeChild(previewApp.renderer.domElement);
  }
  previewApp.renderer = null;
}

function previewAnimation(name, team) {
  previewName.value = name;
  if (!previewApp.scene) initPreview();
  if (!previewApp.scene) return; // double check

  const isT = team === 't';
  const sourceModel = isT ? tModel : ctModel;
  const sourceAnims = isT ? tAnimations : ctAnimations;
  if (!sourceModel) return;

  if (previewApp.currentModel?.userData.team !== team) {
    if (previewApp.currentModel) previewApp.scene.remove(previewApp.currentModel);
    const clone = SkeletonUtils.clone(sourceModel);
    clone.userData.team = team;
    previewApp.scene.add(clone);
    previewApp.currentModel = clone;
    const internalMesh = clone.children[0].children[0];
    if (internalMesh) previewApp.mixer = new THREE.AnimationMixer(internalMesh);
  }

  if (previewApp.mixer) {
    const clip = sourceAnims.find((a) => a.name === name);
    if (clip) {
      previewApp.mixer.stopAllAction();
      const action = previewApp.mixer.clipAction(clip);
      action.reset();
      action.play();
    }
  }
}

function initThreeJS() {
  scene = new THREE.Scene();
  const loader = new THREE.CubeTextureLoader();
  loader.setPath('/threed/maps/skybox/');
  const texture = loader.load([
    `sky_${demoMap.value}_rt.png`,
    `sky_${demoMap.value}_lf.png`,
    `sky_${demoMap.value}_up.png`,
    `sky_${demoMap.value}_dn.png`,
    `sky_${demoMap.value}_bk.png`,
    `sky_${demoMap.value}_ft.png`,
  ]);
  scene.background = texture;
  scene.environment = texture;

  // Use the local container dimensions, NOT the global window dimensions
  const width = canvasContainer.value.clientWidth;
  const height = canvasContainer.value.clientHeight;

  camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 100000);
  camera.position.set(0, 500, 0);
  camera.rotation.order = 'YXZ';
  scene.add(camera);

  // Modernized Lighting setup
  const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 0.6);
  scene.add(hemiLight);

  const sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
  sunLight.position.set(1000, 2000, 1000);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.width = 2048;
  sunLight.shadow.mapSize.height = 2048;
  sunLight.shadow.camera.near = 0.5;
  sunLight.shadow.camera.far = 5000;
  sunLight.shadow.camera.left = -1000;
  sunLight.shadow.camera.right = 1000;
  sunLight.shadow.camera.top = 1000;
  sunLight.shadow.camera.bottom = -1000;
  scene.add(sunLight);

  // High-performance renderer with ACESFilmic tone mapping
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.autoClear = false;
  
  // CRUCIAL: Fixes washed-out GLTF colors
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  canvasContainer.value.appendChild(renderer.domElement);

  freeCamControls = new PointerLockControls(camera, document.body);
  
  freeCamControls.addEventListener('lock', () => {
    if (spectatingId.value && playerMeshes[spectatingId.value]) {
      playerMeshes[spectatingId.value].visible = true;
    }
    isFreeCam.value = true;
    spectatingId.value = null;
  });
  
  freeCamControls.addEventListener('unlock', () => {
    isFreeCam.value = false;
    camera.rotation.setFromQuaternion(camera.quaternion, 'YXZ');
    camera.rotation.z = 0;
  });

  clock = new THREE.Clock();
  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  mapGroup = new THREE.Group();
  playerGroup = new THREE.Group();
  effectsGroup = new THREE.Group();
  grenadeGroup = new THREE.Group();
  debugGroup = new THREE.Group();

  scene.add(mapGroup, playerGroup, effectsGroup, grenadeGroup, debugGroup);

  initTracerPool();
  loadingProgress.value = 20;
}

function loadAssetPromise(url) {
  return new Promise((resolve, reject) => {
    const loader = new GLTFLoader();
    const ktx2Loader = new KTX2Loader().setTranscoderPath('https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/libs/basis/').detectSupport(renderer);
    loader.setKTX2Loader(ktx2Loader);
    loader.setMeshoptDecoder(MeshoptDecoder);

    loader.load(url, resolve, undefined, (err) => {
      console.error(`Error loading asset: ${url}`, err);
      reject(err);
    });
  });
}

async function initializeGame() {
  isLoading.value = true;
  loadingStatus.value = 'Loading Map & Models...';
  try {
    const [mapGltf, tGltf, ctGltf] = await Promise.all([
      loadAssetPromise(`https://csstrats.b-cdn.net/maps/${demoMap.value}.glb?v=1`),
      loadAssetPromise('https://csstrats.b-cdn.net/models/t/t.glb'),
      loadAssetPromise('https://csstrats.b-cdn.net/models/ct/ct.glb'),
    ]);
    loadingProgress.value = 60;

    const map = mapGltf.scene;
    map.traverse((child) => {
      if (child.isMesh) {
        child.frustumCulled = false;
        child.matrixAutoUpdate = false;
        child.updateMatrix();
      }
    });
    mapGroup.add(map);
    updateMapTransform();

    const scale = 39.37;
    const prepareModel = (gltf) => {
      if (gltf.animations) {
        gltf.animations.forEach((clip) => {
          clip.tracks = clip.tracks.filter((track) => !track.name.endsWith('.position'));
        });
      }
      const wrapper = new THREE.Group();
      const pivot = new THREE.Group();
      pivot.scale.set(scale, scale, scale);
      pivot.rotation.y = -Math.PI / 2;
      pivot.add(gltf.scene);
      wrapper.add(pivot);

      wrapper.traverse((c) => {
        if (c.isMesh) {
          c.frustumCulled = false;
          // c.renderOrder = 999;
          if (c.material) {
            c.material.transparent = false;
            c.material.opacity = 1.0;
            c.material.depthTest = true; 
            c.material.depthWrite = true;
          }
        }
      });
      return wrapper;
    };

    tAnimations = tGltf.animations || [];
    tAnimNames.value = tAnimations.map((a) => a.name).sort();
    tModel = prepareModel(tGltf);

    ctAnimations = ctGltf.animations || [];
    ctAnimNames.value = ctAnimations.map((a) => a.name).sort();
    ctModel = prepareModel(ctGltf);

    loadingProgress.value = 80;
    loadingStatus.value = 'Fetching Demo Data...';
    await loadRoundsIndex();
    animate();
  } catch (error) {
      console.group('Model Loading Debug');
      console.error('Message:', error.message);
      console.error('Stack:', error.stack);
      console.dir(error);
      console.groupEnd();
      loadingStatus.value = `Error: ${error.message}`;
  }
}

function updateMapTransform() {
  mapGroup.position.set(mapSettings.x, mapSettings.y, mapSettings.z);
  mapGroup.rotation.y = THREE.MathUtils.degToRad(90);
  mapGroup.scale.set(mapSettings.scale, mapSettings.scale, mapSettings.scale);
  mapGroup.updateMatrixWorld(true);
}

function initTracerPool() {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
  const material = new THREE.LineBasicMaterial({ color: 0xffff00, linewidth: 1, transparent: true, opacity: 0 });
  for (let i = 0; i < MAX_TRACERS; i++) {
    const line = new THREE.Line(geometry.clone(), material.clone());
    line.visible = false;
    line.userData = { active: false, age: 0 };
    effectsGroup.add(line);
    tracerPool.push(line);
  }
}

function setDirectionVector(targetVec, yawDeg, pitchDeg) {
  const yaw = THREE.MathUtils.degToRad(yawDeg);
  const pitch = THREE.MathUtils.degToRad(pitchDeg);
  const x = Math.cos(yaw) * Math.cos(pitch);
  const y = Math.sin(yaw) * Math.cos(pitch);
  const z = -Math.sin(pitch);
  targetVec.set(x, z, -y).normalize();
}

const MIRAGE_CONFIG = getScale(demoMap.value);
const MAP_SIZE = 1024 * MIRAGE_CONFIG.scale;
const radarCanvas = ref(null);

function drawRadar() {
  const canvas = radarCanvas.value;
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const drawPlayer = (p, color) => {
    if (!p || (p.health ?? 0) <= 0 || p.X === undefined || p.Y === undefined) return;
    const normX = (p.X - MIRAGE_CONFIG.pos_x) / MAP_SIZE;
    const normY = (MIRAGE_CONFIG.pos_y - p.Y) / MAP_SIZE;
    const x = normX * w;
    const y = normY * h;
    if (x < -10 || x > w + 10 || y < -10 || y > h + 10) return;

    const angle = -p.yaw * (Math.PI / 180);
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'white';
    ctx.stroke();

    ctx.beginPath();
    const coneLen = 12;
    const spread = 0.6;
    ctx.moveTo(x, y);
    ctx.lineTo(x + Math.cos(angle - spread) * coneLen, y + Math.sin(angle - spread) * coneLen);
    ctx.lineTo(x + Math.cos(angle + spread) * coneLen, y + Math.sin(angle + spread) * coneLen);
    ctx.closePath();
    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.fill();

    if (spectatingId.value === p.name) {
      ctx.beginPath();
      ctx.arc(x, y, 8, 0, 2 * Math.PI);
      ctx.strokeStyle = '#00ff00';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  };
  uiState.ctPlayers.forEach((p) => drawPlayer(p, '#55aaff'));
  uiState.tPlayers.forEach((p) => drawPlayer(p, '#ffcc44'));
}

// --- GRENADE LOGIC ---
function createGrenadeAssets(trajectoryPoints, type) {
  const mat = getGrenadeMat(type);
  const projectile = new THREE.Mesh(assets.geo.projectile, mat);
  projectile.visible = false;
  projectile.matrixAutoUpdate = false;

  let line = null;
  if (trajectoryPoints && trajectoryPoints.length > 0) {
    const points = trajectoryPoints.map((pt) => new THREE.Vector3(pt.X, pt.Z, -pt.Y));
    const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
    const lineMat = new THREE.LineBasicMaterial({ color: mat.color, opacity: 0.8, transparent: true, linewidth: 2 });
    line = new THREE.Line(lineGeo, lineMat);
    line.visible = false;
    line.frustumCulled = false;
    line.matrixAutoUpdate = false;
    line.updateMatrix();
  }

  let effectMesh = null;
  if (type === 'smoke') {
    effectMesh = new THREE.Group();
    for (let i = 0; i < 6; i++) {
      const mesh = new THREE.Mesh(assets.geo.smokeParticle, assets.mat.smoke);
      mesh.position.set((Math.random() - 0.5) * 150, (Math.random() - 0.5) * 60 + 40, (Math.random() - 0.5) * 150);
      mesh.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0);
      mesh.matrixAutoUpdate = false;
      mesh.updateMatrix();
      effectMesh.add(mesh);
    }
  } else if (['molotov', 'incendiary'].includes(type)) {
    effectMesh = new THREE.Mesh(assets.geo.fire, assets.mat.fire);
  }

  if (effectMesh) {
    effectMesh.visible = false;
    grenadeGroup.add(effectMesh);
  }
  grenadeGroup.add(projectile);
  if (line) grenadeGroup.add(line);
  return { projectile, line, effectMesh };
}

function processRoundGrenades(roundNum, sortedTicks) {
  const roundData = roundDataStore.get(roundNum);
  if (!roundData) return;

  sortedTicks.forEach((tick) => {
    const data = roundData[tick];
    if (!data.grenades) return;
    data.grenades.forEach((g) => {
      const id = `${roundNum}_${g.entity_id}`;
      const currentPos = { X: g.X, Y: g.Y, Z: g.Z };
      if (!roundGrenades.has(id)) {
        roundGrenades.set(id, {
          startTick: tick,
          endTick: tick,
          type: g.grenade_type,
          trajectory: [currentPos],
          lastPos: currentPos,
          roundNum: roundNum,
        });
      } else {
        const entry = roundGrenades.get(id);
        entry.endTick = tick;
        entry.lastPos = currentPos;
        entry.trajectory.push(currentPos);
      }
    });
  });

  roundGrenades.forEach((data, id) => {
    if (data.roundNum === roundNum && !data.projectile) {
      const assets = createGrenadeAssets(data.trajectory, data.type);
      if (assets.effectMesh) {
        assets.effectMesh.position.set(data.lastPos.X, data.lastPos.Z, -data.lastPos.Y);
        assets.effectMesh.position.y += data.type === 'smoke' ? 20 : 5;
        assets.effectMesh.updateMatrix();
      }
      Object.assign(data, assets);
    }
  });
}

function updateGrenadeVisuals(currentTick, currentRound) {
  roundGrenades.forEach((g) => {
    if (g.roundNum !== currentRound) {
      if (g.projectile) g.projectile.visible = false;
      if (g.line) g.line.visible = false;
      if (g.effectMesh) g.effectMesh.visible = false;
      return;
    }

    const isProjectile = currentTick >= g.startTick && currentTick <= g.endTick;
    let isEffect = false;

    if (g.type === 'smoke') {
      const smokeStart = g.endTick - 20 * 64; // Approx smoke duration
      const actualStart = Math.max(smokeStart, g.startTick);
      isEffect = currentTick >= actualStart && currentTick <= g.endTick;
      if (isEffect && g.projectile) g.projectile.visible = false;
    } else if (['molotov', 'incendiary'].includes(g.type)) {
      const fireStart = g.endTick - 7 * 64;
      const actualStart = Math.max(fireStart, g.startTick);
      isEffect = currentTick >= actualStart && currentTick <= g.endTick;
    }

    if (g.line) {
      const TRAIL_LENGTH_TICKS = 64;
      const ticksSinceStart = currentTick - g.startTick;
      const startIdx = Math.max(0, ticksSinceStart - TRAIL_LENGTH_TICKS);
      const endIdx = Math.min(g.trajectory.length, ticksSinceStart + 1);
      const drawCount = Math.max(0, endIdx - startIdx);
      if (drawCount > 0) {
        g.line.geometry.setDrawRange(startIdx, drawCount);
        g.line.visible = showTrajectories.value;
      } else {
        g.line.visible = false;
      }
    }

    if (isProjectile && !isEffect) {
      if (!g.projectile.visible) g.projectile.visible = true;
      const duration = g.endTick - g.startTick;
      if (duration > 0) {
        const progress = (currentTick - g.startTick) / duration;
        const idx = Math.min(Math.floor(progress * g.trajectory.length), g.trajectory.length - 1);
        const pt = g.trajectory[idx];
        if (pt) {
          g.projectile.position.set(pt.X, pt.Z, -pt.Y);
          g.projectile.updateMatrix();
        }
      }
    } else {
      if (g.projectile.visible) g.projectile.visible = false;
    }

    if (isEffect && g.effectMesh) {
      if (!g.effectMesh.visible) g.effectMesh.visible = true;
      const effectStart = g.endTick - (g.type === 'smoke' ? 20 * 64 : 7 * 64);
      const ageTicks = currentTick - effectStart;
      if (ageTicks < 35) {
        let scale = Math.max(0, Math.min(1, ageTicks / 30));
        const eased = 1 - Math.pow(1 - scale, 3);
        g.effectMesh.scale.set(eased, eased, eased);
      } else if (g.effectMesh.scale.x !== 1) {
        g.effectMesh.scale.set(1, 1, 1);
      }
      if (g.type === 'smoke') g.effectMesh.rotation.y += 0.002;
    } else if (g.effectMesh && g.effectMesh.visible) {
      g.effectMesh.visible = false;
    }
  });
}

function spawnTracer(startPos, yawDeg, pitchDeg) {
  let tracer = tracerPool[tracerPoolIndex];
  tracerPoolIndex = (tracerPoolIndex + 1) % MAX_TRACERS;
  setDirectionVector(_v1, yawDeg, pitchDeg);
  const endPos = _lookTarget.copy(startPos).add(_v1.multiplyScalar(3000));
  const positions = tracer.geometry.attributes.position.array;
  positions[0] = startPos.x;
  positions[1] = startPos.y;
  positions[2] = startPos.z;
  positions[3] = endPos.x;
  positions[4] = endPos.y;
  positions[5] = endPos.z;
  tracer.geometry.attributes.position.needsUpdate = true;
  tracer.userData.age = 0;
  tracer.userData.active = true;
  tracer.material.opacity = 0.8;
  tracer.visible = true;
}

function updateTracer(delta) {
  for (const tracer of tracerPool) {
    if (!tracer.userData.active) continue;
    tracer.userData.age += delta;
    if (tracer.userData.age > 0.3) {
      tracer.userData.active = false;
      tracer.visible = false;
    } else {
      tracer.material.opacity = 0.8 * (1.0 - tracer.userData.age * 3);
    }
  }
}

async function onSeek() {
  const targetGlobal = scrubberIndex.value;
  const targetRound = roundRegistry.value.find((r) => targetGlobal >= r.startOffset && targetGlobal < r.startOffset + r.tickCount);

  if (targetRound) {
    grenadeGroup.children.forEach((c) => (c.visible = false));
    tracerPool.forEach((t) => { t.visible = false; t.userData.active = false; });

    // If seeking to an unloaded round, fetch it first
    if (!targetRound.loaded) {
      isBuffering.value = true;
      currentPlaybackState.round = targetRound.roundNum;
      
      // Load the requested round
      await loadRoundData(targetRound.roundNum);
      isBuffering.value = false;
    }

    // Trigger Garbage Collection and Preload the next round
    cleanupMemoryManager(targetRound.roundNum);
    loadRoundData(targetRound.roundNum + 1);

    const localIndex = Math.min(targetGlobal - targetRound.startOffset, targetRound.tickCount - 1);
    currentPlaybackState.round = targetRound.roundNum;
    currentPlaybackState.tickInRound = targetRound.sortedTicks[localIndex];
    const tickData = roundDataStore.get(targetRound.roundNum)[currentPlaybackState.tickInRound];
    
    if (tickData) {
      processTick(tickData, currentPlaybackState.tickInRound, targetRound.roundNum);
      updateGrenadeVisuals(currentPlaybackState.tickInRound, targetRound.roundNum);
    }
  }
}

function processTick(tickData, tickNum, roundNum) {
  const players = Array.isArray(tickData) ? tickData : tickData.players || [];
  const weaponFires = tickData.weapon_fires || [];
  const activePlayerIds = new Set();
  const ctTeam = [];
  const tTeam = [];

  players.forEach((player) => {
    processPlayer(player, activePlayerIds, ctTeam, tTeam);
  });

  uiState.ctPlayers = ctTeam.sort((a, b) => a.name.localeCompare(b.name));
  uiState.tPlayers = tTeam.sort((a, b) => a.name.localeCompare(b.name));
  uiState.round = roundNum;

  handleDisconnectedPlayers(activePlayerIds);
  processWeaponFires(weaponFires);
  drawRadar();
}

function createPlayerLabel(name, pTeam) {
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const fontSize = 48;
  canvas.width = 512;
  canvas.height = 128;
  ctx.font = `bold ${fontSize}px "Inter", sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = 4;
  ctx.strokeStyle = 'rgba(0,0,0,0.8)';
  ctx.strokeText(name, canvas.width / 2, canvas.height / 2);
  ctx.fillStyle = pTeam === 2 ? '#ffcc44' : '#55aaff';
  ctx.fillText(name, canvas.width / 2, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const spriteMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true });
  const sprite = new THREE.Sprite(spriteMaterial);
  sprite.scale.set(60, 15, 1);
  return sprite;
}

function processPlayer(p, activePlayerIds, ctTeam, tTeam) {
  const pName = p.name;
  const pTeam = p.team_name === 't' ? 2 : p.team_name === 'ct' ? 3 : 0;
  const isAlive = (p.health ?? 100) > 0;
  activePlayerIds.add(pName);
  const playerData = createPlayerData(p);
  if (pTeam === 3) ctTeam.push(playerData);
  else if (pTeam === 2) tTeam.push(playerData);

  let mesh = playerMeshes[pName];
  if (mesh && mesh.userData.team !== pTeam) {
    playerGroup.remove(mesh);
    delete playerMeshes[pName];
    mesh = null;
  }
  if (!mesh) mesh = getOrCreatePlayerMesh(pName, pTeam);
  mesh = upgradeToModelIfNeeded(mesh, pName, pTeam);
  initializeAnimationMixer(mesh, pTeam);
  updatePlayerState(mesh, p, pTeam, isAlive);

  // If this is the spectated player, update debug stats
  if (spectatingId.value === pName) {
      debugState.pos = { x: p.X, y: p.Y, z: p.Z };
      debugState.rot = { x: p.pitch, y: p.yaw };
      // Velocity calc roughly
      const oldPos = mesh.position; // before update? No, we just updated it.
      // We calculate speed in updateAlivePlayer, store it on userData
      debugState.speed = mesh.userData.currentSpeed || 0;
      debugState.state = mesh.userData.currentState || 'Idle';
      debugState.animName = mesh.userData.currentAnimName || 'None';
      debugState.isCrouched = p.is_crouched;
  }

  mesh.visible = !(spectatingId.value === pName && !isFreeCam.value);
  mesh.updateMatrix();
}

function createPlayerData(p) {
  const activeWeaponRaw = p.active_weapon_name ? p.active_weapon_name.replace('weapon_', '') : '';
  const rawInv = p.inventory || p.weapons || [];
  let inventory = rawInv.map((w) => w.replace('weapon_', ''));
  inventory.sort((a, b) => (isGrenade(a) && !isGrenade(b) ? 1 : !isGrenade(a) && isGrenade(b) ? -1 : 0));
  return { name: p.name, health: p.health ?? 100, account: p.account ?? 0, weapon: activeWeaponRaw, activeWeaponRaw, inventory, X: p.X, Y: p.Y, Z: p.Z, yaw: p.yaw, pitch: p.pitch, isCrouched: p.is_crouched ?? false, steamid: p.steamid || '' };
}

function getOrCreatePlayerMesh(pName, pTeam) {
  if (!playerMeshes[pName]) {
    const mesh = createInitialPlayerMesh(pName, pTeam);
    mesh.matrixAutoUpdate = false;
    const labelSprite = createPlayerLabel(pName, pTeam);
    labelSprite.position.set(0, 85, 0);
    mesh.add(labelSprite);
    mesh.userData.label = labelSprite;
    playerGroup.add(mesh);
    playerMeshes[pName] = mesh;
  }
  return playerMeshes[pName];
}

function createInitialPlayerMesh(pName, pTeam) {
  let mesh;
  if (pTeam === 2 && tModel) mesh = createModelMesh(tModel, tAnimations, pName, pTeam);
  else if (pTeam === 3 && ctModel) mesh = createModelMesh(ctModel, ctAnimations, pName, pTeam);
  else {
    const mat = pTeam === 2 ? assets.mat.t : assets.mat.ct;
    mesh = new THREE.Mesh(assets.geo.player, mat);
    mesh.userData = { id: pName, isDead: false, team: pTeam, isModel: false };
  }
  return mesh;
}

function createModelMesh(model, animations, pName, pTeam) {
  const mesh = SkeletonUtils.clone(model);
  mesh.userData = { id: pName, isDead: false, team: pTeam, isModel: true, currentAnimName: null, spineBone: null };
  const internalMesh = mesh.children[0]?.children[0];
  if (internalMesh && animations.length > 0) {
    mesh.userData.mixer = new THREE.AnimationMixer(internalMesh);
  }
  mesh.traverse((child) => {
    if (child.isBone) {
      const name = child.name.toLowerCase();
      if ((name.includes('spine_3') || name.includes('spine3') || name.includes('neck')) && !mesh.userData.spineBone) {
        mesh.userData.spineBone = child;
      }
    }
  });
  if (!mesh.userData.spineBone) {
    mesh.traverse((child) => {
      if (child.isBone && child.name.toLowerCase().includes('head')) {
        mesh.userData.spineBone = child;
      }
    });
  }
  return mesh;
}

function upgradeToModelIfNeeded(mesh, pName, pTeam) {
  if (mesh.userData.isModel) return mesh;
  const model = pTeam === 2 ? tModel : pTeam === 3 ? ctModel : null;
  const anims = pTeam === 2 ? tAnimations : ctAnimations;
  if (!model) return mesh;
  const newMesh = createModelMesh(model, anims, pName, pTeam);
  newMesh.position.copy(mesh.position);
  newMesh.rotation.copy(mesh.rotation);
  newMesh.matrixAutoUpdate = false;
  if (mesh.userData.label) {
    newMesh.add(mesh.userData.label);
    newMesh.userData.label = mesh.userData.label;
  }
  playerGroup.remove(mesh);
  playerGroup.add(newMesh);
  playerMeshes[pName] = newMesh;
  return newMesh;
}

function initializeAnimationMixer(mesh, pTeam) {
  if (!mesh.userData.isModel || mesh.userData.mixer) return;
  const anims = pTeam === 2 ? (tAnimations.length > 0 ? tAnimations : ctAnimations) : ctAnimations;
  if (anims.length === 0) return;
  const internalMesh = mesh.children[0]?.children[0];
  if (!internalMesh) return;
  mesh.userData.mixer = new THREE.AnimationMixer(internalMesh);
}

function updatePlayerState(mesh, p, pTeam, isAlive) {
  if (isAlive) updateAlivePlayer(mesh, p, pTeam);
  else updateDeadPlayer(mesh, p, pTeam);
}

function playAnimation(mesh, animName, pTeam) {
  if (!mesh.userData.mixer || mesh.userData.currentAnimName === animName) return;
  const anims = pTeam === 2 ? tAnimations : ctAnimations;
  const clip = anims.find((a) => a.name === animName);
  if (!clip) {
    if (animName.includes('crouch')) return playAnimation(mesh, 'idle_for_turns_crouch_rifle', pTeam);
    return playAnimation(mesh, 'idle_for_turns_stand_pistol', pTeam);
  }
  const newAction = mesh.userData.mixer.clipAction(clip);
  if (mesh.userData.activeAction) {
    newAction.reset().play();
    mesh.userData.activeAction.crossFadeTo(newAction, 0.2, true);
  } else {
    newAction.play();
  }
  mesh.userData.activeAction = newAction;
  mesh.userData.currentAnimName = animName;
}

function updateAlivePlayer(mesh, p, pTeam) {
  const oldPos = mesh.position.clone();
  mesh.position.set(p.X, p.Z, -p.Y);
  const speed = mesh.position.distanceTo(oldPos) * TICK_RATE;
  mesh.userData.currentSpeed = speed;

  const weaponCategory = determineWeaponCategory(p.active_weapon_name || '');
  const playerState = getPlayerState(speed, p.is_crouched || false);
  mesh.userData.currentState = playerState;
  
  const animName = getAnimNameForState(playerState, weaponCategory);
  if (mesh.userData.isModel) playAnimation(mesh, animName, pTeam);
  
  const currentEyeHeight = p.is_crouched ? CROUCH_EYE_HEIGHT : STAND_EYE_HEIGHT;
  mesh.userData.currentEyeHeight = currentEyeHeight;
  mesh.userData.isCrouched = p.is_crouched || false;
  mesh.userData.rawRotY = p.yaw ?? 0;
  mesh.userData.rawRotX = (p.pitch ?? 0) + 2; 
  mesh.rotation.set(0, THREE.MathUtils.degToRad((p.yaw ?? 0) - 180), 0);
  if (mesh.userData.isDead) {
    mesh.userData.isDead = false;
    if (!mesh.userData.isModel) mesh.material = pTeam === 2 ? assets.mat.t : assets.mat.ct;
  }
  if (mesh.userData.label) mesh.userData.label.visible = true;
}

function updateDeadPlayer(mesh, p, pTeam) {
  if (!mesh.userData.isDead) {
    mesh.userData.isDead = true;
    if (mesh.userData.isModel) {
      playAnimation(mesh, 'death_shoulder_a', pTeam);
      if (mesh.userData.activeAction) {
        mesh.userData.activeAction.clampWhenFinished = true;
        mesh.userData.activeAction.loop = THREE.LoopOnce;
      }
    } else {
      mesh.material = assets.mat.dead;
    }
  }
  const yOffset = mesh.userData.isModel ? -35 : 10;
  mesh.position.set(p.X, p.Z + yOffset, -p.Y);
  if (!mesh.userData.isModel) mesh.rotation.x = -Math.PI / 2;
  if (mesh.userData.label) mesh.userData.label.visible = false;
}

function handleDisconnectedPlayers(activePlayerIds) {
  for (const id in playerMeshes) {
    if (activePlayerIds.has(id)) continue;
    const mesh = playerMeshes[id];
    if (mesh.userData.isDead) continue;
    mesh.userData.isDead = true;
    if (mesh.userData.isModel) playAnimation(mesh, 'death_shoulder_a', mesh.userData.team);
    else {
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.y -= 20;
      mesh.material = assets.mat.dead;
    }
    if (mesh.userData.label) mesh.userData.label.visible = false;
    mesh.updateMatrix();
  }
}

function processWeaponFires(weaponFires) {
  if (weaponFires.length === 0) return;
  weaponFires.forEach((fireEvent) => {
    const mesh = playerMeshes[fireEvent.player_name];
    if (!mesh || mesh.userData.isDead) return;
    const eyePos = _v1.copy(mesh.position);
    eyePos.y += (mesh.userData.currentEyeHeight || STAND_EYE_HEIGHT) + debugSettings.eyeHeightOffset;
    const yaw = fireEvent.player_yaw ?? fireEvent.yaw ?? mesh.userData.rawRotY;
    const pitch = fireEvent.player_pitch ?? fireEvent.pitch ?? mesh.userData.rawRotX;
    spawnTracer(eyePos, yaw, pitch);
  });
}

async function loadRoundsIndex() {
  try {
    const res = await fetch(`/api/demo/${demoId.value}/info`);
    const data = await res.json();
    let roundsList = typeof data.rounds === 'number' ? Array.from({ length: data.rounds }, (_, i) => ({ round_num: i + 1 })) : data.rounds || [];
    let runningOffset = 0;
    
    roundRegistry.value = roundsList.map((r) => {
      const entry = { roundNum: r.round_num || r, loaded: false, isLoading: false, tickCount: ESTIMATED_ROUND_TICKS, startOffset: runningOffset, sortedTicks: [], freezeEndTick: 960 };
      runningOffset += ESTIMATED_ROUND_TICKS;
      return entry;
    });
    
    loadingProgress.value = 50;
    
    // SMART LOAD: Only load the first round to start playback immediately!
    await loadRoundData(1);
    isLoading.value = false;
    
    // Preload round 2 silently in the background
    if (roundRegistry.value.length > 1) {
      loadRoundData(2);
    }
  } catch (e) {
    console.error('Error loading rounds index:', e);
  }
}

async function loadRoundData(roundNum) {
  const entry = roundRegistry.value.find((r) => r.roundNum === roundNum);
  if (!entry || entry.loaded || entry.isLoading) return;

  entry.isLoading = true;
  try {
    const res = await fetch(`/api/demo-chunk?demo_id=${demoId.value}&round_index=${roundNum}`);
    const data = await res.json();
    await ingestRoundDataAsync(roundNum, data);
  } catch (err) {
    console.error(`Failed to load round ${roundNum}`, err);
  } finally {
    entry.isLoading = false;
  }
}

async function ingestRoundDataAsync(roundNum, data) {
  const ticksMap = data.ticks;
  const sortedTicks = Object.keys(ticksMap).map(Number).sort((a, b) => a - b);
  await yieldToMain();
  
  let detectedFreezeEnd = sortedTicks[0] + 960;
  const startPositions = new Map();
  if (sortedTicks.length > 0) {
    const firstTick = ticksMap[sortedTicks[0]];
    if (firstTick?.players) firstTick.players.forEach((p) => startPositions.set(p.name, { x: p.X, y: p.Y, z: p.Z }));
  }
  
  const scanLimitIndex = Math.min(sortedTicks.length, 30 * 64);
  for (let i = 0; i < scanLimitIndex; i += 8) {
    const tick = sortedTicks[i];
    const tickData = ticksMap[tick];
    if (!tickData?.players) continue;
    let movementFound = false;
    for (const p of tickData.players) {
      const start = startPositions.get(p.name);
      if (start) {
        const distSq = Math.pow(p.X - start.x, 2) + Math.pow(p.Y - start.y, 2) + Math.pow(p.Z - start.z, 2);
        if (distSq > 400) { detectedFreezeEnd = tick; movementFound = true; break; }
      }
    }
    if (movementFound) break;
  }
  
  await yieldToMain();
  roundDataStore.set(roundNum, ticksMap);
  const entry = roundRegistry.value.find((r) => r.roundNum === roundNum);
  if (entry) {
    entry.loaded = true;
    entry.tickCount = sortedTicks.length;
    entry.sortedTicks = sortedTicks;
    entry.freezeEndTick = detectedFreezeEnd;
    processRoundGrenades(roundNum, sortedTicks);
  }
  
  await yieldToMain();
  recalculateOffsets();
  if (isBuffering.value && currentPlaybackState.round === roundNum) isBuffering.value = false;
}

function recalculateOffsets() {
  let currentTotal = 0;
  roundRegistry.value.forEach((entry) => {
    entry.startOffset = currentTotal;
    currentTotal += entry.tickCount;
  });
}

function togglePause() { isPaused.value = !isPaused.value; }

function startSpectating(id) {
  if (spectatingId.value && playerMeshes[spectatingId.value]) playerMeshes[spectatingId.value].visible = true;
  spectatingId.value = id;
  if (isFreeCam.value) freeCamControls.unlock();
  if (playerMeshes[id]) playerMeshes[id].visible = false;
}
function cleanupMemoryManager(currentRound) {
  // Only keep Previous, Current, and Next round in memory
  const roundsToKeep = [currentRound - 1, currentRound, currentRound + 1];

  for (const [roundNum, roundData] of roundDataStore.entries()) {
    if (!roundsToKeep.includes(roundNum)) {
      // 1. NUKE THE JSON DATA (Frees ~150MB of RAM per round)
      roundDataStore.delete(roundNum);

      const entry = roundRegistry.value.find(r => r.roundNum === roundNum);
      if (entry) entry.loaded = false;

      // 2. DISPOSE 3D GRENADE ASSETS (Frees VRAM)
      for (const [id, g] of roundGrenades.entries()) {
        if (g.roundNum === roundNum) {
          if (g.projectile) grenadeGroup.remove(g.projectile);
          
          if (g.line) {
            grenadeGroup.remove(g.line);
            // Lines use unique geometries/materials that MUST be explicitly disposed
            g.line.geometry.dispose();
            g.line.material.dispose();
          }
          
          if (g.effectMesh) grenadeGroup.remove(g.effectMesh);
          
          roundGrenades.delete(id);
        }
      }
    }
  }
}
function stopSpectating() {
  if (!spectatingId.value) return;
  if (playerMeshes[spectatingId.value]) playerMeshes[spectatingId.value].visible = true;
  spectatingId.value = null;
  camera.rotation.z = 0;
  camera.rotation.setFromQuaternion(camera.quaternion, 'YXZ');
}

function toggleFreecam() {
  if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  if (isFreeCam.value) freeCamControls.unlock();
  else freeCamControls.lock();
}

function animate() {
  animationId = requestAnimationFrame(animate);
  const delta = clock.getDelta();
  if (isLoading.value) { 
    renderer.clear();
    renderer.render(scene, camera); 
    return; 
  }

  updateTracer(delta);

  // Determine current spectated mesh for Debug logic
  let spectatedMesh = null;
  if (spectatingId.value && playerMeshes[spectatingId.value]) {
    spectatedMesh = playerMeshes[spectatingId.value];
  }

  // Update Debug Visuals
  if(showDebugPanel.value) {
    updateDebugVisuals(spectatedMesh);
  } else if (currentSkeletonHelper) {
     debugGroup.remove(currentSkeletonHelper);
     currentSkeletonHelper = null;
  }

  Object.values(playerMeshes).forEach((mesh) => {
    if (mesh.userData.mixer) mesh.userData.mixer.update(delta);
    if (mesh.userData.spineBone && !mesh.userData.isDead && mesh.userData.isModel) {
      const pitchDeg = mesh.userData.rawRotX ?? 0;
      // APPLY PITCH FACTOR FROM DEBUGGER
      const pitchRad = THREE.MathUtils.degToRad(pitchDeg) * debugSettings.pitchFactor; 
      mesh.userData.spineBone.rotation.z = pitchRad;
    }
  });

  if (isFreeCam.value) {
    const acceleration = 10.0;
    const targetSpeed = moveState.sprint ? camParams.flySpeed * camParams.sprintMultiplier : camParams.flySpeed;
    let targetZ = 0, targetX = 0, targetY = 0;
    if (moveState.forward) targetZ = targetSpeed;
    if (moveState.backward) targetZ = -targetSpeed;
    camVelocity.z += (targetZ - camVelocity.z) * acceleration * delta;
    if (moveState.right) targetX = targetSpeed;
    if (moveState.left) targetX = -targetSpeed;
    camVelocity.x += (targetX - camVelocity.x) * acceleration * delta;
    if (moveState.up) targetY = targetSpeed;
    if (moveState.down) targetY = -targetSpeed;
    camVelocity.y += (targetY - camVelocity.y) * acceleration * delta;
    if (Math.abs(camVelocity.z) > 1) freeCamControls.moveForward(camVelocity.z * delta);
    if (Math.abs(camVelocity.x) > 1) freeCamControls.moveRight(camVelocity.x * delta);
    camera.position.y += camVelocity.y * delta;
    
    // Update debug state for freecam
    if (showDebugPanel.value) {
       debugState.pos = camera.position;
       const euler = new THREE.Euler().setFromQuaternion(camera.quaternion, 'YXZ');
       debugState.rot = { x: THREE.MathUtils.radToDeg(euler.x), y: THREE.MathUtils.radToDeg(euler.y) };
    }

  } else if (spectatingId.value && playerMeshes[spectatingId.value]) {
    const target = playerMeshes[spectatingId.value];
    // APPLY EYE HEIGHT OFFSET FROM DEBUGGER
    const eyeH = (target.userData.currentEyeHeight || STAND_EYE_HEIGHT) + debugSettings.eyeHeightOffset;
    
    // Calculate position
    const camPos = target.position.clone();
    camPos.y += eyeH;

    // APPLY CAMERA FORWARD OFFSET (Moves camera along look vector)
    if(debugSettings.camZOffset !== 0) {
      const yaw = THREE.MathUtils.degToRad(target.userData.rawRotY);
      const pitch = THREE.MathUtils.degToRad(target.userData.rawRotX);
      const forwardDir = new THREE.Vector3(
        Math.cos(yaw) * Math.cos(pitch),
        -Math.sin(pitch),
        -Math.sin(yaw) * Math.cos(pitch)
      ).normalize();
      camPos.add(forwardDir.multiplyScalar(debugSettings.camZOffset));
    }

    camera.position.copy(camPos);
    // NEW: Apply Pitch Offset
    const finalPitch = (target.userData.rawRotX ?? 0) + debugSettings.camPitchOffset;
    setDirectionVector(_v1, target.userData.rawRotY, finalPitch);
    _lookTarget.copy(camera.position).add(_v1);
    camera.lookAt(_lookTarget);
    camera.rotation.setFromQuaternion(camera.quaternion, 'YXZ');
    camera.rotation.z = 0;
  }

  // Playback Logic
  if (!isPaused.value && totalGlobalTicks.value > 0 && !isBuffering.value) {
    tickAccumulator += delta;
    while (tickAccumulator >= TIME_PER_TICK) {
      if (scrubberIndex.value < totalGlobalTicks.value - 1) {
        scrubberIndex.value++;
        let targetRound = roundRegistry.value.find((r) => scrubberIndex.value >= r.startOffset && scrubberIndex.value < r.startOffset + r.tickCount);
        
        if (!targetRound.loaded) {
          isBuffering.value = true;
          currentPlaybackState.round = targetRound.roundNum;
          loadRoundData(targetRound.roundNum); // Fetch it if missing
          break;
        }

        // NEW: Check if we just crossed into a new round natively
        if (currentPlaybackState.round !== targetRound.roundNum) {
            cleanupMemoryManager(targetRound.roundNum);
            loadRoundData(targetRound.roundNum + 1); // Preload the next one
        }

        currentPlaybackState.round = targetRound.roundNum;
        const localIdx = Math.min(scrubberIndex.value - targetRound.startOffset, targetRound.tickCount - 1);
        const gameTick = targetRound.sortedTicks[localIdx];
        currentPlaybackState.tickInRound = gameTick;
        
        const tickData = roundDataStore.get(currentPlaybackState.round)[gameTick];
        if (tickData) {
          processTick(tickData, gameTick, currentPlaybackState.round);
          updateGrenadeVisuals(gameTick, currentPlaybackState.round);
        }
      } else {
        isPaused.value = true;
      }
      tickAccumulator -= TIME_PER_TICK;
    }
  }

// --- RENDER PASS 1: MAP + SKYBOX + UTILITY + EFFECTS ---
  renderer.clear();
  
  // Configure visibility for World Pass (Occluded by walls)
  playerGroup.visible = false;
  debugGroup.visible = false;
  
  mapGroup.visible = true;
  grenadeGroup.visible = true;
  effectsGroup.visible = true;

  renderer.render(scene, camera);

  // --- RENDER PASS 2: PLAYERS (X-RAY) + DEBUG ---
  renderer.clearDepth(); // Clear depth so these draw on top

  // Temporarily hide skybox
  const bg = scene.background;
  scene.background = null;

  // Configure visibility for X-Ray Pass
  mapGroup.visible = false;
  grenadeGroup.visible = false;
  effectsGroup.visible = false;
  
  playerGroup.visible = true;
  debugGroup.visible = true;

  renderer.render(scene, camera);

  // --- RESTORE STATE ---
  scene.background = bg;
  mapGroup.visible = true;
  grenadeGroup.visible = true;
  effectsGroup.visible = true;
  playerGroup.visible = true;
  debugGroup.visible = true;

  if (showDebugPanel.value && debugTab.value === 'anim') animatePreview();
}

function getSpectatingPlayer() {
  if (!spectatingId.value) return null;
  let p = uiState.ctPlayers.find((x) => x.name === spectatingId.value);
  if (p) { p.team = 3; return p; }
  p = uiState.tPlayers.find((x) => x.name === spectatingId.value);
  if (p) { p.team = 2; return p; }
  return null;
}

function onKeyDown(e) {
  if (e.ctrlKey || e.metaKey) {
    if (['w', 'r', 's', 'p', 'f', 'g'].includes(e.key.toLowerCase())) e.preventDefault();
  }
  if (spectatingId.value && ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyC', 'Space'].includes(e.code)) {
    stopSpectating();
    freeCamControls.lock();
  }
  switch (e.code) {
    case 'KeyW': moveState.forward = true; break;
    case 'KeyA': moveState.left = true; break;
    case 'KeyS': moveState.backward = true; break;
    case 'KeyD': moveState.right = true; break;
    case 'Space': moveState.up = true; break;
    case 'KeyC': moveState.down = true; break;
    case 'ShiftLeft': moveState.sprint = true; break;
  }
}

function onKeyUp(e) {
  switch (e.code) {
    case 'KeyW': moveState.forward = false; break;
    case 'KeyA': moveState.left = false; break;
    case 'KeyS': moveState.backward = false; break;
    case 'KeyD': moveState.right = false; break;
    case 'Space': moveState.up = false; break;
    case 'KeyC': moveState.down = false; break;
    case 'ShiftLeft': moveState.sprint = false; break;
  }
}

function onClick(e) {
  if (isFreeCam.value || e.target.closest('.hud-layer')) return;
  mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
  mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObjects(playerGroup.children);
  if (intersects.length > 0) {
    const hit = intersects.find((o) => o.object.userData.id);
    if (hit) startSpectating(hit.object.userData.id);
  }
}

function onResize() {
  if (!canvasContainer.value) return;
  // Recalculate using container bounds to prevent overflowing the parent layout
  const width = canvasContainer.value.clientWidth;
  const height = canvasContainer.value.clientHeight;
  
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
}

onMounted(() => {
    initThreeJS();
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('click', onClick);
    window.addEventListener('resize', onResize);
    if (demoId.value) {
    initializeGame();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown);
  window.removeEventListener('keyup', onKeyUp);
  window.removeEventListener('click', onClick);
  window.removeEventListener('resize', onResize);
  cancelAnimationFrame(animationId);
  disposePreview();
  if (renderer) {
    renderer.dispose();
    renderer.domElement.remove();
  }
  scene.traverse((o) => {
    if (o.isMesh) {
      o.geometry.dispose();
      if (o.material) o.material.dispose();
    }
  });
});

watch(demoId, (newId) => {
  // Only trigger on changes if the renderer is already active
  if (newId && renderer) {
    initializeGame();
  }
});
</script>
<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;700&display=swap');

/* --- CSS VARIABLES --- */
:root {
  --ct-color: #5988b0;
  --ct-bg: rgba(12, 38, 53, 0.75);
  --t-color: #d69e29;
  --t-bg: rgba(45, 37, 12, 0.75);
  --glass-bg: rgba(20, 20, 20, 0.65);
  --glass-border: rgba(255, 255, 255, 0.08);
  --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
  --glass-blur: blur(12px);
}

/* --- BASE LAYOUT --- */
.cs2-viewer {
  width: 100%;
  height: calc(100vh - 160px); /* Locks to parent container, preventing body scroll */
  position: relative;
  background: #000;
  font-family: 'Inter', sans-serif;
  color: white;
  user-select: none;
}

.canvas-container {
  width: 100%;
  height: calc(100vh - 160px);
  position: absolute;
  top: 0;
  left: 0;
  z-index: 0;
}

.hud-layer {
  position: absolute;
  inset: 0;
  z-index: 10;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.hud-layer > * {
  pointer-events: auto;
}

/* --- VUE TRANSITIONS --- */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* --- LOADING SCREEN --- */
.cs2-loading {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.8);
  backdrop-filter: blur(8px);
  z-index: -1;
}

.loading-content {
  position: relative;
  width: 340px;
  text-align: center;
  z-index: 1000;
}

.map-emblem {
  width: 120px;
  margin-bottom: 24px;
  filter: drop-shadow(0 0 15px rgba(255, 255, 255, 0.2));
}

.map-name {
  font-size: 28px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.map-sub {
  color: #aaa;
  margin-bottom: 20px;
  font-size: 14px;
}

.loading-bar-track {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 10px;
}

.loading-bar-fill {
  height: 100%;
  background: #fff;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.loading-status {
  font-size: 12px;
  color: #888;
  font-family: 'JetBrains Mono', monospace;
}

/* --- TOP HUD (SCORE & AVATARS) --- */
.top-hud {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  width: 100%;
  margin-top: 16px;
  padding: 0 20px;
}

.score-panel {
  display: flex;
  height: 52px;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: var(--glass-shadow);
  margin: 0 24px;
}

.score {
  width: 60px;
  font-size: 26px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.score.ct {
  background: var(--ct-bg);
  border-bottom: 4px solid var(--ct-color);
}
.score.t {
  background: var(--t-bg);
  border-bottom: 4px solid var(--t-color);
}

.timer {
  width: 90px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  font-weight: 700;
  background: rgba(0, 0, 0, 0.4);
  border-bottom: 4px solid rgba(255, 255, 255, 0.1);
}

.red-text { color: #ff4d4d; }

.round-num {
  font-size: 10px;
  text-transform: uppercase;
  color: #aaa;
  margin-top: -2px;
}

.team-avatars {
  display: flex;
  gap: 8px;
  align-items: center;
}

.avatar-slot {
  width: 48px;  /* Strict width prevents giant heads */
  height: 48px; /* Strict height */
  flex-shrink: 0;
  background: rgba(0, 0, 0, 0.6);
  position: relative;
  cursor: pointer;
  border: 2px solid rgba(255,255,255,0.05);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-slot img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.avatar-slot .skull {
  font-size: 24px;
  opacity: 0.8;
}

.avatar-slot:hover {
  transform: translateY(-2px);
  border-color: rgba(255,255,255,0.3);
}

.avatar-slot.active {
  border-color: white;
  box-shadow: 0 0 16px rgba(255, 255, 255, 0.4);
}

.avatar-slot.dead {
  filter: grayscale(100%);
  opacity: 0.4;
}

.hp-bar-mini {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 4px;
  background: rgba(0, 0, 0, 0.8);
  z-index: 2;
}

.hp-bar-mini .fill {
  height: 100%;
  background: var(--ct-color);
  transition: width 0.1s linear;
}
.hp-bar-mini .fill.t-fill {
  background: var(--t-color);
}

/* --- RADAR HUD --- */
.radar-hud {
  position: absolute;
  top: 24px;
  left: 24px;
  pointer-events: auto;
}

.radar-container {
  width: 280px;
  height: 280px;
  border: 1px solid var(--glass-border);
  background: rgba(15, 15, 15, 0.6);
  backdrop-filter: var(--glass-blur);
  position: relative;
  overflow: hidden;
  border-radius: 50%;
  box-shadow: var(--glass-shadow);
}

.radar-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0.85;
}

.radar-container canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

/* --- SPECTATOR CARD --- */
.spectator-card {
  position: absolute;
  bottom: 110px;
  left: 50%;
  transform: translateX(-50%);
  width: 600px;
  height: 80px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  text-shadow: 0 2px 6px rgba(0, 0, 0, 0.8);
  background: radial-gradient(ellipse at bottom, rgba(0,0,0,0.6) 0%, transparent 70%);
  padding-bottom: 15px;
  pointer-events: none;
}

.spec-left, .spec-right {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  padding-bottom: 5px;
}

.spec-left { align-items: flex-end; padding-right: 25px; }
.spec-right { align-items: flex-start; padding-left: 25px; }

.spec-center {
  width: 220px;
  text-align: center;
}

.spec-name {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.spec-team-bar {
  width: 100%;
  height: 4px;
  border-radius: 2px;
  background: #fff;
}
.spec-team-bar.ct-bg {
  background: var(--ct-color);
  box-shadow: 0 0 12px var(--ct-color);
}
.spec-team-bar.t-bg {
  background: var(--t-color);
  box-shadow: 0 0 12px var(--t-color);
}

.health-large, .ammo-large {
  font-size: 32px;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: 'JetBrains Mono', monospace;
}

.health-large .icon { font-size: 24px; color: #fff; opacity: 0.8; }
.ammo-large .reserve { font-size: 18px; color: #aaa; margin-top: 8px; }

.inventory-list {
  display: flex;
  gap: 8px;
  margin-top: 6px;
  align-items: center;
}

.inv-svg {
  height: 18px;
  opacity: 0.4;
  color: white;
  transition: all 0.2s;
  filter: drop-shadow(0 2px 2px rgba(0,0,0,0.8));
}
.inv-svg.active {
  opacity: 1;
  height: 26px;
  filter: drop-shadow(0 0 8px rgba(255,255,255,0.4));
}
.inv-svg.nade { height: 16px; }

/* --- DEMO CONTROLLER --- */
.demo-controller {
  position: absolute;
  bottom: 24px;
  left: 0;
  width: 100%;
  display: flex;
  justify-content: center;
  pointer-events: none;
}

.controller-glass {
  pointer-events: auto;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  padding: 12px 24px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  gap: 18px;
  width: 850px;
  box-shadow: var(--glass-shadow);
}

.ctrl-btn.main-play {
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.2);
  color: white;
  font-size: 16px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}
.ctrl-btn.main-play:hover { background: rgba(255,255,255,0.2); transform: scale(1.05); }

.time-display {
  font-family: 'JetBrains Mono', monospace;
  font-size: 14px;
  font-weight: 600;
  color: #ccc;
  min-width: 45px;
  text-align: center;
}

.scrubber-track {
  flex: 1;
  position: relative;
  height: 12px;
  display: flex;
  align-items: center;
}

.rounds-markers {
  position: absolute;
  inset: 0;
  display: flex;
  gap: 2px;
  border-radius: 4px;
  overflow: hidden;
  background: rgba(0,0,0,0.3);
}

.r-tick {
  background: rgba(255, 255, 255, 0.08);
  height: 100%;
}
.r-tick.loaded {
  background: rgba(255, 255, 255, 0.35);
}

.native-scrubber {
  width: 100%;
  -webkit-appearance: none;
  background: transparent;
  z-index: 2;
  cursor: pointer;
  height: 100%;
  margin: 0;
}

.native-scrubber::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 24px;
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 6px rgba(0,0,0,0.5);
  border: 1px solid rgba(0,0,0,0.2);
  cursor: grab;
}
.native-scrubber::-webkit-slider-thumb:active { cursor: grabbing; background: #ddd; }

.extra-controls {
  display: flex;
  gap: 8px;
}

.ctrl-icon {
  background: rgba(255,255,255,0.05);
  border: 1px solid transparent;
  color: white;
  border-radius: 8px;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}
.ctrl-icon:hover { background: rgba(255,255,255,0.15); }
.ctrl-icon.active { 
  background: rgba(85, 170, 255, 0.2); 
  border-color: #55aaff;
  color: #fff;
  box-shadow: 0 0 10px rgba(85, 170, 255, 0.2);
}

/* --- CROSSHAIR --- */
.crosshair {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  transform: translate(-50%, -50%);
  z-index: 100;
  pointer-events: none;
}

.crosshair::before,
.crosshair::after {
  content: '';
  position: absolute;
  background-color: rgba(0, 255, 0, 0.8);
  box-shadow: 0 0 2px rgba(0,0,0,0.8);
}

.crosshair::before { top: -1px; left: -8px; width: 16px; height: 2px; }
.crosshair::after { left: -1px; top: -8px; width: 2px; height: 16px; }

/* --- BUFFERING MODAL --- */
.buffering-modal {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  padding: 24px 32px;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  box-shadow: var(--glass-shadow);
  pointer-events: none;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 3px solid rgba(255,255,255,0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 1s infinite linear;
}
.buffering-text {
  font-weight: 600;
  letter-spacing: 0.5px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* --- FULL DEBUGGER PANEL --- */
.full-debugger {
  position: absolute;
  top: 80px;
  right: 24px;
  width: 400px;
  background: rgba(15, 15, 15, 0.85);
  backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 12px;
  box-shadow: var(--glass-shadow);
  display: flex;
  flex-direction: column;
  z-index: 2000;
  overflow: hidden;
  pointer-events: auto;
}

.debug-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.4);
  border-bottom: 1px solid rgba(255,255,255,0.05);
}

.tabs {
  display: flex;
  gap: 6px;
}

.tabs button {
  background: transparent;
  border: none;
  color: #888;
  font-size: 12px;
  font-weight: 600;
  padding: 6px 10px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
}
.tabs button:hover { color: #fff; background: rgba(255,255,255,0.05); }
.tabs button.active { background: rgba(85, 170, 255, 0.15); color: #55aaff; }

.close-debug {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  width: 28px;
  height: 28px;
}
.close-debug:hover { background: rgba(255,255,255,0.1); color: #fff; }

.debug-content {
  padding: 16px;
  max-height: 550px;
  overflow-y: auto;
}

/* Inspector */
.stat-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 13px;
}
.stat-row.title { font-weight: 700; color: #fff; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; margin-bottom: 16px;}

.stat-group {
  margin-bottom: 12px;
  background: rgba(0,0,0,0.4);
  border: 1px solid rgba(255,255,255,0.03);
  padding: 10px;
  border-radius: 6px;
}
.stat-group .lbl { font-size: 11px; color: #888; text-transform: uppercase; margin-bottom: 4px; letter-spacing: 0.5px; }
.stat-group .val { font-size: 14px; color: #eee; }
.text-mono { font-family: 'JetBrains Mono', monospace; }
.text-green { color: #44ff88 !important; }

/* Camera */
.control-group { margin-bottom: 18px; }
.control-group label { display: block; font-size: 12px; color: #aaa; margin-bottom: 8px; }
.control-group input[type="range"] { 
  width: 100%; 
  cursor: pointer; 
  accent-color: #55aaff;
}
.val-display { font-size: 12px; color: #55aaff; text-align: right; margin-top: 4px; font-family: 'JetBrains Mono', monospace;}

.info-box {
  background: rgba(85, 170, 255, 0.1);
  border: 1px solid rgba(85, 170, 255, 0.2);
  padding: 10px;
  border-radius: 6px;
  color: #55aaff;
  font-size: 12px;
  text-align: center;
}

/* Visuals */
.toggle-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  cursor: pointer;
  padding: 10px;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,255,255,0.03);
  border-radius: 6px;
  transition: background 0.2s;
}
.toggle-row:hover { background: rgba(0,0,0,0.5); }
.toggle-row input { cursor: pointer; accent-color: #55aaff; width: 16px; height: 16px; }
.toggle-row span { font-size: 13px; color: #ddd; }

/* Animation Tab */
.anim-debug-container { display: flex; flex-direction: column; gap: 12px; }
.debug-lists { display: flex; gap: 12px; height: 160px; }
.debug-column { flex: 1; display: flex; flex-direction: column; background: rgba(0,0,0,0.4); border-radius: 6px; overflow: hidden; border: 1px solid rgba(255,255,255,0.03); }
.debug-column h3 { font-size: 11px; background: rgba(255,255,255,0.05); padding: 6px; margin: 0; text-align: center; color: #aaa; text-transform: uppercase; }
.anim-list-scroll { overflow-y: auto; flex: 1; padding: 4px 0; }
.anim-name { font-size: 11px; padding: 6px 12px; cursor: pointer; color: #888; border-bottom: 1px solid rgba(255,255,255,0.02); }
.anim-name:hover { background: rgba(255,255,255,0.05); color: #fff; }
.anim-name.active { background: rgba(85, 170, 255, 0.15); color: #55aaff; }

.debug-preview {
  height: 220px;
  background: rgba(0,0,0,0.6);
  border-radius: 6px;
  overflow: hidden;
  position: relative;
  border: 1px solid rgba(255,255,255,0.05);
}
.preview-canvas { width: 100%; height: 100%; }

/* Scrollbars */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.4); }
</style>