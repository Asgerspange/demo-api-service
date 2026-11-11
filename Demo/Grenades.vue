<template>
    <div class="flex flex-col lg:flex-row w-full p-4 h-full text-slate-300 overflow-hidden font-sans">
        
        <div class="lg:hidden flex items-center justify-between p-3 bg-zinc-950/80 border-b border-white/10 z-40 rounded-t-lg">
            <div class="flex items-center gap-2">
                <span class="material-symbols text-primary text-base">scatter_plot</span>
                <span class="text-[10px] font-black text-zinc-400 uppercase tracking-[0.18em]">Grenades</span>
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
            class="relative flex-1 flex w-full items-center justify-center overflow-hidden bg-transparent min-h-[400px] lg:min-h-0 touch-none" 
            ref="demoMap"
            @mousedown="startDragging"
            @mousemove="handleMouseMove"
            @mouseup="stopDragging"
            @mouseleave="stopDragging"
            @wheel="handleWheel"
            @touchstart="handleTouchStart"
            @touchmove="handleTouchMove"
            @touchend="stopDragging"
        >
            <div v-if="!isMapLoaded" class="absolute inset-0 flex items-center justify-center z-50">
                <div class="w-10 h-10 border-2 border-primary/15 border-t-primary rounded-full animate-spin"></div>
            </div>

            <div 
                class="absolute inset-0 w-full h-full transition-transform duration-75 ease-out"
                :style="{ transform: `translate(${panOffset.x}px, ${panOffset.y}px) scale(${zoomLevel})` }"
            >
                <img 
                    :src="'/images/demo/' + map + '.svg'" 
                    alt="Map Background" 
                    class="absolute inset-0 w-full h-full transition-transform duration-75 ease-out"
                    :class="isMapLoaded ? 'opacity-100' : 'opacity-0'"
                    @load="onMapImageLoad"
                />
                
                <canvas 
                    ref="demoMapElement" 
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
                
                <section>
                    <div class="flex p-1 bg-black/40 rounded-xl border border-white/5">
                        <button 
                            @click="isHeatmapMode = false; render()"
                            :class="['flex-1 py-2.5 text-xs font-bold rounded-lg transition-all', !isHeatmapMode ? 'bg-zinc-700 text-white shadow-lg' : 'text-zinc-500 hover:text-zinc-300']"
                        >Trajectory</button>
                        <button 
                            @click="isHeatmapMode = true; render()"
                            :class="['flex-1 py-2.5 text-xs font-bold rounded-lg transition-all', isHeatmapMode ? 'bg-zinc-700 text-white shadow-lg' : 'text-zinc-500 hover:text-zinc-300']"
                        >Heatmap</button>
                    </div>
                </section>

                <section class="space-y-5">
                    <div class="space-y-2 flex flex-col">
                        <span class="text-[11px] font-medium text-zinc-400">Utility Types</span>
                        <MultiSelect v-model="selectedType" :options="types" />
                    </div>

                    <div class="grid grid-cols-2 gap-3">
                        <div class="space-y-2">
                            <span class="text-[11px] font-medium text-zinc-400">Team Side</span>
                            <Select v-model="selectedSide" :options="sides" />
                        </div>
                        <div class="space-y-2">
                            <span class="text-[11px] font-medium text-zinc-400">Players</span>
                            <MultiSelect v-model="selectedPlayers" :options="players" :maxSelectedLabels="1" />
                        </div>
                    </div>
                </section>

                <section>
                    <div class="flex items-center justify-between mb-3">
                        <label class="text-[10px] font-black text-zinc-500 uppercase tracking-[0.2em]">Round Selection</label>
                        <button @click="selectedRounds = [...availableRounds]" class="text-[10px] text-primary font-black uppercase tracking-widest hover:opacity-80 transition-opacity">Select All</button>
                    </div>

                    <div class="grid grid-cols-2 gap-2 mb-4">
                        <Button size="sm" severity="secondary" @click="selectedRounds = availableRounds.filter(r => r <= 12)">1st Half</Button>
                        <Button size="sm" severity="secondary" @click="selectedRounds = availableRounds.filter(r => r > 12)">2nd Half</Button>
                    </div>

                    <div class="grid grid-cols-6 gap-1.5 max-h-[125px] overflow-y-auto pr-2 custom-scrollbar">
                        <button
                            v-for="round in availableRounds"
                            :key="round"
                            @click="selectRound(round)"
                            :class="[
                                'aspect-square flex items-center justify-center rounded-md text-[11px] font-mono transition-all border',
                                selectedRounds.includes(round)
                                    ? 'bg-primary border-primary text-black font-black'
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
import simpleheat from 'simpleheat';
import { useRoute } from 'vue-router';
import useDemos from '@/composables/useDemos';

