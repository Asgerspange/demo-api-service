<template>
    <div class="flex flex-col lg:flex-row w-full p-4 h-full text-slate-300 overflow-hidden font-sans">
        
        <div class="lg:hidden flex items-center justify-between p-3 bg-zinc-950/80 border-b border-white/10 z-40 rounded-t-lg">
            <div class="flex items-center gap-2">
                <span class="material-symbols text-primary text-base">map</span>
                <span class="text-[10px] font-black text-zinc-400 uppercase tracking-[0.18em]">Heatmap</span>
            </div>
            <button
                @click="showMobileSidebar = !showMobileSidebar"
                class="px-3 py-1.5 bg-zinc-900/80 border border-white/10 rounded-md text-[10px] font-black uppercase tracking-widest text-zinc-300 hover:text-primary hover:border-primary/40 transition-colors flex items-center gap-1.5"
            >
                <span class="material-symbols" style="font-size:14px">{{ showMobileSidebar ? 'close' : 'tune' }}</span>
                {{ showMobileSidebar ? 'Close' : 'Filters' }}
            </button>
        </div>

        <div 
            class="relative flex-1 flex w-full items-center justify-center overflow-hidden bg-transparent min-h-[400px] lg:min-h-0" 
            ref="heatmapContainer"
        >
            <div v-if="!isMapLoaded" class="absolute inset-0 flex items-center justify-center z-50">
                <div class="w-10 h-10 border-2 border-primary/15 border-t-primary rounded-full animate-spin"></div>
            </div>

            <div class="absolute inset-0 w-full h-full">
                <img 
                    :src="'/images/demo/' + map + '.svg'" 
                    alt="Map Background" 
                    class="absolute inset-0 w-full h-full object-contain"
                    :class="isMapLoaded ? 'opacity-100' : 'opacity-0'"
                    @load="onMapImageLoad"
                    ref="mapImageRef"
                />
                
                <canvas 
                    ref="heatmapElement" 
                    class="absolute inset-0 w-full h-full object-contain pointer-events-none z-20"
                ></canvas>
            </div>
        </div>

        <aside
            :class="[
                'lg:w-[300px] xl:w-[320px] h-fit lg:max-h-[calc(100vh-8rem)] bg-zinc-900/40 backdrop-blur-sm border border-white/10 lg:border-l flex flex-col rounded-lg transition-all duration-300 z-30',
                showMobileSidebar ? 'fixed inset-0 w-full bg-zinc-950 rounded-none border-0' : 'hidden lg:flex'
            ]"
        >
            <div class="flex-1 overflow-y-auto p-5 space-y-8 custom-scrollbar">
                
                <section class="space-y-6">
                    <label class="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em]">Heatmap Settings</label>
                    
                    <div class="space-y-3">
                        <div class="flex justify-between text-[11px] font-medium text-zinc-400">
                            <span>Radius</span>
                            <span class="text-primary">{{ heatmapRadius }}</span>
                        </div>
                        <Slider v-model="heatmapRadius" :min="5" :max="100" @update:modelValue="render" />
                    </div>

                    <div class="space-y-3">
                        <div class="flex justify-between text-[11px] font-medium text-zinc-400">
                            <span>Blur</span>
                            <span class="text-primary">{{ blur }}</span>
                        </div>
                        <Slider v-model="blur" :min="1" :max="100" @update:modelValue="render" />
                    </div>

                    <div class="space-y-3">
                        <div class="flex justify-between text-[11px] font-medium text-zinc-400">
                            <span>Intensity</span>
                            <span class="text-primary">{{ max }}</span>
                        </div>
                        <Slider v-model="max" :min="1" :max="10" @update:modelValue="render" />
                    </div>
                </section>

                <hr class="border-white/5" />

                <section class="space-y-5">
                    <div class="space-y-2 flex flex-col">
                        <span class="text-[11px] font-medium text-zinc-400">Event Type</span>
                        <Select v-model="event" :options="events" />
                    </div>

                    <div class="space-y-2 flex flex-col">
                        <span class="text-[11px] font-medium text-zinc-400">Players</span>
                        <MultiSelect 
                            v-model="selectedPlayers" 
                            :options="playerOptions" 
                            placeholder="Select Players"
                        />
                    </div>
                </section>

                <section>
                    <div class="flex items-center justify-between mb-3">
                        <label class="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em]">Round Selection</label>
                        <button @click="selectedRounds = [...availableRounds]" class="text-[10px] text-primary font-bold transition-colors">Select All</button>
                    </div>

                    <div class="flex gap-2 mb-4">
                        <Button  @click="selectedRounds = availableRounds.filter(r => r <= 12)" size="sm" severity="secondary">1st Half</Button>
                        <Button @click="selectedRounds = availableRounds.filter(r => r > 12)" size="sm" severity="secondary">2nd Half</Button>
                    </div>

                    <div class="grid grid-cols-6 gap-1.5 max-h-[150px] overflow-y-auto pr-2 custom-scrollbar">
                        <button 
                            v-for="round in availableRounds" 
                            :key="round" 
                            @click="selectRound(round)"
                            :class="[
                                'aspect-square flex items-center justify-center rounded-md text-[11px] font-mono transition-all border',
                                selectedRounds.includes(round) 
                                    ? 'bg-primary text-black font-black' 
                                    : 'bg-zinc-900/50 border-white/5 text-zinc-500 hover:border-zinc-600'
                            ]"
                        >
                            {{ round }}
                        </button>
                    </div>
                </section>
            </div>
            
            <button
                v-if="showMobileSidebar"
                @click="showMobileSidebar = false"
                class="lg:hidden w-full py-4 bg-primary text-black font-black uppercase text-[11px] tracking-[0.2em] hover:opacity-90 transition-opacity"
            >Apply & View Map</button>
        </aside>
    </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import getScale from '@/scales.js';
