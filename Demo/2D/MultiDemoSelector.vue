<template>
    <Transition name="selector-slide">
        <div class="dv-selector" role="dialog" aria-label="Compare rounds">

            <!-- Header -->
            <header class="dv-selector__head">
                <div class="dv-selector__title">
                    <span class="dv-selector__kicker">Compare</span>
                    <span class="dv-selector__count" v-if="selectedRounds.length > 0">
                        {{ selectedRounds.length }} selected
                    </span>
                </div>
                <button class="dv-icon-btn" aria-label="Close" @click="$emit('cancel')">
                    <Icon icon="lucide:x" class="dv-icon" />
                </button>
            </header>

            <!-- Demo tabs (only if more than 1) -->
            <nav v-if="allDemos.length > 1" class="dv-selector__tabs" aria-label="Demo source">
                <button
                    v-for="d in allDemos"
                    :key="d.externalId"
                    class="dv-selector__tab"
                    :class="{ 'dv-selector__tab--active': activeDemoTab === d.externalId }"
                    :title="d.name"
                    @click="activeDemoTab = d.externalId"
                >
                    {{ d.name }}
                </button>
            </nav>
            <p v-else-if="allDemos.length === 1" class="dv-selector__single">
                {{ allDemos[0]?.name }}
            </p>

            <!-- Filters -->
            <div class="dv-selector__filters">
                <div class="dv-filter">
                    <span class="dv-filter__label">Side</span>
                    <div class="dv-seg">
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': sideFilter === 'all' }" @click="sideFilter = 'all'">All</button>
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': sideFilter === 'ct' }" @click="sideFilter = 'ct'">CT</button>
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': sideFilter === 't'  }" @click="sideFilter = 't'">T</button>
                    </div>
                </div>

                <div class="dv-filter">
                    <span class="dv-filter__label">Outcome</span>
                    <div class="dv-seg">
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': outcomeFilter === 'all' }" @click="outcomeFilter = 'all'">All</button>
                        <button class="dv-seg__btn dv-seg__btn--win"  :class="{ 'dv-seg__btn--active': outcomeFilter === 'win'  }" @click="outcomeFilter = 'win'">Win</button>
                        <button class="dv-seg__btn dv-seg__btn--loss" :class="{ 'dv-seg__btn--active': outcomeFilter === 'loss' }" @click="outcomeFilter = 'loss'">Loss</button>
                    </div>
                </div>

                <div class="dv-filter dv-filter--full">
                    <span class="dv-filter__label">Phase</span>
                    <div class="dv-seg dv-seg--wrap">
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': phaseFilter === 'all'    }" @click="phaseFilter = 'all'">All</button>
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': phaseFilter === 'pistol' }" @click="phaseFilter = 'pistol'">Pistol</button>
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': phaseFilter === 'first6' }" @click="phaseFilter = 'first6'">First 6</button>
                        <button class="dv-seg__btn" :class="{ 'dv-seg__btn--active': phaseFilter === 'late'   }" @click="phaseFilter = 'late'">Late</button>
                    </div>
                </div>
            </div>

            <!-- Bulk actions -->
            <div class="dv-selector__bulk">
                <button class="dv-link" @click="selectAll" :disabled="!filteredRounds.length">
                    Select all visible ({{ filteredRounds.length }})
                </button>
                <button class="dv-link dv-link--quiet" @click="selectNone" :disabled="!hasAnySelected">
                    Clear
                </button>
            </div>

            <!-- Round list -->
            <div class="dv-selector__list">
                <template v-if="!filteredRounds.length">
                    <p class="dv-selector__empty">No rounds match these filters.</p>
                </template>

                <button
                    v-for="r in filteredRounds"
                    :key="`${activeTabDemo?.externalId}-${r.round_index}`"
                    class="dv-round-row"
                    :class="{
                        'dv-round-row--selected': isSelected(r.round_index),
                        'dv-round-row--win':  outcomeFor(r) === 'win',
                        'dv-round-row--loss': outcomeFor(r) === 'loss',
                    }"
                    @click="toggle(r.round_index)"
                >
                    <span
                        class="dv-round-row__color"
                        :style="isSelected(r.round_index)
                            ? { backgroundColor: selectionColor(r.round_index) }
                            : { background: 'transparent', borderColor: 'var(--dv-border-2)' }"
                    />
                    <div class="dv-round-row__main">
                        <span class="dv-round-row__title">
                            R{{ r.round_index }}
                            <span class="dv-round-row__side" :class="`dv-round-row__side--${sideFor(r)}`">{{ sideFor(r).toUpperCase() }}</span>
                        </span>
                        <span class="dv-round-row__meta">
                            <span class="dv-round-row__score">
                                <span class="dv-round-row__score-ct">{{ r.meta?.CT_score ?? '–' }}</span>
                                <span class="dv-round-row__score-sep">:</span>
                                <span class="dv-round-row__score-t">{{ r.meta?.T_score ?? '–' }}</span>
                            </span>
                            <span v-if="r.meta?.reason" class="dv-round-row__reason">
                                {{ reasonShort(r.meta.reason) }}
                            </span>
                        </span>
                    </div>
                    <span v-if="isSelected(r.round_index)" class="dv-round-row__check">
                        <Icon icon="lucide:check" class="dv-icon" />
                    </span>
                </button>
            </div>

            <!-- Remove secondary demo link -->
            <div
                v-if="activeDemoTab !== String(primaryDemo?.external_id ?? primaryDemo?.id)"
                class="dv-selector__remove"
            >
                <button class="dv-link dv-link--danger" @click="removeAndSwitch">
                    Remove this demo
                </button>
            </div>

            <!-- Footer -->
            <footer class="dv-selector__foot">
                <button class="dv-btn dv-btn--ghost" @click="$emit('cancel')">Cancel</button>
                <button
                    class="dv-btn dv-btn--primary"
                    :disabled="selectedRounds.length === 0"
                    @click="selectedRounds.length > 0 && $emit('apply')"
                >
                    Compare{{ selectedRounds.length > 0 ? ` (${selectedRounds.length})` : '' }}
                </button>
            </footer>
        </div>
    </Transition>
