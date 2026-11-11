<template>
    <Transition name="filter-slide">
        <div v-if="show" class="dv-filters" role="dialog" aria-label="Compare filters">

            <!-- Header -->
            <header class="dv-filters__head">
                <span class="dv-filters__kicker">Filters</span>
                <button class="dv-icon-btn" aria-label="Close filters" @click="$emit('close')">
                    <Icon icon="lucide:x" class="dv-icon" />
                </button>
            </header>

            <div class="dv-filters__body">

                <!-- Side -->
                <section class="dv-section">
                    <div class="dv-section__label">Side</div>
                    <div class="dv-seg">
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': modelTeamFilter === 'both' }" @click="$emit('update:modelTeamFilter', 'both')">Both</button>
                        <button class="dv-seg__btn dv-seg__btn--ct" :class="{ 'dv-seg__btn--active': modelTeamFilter === 'ct' }" @click="$emit('update:modelTeamFilter', 'ct')">CT</button>
                        <button class="dv-seg__btn dv-seg__btn--t" :class="{ 'dv-seg__btn--active': modelTeamFilter === 't' }" @click="$emit('update:modelTeamFilter', 't')">T</button>
                    </div>
                </section>

                <!-- Utility -->
                <section class="dv-section dv-section--row">
                    <div class="dv-section__main">
                        <div class="dv-section__label">Utility</div>
                        <p class="dv-section__hint">Smokes, molotovs, HE, flashes</p>
                    </div>
                    <button
                        class="dv-toggle"
                        :class="{ 'dv-toggle--on': modelShowUtil }"
                        :aria-pressed="modelShowUtil"
                        @click="$emit('update:modelShowUtil', !modelShowUtil)"
                    >
                        <span class="dv-toggle__thumb" />
                    </button>
                </section>

                <!-- Players -->
                <section class="dv-section">
                    <div class="dv-section__head">
                        <div class="dv-section__label">Players</div>
                        <button
                            v-if="modelPlayerFilter !== null"
                            class="dv-link"
                            @click="$emit('update:modelPlayerFilter', null)"
                        >Show all</button>
                    </div>

                    <div v-if="!players.length" class="dv-section__empty">
                        No players loaded yet
                    </div>

                    <ul v-else class="dv-player-list">
                        <li v-for="p in players" :key="p.steamid">
                            <button
                                class="dv-player-row"
                                :class="{ 'dv-player-row--selected': isPlayerSelected(p.steamid) }"
                                @click="togglePlayer(p.steamid)"
                            >
                                <span class="dv-player-row__dot" :style="{ backgroundColor: p.team_name === 'ct' ? 'oklch(0.65 0.10 220)' : 'oklch(0.75 0.12 60)' }" />
                                <span class="dv-player-row__name">{{ p.name }}</span>
                                <span class="dv-player-row__team" :class="`dv-player-row__team--${p.team_name}`">{{ p.team_name }}</span>
                                <Icon v-if="isPlayerSelected(p.steamid)" icon="lucide:check" class="dv-icon dv-player-row__check" />
                            </button>
                        </li>
                    </ul>
                </section>

            </div>

            <!-- Reset -->
            <footer class="dv-filters__foot">
                <button class="dv-btn dv-btn--ghost" @click="resetAll">Reset filters</button>
            </footer>

        </div>
    </Transition>
</template>

<script setup>
import { Icon } from '@iconify/vue';

const props = defineProps({
    show:              { type: Boolean, default: false },
    players:           { type: Array,   default: () => [] },
    modelTeamFilter:   { type: String,  default: 'both' },
    modelPlayerFilter: { default: null },
    modelShowUtil:     { type: Boolean, default: true },
});
const emit = defineEmits([
    'close',
    'update:modelTeamFilter',
    'update:modelPlayerFilter',
    'update:modelShowUtil',
]);

function isPlayerSelected(steamid) {
    return props.modelPlayerFilter !== null && props.modelPlayerFilter.includes(steamid);
}

function togglePlayer(steamid) {
    const current = props.modelPlayerFilter ?? [];
    const next = current.includes(steamid)
        ? current.filter(s => s !== steamid)
        : [...current, steamid];
    emit('update:modelPlayerFilter', next.length === 0 ? null : next);
}

