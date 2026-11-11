<script setup lang="ts">
import Button from '@/components/volt/Button.vue';
import EditFolder from '@/componentsnew/demo/EditFolder.vue';
import EditDemo from '@/componentsnew/demo/EditDemo.vue';
import DemoCard from '@/componentsnew/demo/DemoCard.vue';
import DemoListView from '@/componentsnew/demo/DemoListView.vue';
import DemoFolderCard from '@/componentsnew/demo/DemoFolderCard.vue';
import FaceitDialog from './FaceitDialog.vue';

import { useStore } from '@/store';
import { computed, ref, onUnmounted, watch, onMounted } from 'vue';
import router from '@/router';
import useDemos from '@/composables/useDemos';
import useDemoFolders from '@/composables/useDemoFolders';
import Bus from '@/eventbus';

const store = useStore();
const user = computed(() => store.user);
const userSteamId = computed(() => user.value?.user_info?.steam_id ?? null);

const { Demos } = useDemos();
const { DemoFolders } = useDemoFolders();

const { data: demos, refetch } = Demos.get(true);
const { data: folders } = DemoFolders.get();

const editFolderRef = ref();
const selectedFolder = ref(null);
const editDemoRef = ref();
const selectedDemo = ref(null);

// ── View mode ────────────────────────────────────────────────────────────────
const STORAGE_KEY = 'demos-view-mode';
const viewMode = ref<'grid' | 'list'>(
    (localStorage.getItem(STORAGE_KEY) as 'grid' | 'list') || 'grid'
);
watch(viewMode, (v) => localStorage.setItem(STORAGE_KEY, v));

// ── Filters ───────────────────────────────────────────────────────────────────
const search = ref('');
const mapFilter = ref<string | null>(null);
const resultFilter = ref<'all' | 'won' | 'lost' | 'processing'>('all');

const MAP_OPTIONS = [
    { key: null, label: 'All maps' },
    { key: 'de_mirage', label: 'Mirage' },
    { key: 'de_dust2', label: 'Dust 2' },
    { key: 'de_inferno', label: 'Inferno' },
    { key: 'de_nuke', label: 'Nuke' },
    { key: 'de_overpass', label: 'Overpass' },
    { key: 'de_ancient', label: 'Ancient' },
    { key: 'de_anubis', label: 'Anubis' },
    { key: 'de_train', label: 'Train' },
    { key: 'de_vertigo', label: 'Vertigo' },
];

const RESULT_OPTIONS = [
    { key: 'all', label: 'All' },
    { key: 'won', label: 'Won' },
    { key: 'lost', label: 'Lost' },
    { key: 'processing', label: 'Processing' },
] as const;

const filteredDemos = computed(() => {
    const list = (demos.value as any[]) ?? [];
    const sid = userSteamId.value;
    const q = search.value.trim().toLowerCase();

    return list.filter((d: any) => {
        if (q && !(d.name?.toLowerCase().includes(q) || d.map?.toLowerCase().includes(q))) return false;
        if (mapFilter.value && d.map !== mapFilter.value) return false;
        if (resultFilter.value !== 'all') {
            if (resultFilter.value === 'processing') {
                if (!d.status) return false;
            } else {
                if (d.status) return false;
                const winners = d.lastRound?.meta?.winners;
                if (!winners || !sid) return false;
                const won = winners.includes(sid);
                if (resultFilter.value === 'won' && !won) return false;
                if (resultFilter.value === 'lost' && won) return false;
            }
        }
        return true;
    });
});

const filteredFolders = computed(() => (folders.value as any[]) ?? []);

const totalDemos = computed(() => ((demos.value as any[]) ?? []).length);
const processingCount = computed(() =>
    ((demos.value as any[]) ?? []).filter((d) => d.status).length
);

// ── Navigation ───────────────────────────────────────────────────────────────
const visitFolder = (folderId: number) => router.push({ name: 'DemoFolder', params: { id: folderId } });
const visitDemo = (demoId: number) => router.push({ name: 'DemoOverview', params: { id: demoId } });