</template>

<script setup>
import { ref, computed } from 'vue';
import { Icon } from '@iconify/vue';

const props = defineProps({
    primaryDemo:      { type: Object,   default: null },
    primaryRounds:    { type: Array,    default: () => [] },
    loadedDemos:      { type: Map,      default: () => new Map() },
    selectedRounds:   { type: Array,    default: () => [] },
    isRoundSelected:  { type: Function, required: true },
    userSteamId:      { type: String,   default: null },
});
const emit = defineEmits(['toggle-round', 'apply', 'cancel', 'add-demo', 'remove-demo']);

// ── Demos & active tab ──────────────────────────────────────────────────
const allDemos = computed(() => {
    const primary = props.primaryDemo ? [{
        externalId: String(props.primaryDemo.external_id ?? props.primaryDemo.id),
        id: props.primaryDemo.id,
        name: props.primaryDemo.name ?? 'Primary',
        rounds: props.primaryRounds,
    }] : [];
    return [...primary, ...props.loadedDemos.values()];
});

const activeDemoTab = ref(allDemos.value[0]?.externalId ?? '');
const activeTabDemo = computed(() => allDemos.value.find(d => d.externalId === activeDemoTab.value) ?? null);

// ── Filters ─────────────────────────────────────────────────────────────
const sideFilter    = ref('all');   // 'all' | 'ct' | 't'
const outcomeFilter = ref('all');   // 'all' | 'win' | 'loss'
const phaseFilter   = ref('all');   // 'all' | 'pistol' | 'first6' | 'late'

function sideFor(round) {
    // The team uploading determines side. For the simple selector we infer
    // from the active round's winner alignment with the team's steamid.
    const winners = round.meta?.winners ?? [];
    if (props.userSteamId && winners.includes(String(props.userSteamId))) {
        return (round.meta?.winner || '').toLowerCase() === 'ct' ? 'ct' : 't';
    }
    // fall back: take the side that has more rounds to date at this point
    const ct = Number(round.meta?.CT_score ?? 0);
    const t  = Number(round.meta?.T_score  ?? 0);
    return ct >= t ? 'ct' : 't';
}

function outcomeFor(round) {
    const winners = round.meta?.winners ?? [];
    if (!props.userSteamId || !winners.length) return 'unknown';
    return winners.includes(String(props.userSteamId)) ? 'win' : 'loss';
}

function phaseFor(round) {
    const idx = round.round_index;
    if (idx === 1 || idx === 13) return 'pistol';
    if (idx <= 6 || (idx >= 13 && idx <= 18)) return 'first6';
    return 'late';
}

