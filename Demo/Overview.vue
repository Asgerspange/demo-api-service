<script setup>
import { ref, computed } from 'vue';
import { useRoute } from 'vue-router';
import useDemos from '@/composables/useDemos';

const route = useRoute();
const { Demos } = useDemos();
const { data: demo } = Demos.show(route.params.id);

// ── Sort ───────────────────────────────────────────────────────────────
const sortBy  = ref('rating');
const sortDir = ref('desc');

const COLS = [
    { key: 'kills',  label: 'K' },
    { key: 'deaths', label: 'D' },
    { key: 'kdDiff', label: '+/-' },
    { key: 'adr',    label: 'ADR' },
    { key: 'hs',     label: 'HS%' },
    { key: 'kast',   label: 'KAST' },
    { key: 'rating', label: 'Rating' },
];

function setSort(key) {
    if (sortBy.value === key) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc';
    else { sortBy.value = key; sortDir.value = 'desc'; }
}

// ── Data ───────────────────────────────────────────────────────────────
const allDetailedStats = computed(() => demo.value?.stats?.stats ?? []);
const teamAlpha = computed(() => demo.value?.stats?.team1 ?? []);
const teamBravo = computed(() => demo.value?.stats?.team2 ?? []);
const KDA       = computed(() => demo.value?.stats?.KDA ?? []);
const kast      = computed(() => demo.value?.stats?.kast ?? []);
const rating    = computed(() => demo.value?.stats?.rating ?? []);

const findAll = (arr, sid) => arr?.find(p => p.steamid === sid && (p.side === 'all' || !p.side));

function getStat(stat, sid) {
    if (stat === 'kills' || stat === 'deaths' || stat === 'assists') return findAll(KDA.value, sid)?.[stat] ?? 0;
    if (stat === 'kdDiff') {
        const p = findAll(KDA.value, sid);
        return (p?.kills ?? 0) - (p?.deaths ?? 0);
    }
    if (stat === 'kast')   return Number(findAll(kast.value, sid)?.kast ?? 0);
    if (stat === 'rating') return Number(findAll(rating.value, sid)?.rating ?? 0);
    if (stat === 'hs') {
        const p = findAll(allDetailedStats.value, sid);
        const k = findAll(KDA.value, sid)?.kills ?? 0;
        return k > 0 ? ((p?.headshot_kills ?? 0) / k) * 100 : 0;
    }
    return findAll(allDetailedStats.value, sid)?.[stat] ?? 0;
}

function totalClutches(sid) {
    return [1,2,3,4,5].reduce((s, v) => s + Number(getStat(`1v${v}`, sid) || 0), 0);
}

function sortPlayers(players) {
    const dir = sortDir.value === 'desc' ? -1 : 1;
    return [...players].sort((a, b) => (Number(getStat(sortBy.value, a.steamid)) - Number(getStat(sortBy.value, b.steamid))) * dir);
}

const sortedAlpha = computed(() => sortPlayers(teamAlpha.value));
const sortedBravo = computed(() => sortPlayers(teamBravo.value));

const getTeamName = (sid) => {
    const player = [...teamAlpha.value, ...teamBravo.value].find(p => p.steamid === sid);
    return player?.team_clan_name ?? null;
};

function teamAggregate(team) {
    if (!team?.length) return null;
    const avg = (key) => team.reduce((acc, p) => acc + Number(getStat(key, p.steamid) || 0), 0) / team.length;
    return { avgRating: avg('rating'), avgAdr: avg('adr'), avgKast: avg('kast') };
}

const alphaAgg = computed(() => teamAggregate(teamAlpha.value));
const bravoAgg = computed(() => teamAggregate(teamBravo.value));

const teamSide = (team) => (team?.[0]?.side || '').toLowerCase();

const teams = computed(() => [
    { players: sortedAlpha.value, agg: alphaAgg.value, label: '01', name: getTeamName(teamAlpha.value?.[0]?.steamid) ?? 'Team Alpha', side: teamSide(teamAlpha.value) },
    { players: sortedBravo.value, agg: bravoAgg.value, label: '02', name: getTeamName(teamBravo.value?.[0]?.steamid) ?? 'Team Bravo', side: teamSide(teamBravo.value) },
]);