const toggleEditFolder = (event: Event, folder: any) => {
    event.stopPropagation();
    selectedFolder.value = folder;
    editFolderRef.value.toggle(event);
};

onMounted(() => {
    Bus.on('demosRefresh', () => refetch());
});

const toggleEditDemo = (event: Event, demo: any) => {
    event.stopPropagation();
    selectedDemo.value = demo;
    editDemoRef.value.toggle(event);
};

const openUploadDialog = () => Bus.emit('openUploadDialog');

// ── Auto-refetch while processing ────────────────────────────────────────────
const intervalId = ref<ReturnType<typeof setInterval> | null>(null);

watch(() => demos.value, (newDemos) => {
    const hasProcessing = (newDemos as any[])?.some((demo: any) => demo.status !== undefined && demo.status !== null);
    if (hasProcessing) {
        if (!intervalId.value) {
            intervalId.value = setInterval(() => refetch(), 10000);
        }
    } else if (intervalId.value) {
        clearInterval(intervalId.value);
        intervalId.value = null;
    }
}, { deep: true, immediate: true });

onUnmounted(() => {
    Bus.remove('demosRefresh', () => refetch());
    if (intervalId.value) clearInterval(intervalId.value);
});
</script>

<template>
    <EditFolder ref="editFolderRef" :folder="selectedFolder || {}" />
    <EditDemo ref="editDemoRef" :demo="selectedDemo || {}" :folders="(folders as any) || []" />

    <!-- ── Page ─────────────────────────────────────────────────────────── -->
    <div class="dl-page">
        <!-- Header -->
        <header class="dl-page__head">
            <div class="dl-page__title">
                <span class="dl-page__kicker">Library</span>
                <h1 class="dl-page__heading">Demos</h1>
                <span class="dl-page__count">
                    <span class="dl-page__count-num">{{ filteredDemos.length }}</span>
                    <span class="dl-page__count-sep">/</span>
                    <span class="dl-page__count-tot">{{ totalDemos }}</span>
                    <span v-if="processingCount" class="dl-page__count-pending">{{ processingCount }} processing</span>
                </span>
            </div>
            <div class="dl-page__actions">
                <button class="dl-btn dl-btn--primary" @click="openUploadDialog">
                    <span class="material-symbols dl-btn__icon">upload</span>
                    <span class="dl-btn__label">Upload</span>
                </button>
                <button class="dl-btn dl-btn--ghost" @click="DemoFolders.create()">
                    <span class="material-symbols dl-btn__icon">create_new_folder</span>
                    <span class="dl-btn__label">New folder</span>
                </button>
                <FaceitDialog />
            </div>
        </header>

        <!-- Folders strip -->
        <section v-if="filteredFolders.length" class="dl-folders">
            <header class="dl-folders__head">
                <span class="dl-folders__kicker">
                    Folders
                    <span class="dl-folders__count">{{ filteredFolders.length }}</span>
                </span>
            </header>
            <div class="dl-folders__grid">
                <DemoFolderCard
                    v-for="folder in filteredFolders"
                    :key="folder.id"
                    :folder="folder"
                    @open="visitFolder(folder.id)"
                    @edit="(e) => toggleEditFolder(e, folder)"
                />
            </div>
        </section>

        <!-- Filter toolbar -->
        <div class="dl-toolbar">
            <label class="dl-search">
                <span class="material-symbols dl-search__icon">search</span>
                <input
                    v-model="search"
                    type="search"
                    placeholder="Search demos…"
                    class="dl-search__input"
                />
            </label>

            <select v-model="mapFilter" class="dl-select" aria-label="Filter by map">
                <option v-for="opt in MAP_OPTIONS" :key="opt.label" :value="opt.key">{{ opt.label }}</option>
            </select>

            <div class="dl-seg dl-seg--results" role="group" aria-label="Filter by result">
                <button
                    v-for="opt in RESULT_OPTIONS"
                    :key="opt.key"
                    @click="resultFilter = opt.key"
                    class="dl-seg__btn"
                    :class="{ 'dl-seg__btn--active': resultFilter === opt.key }"
                >{{ opt.label }}</button>
            </div>

            <select v-model="resultFilter" class="dl-select dl-select--mobile-results" aria-label="Filter by result">
                <option v-for="opt in RESULT_OPTIONS" :key="opt.key" :value="opt.key">{{ opt.label }}</option>
            </select>

            <div class="dl-view" role="group" aria-label="View mode">
                <button
                    @click="viewMode = 'grid'"
                    class="dl-view__btn"
                    :class="{ 'dl-view__btn--active': viewMode === 'grid' }"
                    title="Grid view"
                    aria-label="Grid view"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>
                </button>
                <button
                    @click="viewMode = 'list'"
                    class="dl-view__btn"
                    :class="{ 'dl-view__btn--active': viewMode === 'list' }"
                    title="List view"
                    aria-label="List view"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="4" width="18" height="2.5" rx="1"/><rect x="3" y="10.75" width="18" height="2.5" rx="1"/><rect x="3" y="17.5" width="18" height="2.5" rx="1"/></svg>
                </button>
            </div>
        </div>

        <!-- Empty state -->
        <div v-if="!filteredDemos.length && !demos?.length" class="dl-empty">
            <div class="dl-empty__icon"><span class="material-symbols">movie</span></div>
            <h3 class="dl-empty__title">No demos yet</h3>
            <p class="dl-empty__body">Upload your first <code class="dl-empty__code">.dem</code> file to see round-by-round playback and the 2D viewer.</p>
            <button class="dl-btn dl-btn--primary dl-empty__cta" @click="openUploadDialog">
                <span class="material-symbols dl-btn__icon">upload</span>
                <span class="dl-btn__label">Upload demo</span>
            </button>
        </div>

        <div v-else-if="!filteredDemos.length" class="dl-empty dl-empty--filtered">
            <span class="material-symbols dl-empty__icon-inline">search_off</span>
            <p class="dl-empty__body">No demos match these filters.</p>
        </div>

        <!-- Grid view -->
        <div
            v-else-if="viewMode === 'grid'"
            class="demo-grid"
        >
            <DemoCard
                v-for="demo in filteredDemos"
                :key="demo.id"
                :demo="demo"
                :user-steam-id="userSteamId"
                @click="visitDemo(demo.id)"
                @edit="(e) => toggleEditDemo(e, demo)"
            />
        </div>

        <!-- List view -->
        <DemoListView
            v-else
            class="flex-grow mb-4"
            :demos="filteredDemos"
            :user-steam-id="userSteamId"
            @select="visitDemo"
            @edit="({ event, demo }) => toggleEditDemo(event, demo)"
        />
    </div>