const filteredRounds = computed(() => {
    if (!activeTabDemo.value) return [];
    return (activeTabDemo.value.rounds ?? []).filter(r => {
        if (sideFilter.value !== 'all' && sideFor(r) !== sideFilter.value) return false;
        if (outcomeFilter.value !== 'all') {
            const o = outcomeFor(r);
            if (o === 'unknown') return false;
            if (o !== outcomeFilter.value) return false;
        }
        if (phaseFilter.value !== 'all' && phaseFor(r) !== phaseFilter.value) return false;
        return true;
    });
});

// ── Selection ───────────────────────────────────────────────────────────
const isSelected = (roundIndex) =>
    activeTabDemo.value
        ? props.isRoundSelected(activeTabDemo.value.externalId, roundIndex)
        : false;

const hasAnySelected = computed(() => props.selectedRounds.length > 0);

function toggle(roundIndex) {
    if (!activeTabDemo.value) return;
    emit('toggle-round', {
        externalId: activeTabDemo.value.externalId,
        demoId:     activeTabDemo.value.id,
        demoName:   activeTabDemo.value.name,
        roundIndex,
    });
}

function selectAll() {
    if (!activeTabDemo.value) return;
    filteredRounds.value.forEach(r => {
        if (!isSelected(r.round_index)) toggle(r.round_index);
    });
}

function selectNone() {
    if (!activeTabDemo.value) return;
    (activeTabDemo.value.rounds ?? []).forEach(r => {
        if (isSelected(r.round_index)) toggle(r.round_index);
    });
}

function removeAndSwitch() {
    const id = activeDemoTab.value;
    emit('remove-demo', id);
    activeDemoTab.value = String(props.primaryDemo?.external_id ?? props.primaryDemo?.id);
}

// ── Color (matches useMultiDemo logic) ──────────────────────────────────
function selectionColor(roundIndex) {
    if (!activeTabDemo.value) return 'transparent';
    const idx = props.selectedRounds.findIndex(r =>
        r.externalId === activeTabDemo.value.externalId && r.roundIndex === roundIndex
    );
    if (idx === -1) return 'transparent';
    return `hsl(${(idx * 137.508) % 360}, 70%, 60%)`;
}

const REASON_LABELS = {
    bomb_defused: 'Defused',
    bomb_exploded: 'Bomb',
    target_bombed: 'Bomb',
    ct_killed: 'Elimination',
    t_killed: 'Elimination',
    target_saved: 'Time',
    saved_by_time: 'Time',
};
function reasonShort(reason) {
    return REASON_LABELS[reason] ?? reason.replace(/_/g, ' ');
}
</script>

<style scoped>
.dv-selector {
    /* Team-page-aligned palette */
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
    --dv-win:       oklch(0.72 0.14 145);
    --dv-loss:      oklch(0.62 0.20 22);
    --dv-sans:      'Schibsted Grotesk', 'Helvetica Neue', Arial, sans-serif;
    --dv-mono:      'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;

    width: 320px;
    max-width: calc(100vw - 24px);
    /* Height is bounded by the .dv-flyout flex parent in Viewer.vue; this just
       lets the panel shrink so the round list scrolls instead of overflowing. */
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--dv-bg);
    border: 1px solid var(--dv-border-2);
    border-radius: 8px;
    box-shadow: 0 24px 48px -16px oklch(0 0 0 / 0.6);
    color: var(--dv-text);
    font-family: var(--dv-sans);
    overflow: hidden;
}

/* ── Header ── */
.dv-selector__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 11px 14px;
    border-bottom: 1px solid var(--dv-border);
    background: var(--dv-surface);
    flex-shrink: 0;
}

.dv-selector__title {
    display: flex;
    align-items: baseline;
    gap: 10px;
    min-width: 0;
}

.dv-selector__kicker {
    font-family: var(--dv-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--dv-text-2);
}

.dv-selector__count {
    font-family: var(--dv-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--dv-accent);
    padding: 2px 7px;
    border-radius: 2px;
    background: color-mix(in oklch, var(--dv-accent) 12%, transparent);
}

.dv-icon-btn {
    background: none;
    border: none;
    color: var(--dv-text-3);
    cursor: pointer;
    padding: 5px;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: color 150ms ease, background 150ms ease;
}
.dv-icon-btn:hover { color: var(--dv-text); background: var(--dv-surface-2); }
.dv-icon-btn:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; }