const route = useRoute();
const { Demos } = useDemos();
const { data: demo } = Demos.show(route.params.id);

// UI State
const showMobileSidebar = ref(false);
const demoMapElement = ref(null);
const demoMap = ref(null);
const isMapLoaded = ref(false);
const mapImage = ref(null);
const heatmapInstance = ref(null);
const isHeatmapMode = ref(false);

// Pan & Zoom State
const zoomLevel = ref(1);
const panOffset = ref({ x: 0, y: 0 });
const isDragging = ref(false);
const dragStart = ref({ x: 0, y: 0 });
const initialTouchDistance = ref(0);

const types = ['Smokes', 'Flashes', 'Grenades', 'Molotovs'];
const selectedType = ref(['Smokes']);
const sides = ["Both", "T", "CT"];
const selectedSide = ref("Both");
const selectedPlayers = ref([]);
const selectedRounds = ref([1]);

// Transform refs
const svgOffsetX = ref(0);
const svgOffsetY = ref(0);
const svgScale = ref(1);

const map = computed(() => demo.value?.map || 'unknown');
const util = computed(() => demo.value?.utility || []);

const players = computed(() => {
    if (!util.value?.length) return [];
    const playerSet = new Set();
    util.value.forEach(u => {
        if (u.data) {
            Object.values(u.data).forEach(g => {
                if (g.thrower) playerSet.add(g.thrower);
            });
        }
    });
    return Array.from(playerSet).sort();
});

const availableRounds = computed(() => {
    if (!util.value?.length) return [];
    const rounds = util.value.map(u => u.round_index).filter(r => !isNaN(r));
    return Array.from(new Set(rounds)).sort((a, b) => a - b);
});

const utility = computed(() => {
    const data = { smokes: [], flashes: [], grenades: [], molotovs: [] };
    if (!util.value?.length) return data;

    util.value.forEach(u => {
        Object.entries(u.data || {}).forEach(([key, val]) => {
            const obj = { id: key, ...val, round: u.round_index };
            if (!shouldInclude(obj)) return;
            
            const typeKey = val.type === 'smoke' ? 'smokes' :
                            val.type === 'flashbang' ? 'flashes' :
                            val.type === 'he_grenade' ? 'grenades' :
                            ['molotov', 'incendiary_grenade'].includes(val.type) ? 'molotovs' : null;
            
            if (typeKey) data[typeKey].push(obj);
        });
    });
    return data;
});

const filteredUtilityCount = computed(() => {
    return Object.values(utility.value).flat().filter(g => selectedRounds.value.includes(g.round)).length;
});

const shouldInclude = (g) => {
    if (selectedPlayers.value.length && !selectedPlayers.value.includes(g.thrower)) return false;
    if (selectedSide.value !== "Both" && g.thrower_side?.toUpperCase() !== selectedSide.value.toUpperCase()) return false;
    return true;
};

const toCanvasCoords = (x, y) => {
    const gs = getScale(map.value);
    const nx = (x - gs.pos_x) / gs.scale;
    const ny = (gs.pos_y - y) / gs.scale;
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

// Interaction Handlers
const handleWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.min(Math.max(zoomLevel.value * delta, 1), 8);
    zoomLevel.value = newZoom;
    if (zoomLevel.value === 1) panOffset.value = { x: 0, y: 0 };
};

const startDragging = (e) => {
    isDragging.value = true;
    dragStart.value = { x: e.clientX - panOffset.value.x, y: e.clientY - panOffset.value.y };
};

const handleMouseMove = (e) => {
    if (!isDragging.value || zoomLevel.value === 1) return;
    panOffset.value = { x: e.clientX - dragStart.value.x, y: e.clientY - dragStart.value.y };
};

const handleTouchStart = (e) => {
    if (e.touches.length === 1) {
        isDragging.value = true;
        dragStart.value = { x: e.touches[0].clientX - panOffset.value.x, y: e.touches[0].clientY - panOffset.value.y };
    } else if (e.touches.length === 2) {
        initialTouchDistance.value = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
    }
};

