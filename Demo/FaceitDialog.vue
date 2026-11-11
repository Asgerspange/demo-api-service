<script setup>
import { ref } from 'vue';
import axios from 'axios';
import Dialog from '@/components/volt/Dialog.vue';
import Button from '@/components/volt/Button.vue';
import DataTable from 'primevue/datatable';
import Column from 'primevue/column';
import Skeleton from 'primevue/skeleton';
import Tag from 'primevue/tag';
import useDemos from '@/composables/useDemos';

const { Demos } = useDemos();

const visible = ref(false);
const loading = ref(false);
const unlinked = ref(false);
const matches = ref([]);
const expandedRows = ref({});
const queueingIds = ref(new Set()); // Loading state for individual buttons

const fetchMatches = async (force = false) => {
    visible.value = true;
    if (matches.value.length > 0 && !force) return;
    
    loading.value = true;
    unlinked.value = false;
    expandedRows.value = {};
    
    // Create placeholders for skeleton
    matches.value = Array.from({ length: 12 }, (_, i) => ({ match_id: i })); 
    
    try {
        const { data } = await axios.get('/api/faceit/matches');
        matches.value = data;
    } catch (e) {
        if (e.response?.status === 400) {
            unlinked.value = true;
            matches.value = [];
        }
    } finally {
        loading.value = false;
    }
};

const handleQueue = async (match) => {
    queueingIds.value.add(match.match_id);
    await axios.post('/api/faceit/queue', {
        match_id: match.match_id,
        my_team: match.my_team,
        opp_team: match.opp_team
    });
    match.is_queued = true;
    Demos.refresh();
    queueingIds.value.delete(match.match_id);
};

const onRowClick = (event) => {
    if (loading.value) return;
    const id = event.data.match_id;
    expandedRows.value[id] ? delete expandedRows.value[id] : expandedRows.value[id] = true;
};

const formatDate = (unix) => unix ? new Date(unix * 1000).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) : '';
</script>

<template>
    <div class="card flex justify-center">
        <Button size="sm" severity="secondary" @click="fetchMatches(false)">
            <span class="material-symbols mr-1" style="font-size: 15px">history</span>
            Faceit Matches
        </Button>

        <Dialog v-model:visible="visible" modal :style="{ width: '70vw' }" header="Recent Faceit Matches">
            <template #header>
                <div class="flex items-center justify-between w-full pr-8">
                    <span class="text-2xl font-bold">Recent Faceit Matches</span>
                    <Button v-if="!unlinked" icon="pi pi-refresh" @click="fetchMatches(true)" :loading="loading" class="p-button-text p-button-rounded" />
                </div>
            </template>

            <div v-if="unlinked" class="flex flex-col items-center justify-center p-12 text-center">
                <i class="pi pi-exclamation-triangle text-4xl mb-4 text-orange-500"></i>
                <h3 class="text-xl mb-2">Faceit Not Linked</h3>
                <p class="text-500 mb-6">Connect your Faceit account in settings to view match history.</p>
                <a href="/profile" class="p-button p-button-primary no-underline px-6">Link Account</a>
            </div>

            <DataTable 
                v-else
                :value="matches" 
                v-model:expandedRows="expandedRows" 
                dataKey="match_id"
                class="p-datatable-sm" 
                stripedRows
                scrollable
                scrollHeight="550px"
                @row-click="onRowClick"
            >
                <Column v-if="loading" style="width: 3rem">
                    <template #body><Skeleton shape="circle" size="1.8rem" /></template>
                </Column>
                <Column v-else expander style="width: 3rem" />

                <Column header="MATCH">
                    <template #body="{ data }">
                        <div v-if="loading" class="flex flex-column gap-2">
                            <Skeleton width="80px" height="16px" /><Skeleton width="50px" height="12px" />
                        </div>
                        <div v-else class="flex flex-column gap-1">
                            <span class="text-base font-bold text-blue-500">{{ data.map }}</span>
                            <span class="text-xs text-500">{{ formatDate(data.date) }}</span>
                        </div>
                    </template>
                </Column>

                <Column header="OPPONENT">
                    <template #body="{ data }">
                        <Skeleton v-if="loading" width="80%" height="18px" />
                        <div v-else class="flex flex-column text-sm">
                            <span class="font-bold truncate">{{ data.my_team }}</span>
                            <span class="text-500">vs {{ data.opp_team }}</span>
                        </div>
                    </template>
                </Column>

                <Column header="SCORE" style="width: 8rem">
                    <template #body="{ data }">
                        <Skeleton v-if="loading" width="60px" height="18px" />
                        <span v-else class="font-mono font-bold">{{ data.score }}</span>
                    </template>
                </Column>

                <Column header="RES" style="width: 5rem">
                    <template #body="{ data }">
                        <Skeleton v-if="loading" width="40px" height="18px" />
                        <span v-else :class="data.result === 'WIN' ? 'text-green-500' : 'text-red-500'" class="text-sm font-black">{{ data.result }}</span>
                    </template>
                </Column>

                <Column header="ACTION" :style="{ width: '120px', minWidth: '120px' }">
                    <template #body="{ data }">
                        <Skeleton v-if="loading" width="80px" height="32px" />
                        <div v-else @click.stop> <Tag v-if="data.is_queued" severity="success" value="QUEUED" class="w-full" />
                            <Button 
                                v-else 
                                icon="pi pi-download" 
                                label="Queue" 
                                size="small"
                                class="p-button-outlined p-button-info w-full"
                                :loading="queueingIds.has(data.match_id)"
                                @click="handleQueue(data)"
                            />
                        </div>
                    </template>
                </Column>

                <template #expansion="{ data }">
                    <div v-if="data.players" class="p-4 bg-black-alpha-10">
                        <table class="w-full text-left compact-table">
                            <thead>
                                <tr>
                                    <th>PLAYER</th>
                                    <th>K</th>
                                    <th>D</th>
                                    <th>K/D</th>
                                    <th>HS%</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr v-for="p in data.players" :key="p.nickname">
                                    <td class="font-bold">{{ p.nickname }}</td>
                                    <td>{{ p.k }}</td>
                                    <td>{{ p.d }}</td>
                                    <td :class="parseFloat(p.kd) >= 1 ? 'text-green-500' : 'text-red-500'">{{ p.kd }}</td>
                                    <td>{{ p.hs }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </template>
            </DataTable>
        </Dialog>
    </div>
</template>

<style scoped>
:deep(.p-datatable-thead > tr > th) {
    font-size: 11px !important;
    background: var(--surface-section) !important;
    text-transform: uppercase;
}

.compact-table th {
    padding: 8px 0;
    color: #94a3b8;
    font-size: 11px;
    border-bottom: 1px solid var(--surface-border);
}

.compact-table td {
    padding: 8px 0;
    border-bottom: 1px solid var(--surface-border);
}
</style>