.dv-icon { width: 14px; height: 14px; }

/* ── Demo tabs ── */
.dv-selector__tabs {
    display: flex;
    border-bottom: 1px solid var(--dv-border);
    background: var(--dv-bg);
    overflow-x: auto;
    scrollbar-width: none;
    flex-shrink: 0;
}
.dv-selector__tabs::-webkit-scrollbar { display: none; }

.dv-selector__tab {
    flex-shrink: 0;
    padding: 9px 14px;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    font-family: var(--dv-sans);
    font-size: 12px;
    font-weight: 500;
    color: var(--dv-text-3);
    cursor: pointer;
    white-space: nowrap;
    max-width: 140px;
    overflow: hidden;
    text-overflow: ellipsis;
    transition: color 150ms ease, border-color 150ms ease;
}
.dv-selector__tab:hover { color: var(--dv-text-2); }
.dv-selector__tab--active {
    color: var(--dv-text);
    border-bottom-color: var(--dv-accent);
}

.dv-selector__single {
    padding: 8px 14px;
    margin: 0;
    border-bottom: 1px solid var(--dv-border);
    font-family: var(--dv-mono);
    font-size: 11px;
    color: var(--dv-text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex-shrink: 0;
}

/* ── Filters ── */
.dv-selector__filters {
    padding: 10px 14px;
    border-bottom: 1px solid var(--dv-border);
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    background: var(--dv-bg);
    flex-shrink: 0;
}

.dv-filter { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.dv-filter--full { grid-column: span 2; }

.dv-filter__label {
    font-family: var(--dv-mono);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--dv-text-3);
}

.dv-seg {
    display: flex;
    gap: 2px;
    background: var(--dv-surface);
    border: 1px solid var(--dv-border);
    border-radius: 4px;
    padding: 2px;
}
.dv-seg--wrap { flex-wrap: wrap; }

.dv-seg__btn {
    flex: 1;
    min-width: 0;
    padding: 5px 8px;
    background: none;
    border: none;
    border-radius: 2px;
    font-family: var(--dv-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--dv-text-3);
    cursor: pointer;
    transition: color 150ms ease, background 150ms ease;
    white-space: nowrap;
}
.dv-seg__btn:hover { color: var(--dv-text-2); }
.dv-seg__btn--active {
    background: var(--dv-surface-2);
    color: var(--dv-text);
}
.dv-seg__btn--win.dv-seg__btn--active  { color: var(--dv-win); }
.dv-seg__btn--loss.dv-seg__btn--active { color: var(--dv-loss); }
.dv-seg__btn:focus-visible {
    outline: 2px solid var(--dv-accent);
    outline-offset: 2px;
}

/* ── Bulk actions ── */
.dv-selector__bulk {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 14px;
    border-bottom: 1px solid var(--dv-border);
    flex-shrink: 0;
}

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
    transition: color 150ms ease;
}
.dv-link:hover { color: oklch(0.62 0.20 50); }
.dv-link:disabled { color: var(--dv-text-4); cursor: not-allowed; }
.dv-link--quiet { color: var(--dv-text-3); }
.dv-link--quiet:hover { color: var(--dv-text); }
.dv-link--danger { color: var(--dv-loss); }
.dv-link--danger:hover { color: oklch(0.7 0.2 22); }
.dv-link:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; border-radius: 2px; }

/* ── Round list ── */
.dv-selector__list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 6px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    scrollbar-width: thin;
    scrollbar-color: var(--dv-border-2) transparent;
}
.dv-selector__list::-webkit-scrollbar { width: 5px; }
.dv-selector__list::-webkit-scrollbar-thumb { background: var(--dv-border-2); border-radius: 3px; }

.dv-selector__empty {
    text-align: center;
    padding: 20px;
    margin: 0;
    font-family: var(--dv-sans);
    font-size: 12px;
    color: var(--dv-text-3);
}

.dv-round-row {
    display: grid;
    grid-template-columns: 12px 1fr auto;
    gap: 10px;
    align-items: center;
    padding: 8px 10px;
    background: none;
    border: 1px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    text-align: left;
    transition: background 120ms ease, border-color 120ms ease;
}
.dv-round-row:hover { background: var(--dv-surface); }
.dv-round-row--selected {
    background: var(--dv-surface);
    border-color: var(--dv-border-2);
}
.dv-round-row:focus-visible {
    outline: 2px solid var(--dv-accent);
    outline-offset: -2px;
}

