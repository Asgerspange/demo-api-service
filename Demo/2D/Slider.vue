<template>
    <div
        ref="timeline"
        class="dv-slider"
        :class="{ 'dv-slider--dragging': isDragging }"
        role="slider"
        :aria-valuemin="0"
        :aria-valuemax="totalTicks"
        :aria-valuenow="modelValue"
        aria-label="Round timeline"
        tabindex="0"
        @mousedown="startDrag"
        @mousemove="onDrag"
        @mouseup="stopDrag"
        @mouseleave="stopDrag"
        @click="onClick"
        @touchstart.passive="onTouchStart"
        @touchmove.passive="onTouchMove"
        @touchend="onTouchEnd"
        @keydown="onKeyDown"
    >
        <!-- Track -->
        <div class="dv-slider__track" />

        <!-- Phase segments (visual reference, not interactive) -->
        <div v-if="freezePercent > 0" class="dv-slider__phase dv-slider__phase--freeze" :style="{ width: freezePercent + '%' }" aria-hidden="true" />
        <div v-if="postPlantPercent !== null" class="dv-slider__phase dv-slider__phase--postplant" :style="{ left: postPlantPercent + '%', right: 0 }" aria-hidden="true" />

        <!-- Fill (current progress) -->
        <div class="dv-slider__fill" :style="{ width: fillWidth + '%' }" />

        <!-- Thumb -->
        <div class="dv-slider__thumb" :style="{ left: `calc(${fillWidth}% - 9px)` }" />

        <!-- Event markers (above the track) -->
        <div
            v-for="marker in markers"
            v-show="marker.percent !== null"
            :key="marker.type"
            class="dv-marker"
            :class="`dv-marker--${marker.type}`"
            :style="{ left: marker.percent + '%' }"
            :title="marker.label"
        >
            <div class="dv-marker__stem" />
            <div class="dv-marker__icon">
                <img :src="marker.icon" alt="" class="dv-marker__img" />
            </div>
        </div>
    </div>
</template>

<script setup>
import { ref, computed } from 'vue';

const props = defineProps({
    round:      { type: Object, required: true },
    modelValue: { type: Number, required: true },
});
const emit = defineEmits(['update:modelValue']);

const timeline   = ref(null);
const isDragging = ref(false);
let cachedRect = null;

const totalTicks = computed(() => Math.max(1, (props.round?.tickNumbers?.length ?? 1) - 1));
const fillWidth  = computed(() => (props.modelValue / totalTicks.value) * 100);

// ── Binary search for nearest tick ──────────────────────────────────────
function findClosestTickIndex(tickNumbers, target) {
    let lo = 0;
    let hi = tickNumbers.length - 1;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (tickNumbers[mid] < target) lo = mid + 1;
        else hi = mid;
    }
    if (lo > 0 && Math.abs(tickNumbers[lo - 1] - target) < Math.abs(tickNumbers[lo] - target)) {
        return lo - 1;
    }
    return lo;
}

function tickPercent(tickNumbers, target) {
    if (!tickNumbers?.length) return null;
    const idx = findClosestTickIndex(tickNumbers, target);
    return (idx / (tickNumbers.length - 1)) * 100;
}

// ── Phase rendering ─────────────────────────────────────────────────────
const freezePercent = computed(() => {
    const freezeEnd = props.round?.meta?.freeze_end;
    if (freezeEnd == null) return 0;
    return tickPercent(props.round?.tickNumbers, freezeEnd) ?? 0;
});

const postPlantPercent = computed(() => {
    const plantTick = props.round?.meta?.bomb_plant;
    if (plantTick == null) return null;
    return tickPercent(props.round?.tickNumbers, plantTick);
});

// ── Event markers ───────────────────────────────────────────────────────
const bombPlantPercent = computed(() => {
    const plantTick = props.round?.meta?.bomb_plant;
    if (plantTick == null) return null;
    return tickPercent(props.round?.tickNumbers, plantTick);
});

const bombExplosionPercent = computed(() => {
    if (props.round?.meta?.reason !== 'bomb_exploded') return null;
    const explodeTick = props.round?.meta?.end;
    if (explodeTick == null) return null;
    return tickPercent(props.round?.tickNumbers, explodeTick);
});

const bombDefusedPercent = computed(() => {
    if (props.round?.meta?.reason !== 'bomb_defused') return null;
    const defuseTick = props.round?.meta?.end;
    if (defuseTick == null) return null;
    return tickPercent(props.round?.tickNumbers, defuseTick);
});

const markers = computed(() => [
    { type: 'plant',   percent: bombPlantPercent.value,     icon: '/images/c4_planted.png', label: 'Bomb planted' },
    { type: 'explode', percent: bombExplosionPercent.value, icon: '/images/explosion.png',  label: 'Bomb exploded' },
    { type: 'defuse',  percent: bombDefusedPercent.value,   icon: '/images/defuser.webp',   label: 'Bomb defused' },
]);

// ── Input handling ──────────────────────────────────────────────────────
function getCachedOrFreshRect() {
    return cachedRect ?? (timeline.value?.getBoundingClientRect() ?? null);
}