</template>

<style scoped>
.dl-page {
    --pg-bg:        oklch(0.125 0.012 250);
    --pg-surface:   oklch(0.175 0.014 250);
    --pg-surface-2: oklch(0.215 0.016 250);
    --pg-surface-3: oklch(0.26 0.018 250);
    --pg-border:    oklch(1 0 0 / 0.09);
    --pg-border-2:  oklch(1 0 0 / 0.14);
    --pg-text:      oklch(1 0 0 / 0.96);
    --pg-text-2:    oklch(1 0 0 / 0.70);
    --pg-text-3:    oklch(1 0 0 / 0.62);
    --pg-text-4:    oklch(1 0 0 / 0.50);
    --pg-accent:    var(--main-color, #ff8c00);
    --pg-sans:      'Schibsted Grotesk', sans-serif;
    --pg-mono:      'JetBrains Mono', monospace;

    width: 100%;
    height: 100%;
    max-width: 2560px;
    margin: 0 auto;
    padding: 18px 16px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    overflow: hidden;
    background: var(--pg-bg);
    color: var(--pg-text);
    font-family: var(--pg-sans);
}

@media (min-width: 640px) { .dl-page { padding: 24px 20px; gap: 20px; } }
@media (min-width: 1024px) { .dl-page { padding: 32px 32px; gap: 24px; } }

/* ── Header ── */
.dl-page__head {
    display: flex;
    flex-direction: column;
    gap: 14px;
    flex-shrink: 0;
}

@media (min-width: 700px) {
    .dl-page__head { flex-direction: row; align-items: flex-end; justify-content: space-between; }
}

.dl-page__title { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

.dl-page__kicker {
    font-family: var(--pg-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--pg-text-3);
}

.dl-page__heading {
    font-family: var(--pg-sans);
    font-size: clamp(1.5rem, 3vw, 2rem);
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--pg-text);
    margin: 0;
    line-height: 1;
}

.dl-page__count {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--pg-mono);
    font-size: 11px;
    color: var(--pg-text-3);
    margin-top: 2px;
}
.dl-page__count-num { color: var(--pg-text); font-weight: 700; font-variant-numeric: tabular-nums; }
.dl-page__count-sep, .dl-page__count-tot { font-variant-numeric: tabular-nums; }
.dl-page__count-pending {
    color: var(--pg-accent);
    margin-left: 6px;
    padding-left: 8px;
    border-left: 1px solid var(--pg-border-2);
}