.dv-round-row__color {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 1px solid var(--dv-border-2);
    flex-shrink: 0;
}

.dv-round-row__main {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
}

.dv-round-row__title {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: var(--dv-mono);
    font-size: 12px;
    font-weight: 700;
    color: var(--dv-text);
    letter-spacing: 0.02em;
}

.dv-round-row__side {
    font-family: var(--dv-mono);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.08em;
    padding: 1px 5px;
    border-radius: 2px;
    line-height: 1.4;
}
.dv-round-row__side--ct {
    color: oklch(0.70 0.10 220);
    background: color-mix(in oklch, oklch(0.65 0.10 220) 18%, transparent);
}
.dv-round-row__side--t {
    color: oklch(0.75 0.12 60);
    background: color-mix(in oklch, oklch(0.65 0.13 60) 18%, transparent);
}

.dv-round-row__meta {
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    font-family: var(--dv-mono);
    font-size: 10px;
    color: var(--dv-text-3);
}

.dv-round-row__score {
    font-variant-numeric: tabular-nums;
}

.dv-round-row__score-ct { color: oklch(0.70 0.10 220); }
.dv-round-row__score-t  { color: oklch(0.75 0.12 60); }
.dv-round-row__score-sep { color: var(--dv-text-4); margin: 0 1px; }

.dv-round-row__reason {
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--dv-text-3);
}

.dv-round-row__check {
    color: var(--dv-accent);
    display: inline-flex;
    align-items: center;
}

/* Win/loss tinting on rows */
.dv-round-row--win:not(.dv-round-row--selected) { box-shadow: inset 2px 0 0 0 color-mix(in oklch, var(--dv-win) 60%, transparent); }
.dv-round-row--loss:not(.dv-round-row--selected) { box-shadow: inset 2px 0 0 0 color-mix(in oklch, var(--dv-loss) 60%, transparent); }

/* ── Remove demo link ── */
.dv-selector__remove {
    padding: 8px 14px;
    border-top: 1px solid var(--dv-border);
    background: var(--dv-bg);
    flex-shrink: 0;
}

/* ── Footer ── */
.dv-selector__foot {
    display: flex;
    gap: 8px;
    padding: 10px 14px;
    border-top: 1px solid var(--dv-border);
    background: var(--dv-surface);
    flex-shrink: 0;
}

.dv-btn {
    flex: 1;
    padding: 9px 12px;
    border-radius: 4px;
    border: 1px solid transparent;
    font-family: var(--dv-mono);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 150ms ease, color 150ms ease, border-color 150ms ease;
}
.dv-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.dv-btn:focus-visible { outline: 2px solid var(--dv-accent); outline-offset: 2px; }

.dv-btn--ghost {
    background: transparent;
    color: var(--dv-text-2);
    border-color: var(--dv-border-2);
}
.dv-btn--ghost:hover:not(:disabled) {
    background: var(--dv-surface-2);
    color: var(--dv-text);
}

.dv-btn--primary {
    background: var(--dv-accent);
    color: oklch(0.125 0.012 250);
    border-color: var(--dv-accent);
}
.dv-btn--primary:hover:not(:disabled) {
    background: oklch(0.62 0.20 50);
    color: var(--dv-text);
    border-color: oklch(0.62 0.20 50);
}

/* ── Transitions ── */
.selector-slide-enter-active, .selector-slide-leave-active {
    transition: opacity 180ms cubic-bezier(0.22, 1, 0.36, 1),
                transform  180ms cubic-bezier(0.22, 1, 0.36, 1);
}
.selector-slide-enter-from, .selector-slide-leave-to {
    opacity: 0;
    transform: translateY(-6px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
    .selector-slide-enter-active, .selector-slide-leave-active {
        transition: opacity 100ms ease;
    }
    .selector-slide-enter-from, .selector-slide-leave-to {
        transform: none;
    }
}

/* ── Mobile: bottom-sheet pattern ── */
@media (max-width: 640px) {
    .dv-selector {
        width: 100vw;
        max-width: 100vw;
        max-height: 70dvh;
        border-radius: 8px 8px 0 0;
        border-bottom: none;
    }
    .dv-selector__filters { grid-template-columns: 1fr; }
    .dv-filter--full { grid-column: span 1; }
}
</style>