// ── Highlights (single row, compact) ───────────────────────────────────
const allPlayers = computed(() => [...teamAlpha.value, ...teamBravo.value]);

const highlights = computed(() => {
    if (!allPlayers.value.length) return [];

    const byRating = allPlayers.value.map(p => ({ p, v: Number(getStat('rating', p.steamid)) })).sort((a,b) => b.v - a.v)[0];
    const byImpact = allPlayers.value.map(p => ({ p, v: Number(getStat('kdDiff', p.steamid)) })).sort((a,b) => b.v - a.v)[0];
    const byClutch = allPlayers.value.map(p => ({ p, v: totalClutches(p.steamid) })).sort((a,b) => b.v - a.v)[0];
    const byUtil   = allPlayers.value.map(p => ({ p, v: Number(getStat('utility_damage', p.steamid)) })).sort((a,b) => b.v - a.v)[0];

    const out = [];
    if (byRating?.v > 0) out.push({ tag: 'Top rated',    name: byRating.p.name, value: byRating.v.toFixed(2),         tone: 'elite' });
    if (byImpact)        out.push({ tag: 'Impact',       name: byImpact.p.name, value: (byImpact.v > 0 ? '+' : '') + byImpact.v, tone: 'good' });
    if (byClutch?.v > 0) out.push({ tag: 'Clutches',     name: byClutch.p.name, value: byClutch.v + ' won',           tone: 'accent' });
    if (byUtil?.v > 0)   out.push({ tag: 'Utility dmg',  name: byUtil.p.name,   value: Math.round(byUtil.v),          tone: 'neutral' });
    return out;
});

// ── Rating helpers ──────────────────────────────────────────────────────
function ratingTier(r) {
    if (r >= 1.20) return 'elite';
    if (r >= 1.05) return 'good';
    if (r >= 0.90) return 'avg';
    return 'low';
}

function ratingBarPct(r) {
    const v = Math.max(0.5, Math.min(1.5, r));
    return ((v - 0.5) / 1.0) * 100;
}

const fmt = (v, d = 0) => Number(v ?? 0).toFixed(d);
</script>

