<template>
    <Teleport to="body">
        <div class="dsm" role="dialog" aria-modal="true" aria-label="Add demo to compare">
            <div class="dsm__backdrop" @click="$emit('close')" />

            <div class="dsm__panel" role="document">

                <header class="dsm__head">
                    <div class="dsm__title">
                        <span class="dsm__kicker">Compare</span>
                        <h2 class="dsm__heading">Add demo</h2>
                    </div>
                    <button class="dsm__close" aria-label="Close" @click="$emit('close')">
                        <Icon icon="lucide:x" class="dsm__icon" />
                    </button>
                </header>

                <!-- Filter toolbar -->
                <div class="dsm__filters">
                    <label class="dsm__search">
                        <Icon icon="lucide:search" class="dsm__icon dsm__icon--search" />
                        <input
                            v-model="search"
                            type="search"
                            class="dsm__search-input"
                            placeholder="Search demos…"
                            ref="searchInput"
                        />
                    </label>

                    <select v-model="mapFilter" class="dsm__select" aria-label="Filter by map">
                        <option :value="null">All maps</option>
                        <option v-for="m in availableMaps" :key="m" :value="m">{{ mapName(m) }}</option>
                    </select>

                    <div class="dsm__count">
                        <span class="dsm__count-num">{{ filtered.length }}</span>
                        <span class="dsm__count-sep">/</span>
                        <span class="dsm__count-tot">{{ allDemos?.length ?? 0 }}</span>
                    </div>
                </div>

                <!-- Demo list -->
                <div class="dsm__list" ref="listEl">
                    <p v-if="!filtered.length" class="dsm__empty">No demos match these filters.</p>

                    <button
                        v-for="(demo, idx) in filtered"
                        :key="demo.id"
                        class="dsm-row"
                        :class="{
                            'dsm-row--cursor': cursor === idx,
                            'dsm-row--added': alreadyAdded(demo),
                        }"
                        @click="select(demo)"
                        @mouseenter="cursor = idx"
                        ref="rowEls"
                    >
                        <div class="dsm-row__map" :data-map="shortMap(demo.map)">
                            <div class="dsm-row__map-name">{{ mapShortName(demo.map) }}</div>
                        </div>

                        <div class="dsm-row__main">
                            <span class="dsm-row__name">{{ demo.name || 'Untitled demo' }}</span>
                            <span class="dsm-row__meta">
                                <span class="dsm-row__date">{{ formatDate(demo.created_at) }}</span>
                                <span class="dsm-row__sep">·</span>
                                <span class="dsm-row__map-text">{{ mapName(demo.map) }}</span>
                            </span>
                        </div>

                        <div class="dsm-row__score">
                            <span class="dsm-row__score-num dsm-row__score-num--ct">{{ demo?.lastRound?.meta?.CT_score ?? '–' }}</span>
                            <span class="dsm-row__score-sep">:</span>
                            <span class="dsm-row__score-num dsm-row__score-num--t">{{ demo?.lastRound?.meta?.T_score ?? '–' }}</span>
                        </div>

                        <div class="dsm-row__action">
                            <span v-if="alreadyAdded(demo)" class="dsm-row__chip">
                                <Icon icon="lucide:check" class="dsm__icon dsm__icon--small" />
                                Added
                            </span>
                            <span v-else class="dsm-row__plus">
                                <Icon icon="lucide:plus" class="dsm__icon dsm__icon--small" />
                            </span>
                        </div>
                    </button>
                </div>

                <footer class="dsm__foot">
                    <div class="dsm__shortcuts">
                        <span class="dsm__shortcut"><kbd>↑↓</kbd>Navigate</span>
                        <span class="dsm__shortcut"><kbd>Enter</kbd>Add</span>
                        <span class="dsm__shortcut"><kbd>Esc</kbd>Close</span>
                    </div>
                </footer>
            </div>
        </div>
    </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue';
import { Icon } from '@iconify/vue';
import useDemos from '@/composables/useDemos';

const props = defineProps<{ loadedDemoIds: string[] }>();
const emit = defineEmits(['select', 'close']);

const { Demos } = useDemos();
const { data: allDemos } = Demos.get();

const search = ref('');
const mapFilter = ref<string | null>(null);
const cursor = ref(0);
const searchInput = ref<HTMLInputElement | null>(null);
const listEl = ref<HTMLElement | null>(null);
const rowEls = ref<HTMLElement[]>([]);

