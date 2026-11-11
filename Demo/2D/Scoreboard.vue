<template>
    <Dialog v-model:visible="visible" modal :pt="{content:() => ({style: {'overflow-y': 'auto !important'}})}" header="CS:GO Match Scoreboard" :style="{ width: '60vw' }" :breakpoints="{ '960px': '75vw', '640px': '90vw' }" :closeOnEscape="true" :dismissableMask="true" :showHeader="false" :appendTo="'self'"  @update:visible="close()">
        <div class="match-container">
            <div class="match-header">
                <div class="team-header team-ct">
                    <h2>{{ ctPlayers?.[0]?.['team_clan_name'] ?? 'Counter-Terrorists' }}</h2>
                    <div class="team-score">{{ meta.CT_score }}</div>
                </div>
                <div class="vs">VS</div>
                <div class="team-header team-t">
                    <div class="team-score">{{ meta.T_score }}</div>
                    <h2>{{ tPlayers?.[0]?.['team_clan_name'] ?? 'Terrorists' }}</h2>
                </div>
            </div>
            
            <div class="scoreboard-container">
                <div class="team-section">
                    <h3 class="team-name-tab ct"></h3>
                    <div class="scoreboard-table">
                        <div class="scoreboard-header">
                            <div class="col-player">PLAYER</div>
                            <div class="col-stat">K</div>
                            <div class="col-stat">D</div>
                            <div class="col-stat">A</div>
                            <div class="col-stat">3K</div>
                            <div class="col-stat">4K</div>
                            <div class="col-stat">$</div>
                            <div class="col-stat">HEALTH</div>
                            <div class="col-stat">ARMOR</div>
                            <div class="col-weapon">WEAPONS</div>
                        </div>
                        <div v-for="player in ctPlayers" :key="player.steamid" class="player-row">
                            <div class="col-player">
                                <Avatar :image="getAvatarUrl(player.name)" shape="circle" />
                                <div class="player-info">
                                    <span class="player-name">{{ player.name }}</span>
                                    <!-- <div class="player-honors">
                                        <Badge v-tooltip.top="'Leader Honor'" value="L" severity="info" class="mr-1" />{{ player.leader_honors }} 
                                        <Badge v-tooltip.top="'Teacher Honor'" value="T" severity="success" class="mx-1" />{{ player.teacher_honors }}
                                        <Badge v-tooltip.top="'Friendly Honor'" value="F" severity="warning" class="ml-1" />{{ player.friendly_honors }}
                                    </div> -->
                                </div>
                            </div>
                            <div class="col-stat">{{ player.kills_total }}</div>
                            <div class="col-stat">{{ player.deaths_total }}</div>
                            <div class="col-stat">{{ player.assists_total }}</div>
                            <div class="col-stat">{{ player["3k_rounds_total"] }}</div>
                            <div class="col-stat">{{ player["4k_rounds_total"] }}</div>
                            <div class="col-stat">${{ player.balance }}</div>
                            <div class="col-stat">
                                <ProgressBar :value="player.health" :showValue="false" class="health-bar" />
                                <span>{{ player.health }}</span>
                            </div>
                            <div class="col-stat">
                                <ProgressBar :value="player.armor_value" :showValue="false" class="armor-bar" />
                                <span>{{ player.armor_value }}</span>
                            </div>
                            <div class="col-weapon">
                                <template v-for="(weapon, index) in player.inventory">
                                    <svg v-if="!weapon.toLowerCase().includes('knife')" :key="index" alt="" viewBox="30 -30 40 100" class="weapon-icon">
                                        <path :d="getWeapon(weapon).svg_path" fill="currentColor" />
                                    </svg>
                                </template>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="team-section">
                    <h3 class="team-name-tab t"></h3>
                    <div class="scoreboard-table">
                        <div class="scoreboard-header">
                            <div class="col-player">PLAYER</div>
                            <div class="col-stat">K</div>
                            <div class="col-stat">D</div>
                            <div class="col-stat">A</div>
                            <div class="col-stat">3K</div>
                            <div class="col-stat">4K</div>
                            <div class="col-stat">$</div>
                            <div class="col-stat">HEALTH</div>
                            <div class="col-stat">ARMOR</div>
                            <div class="col-weapon">WEAPONS</div>
                        </div>
                        <div v-for="player in tPlayers" :key="player.steamid" class="player-row">
                            <div class="col-player">
                                <Avatar :image="getAvatarUrl(player.name)" shape="circle" />
                                <div class="player-info">
                                    <span class="player-name">{{ player.name }}</span>
                                    <!-- <div class="player-honors">
                                        <Badge v-tooltip.top="'Leader Honor'" value="L" severity="info" class="mr-1" />{{ player.leader_honors }}
                                        <Badge v-tooltip.top="'Teacher Honor'" value="T" severity="success" class="mx-1" />{{ player.teacher_honors }}
                                        <Badge v-tooltip.top="'Friendly Honor'" value="F" severity="warning" class="ml-1" />{{ player.friendly_honors }}
                                    </div> -->
                                </div>
                            </div>
                            <div class="col-stat">{{ player.kills_total }}</div>
                            <div class="col-stat">{{ player.deaths_total }}</div>
                            <div class="col-stat">{{ player.assists_total }}</div>
                            <div class="col-stat">{{ player["3k_rounds_total"] }}</div>
                            <div class="col-stat">{{ player["4k_rounds_total"] }}</div>
                            <div class="col-stat">${{ player.balance }}</div>
                            <div class="col-stat">
                                <ProgressBar :value="player.health" :showValue="false" class="health-bar" />
                                <span>{{ player.health }}</span>
                            </div>
                            <div class="col-stat">
                                <ProgressBar :value="player.armor_value" :showValue="false" class="armor-bar" />
                                <span>{{ player.armor_value }}</span>
                            </div>
                            <div class="col-weapon">
                                <template v-for="(weapon, index) in player.inventory">
                                    <svg v-if="!weapon.toLowerCase().includes('knife')" :key="index" alt="" viewBox="30 -30 40 100" class="weapon-icon">
                                        <path :d="getWeapon(weapon).svg_path" fill="currentColor" />
                                    </svg>
                                </template>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </Dialog>