<template>
    <div class="ov" v-if="demo">

        <!-- Highlights strip (compact, single row) -->
        <ul v-if="highlights.length" class="ov-hi">
            <li v-for="(h, i) in highlights" :key="i" class="ov-hi__cell">
                <span class="ov-hi__tag">{{ h.tag }}</span>
                <span class="ov-hi__name">{{ h.name }}</span>
                <span class="ov-hi__val" :class="`ov-hi__val--${h.tone}`">{{ h.value }}</span>
            </li>
        </ul>

        <!-- Team blocks -->
        <section v-for="(team, idx) in teams" :key="idx" class="ov-team">

            <header class="ov-team__head">
                <span class="ov-team__num">{{ team.label }}</span>
                <h3 class="ov-team__name">{{ team.name }}</h3>
                <div class="ov-team__agg" v-if="team.agg">
                    <span class="ov-team__agg-cell"><span>R</span> {{ fmt(team.agg.avgRating, 2) }}</span>
                    <span class="ov-team__agg-cell"><span>ADR</span> {{ fmt(team.agg.avgAdr) }}</span>
                    <span class="ov-team__agg-cell"><span>KAST</span> {{ fmt(team.agg.avgKast) }}%</span>
                </div>
            </header>

            <!-- Desktop table -->
            <table class="ov-table">
                <thead>
                    <tr>
                        <th class="ov-th ov-th--name">Player</th>
                        <th v-for="col in COLS" :key="col.key" class="ov-th ov-th--num">
                            <button
                                class="ov-th__btn"
                                :class="{ 'ov-th__btn--active': sortBy === col.key }"
                                @click="setSort(col.key)"
                            >
                                {{ col.label }}<span v-if="sortBy === col.key" class="ov-th__arrow">{{ sortDir === 'desc' ? '↓' : '↑' }}</span>
                            </button>
                        </th>
                        <th class="ov-th ov-th--num">Clutch</th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="(player, pidx) in team.players"
                        :key="player.steamid"
                        class="ov-tr"
                        :class="{ 'ov-tr--top': pidx === 0 }"
                    >
                        <td class="ov-td ov-td--name">
                            <span class="ov-td__rank">{{ pidx + 1 }}</span>
                            <span class="ov-td__player">{{ player.name }}</span>
                        </td>
                        <td class="ov-td">{{ getStat('kills', player.steamid) }}</td>
                        <td class="ov-td ov-td--quiet">{{ getStat('deaths', player.steamid) }}</td>
                        <td class="ov-td" :class="getStat('kdDiff', player.steamid) >= 0 ? 'ov-td--plus' : 'ov-td--minus'">
                            {{ getStat('kdDiff', player.steamid) > 0 ? '+' : '' }}{{ getStat('kdDiff', player.steamid) }}
                        </td>
                        <td class="ov-td">{{ Math.round(getStat('adr', player.steamid)) }}</td>
                        <td class="ov-td ov-td--quiet">{{ Math.round(getStat('hs', player.steamid)) }}%</td>
                        <td class="ov-td ov-td--quiet">{{ Math.round(getStat('kast', player.steamid)) }}%</td>
                        <td class="ov-td ov-td--rating">
                            <span class="ov-rating">
                                <span class="ov-rating__num" :class="`ov-rating__num--${ratingTier(getStat('rating', player.steamid))}`">{{ fmt(getStat('rating', player.steamid), 2) }}</span>
                                <span class="ov-rating__bar">
                                    <span
                                        class="ov-rating__bar-fill"
                                        :class="`ov-rating__bar-fill--${ratingTier(getStat('rating', player.steamid))}`"
                                        :style="{ transform: `scaleX(${ratingBarPct(getStat('rating', player.steamid)) / 100})` }"
                                    />
                                </span>
                            </span>
                        </td>
                        <td class="ov-td ov-td--clutch">
                            <span v-if="totalClutches(player.steamid) > 0" class="ov-cl">
                                <span
                                    v-for="v in [1,2,3,4,5]"
                                    :key="v"
                                    class="ov-cl__dot"
                                    :class="{ 'ov-cl__dot--on': getStat(`1v${v}`, player.steamid) > 0 }"
                                    :title="`1v${v}: ${getStat(`1v${v}`, player.steamid)}`"
                                />
                                <span class="ov-cl__sum">{{ totalClutches(player.steamid) }}</span>
                            </span>
                            <span v-else class="ov-cl ov-cl--empty">—</span>
                        </td>
                    </tr>
                </tbody>
            </table>

            <!-- Mobile rows -->
            <ul class="ov-mobile">
                <li
                    v-for="(player, pidx) in team.players"
                    :key="player.steamid + '-m'"
                    class="ov-mrow"
                    :class="{ 'ov-mrow--top': pidx === 0 }"
                >
                    <div class="ov-mrow__head">
                        <span class="ov-mrow__rank">{{ pidx + 1 }}</span>
                        <span class="ov-mrow__name">{{ player.name }}</span>
                        <span class="ov-mrow__rating" :class="`ov-mrow__rating--${ratingTier(getStat('rating', player.steamid))}`">
                            {{ fmt(getStat('rating', player.steamid), 2) }}
                        </span>
                    </div>
                    <div class="ov-mrow__line">
                        <span class="ov-mrow__chip">
                            <span class="ov-mrow__chip-num">{{ getStat('kills', player.steamid) }}</span>
                            <span class="ov-mrow__chip-sep">/</span>
                            <span class="ov-mrow__chip-num ov-mrow__chip-num--quiet">{{ getStat('deaths', player.steamid) }}</span>
                            <span class="ov-mrow__chip-label">K/D</span>
                        </span>
                        <span class="ov-mrow__chip">
                            <span class="ov-mrow__chip-num" :class="getStat('kdDiff', player.steamid) >= 0 ? 'ov-td--plus' : 'ov-td--minus'">
                                {{ getStat('kdDiff', player.steamid) > 0 ? '+' : '' }}{{ getStat('kdDiff', player.steamid) }}
                            </span>
                            <span class="ov-mrow__chip-label">+/-</span>
                        </span>
                        <span class="ov-mrow__chip">
                            <span class="ov-mrow__chip-num">{{ Math.round(getStat('adr', player.steamid)) }}</span>
                            <span class="ov-mrow__chip-label">ADR</span>
                        </span>
                        <span class="ov-mrow__chip">
                            <span class="ov-mrow__chip-num">{{ Math.round(getStat('hs', player.steamid)) }}%</span>
                            <span class="ov-mrow__chip-label">HS</span>
                        </span>
                        <span class="ov-mrow__chip">
                            <span class="ov-mrow__chip-num">{{ Math.round(getStat('kast', player.steamid)) }}%</span>
                            <span class="ov-mrow__chip-label">KAST</span>
                        </span>
                        <span v-if="totalClutches(player.steamid) > 0" class="ov-mrow__chip ov-mrow__chip--clutch">
                            <span class="ov-mrow__chip-num">{{ totalClutches(player.steamid) }}</span>
                            <span class="ov-mrow__chip-label">CL</span>
                        </span>
                    </div>
                </li>
            </ul>
        </section>
    </div>