const MAP_NAMES: Record<string, string> = {
    de_mirage: 'Mirage',
    de_dust2: 'Dust 2',
    de_inferno: 'Inferno',
    de_nuke: 'Nuke',
    de_overpass: 'Overpass',
    de_ancient: 'Ancient',
    de_anubis: 'Anubis',
    de_train: 'Train',
    de_vertigo: 'Vertigo',
};

const mapName = (m: string | undefined | null): string =>
    !m ? 'Unknown' : (MAP_NAMES[m] ?? m.replace(/^de_/, '').replace(/^cs_/, ''));

const mapShortName = (m: string | undefined | null): string =>
    !m ? '???' : (m.replace(/^de_/, '').replace(/^cs_/, '').slice(0, 3).toUpperCase());

const shortMap = (m: string | undefined | null): string =>
    !m ? 'unk' : m.replace(/^de_/, '').replace(/^cs_/, '');

const availableMaps = computed(() => {
    const set = new Set<string>();
    (allDemos.value as any[] | undefined)?.forEach(d => {
        if (d.map) set.add(d.map);
    });
    return Array.from(set).sort();
});

const filtered = computed(() => {
    const list = (allDemos.value as any[]) ?? [];
    const q = search.value.trim().toLowerCase();
    return list.filter(d => {
        if (mapFilter.value && d.map !== mapFilter.value) return false;
        if (q && !(d.name?.toLowerCase().includes(q) || d.map?.toLowerCase().includes(q))) return false;
        return true;
    });
});

function alreadyAdded(demo: any) {
    return props.loadedDemoIds.includes(demo.external_id ?? String(demo.id));
}

function select(demo: any) {
    if (alreadyAdded(demo)) return;
    emit('select', demo.external_id ?? String(demo.id));
}

function scrollCursorIntoView() {
    const row = rowEls.value?.[cursor.value];
    row?.scrollIntoView({ block: 'nearest', behavior: 'instant' as ScrollBehavior });
}

watch(filtered, () => { cursor.value = 0; });
watch(cursor, () => nextTick(scrollCursorIntoView));

function onKeydown(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
        e.preventDefault();
        cursor.value = Math.min(filtered.value.length - 1, cursor.value + 1);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        cursor.value = Math.max(0, cursor.value - 1);
    } else if (e.key === 'Enter') {
        if (filtered.value[cursor.value]) select(filtered.value[cursor.value]);
    } else if (e.key === 'Escape') {
        emit('close');
    }
}

onMounted(() => {
    window.addEventListener('keydown', onKeydown);
    nextTick(() => searchInput.value?.focus());
});
onUnmounted(() => window.removeEventListener('keydown', onKeydown));

const formatDate = (date: string | undefined) =>
    date ? new Date(date).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
</script>

<style scoped>
.dsm {
    --dsm-bg:        oklch(0.125 0.012 250);
    --dsm-surface:   oklch(0.175 0.014 250);
    --dsm-surface-2: oklch(0.215 0.016 250);
    --dsm-surface-3: oklch(0.26 0.018 250);
    --dsm-border:    oklch(1 0 0 / 0.09);
    --dsm-border-2:  oklch(1 0 0 / 0.14);
    --dsm-text:      oklch(1 0 0 / 0.96);
    --dsm-text-2:    oklch(1 0 0 / 0.70);
    --dsm-text-3:    oklch(1 0 0 / 0.62);
    --dsm-text-4:    oklch(1 0 0 / 0.50);
    --dsm-accent:    var(--main-color, #ff8c00);
    --dsm-sans:      'Schibsted Grotesk', 'Helvetica Neue', Arial, sans-serif;
    --dsm-mono:      'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;

    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--dsm-sans);
}

.dsm__backdrop {
    position: absolute;
    inset: 0;
    background: oklch(0.05 0.005 250 / 0.72);
    backdrop-filter: blur(6px);
}

.dsm__panel {
    position: relative;
    width: min(820px, calc(100vw - 24px));
    max-height: calc(100dvh - 64px);
    margin: 24px;
    background: var(--dsm-bg);
    border: 1px solid var(--dsm-border-2);
    border-radius: 8px;
    box-shadow: 0 32px 64px -20px oklch(0 0 0 / 0.8);
    color: var(--dsm-text);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* ── Header ── */
.dsm__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 18px;
    border-bottom: 1px solid var(--dsm-border);
    background: var(--dsm-surface);
    flex-shrink: 0;
}