</template>

<script setup>
import { ref, watch } from 'vue';
import Dialog from 'primevue/dialog';
import Avatar from 'primevue/avatar';
import ProgressBar from 'primevue/progressbar';

const emit = defineEmits(['update:visible']);

const visible = ref(false);
const props = defineProps([
    'players',
    'visible',
    'meta',
    'weapons'
]);

const ctPlayers = ref([]);
const tPlayers = ref([]);

watch(() => props.players,
    (newPlayers) => {
        if (newPlayers) {
            ctPlayers.value = newPlayers.filter(player => player.team_name === 'ct');
            tPlayers.value = newPlayers.filter(player => player.team_name === 't');
        }
    },
    { immediate: true }
);

watch(() => props.visible, (newVisible) => {
    visible.value = newVisible;
});

const close = () => {
    visible.value = false;
    emit('update:visible', false);
};

const getAvatarUrl = (name) => {
    return `https://api.dicebear.com/6.x/initials/svg?seed=${encodeURIComponent(name)}`;
};

const getWeapon = (name) => {
    if (!name) return { url: "", svg_path: "" };

    name = name.toLowerCase();

    name = {
        "high explosive grenade": "he-grenade",
        "he_grenade": "he-grenade",
        "smoke": "smoke-grenade",
        "smoke grenade": "smoke-grenade",
        "incendiary grenade": "incendiary-grenade",
        "dual berettas": "dual-berettas",
        "desert eagle": "desert-eagle",
        "galil ar": "galil-ar",
        "decoy": "decoy-grenade",
        "incendiary_grenade": "incendiary-grenade",
        "usp_silencer": "usp-s",
        'glock': 'glock-18',
        'hkp2000': 'p2000',
        'elite': 'dual-berettas',
        'ssg 08': 'ssg-08',
        'ssg08': 'ssg-08',
        'scar 20': 'scar-20',
        'fiveseven': 'five-seven',
        'ak47': 'ak-47',
        'galilar': 'galil-ar',
        'mac10': 'mac-10',
        'm4a1_silencer': 'm4a1-s',
        'deagle': 'desert-eagle',
        'tec9': 'tec-9',
        'hegrenade': 'he-grenade',
        'm4a1': 'm4a1-s',
        'decoy grenade': 'decoy-grenade',
        'ump45': 'ump-45',
        'karambit': 'knife_karambit',
        'butterfly knife': 'knife_butterfly',
        'kukri knife': 'knife_kukri',
        'ursus knife': 'knife_ursus',
        'm9 bayonet': 'knife_m9_bayonet',
        'navaja knife': 'knife_navaja',
        'stiletto knife': 'knife_stiletto',
        'flip knife': 'knife_flip',
        'shadow daggers': 'knife_push',
        'survival knife': 'knife_canis',
        'skeleton knife': 'knife_skeleton',
        'paracord knife': 'knife_cord',
        'talon knife': 'knife_widowmaker',
        'nomad knife': 'knife_outdoor',
        'zeus x27': 'zeus',
        'c4 explosive': 'c4',
        'cflashbang': 'flashbang',
        'chegrenade': 'he-grenade',
        'csmokegrenade': 'smoke-grenade',
        'cincendiarygrenade': 'incendiary-grenade',
        'cmolotovgrenade': 'molotov',
        'csmokegrenadeprojectile': 'smoke-grenade',
        'chegrenadeprojectile': 'he-grenade',
        'cmolotovprojectile': 'molotov',
        'cflashbangprojectile': 'flashbang',
        "bowie knife": "knife_survival_bowie",
        "planted_c4": "c4",
        "huntsman knife": "knife_tactical",

        

    }[name] || name;

    if (!props.weapons[name]) {
        console.error('Unknown weapon:', name);
        return { url: "", svg_path: "" };
    }
    return props.weapons[name];
};
</script>