.dl-page__actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

/* ── Buttons ── */
.dl-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 4px;
    border: 1px solid transparent;
    font-family: var(--pg-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    cursor: pointer;
    text-decoration: none;
    transition: background 150ms ease, color 150ms ease, border-color 150ms ease;
}

.dl-btn:focus-visible { outline: 2px solid var(--pg-accent); outline-offset: 2px; }

.dl-btn__icon { font-size: 14px; }

.dl-btn--primary {
    background: var(--pg-accent);
    color: oklch(0.125 0.012 250);
    border-color: var(--pg-accent);
}
.dl-btn--primary:hover {
    background: oklch(0.62 0.20 50);
    color: var(--pg-text);
    border-color: oklch(0.62 0.20 50);
}

.dl-btn--ghost {
    background: transparent;
    color: var(--pg-text-2);
    border-color: var(--pg-border-2);
}
.dl-btn--ghost:hover {
    background: var(--pg-surface-2);
    color: var(--pg-text);
}

/* ── Folders strip ── */
.dl-folders {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.dl-folders__head { display: flex; align-items: center; justify-content: space-between; padding: 0 2px; }

.dl-folders__kicker {
    font-family: var(--pg-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--pg-text-3);
}

.dl-folders__count {
    margin-left: 6px;
    color: var(--pg-text-4);
    font-variant-numeric: tabular-nums;
}

.dl-folders__grid {
    display: grid;
    gap: 10px;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}

@media (min-width: 640px)  { .dl-folders__grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); } }
@media (min-width: 1024px) { .dl-folders__grid { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; } }

/* ── Filter toolbar ── */
.dl-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    flex-shrink: 0;
    padding: 8px;
    background: var(--pg-surface);
    border: 1px solid var(--pg-border);
    border-radius: 6px;
}

.dl-search {
    position: relative;
    flex: 1;
    min-width: 180px;
    max-width: 360px;
    display: flex;
    align-items: center;
}

.dl-search__icon {
    position: absolute;
    left: 10px;
    color: var(--pg-text-3);
    font-size: 16px !important;
    pointer-events: none;
}

.dl-search__input {
    width: 100%;
    background: var(--pg-surface-2);
    border: 1px solid var(--pg-border);
    border-radius: 4px;
    padding: 7px 12px 7px 32px;
    font-family: var(--pg-sans);
    font-size: 13px;
    color: var(--pg-text);
    outline: none;
    transition: border-color 150ms ease, box-shadow 150ms ease;
}
.dl-search__input::placeholder { color: var(--pg-text-3); }
.dl-search__input:focus-visible {
    border-color: var(--pg-accent);
    box-shadow: 0 0 0 2px color-mix(in oklch, var(--pg-accent) 22%, transparent);
}