.dsm__title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }

.dsm__kicker {
    font-family: var(--dsm-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--dsm-text-3);
}

.dsm__heading {
    font-family: var(--dsm-sans);
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--dsm-text);
    margin: 0;
}

.dsm__close {
    background: none;
    border: none;
    color: var(--dsm-text-3);
    cursor: pointer;
    padding: 6px;
    border-radius: 4px;
    display: inline-flex;
    transition: color 150ms ease, background 150ms ease;
}
.dsm__close:hover { color: var(--dsm-text); background: var(--dsm-surface-2); }
.dsm__close:focus-visible { outline: 2px solid var(--dsm-accent); outline-offset: 2px; }

.dsm__icon { width: 14px; height: 14px; flex-shrink: 0; }
.dsm__icon--small { width: 12px; height: 12px; }

/* ── Filters ── */
.dsm__filters {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 18px;
    border-bottom: 1px solid var(--dsm-border);
    background: var(--dsm-bg);
    flex-shrink: 0;
}

.dsm__search {
    flex: 1;
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
}

.dsm__icon--search {
    position: absolute;
    left: 10px;
    color: var(--dsm-text-3);
    pointer-events: none;
}

.dsm__search-input {
    width: 100%;
    background: var(--dsm-surface);
    border: 1px solid var(--dsm-border);
    border-radius: 5px;
    padding: 8px 12px 8px 32px;
    font-family: var(--dsm-sans);
    font-size: 13px;
    color: var(--dsm-text);
    outline: none;
    transition: border-color 150ms ease, box-shadow 150ms ease;
}
.dsm__search-input::placeholder { color: var(--dsm-text-3); }
.dsm__search-input:focus-visible {
    border-color: var(--dsm-accent);
    box-shadow: 0 0 0 2px color-mix(in oklch, var(--dsm-accent) 22%, transparent);
}

.dsm__select {
    font-family: var(--dsm-mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.04em;
    background: var(--dsm-surface);
    border: 1px solid var(--dsm-border);
    color: var(--dsm-text);
    padding: 8px 10px;
    border-radius: 5px;
    cursor: pointer;
    outline: none;
}
.dsm__select:focus-visible {
    border-color: var(--dsm-accent);
    box-shadow: 0 0 0 2px color-mix(in oklch, var(--dsm-accent) 22%, transparent);
}

.dsm__count {
    font-family: var(--dsm-mono);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    color: var(--dsm-text-3);
    flex-shrink: 0;
}

.dsm__count-num { color: var(--dsm-text); font-weight: 700; }
.dsm__count-sep { margin: 0 2px; color: var(--dsm-text-4); }

/* ── List ── */
.dsm__list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    background: var(--dsm-bg);
    scrollbar-width: thin;
    scrollbar-color: var(--dsm-border-2) transparent;
}
.dsm__list::-webkit-scrollbar { width: 6px; }
.dsm__list::-webkit-scrollbar-thumb { background: var(--dsm-border-2); border-radius: 3px; }

.dsm__empty {
    padding: 40px 18px;
    margin: 0;
    text-align: center;
    color: var(--dsm-text-3);
    font-size: 13px;
}

/* ── Row ── */
.dsm-row {
    width: 100%;
    display: grid;
    grid-template-columns: 56px 1fr 90px 80px;
    align-items: center;
    gap: 14px;
    padding: 10px 18px;
    background: none;
    border: none;
    border-bottom: 1px solid var(--dsm-border);
    cursor: pointer;
    text-align: left;
    transition: background 100ms ease;
}

.dsm-row:last-child { border-bottom: none; }
.dsm-row:hover, .dsm-row--cursor { background: var(--dsm-surface); }
.dsm-row--added { opacity: 0.5; cursor: not-allowed; }

.dsm-row:focus-visible {
    outline: 2px solid var(--dsm-accent);
    outline-offset: -2px;
}

/* Map thumbnail / fallback */
.dsm-row__map {
    width: 56px;
    height: 40px;
    border-radius: 4px;
    background: var(--dsm-surface-2);
    border: 1px solid var(--dsm-border);
    display: flex;
    align-items: center;
    justify-content: center;
    background-size: cover;
    background-position: center;
    overflow: hidden;
    position: relative;
}