import MultiSelect from '@/components/volt/MultiSelect.vue';
import Select from '@/components/volt/Select.vue';
import Button from '@/components/volt/Button.vue';
import Slider from '@/components/volt/Slider.vue';
import simpleheat from 'simpleheat';
import { useRoute } from 'vue-router';
import useDemos from '@/composables/useDemos';

const route = useRoute();
const { Demos } = useDemos();
const { data: demo } = Demos.show(route.params.id);

// UI State
const showMobileSidebar = ref(false);
const heatmapElement = ref(null);
const heatmapContainer = ref(null);
const mapImageRef = ref(null);
const isMapLoaded = ref(false);
const heatmapInstance = ref(null);

// Heatmap config
const heatmapRadius = ref(10);
const blur = ref(15);
const max = ref(1);
const event = ref('Kill');
const events = ['Kill', 'Death'];

// Selection State
const selectedRounds = ref([]);
const selectedPlayers = ref([]);

// Coordinate Transform refs
const svgOffsetX = ref(0);
const svgOffsetY = ref(0);
const svgScale = ref(1);

const map = computed(() => demo.value?.map || 'unknown');
const heatmap = computed(() => demo.value?.heatmap || null);

const playerOptions = computed(() => {
    const t1 = heatmap.value?.team1 || [];
    const t2 = heatmap.value?.team2 || [];
    return [...t1, ...t2].map(p => ({ label: p.name, value: p.steamid }));
});

const availableRounds = computed(() => {
    const uniqueRounds = new Set();
    const eventData = getEventData();
    for (let steamId in eventData) {
        for (let round in eventData[steamId]) {
            uniqueRounds.add(parseInt(round));
        }
    }
    return Array.from(uniqueRounds).sort((a, b) => a - b);
});

const getEventData = () => {
    const entry = event.value.toLowerCase() + "_data";
    return heatmap.value?.[entry] || {};
};

const toCanvasCoords = (x, y) => {
    const gs = getScale(map.value);
    // Convert game units to 0-1024 normalized units
    const nx = (x - gs.pos_x) / gs.scale;
    const ny = (gs.pos_y - y) / gs.scale;
    // Map to actual canvas pixels based on image offset/scale
    return { 
        x: svgOffsetX.value + (nx * svgScale.value), 
        y: svgOffsetY.value + (ny * svgScale.value) 
    };
};

const selectRound = (r) => {
    selectedRounds.value.includes(r) 
        ? selectedRounds.value = selectedRounds.value.filter(i => i !== r) 
        : selectedRounds.value.push(r);
};

// Canvas Logic
const updateSvgDimensions = () => {
    const container = heatmapContainer.value;
    const img = mapImageRef.value;
    if (!container || !img) return;

    // Fix: Match canvas resolution to display size
    heatmapElement.value.width = container.clientWidth;
    heatmapElement.value.height = container.clientHeight;

    const nw = img.naturalWidth || 1024;
    const nh = img.naturalHeight || 1024;
    const ratio = Math.min(container.clientWidth / nw, container.clientHeight / nh);

    svgScale.value = ratio;
    svgOffsetX.value = (container.clientWidth - (nw * ratio)) / 2;
    svgOffsetY.value = (container.clientHeight - (nh * ratio)) / 2;

    render();
};

const render = () => {
    const canvas = heatmapElement.value;
    if (!canvas) return;

    // Initialize or refresh simpleheat
    heatmapInstance.value = simpleheat(canvas);
    
    const data = [];
    const eventData = getEventData();
    
    for (let steamId in eventData) {
        if (selectedPlayers.value.length && !selectedPlayers.value.includes(steamId)) continue;
        
        for (let round in eventData[steamId]) {
            const roundNum = parseInt(round);
            if (selectedRounds.value.length === 0 || selectedRounds.value.includes(roundNum)) {
                eventData[steamId][round].forEach(point => {
                    const { x, y } = toCanvasCoords(point.x, point.y);
                    data.push([x, y, point.value || 1]);
                });
            }
        }
    }

    heatmapInstance.value.data(data);
    heatmapInstance.value.radius(heatmapRadius.value, blur.value);
    heatmapInstance.value.max(max.value);
    heatmapInstance.value.draw();
};

const onMapImageLoad = () => {
    isMapLoaded.value = true;
    nextTick(updateSvgDimensions);
};

onMounted(() => {
    window.addEventListener('resize', updateSvgDimensions);
    // Initial round selection if rounds exist
    nextTick(() => {
        if (availableRounds.value.length > 0) {
            selectedRounds.value = [availableRounds.value[0]];
        }
    });
});

onBeforeUnmount(() => {
    window.removeEventListener('resize', updateSvgDimensions);
});

watch([selectedPlayers, selectedRounds, event, heatmap], () => {
    nextTick(render);
}, { deep: true });
</script>

<style scoped>
.custom-scrollbar::-webkit-scrollbar { width: 5px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.05); border-radius: 10px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.1); }
button:focus { outline: none; }
</style>