const handleTouchMove = (e) => {
    if (e.touches.length === 1 && isDragging.value && zoomLevel.value > 1) {
        panOffset.value = { x: e.touches[0].clientX - dragStart.value.x, y: e.touches[0].clientY - dragStart.value.y };
    } else if (e.touches.length === 2) {
        const distance = Math.hypot(
            e.touches[0].clientX - e.touches[1].clientX,
            e.touches[0].clientY - e.touches[1].clientY
        );
        const delta = distance / initialTouchDistance.value;
        zoomLevel.value = Math.min(Math.max(zoomLevel.value * delta, 1), 8);
        initialTouchDistance.value = distance;
    }
};

const stopDragging = () => {
    isDragging.value = false;
};

// Canvas Drawing
const initHeatmap = () => {
    if (!demoMapElement.value) return;
    heatmapInstance.value = simpleheat(demoMapElement.value);
};

const render = () => {
    if (isHeatmapMode.value) drawHeatmap();
    else drawGrenades();
};

const drawHeatmap = () => {
    if (!demoMapElement.value) return;
    if (!heatmapInstance.value) initHeatmap();
    
    const ctx = demoMapElement.value.getContext('2d');
    ctx.clearRect(0, 0, demoMapElement.value.width, demoMapElement.value.height);

    const points = [];
    selectedType.value.forEach(t => {
        const key = t.toLowerCase();
        (utility.value[key] || []).filter(g => selectedRounds.value.includes(g.round)).forEach(g => {
            if (g.end) {
                const { x, y } = toCanvasCoords(g.end[0], g.end[1]);
                points.push([x, y, 0.8]);
            }
        });
    });

    if (points.length) {
        heatmapInstance.value.data(points).radius(18, 12).draw();
    }
};

const drawGrenades = () => {
    const canvas = demoMapElement.value;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const colors = { 
        smoke: '#4ECDC4', 
        flashbang: '#FFF600', 
        he_grenade: '#FF6B6B', 
        molotov: '#FFA500', 
        incendiary_grenade: '#FFA500' 
    };

    selectedType.value.forEach(t => {
        const key = t.toLowerCase();
        (utility.value[key] || []).filter(g => selectedRounds.value.includes(g.round)).forEach(g => {
            const pts = [g.origin, ...(g.bounces || []), g.end];
            const color = colors[g.type] || '#ffffff';

            ctx.shadowBlur = 4;
            ctx.shadowColor = 'rgba(0,0,0,0.5)';
            ctx.strokeStyle = 'rgba(255,255,255,0.4)';
            ctx.setLineDash([6, 4]);
            ctx.lineWidth = 1.5;
            ctx.lineJoin = 'round';
            ctx.lineCap = 'round';
            
            ctx.beginPath();
            pts.forEach((p, i) => {
                const { x, y } = toCanvasCoords(p[0], p[1]);
                i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            });
            ctx.stroke();
            
            const end = toCanvasCoords(g.end[0], g.end[1]);
            ctx.setLineDash([]);
            ctx.shadowBlur = 10;
            ctx.shadowColor = color;
            ctx.fillStyle = color;
            
            ctx.beginPath();
            ctx.arc(end.x, end.y, 4.5, 0, Math.PI * 2);
            ctx.fill();
            
            ctx.strokeStyle = '#000';
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.shadowBlur = 0;
        });
    });
};

const updateSvgDimensions = () => {
    const container = demoMap.value;
    const img = mapImage.value;
    if (!container || !img) return;

    demoMapElement.value.width = container.clientWidth;
    demoMapElement.value.height = container.clientHeight;

    const nw = img.naturalWidth || 1024;
    const nh = img.naturalHeight || 1024;
    const ratio = Math.min(container.clientWidth / nw, container.clientHeight / nh);

    svgScale.value = ratio;
    svgOffsetX.value = (container.clientWidth - (nw * ratio)) / 2;
    svgOffsetY.value = (container.clientHeight - (nh * ratio)) / 2;

    if (heatmapInstance.value) heatmapInstance.value = null; 
    render();
};

const onMapImageLoad = (e) => {
    isMapLoaded.value = true;
    mapImage.value = e.target;
    nextTick(updateSvgDimensions);
};

onMounted(() => {
    window.addEventListener('resize', updateSvgDimensions);
});

onBeforeUnmount(() => {
    window.removeEventListener('resize', updateSvgDimensions);
});

watch([selectedType, selectedPlayers, selectedSide, selectedRounds, utility, isHeatmapMode], () => {
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