.dl-select {
    font-family: var(--pg-mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    background: var(--pg-surface-2);
    border: 1px solid var(--pg-border);
    color: var(--pg-text);
    padding: 7px 10px;
    border-radius: 4px;
    cursor: pointer;
    outline: none;
}
.dl-select:focus-visible {
    border-color: var(--pg-accent);
    box-shadow: 0 0 0 2px color-mix(in oklch, var(--pg-accent) 22%, transparent);
}

.dl-select--mobile-results { display: none; }
@media (max-width: 640px) {
    .dl-seg--results { display: none; }
    .dl-select--mobile-results { display: block; }
}

.dl-seg {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    background: var(--pg-surface-2);
    border: 1px solid var(--pg-border);
    border-radius: 4px;
}

.dl-seg__btn {
    background: none;
    border: none;
    padding: 5px 10px;
    border-radius: 3px;
    font-family: var(--pg-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--pg-text-3);
    cursor: pointer;
    transition: color 150ms ease, background 150ms ease;
}
.dl-seg__btn:hover { color: var(--pg-text-2); }
.dl-seg__btn--active {
    background: var(--pg-surface-3);
    color: var(--pg-text);
}
.dl-seg__btn:focus-visible { outline: 2px solid var(--pg-accent); outline-offset: 2px; }

.dl-view {
    margin-left: auto;
    display: inline-flex;
    gap: 1px;
    background: var(--pg-surface-2);
    border: 1px solid var(--pg-border);
    border-radius: 4px;
    overflow: hidden;
}

.dl-view__btn {
    background: none;
    border: none;
    padding: 6px 9px;
    color: var(--pg-text-3);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: color 150ms ease, background 150ms ease;
}
.dl-view__btn:hover { color: var(--pg-text-2); }
.dl-view__btn--active { background: var(--pg-surface-3); color: var(--pg-accent); }
.dl-view__btn:focus-visible { outline: 2px solid var(--pg-accent); outline-offset: 2px; }

/* ── Empty state ── */
.dl-empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    text-align: center;
    padding: 32px 16px;
}

.dl-empty--filtered { gap: 8px; opacity: 0.7; }

.dl-empty__icon {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: var(--pg-surface);
    border: 1px solid var(--pg-border);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--pg-text-3);
    margin-bottom: 4px;
}
.dl-empty__icon .material-symbols { font-size: 24px; }
.dl-empty__icon-inline { color: var(--pg-text-3); font-size: 22px !important; }

.dl-empty__title {
    font-family: var(--pg-sans);
    font-size: 16px;
    font-weight: 700;
    color: var(--pg-text);
    margin: 0;
}

.dl-empty__body {
    font-family: var(--pg-sans);
    font-size: 13px;
    color: var(--pg-text-3);
    margin: 0;
    max-width: 36ch;
    line-height: 1.5;
}

.dl-empty__code {
    font-family: var(--pg-mono);
    color: var(--pg-accent);
    font-size: 12px;
}

.dl-empty__cta { margin-top: 6px; }

/* ── Demo grid ── */
.demo-grid {
    display: grid;
    gap: 12px;
    flex-grow: 1;
    width: 100%;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 0 4px 16px;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    grid-auto-rows: 170px;
    scrollbar-width: thin;
    scrollbar-color: var(--pg-border-2) transparent;
}
.demo-grid::-webkit-scrollbar { width: 6px; }
.demo-grid::-webkit-scrollbar-thumb { background-color: var(--pg-border-2); border-radius: 3px; }
.demo-grid::-webkit-scrollbar-track { background-color: transparent; }

@media (min-width: 640px)  { .demo-grid { grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); grid-auto-rows: 185px; gap: 14px; } }
@media (min-width: 1024px) { .demo-grid { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); grid-auto-rows: 190px; gap: 16px; } }
@media (min-width: 1280px) { .demo-grid { gap: 20px; } }
@media (min-width: 2100px) { .demo-grid { grid-template-columns: repeat(8, minmax(0, 1fr)); } }

.custom-track::-webkit-scrollbar { width: 6px; }
.custom-track::-webkit-scrollbar-thumb { background-color: var(--pg-border-2); border-radius: 10px; }
.custom-track::-webkit-scrollbar-track { background-color: transparent; }
.custom-track { scrollbar-width: thin; scrollbar-color: var(--pg-border-2) transparent; }
</style>