</template>

<style scoped>
.ov {
    --ov-bg:        oklch(0.125 0.012 250);
    --ov-surface:   oklch(0.175 0.014 250);
    --ov-surface-2: oklch(0.215 0.016 250);
    --ov-surface-3: oklch(0.26 0.018 250);
    --ov-border:    oklch(1 0 0 / 0.09);
    --ov-text:      oklch(1 0 0 / 0.96);
    --ov-text-2:    oklch(1 0 0 / 0.70);
    --ov-text-3:    oklch(1 0 0 / 0.62);
    --ov-text-4:    oklch(1 0 0 / 0.50);
    --ov-accent:    var(--main-color, #ff8c00);
    --ov-elite:     oklch(0.72 0.18 50);
    --ov-good:      oklch(0.72 0.14 145);
    --ov-low:       oklch(0.62 0.20 22);
    --ov-sans:      'Schibsted Grotesk', sans-serif;
    --ov-mono:      'JetBrains Mono', monospace;

    display: flex;
    flex-direction: column;
    gap: 14px;
    padding-bottom: 24px;
}

/* ── Highlights ── */
.ov-hi {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1px;
    background: var(--ov-border);
    border: 1px solid var(--ov-border);
    border-radius: 5px;
    margin: 0;
    padding: 0;
    list-style: none;
    overflow: hidden;
}

.ov-hi__cell {
    background: var(--ov-surface);
    padding: 8px 12px;
    display: grid;
    grid-template-columns: 1fr auto;
    grid-template-rows: auto auto;
    gap: 0 8px;
    align-items: baseline;
}

.ov-hi__tag {
    grid-column: 1;
    grid-row: 1;
    font-family: var(--ov-mono);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ov-text-3);
}