.dsm-row__map[data-map="mirage"]   { background-image: url('/images/maps/mirage.webp'); }
.dsm-row__map[data-map="dust2"]    { background-image: url('/images/maps/dust2.webp'); }
.dsm-row__map[data-map="inferno"]  { background-image: url('/images/maps/inferno.webp'); }
.dsm-row__map[data-map="nuke"]     { background-image: url('/images/maps/nuke.webp'); }
.dsm-row__map[data-map="overpass"] { background-image: url('/images/maps/overpass.webp'); }
.dsm-row__map[data-map="ancient"]  { background-image: url('/images/maps/ancient.webp'); }
.dsm-row__map[data-map="anubis"]   { background-image: url('/images/maps/anubis.webp'); }
.dsm-row__map[data-map="train"]    { background-image: url('/images/maps/train.webp'); }
.dsm-row__map[data-map="vertigo"]  { background-image: url('/images/maps/vertigo.webp'); }

.dsm-row__map::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(to top, oklch(0 0 0 / 0.6) 0%, oklch(0 0 0 / 0.1) 70%);
}

.dsm-row__map-name {
    position: relative;
    z-index: 1;
    font-family: var(--dsm-mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--dsm-text);
}

/* Main column */
.dsm-row__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }

.dsm-row__name {
    font-family: var(--dsm-sans);
    font-size: 14px;
    font-weight: 600;
    color: var(--dsm-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.dsm-row__meta {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    font-family: var(--dsm-mono);
    font-size: 10px;
    color: var(--dsm-text-3);
}

.dsm-row__sep { color: var(--dsm-text-4); }
.dsm-row__map-text { color: var(--dsm-accent); }

/* Score column */
.dsm-row__score {
    display: inline-flex;
    align-items: baseline;
    justify-content: center;
    gap: 3px;
    font-family: var(--dsm-mono);
    font-size: 14px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
}

.dsm-row__score-num--ct { color: oklch(0.70 0.10 220); }
.dsm-row__score-num--t  { color: oklch(0.75 0.12 60); }
.dsm-row__score-sep { color: var(--dsm-text-4); }

/* Action column */
.dsm-row__action { display: flex; justify-content: flex-end; align-items: center; }

.dsm-row__chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    border-radius: 3px;
    font-family: var(--dsm-mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: oklch(0.72 0.14 145);
    background: color-mix(in oklch, oklch(0.72 0.14 145) 14%, transparent);
}

.dsm-row__plus {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: 1px solid var(--dsm-border-2);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--dsm-text-3);
    transition: color 150ms ease, border-color 150ms ease, background 150ms ease;
}

.dsm-row:hover:not(.dsm-row--added) .dsm-row__plus,
.dsm-row--cursor:not(.dsm-row--added) .dsm-row__plus {
    color: var(--dsm-accent);
    border-color: color-mix(in oklch, var(--dsm-accent) 50%, transparent);
    background: color-mix(in oklch, var(--dsm-accent) 12%, transparent);
}

/* ── Footer ── */
.dsm__foot {
    padding: 10px 18px;
    border-top: 1px solid var(--dsm-border);
    background: var(--dsm-surface);
    flex-shrink: 0;
}

.dsm__shortcuts {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
}

.dsm__shortcut {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: var(--dsm-mono);
    font-size: 10px;
    color: var(--dsm-text-3);
    letter-spacing: 0.04em;
}

.dsm__shortcut kbd {
    background: var(--dsm-surface-2);
    color: var(--dsm-text);
    padding: 2px 5px;
    border-radius: 2px;
    border: 1px solid var(--dsm-border);
    font-family: var(--dsm-mono);
    font-size: 9px;
    font-weight: 600;
}

/* ── Responsive ── */
@media (max-width: 640px) {
    .dsm { align-items: flex-end; }
    .dsm__panel {
        width: 100vw;
        max-width: 100vw;
        margin: 0;
        max-height: 90dvh;
        border-radius: 8px 8px 0 0;
        border-bottom: none;
    }
    .dsm-row {
        grid-template-columns: 48px 1fr auto;
        gap: 10px;
        padding: 10px 14px;
    }
    .dsm-row__map { width: 48px; height: 36px; }
    .dsm-row__score { display: none; }
    .dsm__filters { flex-wrap: wrap; }
    .dsm__shortcut { font-size: 9px; }
}

@media (prefers-reduced-motion: reduce) {
    .dsm-row, .dsm-row__plus { transition: none; }
}
</style>
