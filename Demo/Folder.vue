<script setup lang="ts">
import EditDemo from '@/componentsnew/demo/EditDemo.vue';
import DemoCard from '@/componentsnew/demo/DemoCard.vue';
import DemoListView from '@/componentsnew/demo/DemoListView.vue';

import { useStore } from '@/store';
import { computed, ref, watch } from 'vue';
import { useRoute, RouterLink } from 'vue-router';
import router from '@/router';
import useDemoFolders from '@/composables/useDemoFolders';

const route = useRoute();
const store = useStore();
const user = computed(() => store.user);
const userSteamId = computed(() => user.value?.user_info?.steam_id ?? null);

const { DemoFolders } = useDemoFolders();
const { data: folder } = DemoFolders.find(Number(route.params.id));

const demos = computed(() => (folder.value?.demos as any[]) ?? []);

const editDemoRef = ref();
const selectedDemo = ref(null);

const toggleEditDemo = (event: Event, demo: any) => {
    event.stopPropagation();
    selectedDemo.value = demo;
    editDemoRef.value.toggle(event);
};

const visitDemo = (demoId: number) => router.push({ name: 'DemoOverview', params: { id: demoId } });

// ── View mode ────────────────────────────────────────────────────────────────
const STORAGE_KEY = 'demos-view-mode';
const viewMode = ref<'grid' | 'list'>(
    (localStorage.getItem(STORAGE_KEY) as 'grid' | 'list') || 'grid'
);
watch(viewMode, (v) => localStorage.setItem(STORAGE_KEY, v));

// ── Filters ─────────────────────────────────────────────────────────────────
const search = ref('');
const mapFilter = ref<string | null>(null);

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

const filteredDemos = computed(() => {
    const q = search.value.trim().toLowerCase();
    return demos.value.filter((d: any) => {
        if (q && !(d.name?.toLowerCase().includes(q) || d.map?.toLowerCase().includes(q))) return false;
        if (mapFilter.value && d.map !== mapFilter.value) return false;
        return true;
    });
});

const stripeColor = computed(() => `#${folder.value?.color ?? 'ff8c00'}`);
const tileBg = computed(() => `#${folder.value?.color ?? 'ff8c00'}26`);
</script>