.ov-hi__name {
    grid-column: 1;
    grid-row: 2;
    font-family: var(--ov-sans);
    font-size: 12px;
    font-weight: 500;
    color: var(--ov-text-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ov-hi__val {
    grid-column: 2;
    grid-row: 1 / span 2;
    align-self: center;
    font-family: var(--ov-mono);
    font-size: 15px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}

.ov-hi__val--elite   { color: var(--ov-elite); }
.ov-hi__val--good    { color: var(--ov-good); }
.ov-hi__val--accent  { color: var(--ov-accent); }
.ov-hi__val--neutral { color: var(--ov-text); }

/* ── Team block ── */
.ov-team {
    background: var(--ov-surface);
    border: 1px solid var(--ov-border);
    border-radius: 5px;
    overflow: hidden;
}

.ov-team__head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 14px;
    background: var(--ov-surface-2);
    border-bottom: 1px solid var(--ov-border);
}

.ov-team__num {
    font-family: var(--ov-mono);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: var(--ov-accent);
    padding: 2px 6px;
    background: color-mix(in oklch, var(--ov-accent) 14%, transparent);
    border-radius: 2px;
    line-height: 1.4;
}

.ov-team__name {
    font-family: var(--ov-sans);
    font-size: 13px;
    font-weight: 600;
    color: var(--ov-text);
    margin: 0;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ov-team__agg {
    display: flex;
    gap: 14px;
}

.ov-team__agg-cell {
    font-family: var(--ov-mono);
    font-size: 11px;
    font-weight: 600;
    color: var(--ov-text);
    font-variant-numeric: tabular-nums;
}

.ov-team__agg-cell > span {
    color: var(--ov-text-3);
    font-weight: 500;
    letter-spacing: 0.06em;
    margin-right: 3px;
}

/* ── Table (desktop) ── */
.ov-table {
    display: none;
    width: 100%;
    border-collapse: collapse;
}

@media (min-width: 800px) {
    .ov-table { display: table; }
    .ov-mobile { display: none; }
}

.ov-th {
    padding: 8px 10px;
    font-family: var(--ov-mono);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ov-text-3);
    border-bottom: 1px solid var(--ov-border);
    background: var(--ov-surface);
    text-align: right;
    line-height: 1;
}

.ov-th--name { text-align: left; padding-left: 14px; }
.ov-th--num  { text-align: right; }
.ov-th:last-child { padding-right: 14px; }

.ov-th__btn {
    background: none;
    border: none;
    color: inherit;
    font: inherit;
    letter-spacing: inherit;
    text-transform: inherit;
    cursor: pointer;
    padding: 0;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    transition: color 150ms ease;
}
.ov-th__btn:hover { color: var(--ov-text-2); }
.ov-th__btn--active { color: var(--ov-text); }
.ov-th__btn:focus-visible { outline: 2px solid var(--ov-accent); outline-offset: 2px; border-radius: 2px; }
.ov-th__arrow { font-size: 9px; color: var(--ov-accent); }

.ov-tr { transition: background 110ms ease; }
.ov-tr:hover { background: var(--ov-surface-2); }
.ov-tr--top { background: color-mix(in oklch, var(--ov-accent) 3%, transparent); }

.ov-td {
    padding: 7px 10px;
    font-family: var(--ov-mono);
    font-size: 12px;
    font-weight: 500;
    color: var(--ov-text);
    text-align: right;
    border-bottom: 1px solid var(--ov-border);
    font-variant-numeric: tabular-nums;
    line-height: 1.3;
}

.ov-tr:last-child .ov-td { border-bottom: none; }
.ov-td:last-child { padding-right: 14px; }

.ov-td--name {
    text-align: left;
    padding-left: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.ov-td__rank {
    width: 18px;
    height: 18px;
    border-radius: 2px;
    background: var(--ov-surface-3);
    color: var(--ov-text-3);
    font-family: var(--ov-mono);
    font-size: 10px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.ov-tr--top .ov-td__rank {
    color: var(--ov-accent);
    background: color-mix(in oklch, var(--ov-accent) 18%, transparent);
}

.ov-td__player {
    font-family: var(--ov-sans);
    font-size: 13px;
    font-weight: 600;
    color: var(--ov-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ov-td--quiet { color: var(--ov-text-3); }
.ov-td--plus  { color: var(--ov-good); }
.ov-td--minus { color: var(--ov-low); }

/* Rating */
.ov-td--rating { min-width: 110px; }

.ov-rating {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    justify-content: flex-end;
    width: 100%;
}

.ov-rating__num {
    font-family: var(--ov-mono);
    font-size: 12px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    min-width: 32px;
    text-align: right;
}

.ov-rating__num--elite { color: var(--ov-elite); }
.ov-rating__num--good  { color: var(--ov-good); }
.ov-rating__num--avg   { color: var(--ov-text); }
.ov-rating__num--low   { color: var(--ov-low); }

.ov-rating__bar {
    width: 48px;
    height: 3px;
    background: var(--ov-surface-3);
    border-radius: 2px;
    overflow: hidden;
}

.ov-rating__bar-fill {
    height: 100%;
    width: 100%;
    transform-origin: left center;
    background: var(--ov-text-3);
    transition: transform 300ms cubic-bezier(0.22, 1, 0.36, 1);
}

.ov-rating__bar-fill--elite { background: var(--ov-elite); }
.ov-rating__bar-fill--good  { background: var(--ov-good); }
.ov-rating__bar-fill--avg   { background: var(--ov-text-2); }
.ov-rating__bar-fill--low   { background: var(--ov-low); }

/* Clutches (compact dot strip) */
.ov-td--clutch { white-space: nowrap; }

.ov-cl {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    justify-content: flex-end;
}

.ov-cl--empty { color: var(--ov-text-4); }

.ov-cl__dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ov-surface-3);
    flex-shrink: 0;
}

.ov-cl__dot--on { background: var(--ov-accent); }

.ov-cl__sum {
    margin-left: 4px;
    font-family: var(--ov-mono);
    font-size: 11px;
    font-weight: 700;
    color: var(--ov-accent);
}

/* ── Mobile rows ── */
.ov-mobile {
    list-style: none;
    margin: 0;
    padding: 0;
}

.ov-mrow {
    padding: 8px 12px;
    border-bottom: 1px solid var(--ov-border);
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.ov-mrow:last-child { border-bottom: none; }
.ov-mrow--top { background: color-mix(in oklch, var(--ov-accent) 3%, transparent); }

.ov-mrow__head {
    display: grid;
    grid-template-columns: 20px 1fr auto;
    align-items: center;
    gap: 8px;
}

.ov-mrow__rank {
    width: 20px;
    height: 20px;
    border-radius: 2px;
    background: var(--ov-surface-3);
    color: var(--ov-text-3);
    font-family: var(--ov-mono);
    font-size: 10px;
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.ov-mrow--top .ov-mrow__rank {
    color: var(--ov-accent);
    background: color-mix(in oklch, var(--ov-accent) 18%, transparent);
}

.ov-mrow__name {
    font-family: var(--ov-sans);
    font-size: 13px;
    font-weight: 600;
    color: var(--ov-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.ov-mrow__rating {
    font-family: var(--ov-mono);
    font-size: 14px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}
.ov-mrow__rating--elite { color: var(--ov-elite); }
.ov-mrow__rating--good  { color: var(--ov-good); }
.ov-mrow__rating--avg   { color: var(--ov-text); }
.ov-mrow__rating--low   { color: var(--ov-low); }

.ov-mrow__line {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 10px;
    padding-left: 28px;
}

.ov-mrow__chip {
    display: inline-flex;
    align-items: baseline;
    gap: 3px;
    line-height: 1.2;
}

.ov-mrow__chip-num {
    font-family: var(--ov-mono);
    font-size: 12px;
    font-weight: 600;
    color: var(--ov-text);
    font-variant-numeric: tabular-nums;
}

.ov-mrow__chip-num--quiet { color: var(--ov-text-3); }

.ov-mrow__chip-sep {
    color: var(--ov-text-4);
    font-family: var(--ov-mono);
    font-size: 10px;
}

.ov-mrow__chip-label {
    font-family: var(--ov-mono);
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--ov-text-3);
}

.ov-mrow__chip--clutch .ov-mrow__chip-num { color: var(--ov-accent); }

@media (max-width: 540px) {
    .ov-team__head { flex-wrap: wrap; gap: 6px 10px; }
    .ov-team__agg { width: 100%; justify-content: space-between; gap: 8px; }
}

@media (prefers-reduced-motion: reduce) {
    .ov-rating__bar-fill { transition: none; }
}
</style>
