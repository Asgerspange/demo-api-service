<script setup>
import { ref, computed, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import useDemos from '@/composables/useDemos';
import { storeToRefs } from 'pinia';
import { useStore } from '@/store';

const route = useRoute();
const { Demos } = useDemos();
const { data: demo } = Demos.show(route.params.id);

const store = useStore();
const { user } = storeToRefs(store);
const userSteamId = computed(() => user.value?.user_info?.steam_id ?? null);

const showHero = computed(() => !['Demo2D', 'Demo3D'].includes(route.name));

const viewerTabs = [
    { name: 'Stats',     route: 'DemoOverview', icon: 'lucide:table-2' },
    { name: '2D Viewer', route: 'Demo2D',       icon: 'lucide:map' },
    { name: '3D Viewer', route: 'Demo3D',       icon: 'lucide:box' },
];

const analysisTabs = [
    { name: 'Overview', route: 'DemoOverview' },
    { name: 'Heatmaps', route: 'DemoHeatmaps' },
    { name: 'Grenades', route: 'DemoGrenades' },
];

// ── Derived data ────────────────────────────────────────────────────────
const teamAName = computed(() => demo.value?.stats?.team1?.[0]?.team_clan_name || 'Team Alpha');
const teamBName = computed(() => demo.value?.stats?.team2?.[0]?.team_clan_name || 'Team Bravo');

const meta = computed(() => demo.value?.last_round?.meta);

const tScore  = computed(() => Number(meta.value?.T_score ?? 0));
const ctScore = computed(() => Number(meta.value?.CT_score ?? 0));
const winningSide = computed(() => (meta.value?.winner || '').toLowerCase());

const teamASide = computed(() => (demo.value?.stats?.team1?.[0]?.side || '').toLowerCase());
const teamBSide = computed(() => (demo.value?.stats?.team2?.[0]?.side || '').toLowerCase());

const teamAScore = computed(() => teamASide.value === 'ct' ? ctScore.value : tScore.value);
const teamBScore = computed(() => teamBSide.value === 'ct' ? ctScore.value : tScore.value);

const teamAWon = computed(() => teamASide.value && winningSide.value && teamASide.value === winningSide.value);
const teamBWon = computed(() => teamBSide.value && winningSide.value && teamBSide.value === winningSide.value);

const mapName = computed(() => demo.value?.map ?? '');
const mapDisplay = computed(() => {
    const m = mapName.value;
    if (!m) return 'Unknown';
    const dict = {
        de_mirage: 'Mirage', de_dust2: 'Dust 2', de_inferno: 'Inferno',
        de_nuke: 'Nuke', de_overpass: 'Overpass', de_ancient: 'Ancient',
        de_anubis: 'Anubis', de_train: 'Train', de_vertigo: 'Vertigo',
    };
    return dict[m] ?? m.replace(/^de_/, '');
});
const mapBgKey = computed(() => mapName.value.replace(/^de_/, '').replace(/^cs_/, ''));

const durationMin = computed(() => {
    const officialEnd = meta.value?.official_end;
    if (!officialEnd) return null;
    return Math.round(officialEnd / 64 / 60);
});

const totalRounds = computed(() => tScore.value + ctScore.value);

const matchDate = computed(() => {
    const d = demo.value?.created_at;
    if (!d) return null;
    return new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
});

// Did the current user win? (used for verdict pill)
const userWon = computed(() => {
    const winners = meta.value?.winners;
    if (!winners || !userSteamId.value) return null;
    return winners.includes(String(userSteamId.value));
});

const breadcrumbs = computed(() => [
    { name: 'Demos', link: '/demos' },
    { name: demo.value?.name || '...', link: '#' },
]);

const isTabActive = (routeName) => route.name === routeName;
const isAnalysisRoute = computed(() => ['DemoOverview', 'DemoHeatmaps', 'DemoGrenades'].includes(route.name));
</script>

<template>
    <div class="dl" :class="{ 'dl--viewer': !showHero }">
        <!-- ── Top bar (always full-width container) ─────────────────── -->
        <header class="dl__top">
            <nav class="dl__crumbs" aria-label="Breadcrumb">
                <template v-for="(c, i) in breadcrumbs" :key="i">
                    <router-link :to="c.link" class="dl__crumb">{{ c.name }}</router-link>
                    <span v-if="i < breadcrumbs.length - 1" class="dl__crumb-sep">/</span>
                </template>
            </nav>

            <nav class="dl__modes" aria-label="View mode">
                <router-link
                    v-for="t in viewerTabs"
                    :key="t.name"
                    :to="{ name: t.route, params: { id: route.params.id }}"
                    class="dl__mode"
                    :class="{ 'dl__mode--active': isTabActive(t.route) || (t.route === 'DemoOverview' && isAnalysisRoute) }"
                >{{ t.name }}</router-link>
            </nav>
        </header>

        <!-- ── Analysis routes: hero + subnav + router-view in centered container ── -->
        <div v-if="showHero" class="dl__inner">

            <!-- ── Hero panel (only on analysis routes) ───────────────── -->
            <section v-if="showHero && demo" class="dl-hero">

                <div class="dl-hero__map" :data-map="mapBgKey" aria-hidden="true">
                    <div class="dl-hero__map-shade" />
                </div>

                <div class="dl-hero__content">

                    <!-- Top row: meta -->
                    <div class="dl-hero__meta">
                        <span class="dl-hero__meta-cell">
                            <span class="dl-hero__meta-label">Map</span>
                            <span class="dl-hero__meta-value">{{ mapDisplay }}</span>
                        </span>
                        <span class="dl-hero__meta-sep" />
                        <span class="dl-hero__meta-cell">
                            <span class="dl-hero__meta-label">Rounds</span>
                            <span class="dl-hero__meta-value">{{ totalRounds || '—' }}</span>
                        </span>
                        <span v-if="durationMin" class="dl-hero__meta-sep" />
                        <span v-if="durationMin" class="dl-hero__meta-cell">
                            <span class="dl-hero__meta-label">Duration</span>
                            <span class="dl-hero__meta-value">{{ durationMin }}m</span>
                        </span>
                        <span v-if="matchDate" class="dl-hero__meta-sep" />
                        <span v-if="matchDate" class="dl-hero__meta-cell">
                            <span class="dl-hero__meta-label">Date</span>
                            <span class="dl-hero__meta-value">{{ matchDate }}</span>
                        </span>
                        <span v-if="userWon !== null" class="dl-hero__verdict" :class="userWon ? 'dl-hero__verdict--w' : 'dl-hero__verdict--l'">
                            {{ userWon ? 'Win' : 'Loss' }}
                        </span>
                    </div>

                    <!-- Scoreboard -->
                    <div class="dl-hero__board">
                        <div class="dl-hero__team dl-hero__team--left" :class="{ 'dl-hero__team--won': teamAWon }">
                            <span class="dl-hero__team-side" :class="`dl-hero__team-side--${teamASide || 'unknown'}`">{{ teamASide ? teamASide.toUpperCase() : '' }}</span>
                            <h2 class="dl-hero__team-name">{{ teamAName }}</h2>
                        </div>

                        <div class="dl-hero__score">
                            <span class="dl-hero__score-num" :class="teamAWon ? 'dl-hero__score-num--w' : 'dl-hero__score-num--l'">{{ teamAScore }}</span>
                            <span class="dl-hero__score-sep">:</span>
                            <span class="dl-hero__score-num" :class="teamBWon ? 'dl-hero__score-num--w' : 'dl-hero__score-num--l'">{{ teamBScore }}</span>
                        </div>

                        <div class="dl-hero__team dl-hero__team--right" :class="{ 'dl-hero__team--won': teamBWon }">
                            <span class="dl-hero__team-side" :class="`dl-hero__team-side--${teamBSide || 'unknown'}`">{{ teamBSide ? teamBSide.toUpperCase() : '' }}</span>
                            <h2 class="dl-hero__team-name">{{ teamBName }}</h2>
                        </div>
                    </div>

                </div>
            </section>

            <!-- ── Analysis sub-tabs ──────────────────────────────────── -->
            <nav class="dl-subnav" aria-label="Analysis tabs">
                <router-link
                    v-for="t in analysisTabs"
                    :key="t.name"
                    :to="{ name: t.route, params: { id: route.params.id }}"
                    class="dl-subnav__tab"
                    :class="{ 'dl-subnav__tab--active': isTabActive(t.route) }"
                >{{ t.name }}</router-link>
            </nav>

            <!-- Content well: gives the active analysis route a defined area so
                 canvas-based pages (Heatmap, Grenades) using h-full work correctly -->
            <div class="dl__content">
                <router-view v-if="demo" :demo="demo" />
            </div>
        </div>

        <!-- ── Viewer routes: router-view fills the remaining space full-width ── -->
        <div v-else class="dl__viewer-wrap">
            <router-view v-if="demo" :demo="demo" />
        </div>
    </div>
</template>

<style scoped>
.dl {
    --dl-bg:        oklch(0.125 0.012 250);
    --dl-surface:   oklch(0.175 0.014 250);
    --dl-surface-2: oklch(0.215 0.016 250);
    --dl-surface-3: oklch(0.26 0.018 250);
    --dl-border:    oklch(1 0 0 / 0.09);
    --dl-border-2:  oklch(1 0 0 / 0.14);
    --dl-text:      oklch(1 0 0 / 0.96);
    --dl-text-2:    oklch(1 0 0 / 0.70);
    --dl-text-3:    oklch(1 0 0 / 0.62);
    --dl-text-4:    oklch(1 0 0 / 0.50);
    --dl-accent:    var(--main-color, #ff8c00);
    --dl-win:       oklch(0.72 0.14 145);
    --dl-loss:      oklch(0.62 0.20 22);
    --dl-sans:      'Schibsted Grotesk', 'Helvetica Neue', Arial, sans-serif;
    --dl-mono:      'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;

    position: relative;
    width: 100%;
    height: 100%;
    overflow-y: auto;
    background: var(--dl-bg);
    color: var(--dl-text);
    font-family: var(--dl-sans);
    scrollbar-width: thin;
    scrollbar-color: var(--dl-border-2) transparent;
    display: flex;
    flex-direction: column;
}
.dl::-webkit-scrollbar { width: 6px; }
.dl::-webkit-scrollbar-thumb { background: var(--dl-border-2); border-radius: 3px; }

/* Viewer routes: no inner constraint, no padding — viewer takes the space */
.dl--viewer {
    overflow: hidden;
}

.dl--viewer .dl__top {
    padding: 12px 16px;
    border-bottom: 1px solid var(--dl-border);
    background: var(--dl-bg);
    z-index: 30;
    flex-shrink: 0;
}

.dl__inner {
    max-width: 1400px;
    width: 100%;
    margin: 0 auto;
    padding: 0 16px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    flex: 1;
    min-height: 0;
}

.dl__content {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
}

.dl__viewer-wrap {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

@media (min-width: 640px) {
    .dl__inner { padding: 0 24px 32px; }
    .dl--viewer .dl__top { padding: 14px 24px; }
}

@media (min-width: 1024px) {
    .dl__inner { padding: 0 32px 40px; }
    .dl--viewer .dl__top { padding: 16px 32px; }
}

/* ── Top ── */
.dl__top {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 18px 16px 0;
}
@media (min-width: 640px) {
    .dl__top { flex-direction: row; align-items: center; justify-content: space-between; padding: 24px 24px 0; }
}
@media (min-width: 1024px) {
    .dl__top { padding: 28px 32px 0; }
}

/* Viewer-mode .dl__top overrides defined earlier (line 233 etc.) */

.dl__crumbs {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
    min-width: 0;
}

.dl__crumb {
    font-family: var(--dl-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--dl-text-3);
    text-decoration: none;
    transition: color 150ms ease;
    max-width: 12rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.dl__crumb:hover { color: var(--dl-accent); }
.dl__crumb:last-of-type { color: var(--dl-text); }

.dl__crumb-sep { color: var(--dl-text-4); }

.dl__modes {
    display: flex;
    gap: 2px;
    padding: 3px;
    background: var(--dl-surface);
    border: 1px solid var(--dl-border);
    border-radius: 6px;
    overflow-x: auto;
    scrollbar-width: none;
    flex-shrink: 0;
}
.dl__modes::-webkit-scrollbar { display: none; }

.dl__mode {
    font-family: var(--dl-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--dl-text-3);
    padding: 7px 12px;
    border-radius: 4px;
    text-decoration: none;
    white-space: nowrap;
    transition: color 150ms ease, background 150ms ease;
}
.dl__mode:hover { color: var(--dl-text-2); }
.dl__mode--active {
    color: var(--dl-text);
    background: var(--dl-surface-2);
}

/* ── Hero panel ── */
.dl-hero {
    position: relative;
    border: 1px solid var(--dl-border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--dl-surface);
    isolation: isolate;
}

.dl-hero__map {
    position: absolute;
    inset: 0;
    background-size: cover;
    background-position: center;
    z-index: 0;
    opacity: 0.18;
}

.dl-hero__map[data-map="mirage"]   { background-image: url('/images/maps/mirage.webp'); }
.dl-hero__map[data-map="dust2"]    { background-image: url('/images/maps/dust2.webp'); }
.dl-hero__map[data-map="inferno"]  { background-image: url('/images/maps/inferno.webp'); }
.dl-hero__map[data-map="nuke"]     { background-image: url('/images/maps/nuke.webp'); }
.dl-hero__map[data-map="overpass"] { background-image: url('/images/maps/overpass.webp'); }
.dl-hero__map[data-map="ancient"]  { background-image: url('/images/maps/ancient.webp'); }
.dl-hero__map[data-map="anubis"]   { background-image: url('/images/maps/anubis.webp'); }
.dl-hero__map[data-map="train"]    { background-image: url('/images/maps/train.webp'); }
.dl-hero__map[data-map="vertigo"]  { background-image: url('/images/maps/vertigo.webp'); }

.dl-hero__map-shade {
    position: absolute;
    inset: 0;
    background: linear-gradient(
        to bottom,
        oklch(0.175 0.014 250 / 0.55) 0%,
        oklch(0.175 0.014 250 / 0.92) 70%,
        oklch(0.175 0.014 250 / 0.98) 100%
    );
}

.dl-hero__content {
    position: relative;
    z-index: 1;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 18px;
}

@media (min-width: 768px) {
    .dl-hero__content { padding: 22px 28px; gap: 22px; }
}

/* Meta row */
.dl-hero__meta {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
}

.dl-hero__meta-cell { display: flex; flex-direction: column; gap: 2px; }

.dl-hero__meta-label {
    font-family: var(--dl-mono);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--dl-text-3);
}

.dl-hero__meta-value {
    font-family: var(--dl-mono);
    font-size: 13px;
    font-weight: 600;
    color: var(--dl-text);
    font-variant-numeric: tabular-nums;
}

.dl-hero__meta-sep {
    width: 1px;
    height: 22px;
    background: var(--dl-border-2);
}

.dl-hero__verdict {
    font-family: var(--dl-mono);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 4px 10px;
    border-radius: 3px;
    margin-left: auto;
}

.dl-hero__verdict--w {
    color: var(--dl-win);
    background: color-mix(in oklch, var(--dl-win) 14%, transparent);
}

.dl-hero__verdict--l {
    color: var(--dl-loss);
    background: color-mix(in oklch, var(--dl-loss) 14%, transparent);
}

/* Scoreboard */
.dl-hero__board {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    gap: 16px;
}

.dl-hero__team {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
}

.dl-hero__team--left  { align-items: flex-end;   text-align: right; }
.dl-hero__team--right { align-items: flex-start; text-align: left;  }

.dl-hero__team-side {
    font-family: var(--dl-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    padding: 2px 7px;
    border-radius: 2px;
    line-height: 1.4;
}

.dl-hero__team-side--ct {
    color: oklch(0.75 0.10 220);
    background: color-mix(in oklch, oklch(0.65 0.10 220) 18%, transparent);
}
.dl-hero__team-side--t {
    color: oklch(0.80 0.13 60);
    background: color-mix(in oklch, oklch(0.65 0.13 60) 18%, transparent);
}
.dl-hero__team-side--unknown { display: none; }

.dl-hero__team-name {
    font-family: var(--dl-sans);
    font-size: clamp(1rem, 2.4vw, 1.625rem);
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--dl-text);
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
    opacity: 0.72;
    transition: opacity 250ms ease;
}

.dl-hero__team--won .dl-hero__team-name { opacity: 1; }

.dl-hero__score {
    display: inline-flex;
    align-items: baseline;
    gap: 8px;
    padding: 8px 18px;
    background: var(--dl-surface-2);
    border: 1px solid var(--dl-border);
    border-radius: 6px;
}

.dl-hero__score-num {
    font-family: var(--dl-mono);
    font-size: clamp(1.625rem, 4vw, 2.5rem);
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
}

.dl-hero__score-num--w { color: var(--dl-win); }
.dl-hero__score-num--l { color: var(--dl-text-2); }

.dl-hero__score-sep {
    font-family: var(--dl-mono);
    font-size: clamp(1.625rem, 4vw, 2.5rem);
    font-weight: 800;
    color: var(--dl-text-4);
    line-height: 1;
}

/* ── Subnav ── */
.dl-subnav {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--dl-border);
    overflow-x: auto;
    scrollbar-width: none;
}
.dl-subnav::-webkit-scrollbar { display: none; }

.dl-subnav__tab {
    position: relative;
    font-family: var(--dl-sans);
    font-size: 13px;
    font-weight: 500;
    color: var(--dl-text-3);
    padding: 10px 16px;
    text-decoration: none;
    white-space: nowrap;
    transition: color 150ms ease;
}
.dl-subnav__tab:first-child { padding-left: 2px; }
.dl-subnav__tab:hover { color: var(--dl-text-2); }
.dl-subnav__tab--active { color: var(--dl-text); }

.dl-subnav__tab--active::after {
    content: '';
    position: absolute;
    bottom: -1px;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--dl-accent);
}

.dl-subnav__tab:focus-visible {
    outline: 2px solid var(--dl-accent);
    outline-offset: 4px;
    border-radius: 2px;
}

/* ── Mobile responsive ── */
@media (max-width: 540px) {
    .dl-hero__content { padding: 14px 16px; gap: 14px; }

    .dl-hero__meta { gap: 10px; }
    .dl-hero__meta-sep { display: none; }
    .dl-hero__verdict { margin-left: 0; order: -1; width: 100%; }

    .dl-hero__board {
        grid-template-columns: 1fr;
        gap: 10px;
    }
    .dl-hero__team {
        align-items: center;
        text-align: center;
    }
    .dl-hero__team--left  { align-items: center; text-align: center; }
    .dl-hero__team--right { align-items: center; text-align: center; }
    .dl-hero__team-name { font-size: 1.125rem; }
    .dl-hero__score { padding: 6px 14px; }
}
</style>