<template>
    <EditDemo ref="editDemoRef" :demo="selectedDemo || {}" :folders="[]" :moveBack="true" />

    <div class="p-4 md:p-10 xl:p-12 h-full w-full max-w-[2560px] mx-auto overflow-hidden flex flex-col">
        <!-- Breadcrumbs -->
        <nav class="flex items-center gap-2 mb-4 text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500 shrink-0">
            <RouterLink :to="{ name: 'Demo' }" class="hover:text-primary transition-colors">Demos</RouterLink>
            <span class="text-zinc-700">/</span>
            <span class="text-zinc-300 truncate">{{ folder?.name ?? '...' }}</span>
        </nav>

        <!-- Header -->
        <header class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-6 md:mb-8 shrink-0">
            <div class="flex items-center gap-4 min-w-0">
                <RouterLink
                    :to="{ name: 'Demo' }"
                    class="shrink-0 w-10 h-10 rounded-lg border border-white/10 bg-zinc-900/60 flex items-center justify-center text-zinc-400 hover:text-primary hover:border-primary/40 transition-colors"
                    title="Back to demos"
                >
                    <span class="material-symbols">arrow_back</span>
                </RouterLink>
                <div
                    class="shrink-0 w-11 h-11 rounded-lg flex items-center justify-center"
                    :style="{ backgroundColor: tileBg }"
                >
                    <span class="material-symbols text-2xl" :style="{ color: stripeColor }">folder_open</span>
                </div>
                <div class="flex flex-col min-w-0">
                    <span class="text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">Folder</span>
                    <h1 class="text-2xl md:text-3xl font-black tracking-tight text-white truncate leading-none">
                        {{ folder?.name ?? '...' }}
                    </h1>
                </div>
            </div>
            <div class="text-xs text-zinc-500 tabular-nums font-mono uppercase tracking-wider">
                {{ demos.length }} demo{{ demos.length !== 1 ? 's' : '' }}
            </div>
        </header>

        <!-- Filters toolbar -->
        <div class="flex flex-wrap items-center gap-2 md:gap-3 mb-4 shrink-0">
            <label class="relative flex-1 min-w-[200px] max-w-md">
                <span class="material-symbols absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" style="font-size: 16px">search</span>
                <input
                    v-model="search"
                    type="search"
                    placeholder="Search demos…"
                    class="w-full bg-zinc-900/60 border border-white/10 rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/30 transition-colors"
                />
            </label>
            <select
                v-model="mapFilter"
                class="bg-zinc-900/60 border border-white/10 rounded-lg px-3 py-2 text-xs font-bold uppercase tracking-wider text-white focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/30 transition-colors"
            >
                <option v-for="opt in MAP_OPTIONS" :key="opt.label" :value="opt.key">{{ opt.label }}</option>
            </select>
        </div>

        <!-- View toggle + count -->
        <div class="flex items-center justify-between mb-4 px-2 shrink-0">
            <span class="text-xs text-zinc-500 tabular-nums">
                {{ filteredDemos.length }} shown
            </span>
            <div class="flex items-center border border-white/10 rounded-lg overflow-hidden">
                <button
                    @click="viewMode = 'grid'"
                    class="px-2.5 py-1.5 transition-all"
                    :class="viewMode === 'grid' ? 'bg-primary/20 text-primary' : 'text-zinc-500 hover:text-white hover:bg-white/5'"
                    title="Grid view"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                        <rect x="3" y="3" width="7" height="7" rx="1.5"/>
                        <rect x="14" y="3" width="7" height="7" rx="1.5"/>
                        <rect x="3" y="14" width="7" height="7" rx="1.5"/>
                        <rect x="14" y="14" width="7" height="7" rx="1.5"/>
                    </svg>
                </button>
                <button
                    @click="viewMode = 'list'"
                    class="px-2.5 py-1.5 transition-all"
                    :class="viewMode === 'list' ? 'bg-primary/20 text-primary' : 'text-zinc-500 hover:text-white hover:bg-white/5'"
                    title="List view"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
                        <rect x="3" y="4" width="18" height="2.5" rx="1"/>
                        <rect x="3" y="10.75" width="18" height="2.5" rx="1"/>
                        <rect x="3" y="17.5" width="18" height="2.5" rx="1"/>
                    </svg>
                </button>
            </div>
        </div>

        <!-- Empty state -->
        <div v-if="!demos.length" class="flex-1 flex flex-col items-center justify-center text-center gap-3 opacity-70">
            <div class="w-14 h-14 rounded-full bg-zinc-900/60 border border-white/10 flex items-center justify-center">
                <span class="material-symbols text-2xl text-zinc-500">folder_off</span>
            </div>
            <p class="text-sm text-zinc-400">This folder is empty.</p>
        </div>

        <div v-else-if="!filteredDemos.length" class="flex-1 flex flex-col items-center justify-center text-center gap-2 opacity-60">
            <span class="material-symbols text-2xl text-zinc-500">search_off</span>
            <p class="text-sm text-zinc-400">No demos match these filters.</p>
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
.custom-track::-webkit-scrollbar { width: 6px; }
.custom-track::-webkit-scrollbar-thumb { background-color: var(--color-primary); border-radius: 10px; }
.custom-track::-webkit-scrollbar-track { background-color: transparent; }
.custom-track { scrollbar-width: thin; scrollbar-color: var(--color-primary) transparent; }

.demo-grid {
    display: grid;
    gap: 12px;
    flex-grow: 1;
    width: 100%;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 0 8px 16px;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    grid-auto-rows: 170px;
    scrollbar-width: thin;
    scrollbar-color: var(--color-primary) transparent;
}
.demo-grid::-webkit-scrollbar { width: 6px; }
.demo-grid::-webkit-scrollbar-thumb { background-color: var(--color-primary); border-radius: 10px; }
.demo-grid::-webkit-scrollbar-track { background-color: transparent; }

@media (min-width: 640px)  { .demo-grid { grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); grid-auto-rows: 185px; gap: 14px; } }
@media (min-width: 1024px) { .demo-grid { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); grid-auto-rows: 190px; gap: 16px; } }
@media (min-width: 1280px) { .demo-grid { gap: 20px; } }
@media (min-width: 2100px) { .demo-grid { grid-template-columns: repeat(8, minmax(0, 1fr)); } }
</style>