function resetAll() {
    emit('update:modelTeamFilter',   'both');
    emit('update:modelPlayerFilter', null);
    emit('update:modelShowUtil',     true);
}
</script>

<style scoped>
.dv-filters {
    --dv-bg:        oklch(0.125 0.012 250);
    --dv-surface:   oklch(0.175 0.014 250);
    --dv-surface-2: oklch(0.215 0.016 250);
    --dv-border:    oklch(1 0 0 / 0.09);
    --dv-border-2:  oklch(1 0 0 / 0.14);
    --dv-text:      oklch(1 0 0 / 0.96);
    --dv-text-2:    oklch(1 0 0 / 0.70);
    --dv-text-3:    oklch(1 0 0 / 0.62);
    --dv-text-4:    oklch(1 0 0 / 0.50);
    --dv-accent:    #ff8c00;
    --dv-sans:      'Schibsted Grotesk', sans-serif;
    --dv-mono:      'JetBrains Mono', monospace;

    width: 280px;
    max-width: calc(100vw - 24px);
    /* Height is bounded by the .dv-flyout flex parent in Viewer.vue. */
    min-height: 0;
    background: var(--dv-bg);
    border: 1px solid var(--dv-border-2);
    border-radius: 8px;
    box-shadow: 0 24px 48px -16px oklch(0 0 0 / 0.6);
    display: flex;
    flex-direction: column;
    color: var(--dv-text);
    font-family: var(--dv-sans);
    overflow: hidden;
}

.dv-filters__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 11px 14px;
    background: var(--dv-surface);
    border-bottom: 1px solid var(--dv-border);
    flex-shrink: 0;
}

.dv-filters__kicker {
    font-family: var(--dv-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--dv-text-2);
}

.dv-icon-btn {
    background: none;
    border: none;
    color: var(--dv-text-3);
    cursor: pointer;
    padding: 5px;
    border-radius: 4px;
    display: inline-flex;
    transition: color 150ms ease, background 150ms ease;
}
.dv-icon-btn:hover { color: var(--dv-text); background: var(--dv-surface-2); }
.dv-icon-btn:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; }

.dv-icon { width: 14px; height: 14px; }

.dv-filters__body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--dv-border-2) transparent;
}
.dv-filters__body::-webkit-scrollbar { width: 5px; }
.dv-filters__body::-webkit-scrollbar-thumb { background: var(--dv-border-2); border-radius: 3px; }

/* ── Sections ── */
.dv-section {
    padding: 12px 14px;
    border-bottom: 1px solid var(--dv-border);
}
.dv-section:last-child { border-bottom: none; }

.dv-section--row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.dv-section__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }

.dv-section__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}

.dv-section__label {
    font-family: var(--dv-mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--dv-text-3);
    margin-bottom: 6px;
}

.dv-section--row .dv-section__label { margin-bottom: 0; }
.dv-section__head .dv-section__label { margin-bottom: 0; }

.dv-section__hint {
    font-family: var(--dv-sans);
    font-size: 11px;
    color: var(--dv-text-3);
    margin: 0;
}

.dv-section__empty {
    font-family: var(--dv-sans);
    font-size: 12px;
    color: var(--dv-text-3);
    text-align: center;
    padding: 14px 0;
}

/* ── Segmented control ── */
.dv-seg {
    display: flex;
    gap: 2px;
    background: var(--dv-surface);
    border: 1px solid var(--dv-border);
    border-radius: 4px;
    padding: 2px;
}

.dv-seg__btn {
    flex: 1;
    min-width: 0;
    padding: 6px 10px;
    background: none;
    border: none;
    border-radius: 2px;
    font-family: var(--dv-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--dv-text-3);
    cursor: pointer;
    transition: color 150ms ease, background 150ms ease;
}
.dv-seg__btn:hover { color: var(--dv-text-2); }
.dv-seg__btn--active {
    background: var(--dv-surface-2);
    color: var(--dv-text);
}
.dv-seg__btn--ct.dv-seg__btn--active  { color: oklch(0.75 0.10 220); }
.dv-seg__btn--t.dv-seg__btn--active   { color: oklch(0.80 0.13 60); }
.dv-seg__btn:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; }