function updatePosition(clientX) {
    const rect = getCachedOrFreshRect();
    if (!rect || !rect.width) return;
    const percent = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
    emit('update:modelValue', Math.round(percent * totalTicks.value));
}

function startDrag(e) {
    isDragging.value = true;
    cachedRect = timeline.value.getBoundingClientRect();
    updatePosition(e.clientX);
}

function onDrag(e) {
    if (isDragging.value) updatePosition(e.clientX);
}

function stopDrag() {
    isDragging.value = false;
    cachedRect = null;
}

function onClick(e) {
    cachedRect = timeline.value.getBoundingClientRect();
    updatePosition(e.clientX);
    cachedRect = null;
}

// ── Touch handling ──────────────────────────────────────────────────────
function onTouchStart(e) {
    if (!e.touches?.length) return;
    isDragging.value = true;
    cachedRect = timeline.value.getBoundingClientRect();
    updatePosition(e.touches[0].clientX);
}

function onTouchMove(e) {
    if (!isDragging.value || !e.touches?.length) return;
    updatePosition(e.touches[0].clientX);
}

function onTouchEnd() {
    isDragging.value = false;
    cachedRect = null;
}

// ── Keyboard ────────────────────────────────────────────────────────────
function onKeyDown(e) {
    const step = e.shiftKey ? 64 : 8; // shift = ~1 second jumps
    if (e.key === 'ArrowLeft') {
        e.preventDefault();
        emit('update:modelValue', Math.max(0, props.modelValue - step));
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        emit('update:modelValue', Math.min(totalTicks.value, props.modelValue + step));
    } else if (e.key === 'Home') {
        e.preventDefault();
        emit('update:modelValue', 0);
    } else if (e.key === 'End') {
        e.preventDefault();
        emit('update:modelValue', totalTicks.value);
    }
}
</script>

<style scoped>
.dv-slider {
    --slider-bg:      oklch(1 0 0 / 0.08);
    --slider-fill:    var(--main-color, #ff8c00);
    --slider-thumb:   oklch(0.96 0 0);
    --slider-freeze:  oklch(1 0 0 / 0.04);
    --slider-plant:   oklch(0.62 0.20 22 / 0.10);

    position: relative;
    flex: 1;
    height: 10px;
    border-radius: 4px;
    background: var(--slider-bg);
    cursor: pointer;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    touch-action: pan-y;
}

.dv-slider:focus-visible {
    outline: 2px solid var(--main-color, #ff8c00);
    outline-offset: 4px;
}

.dv-slider__track {
    position: absolute;
    inset: 0;
    border-radius: 4px;
    pointer-events: none;
}

/* Phase backgrounds (visual reference inside the track) */
.dv-slider__phase {
    position: absolute;
    top: 0;
    bottom: 0;
    border-radius: 4px;
    pointer-events: none;
}

.dv-slider__phase--freeze   { left: 0; background: var(--slider-freeze); }
.dv-slider__phase--postplant { background: var(--slider-plant); }

/* Fill (above phase backgrounds) — width updates per-tick, no transition (driven by playback RAF) */
.dv-slider__fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    background: var(--slider-fill);
    border-radius: 4px;
    pointer-events: none;
}

/* Thumb */
.dv-slider__thumb {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--slider-thumb);
    box-shadow: 0 4px 14px oklch(0 0 0 / 0.4);
    pointer-events: none;
    opacity: 0;
    transition: opacity 150ms ease, transform 150ms ease;
}

.dv-slider:hover .dv-slider__thumb,
.dv-slider:focus-visible .dv-slider__thumb,
.dv-slider--dragging .dv-slider__thumb {
    opacity: 1;
}

/* ── Event markers ── */
.dv-marker {
    position: absolute;
    left: 0;
    bottom: 100%;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    pointer-events: none;
    margin-bottom: 4px;
}

.dv-marker__stem {
    width: 2px;
    height: 8px;
    border-radius: 1px;
    margin-top: 2px;
    order: 2;
}

.dv-marker__icon {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    padding: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    order: 1;
    transition: transform 150ms ease;
}

.dv-marker__img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    filter: invert(1);
}

.dv-marker--plant .dv-marker__icon, .dv-marker--explode .dv-marker__icon {
    background: oklch(0.62 0.20 22);
    box-shadow: 0 4px 12px oklch(0.62 0.20 22 / 0.45);
}
.dv-marker--plant .dv-marker__stem, .dv-marker--explode .dv-marker__stem {
    background: oklch(0.62 0.20 22);
}

.dv-marker--defuse .dv-marker__icon {
    background: oklch(0.55 0.18 235);
    box-shadow: 0 4px 12px oklch(0.55 0.18 235 / 0.45);
}
.dv-marker--defuse .dv-marker__stem { background: oklch(0.55 0.18 235); }

/* Mobile: bigger touch target */
@media (max-width: 640px) {
    .dv-slider { height: 14px; }
    .dv-slider__thumb {
        width: 22px;
        height: 22px;
        opacity: 1;
    }
    .dv-marker__icon {
        width: 18px;
        height: 18px;
        padding: 3px;
    }
}

@media (prefers-reduced-motion: reduce) {
    .dv-slider,
    .dv-slider__fill,
    .dv-slider__thumb,
    .dv-marker__icon {
        transition: none;
    }
}
</style>