<style lang="scss" scoped>
.match-container {
    display: flex;
    flex-direction: column;
    width: 100%;
}

.match-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 0;
    margin-bottom: 1rem;
    border-bottom: 2px solid #ccc;
}

.team-header {
    display: flex;
    align-items: center;
    gap: 1rem;

    .team-score {
        font-size: 2rem;
        font-weight: bold;
        background-color: rgba(0, 0, 0, 0.1);
        border-radius: 4px;
        padding: 0.5rem 1rem;
        min-width: 3rem;
        text-align: center;
    }
}

.team-ct {
    color: #5d79ae;
}

.team-t {
    color: #de9b35;
    flex-direction: row-reverse;
}

.vs {
    font-size: 1.5rem;
    font-weight: bold;
    color: #666;
}



.scoreboard-container {
    display: flex;
    flex-direction: column;
    gap: 2rem;
}

.team-section {
    background-color: rgba(0, 0, 0, 0.02);
    border-radius: 8px;
    padding: 1rem;
}

.team-name-tab {
    margin-top: 0;
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
}

.team-name-tab.ct {
    color: #5d79ae;
}

.team-name-tab.t {
    color: #de9b35;
}

.scoreboard-table {
    width: 100%;
}

.scoreboard-header {
    display: flex;
    background-color: rgba(0, 0, 0, 0.05);
    padding: 0.5rem;
    border-radius: 4px;
    font-weight: bold;
    margin-bottom: 0.5rem;
}

.weapon-icon {
    width: 3rem;
    height: 3rem;
    border-radius: 4px;
    background-color: rgba(0, 0, 0, 0.1);
    padding: 0.25rem;
}

.player-row {
    display: flex;
    padding: 0.5rem;
    border-bottom: 1px solid #eee;
    align-items: center;
}

.player-row:last-child {
    border-bottom: none;
}

.col-player {
    flex: 3;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.col-stat {
    flex: 1;
    text-align: center;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    gap: 0.25rem;
}

.col-weapon {
    flex: 3;
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    align-items: center;
}

.player-info {
    display: flex;
    flex-direction: column;
}

.player-name {
    font-weight: bold;
}

.player-honors {
    display: flex;
    align-items: center;
    font-size: 0.8rem;
    color: #666;
}

.health-bar .p-progressbar-value {
    background-color: #4CAF50 !important;
}

.armor-bar .p-progressbar-value {
    background-color: #2196F3 !important;
}

.health-bar, .armor-bar {
    height: 0.5rem !important;
    width: 100%;
}

.defuser-icon, .bomb-icon {
    margin-left: 0.5rem;
    color: #ff5722;
}

.p-dialog-content {
    padding: 0 1.5rem 1.5rem 1.5rem !important;
}
</style>