/* ── Toggle ── */
.dv-toggle {
    width: 36px;
    height: 22px;
    border-radius: 12px;
    border: 1px solid var(--dv-border);
    background: var(--dv-surface);
    position: relative;
    cursor: pointer;
    transition: background 180ms ease, border-color 180ms ease;
    flex-shrink: 0;
}

.dv-toggle__thumb {
    position: absolute;
    top: 1px;
    left: 1px;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--dv-text-3);
    transition: transform 180ms cubic-bezier(0.22, 1, 0.36, 1), background 180ms ease;
}

.dv-toggle--on {
    background: color-mix(in oklch, var(--dv-accent) 22%, var(--dv-surface));
    border-color: color-mix(in oklch, var(--dv-accent) 40%, var(--dv-border));
}

.dv-toggle--on .dv-toggle__thumb {
    transform: translateX(14px);
    background: var(--dv-accent);
}

.dv-toggle:focus-visible {
    outline: 2px solid var(--dv-accent);
    outline-offset: 2px;
}

/* ── Player list ── */
.dv-player-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
}

.dv-player-row {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 9px;
    background: none;
    border: 1px solid transparent;
    border-radius: 3px;
    cursor: pointer;
    text-align: left;
    transition: background 120ms ease, border-color 120ms ease;
}
.dv-player-row:hover { background: var(--dv-surface); }
.dv-player-row--selected {
    background: var(--dv-surface);
    border-color: var(--dv-border-2);
}
.dv-player-row:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; }

.dv-player-row__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.dv-player-row__name {
    font-family: var(--dv-sans);
    font-size: 12px;
    font-weight: 500;
    color: var(--dv-text);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.dv-player-row__team {
    font-family: var(--dv-mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 1px 5px;
    border-radius: 2px;
    line-height: 1.4;
}
.dv-player-row__team--ct {
    color: oklch(0.75 0.10 220);
    background: color-mix(in oklch, oklch(0.65 0.10 220) 18%, transparent);
}
.dv-player-row__team--t {
    color: oklch(0.80 0.13 60);
    background: color-mix(in oklch, oklch(0.65 0.13 60) 18%, transparent);
}

.dv-player-row__check { color: var(--dv-accent); }

/* ── Link ── */
.dv-link {
    background: none;
    border: none;
    cursor: pointer;
    padding: 2px 4px;
    font-family: var(--dv-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--dv-accent);
}
.dv-link:hover { color: oklch(0.62 0.20 50); }
.dv-link:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; border-radius: 2px; }

/* ── Footer ── */
.dv-filters__foot {
    padding: 10px 14px;
    background: var(--dv-surface);
    border-top: 1px solid var(--dv-border);
    flex-shrink: 0;
}

.dv-btn {
    width: 100%;
    padding: 9px 12px;
    border-radius: 4px;
    border: 1px solid var(--dv-border-2);
    font-family: var(--dv-mono);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    background: transparent;
    color: var(--dv-text-2);
    transition: background 150ms ease, color 150ms ease, border-color 150ms ease;
}
.dv-btn:hover {
    background: var(--dv-surface-2);
    color: var(--dv-text);
}
.dv-btn:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; }

/* ── Transition ── */
.filter-slide-enter-active, .filter-slide-leave-active {
    transition: opacity 180ms cubic-bezier(0.22, 1, 0.36, 1),
                transform  180ms cubic-bezier(0.22, 1, 0.36, 1);
}
.filter-slide-enter-from, .filter-slide-leave-to {
    opacity: 0;
    transform: translateY(-6px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
    .filter-slide-enter-active, .filter-slide-leave-active {
        transition: opacity 100ms ease;
    }
    .filter-slide-enter-from, .filter-slide-leave-to { transform: none; }
}

@media (max-width: 640px) {
    .dv-filters {
        width: 100vw;
        max-width: 100vw;
        max-height: 70dvh;
        border-radius: 8px 8px 0 0;
        border-bottom: none;
    }
}
</style>
