<template>
    <div class="flex flex-col h-full bg-card/95 backdrop-blur-xl border border-primary/10 rounded-2xl shadow-2xl overflow-hidden">

        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-white/10 shrink-0">
            <div class="flex items-center gap-2">
                <div class="w-6 h-6 rounded-lg bg-primary/20 flex items-center justify-center">
                    <Icon icon="lucide:sparkles" class="text-primary text-xs" />
                </div>
                <div>
                    <p class="text-sm font-bold text-white">AI Demo Chat</p>
                    <p class="text-[10px] text-white/40">{{ contextLabel }}</p>
                </div>
            </div>
            <div class="flex items-center gap-1">
                <button v-if="messages.length"
                    @click="clearChat"
                    class="w-7 h-7 rounded-lg hover:bg-white/10 flex items-center justify-center text-white/30 hover:text-white transition-colors">
                    <Icon icon="lucide:trash-2" class="w-3.5 h-3.5" />
                </button>
                <button
                    class="w-7 h-7 rounded-lg hover:bg-white/10 flex items-center justify-center text-white/50 hover:text-white transition-colors"
                    @click="$emit('close')">
                    <Icon icon="lucide:x" class="w-4 h-4" />
                </button>
            </div>
        </div>

        <!-- Context toggle -->
        <div class="flex gap-1 p-2 border-b border-white/5 shrink-0">
            <button
                v-for="ctx in contextOptions" :key="ctx.id"
                @click="switchContext(ctx.id)"
                class="flex-1 py-1.5 rounded-lg text-[10px] font-bold transition-colors"
                :class="activeContext === ctx.id
                    ? 'bg-primary/20 text-primary'
                    : 'text-white/30 hover:text-white/60'">
                {{ ctx.label }}
            </button>
        </div>

        <!-- Messages -->
        <div ref="scrollRef" class="flex-1 overflow-y-auto p-3 space-y-3 custom-track">
            <!-- Empty state -->
            <div v-if="messages.length === 0" class="flex flex-col items-center justify-center gap-3 py-6">
                <div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                    <Icon icon="lucide:message-circle" class="text-primary text-lg" />
                </div>
                <p class="text-xs text-white/40 text-center">
                    Ask about this {{ activeContext === 'round' ? 'round' : 'demo' }}
                </p>
                <div class="flex flex-col gap-1.5 w-full">
                    <button v-for="s in activeSuggestions" :key="s"
                        @click="sendSuggestion(s)"
                        class="text-[10px] px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/8 text-white/50 hover:text-white/80 hover:border-white/15 transition-colors text-left">
                        {{ s }}
                    </button>
                </div>
            </div>

            <!-- Messages -->
            <template v-else>
                <div v-for="(msg, i) in messages" :key="i"
                    class="flex gap-2"
                    :class="msg.role === 'user' ? 'flex-row-reverse' : ''">
                    <div class="w-6 h-6 rounded-full shrink-0 flex items-center justify-center text-[10px] font-bold"
                        :class="msg.role === 'user' ? 'bg-zinc-700 text-zinc-300' : 'bg-primary/20 text-primary'">
                        <Icon v-if="msg.role === 'assistant'" icon="lucide:sparkles" class="text-[10px]" />
                        <span v-else>U</span>
                    </div>
                    <div class="max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed"
                        :class="msg.role === 'user'
                            ? 'bg-primary/15 text-white rounded-tr-sm'
                            : 'bg-white/5 border border-white/8 text-white/80 rounded-tl-sm'">
                        <div v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)" />
                        <span v-else>{{ msg.content }}</span>
                    </div>
                </div>

                <!-- Typing indicator -->
                <div v-if="isLoading" class="flex gap-2">
                    <div class="w-6 h-6 rounded-full bg-primary/20 shrink-0 flex items-center justify-center">
                        <Icon icon="lucide:sparkles" class="text-primary text-[10px]" />
                    </div>
                    <div class="bg-white/5 border border-white/8 rounded-xl rounded-tl-sm px-3 py-2.5">
                        <div class="flex gap-1 items-center">
                            <span class="w-1 h-1 rounded-full bg-white/40 animate-bounce" style="animation-delay:0ms" />
                            <span class="w-1 h-1 rounded-full bg-white/40 animate-bounce" style="animation-delay:150ms" />
                            <span class="w-1 h-1 rounded-full bg-white/40 animate-bounce" style="animation-delay:300ms" />
                        </div>
                    </div>
                </div>
            </template>
        </div>

        <!-- Input -->
        <div class="px-3 py-3 border-t border-white/5 shrink-0">
            <div class="flex gap-2 items-end">
                <textarea
                    ref="inputRef"
                    v-model="input"
                    rows="1"
                    :placeholder="activeContext === 'round' ? 'Ask about round ' + currentRound + '…' : 'Ask about this demo…'"
                    class="flex-1 bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-xs text-white placeholder-white/25 resize-none focus:outline-none focus:border-primary/40 transition-colors"
                    style="max-height: 80px; overflow-y: auto;"
                    @keydown.enter.exact.prevent="send"
                    @keydown.enter.shift.exact="() => {}"
                    @input="autoResize"
                />
                <button
                    class="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 transition-colors"
                    :class="input.trim() && !isLoading
                        ? 'bg-primary text-black hover:bg-primary/90'
                        : 'bg-white/5 text-white/20 cursor-not-allowed'"
                    :disabled="!input.trim() || isLoading"
                    @click="send">
                    <Icon icon="lucide:send" class="text-xs" />
                </button>
            </div>
            <p class="text-[9px] text-white/20 mt-1.5">Enter to send · Shift+Enter for new line</p>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import { Icon } from '@iconify/vue';

const props = defineProps<{
    demoId:       number | string;
    currentRound: number;
    round:        any;   // full round object from useRoundData — has meta, tickNumbers
    currentTick:  any;   // currentTick reactive from useRoundData
    currentEvents: any[]; // kill events for current tick
}>();

defineEmits(['close']);

// ── Context ───────────────────────────────────────────────────────────────────
const activeContext = ref<'round' | 'demo'>('round');

const contextOptions = computed(() => [
    { id: 'round', label: `Round ${props.currentRound}` },
    { id: 'demo',  label: 'Full demo' },
]);

const contextLabel = computed(() =>
    activeContext.value === 'round'
        ? `Viewing round ${props.currentRound}`
        : 'Full demo stats'
);

const roundSuggestions = computed(() => [
    `What happened in round ${props.currentRound}?`,
    'How did T-side execute this round?',
    'What utility was used and by whom?',
    'Who had the best positioning CT-side?',
    'Any mistakes made this round?',
]);

const demoSuggestions = [
    'Who was the best performing player?',
    'What were the most impactful rounds?',
    'How did the economy affect the outcome?',
    'What patterns did T-side use?',
    'Who clutched the most?',
];

const activeSuggestions = computed(() =>
    activeContext.value === 'round' ? roundSuggestions.value : demoSuggestions
);

const switchContext = (ctx: 'round' | 'demo') => {
    activeContext.value = ctx;
    messages.value = [];
};

// ── Build rich round context from available data ──────────────────────────────
const buildContext = () => {
    if (activeContext.value === 'round') {
        const players = props.currentTick?.players ?? [];

        const ct = players
            .filter((p: any) => p.team_name === 'ct')
            .map((p: any) => ({
                name:          p.name,
                health:        p.health,
                armor:         p.armor_value,
                kills:         p.kills_total,
                deaths:        p.deaths_total,
                weapon:        p.active_weapon_name,
                inventory:     p.inventory,
                balance:       p.balance,
                alive:         p.health > 0,
            }));

        const t = players
            .filter((p: any) => p.team_name === 't')
            .map((p: any) => ({
                name:          p.name,
                health:        p.health,
                armor:         p.armor_value,
                kills:         p.kills_total,
                deaths:        p.deaths_total,
                weapon:        p.active_weapon_name,
                inventory:     p.inventory,
                balance:       p.balance,
                alive:         p.health > 0,
            }));

        // Pull all kills from round meta
        const kills: any[] = [];
        const killsMap = props.round?.meta?.kills ?? {};
        for (const tickKills of Object.values(killsMap) as any[]) {
            for (const k of tickKills) {
                kills.push({
                    attacker:    k.attacker_name,
                    victim:      k.victim_name,
                    weapon:      k.weapon,
                    headshot:    k.headshot,
                    thru_smoke:  k.thrusmoke,
                    blind:       k.attackerblind,
                });
            }
        }

        // Smokes — full detail: who threw, where
        const smokes = (props.round?.smokes ?? []).map((s: any) => ({
            thrower:    s.thrower_name ?? s.thrower_steamid,
            side:       s.thrower_side,
            x: s.X, y: s.Y,
            duration_ticks: (s.end_tick ?? 0) - (s.start_tick ?? 0),
        }));

        // Molotovs/infernos — who threw, where
        const infernos = (props.round?.infernos ?? []).map((inf: any) => ({
            thrower:    inf.thrower_name ?? inf.thrower_steamid,
            side:       inf.thrower_side,
            x: inf.X, y: inf.Y,
            duration_ticks: (inf.end_tick ?? 0) - (inf.start_tick ?? 0),
        }));

        // Grenade projectiles — round.grenades is a Map (iterable of [entityId, grenadeObj])
        // Each grenade object has: entity_id, grenade_type, thrower_steamid, trajectory[], throwTick, tick
        // thrower_steamid links to players in currentTick — build a steamid→name lookup first
        const steamToName: Record<string, string> = {};
        for (const p of props.currentTick?.players ?? []) {
            steamToName[String(p.steamid)] = p.name;
        }

        const flashbangs: any[] = [];
        const heGrenades: any[] = [];
        const decoys: any[] = [];
        const seenEntityIds = new Set<number>();

        // round.grenades is a Map — iterate with for...of
        const grenadeMap = props.round?.grenades;
        // round.grenades is a plain object keyed by entity_id string
        // BUT the renderer processes it into a flat array of per-tick grenade positions
        // so we must deduplicate by entity_id from inside the object
        const grenadeEntries: any[] = grenadeMap
            ? (typeof grenadeMap.values === 'function'
                ? Array.from(grenadeMap.values())
                : Object.values(grenadeMap))
            : [];

        for (const g of grenadeEntries) {
            // Skip synthetic flash pulse entries created by the renderer
            // Real grenades have numeric entity_ids; renderer creates '81_flash_1' etc
            const rawEid = g.entity_id ?? g.entityId;
            if (typeof rawEid === 'string' && rawEid.includes('_')) continue;
            const eid = Number(rawEid ?? -1);
            if (eid < 0 || seenEntityIds.has(eid)) continue;
            seenEntityIds.add(eid);

            const rawType = (g.grenade_type ?? '').toLowerCase();
            let type = rawType;
            if (rawType.includes('smoke'))                              type = 'smoke';
            else if (rawType.includes('flash'))                        type = 'flashbang';
            else if (rawType.includes('molotov') || rawType.includes('incendiary')) type = 'molotov';
            else if (rawType.includes('he'))                           type = 'he_grenade';
            else if (rawType.includes('decoy'))                        type = 'decoy';

            // Resolve thrower name from steamid
            const thrower = steamToName[String(g.thrower_steamid)] ?? 'unknown';
            const entry   = { thrower, type };

            if (type === 'flashbang')       flashbangs.push(entry);
            else if (type === 'he_grenade') heGrenades.push(entry);
            else if (type === 'decoy')      decoys.push(entry);
            // smokes/molotovs come from round.smokes/infernos — skip here
        }

        return {
            context:      'round',
            round_index:  props.currentRound,
            score: {
                ct: props.round?.meta?.CT_score,
                t:  props.round?.meta?.T_score,
            },
            winner:     props.round?.meta?.winner,
            win_reason: props.round?.meta?.reason,
            ct_players: ct,
            t_players:  t,
            kills,
            utility: {
                smokes,
                molotovs_infernos: infernos,
                // Summarise flashbangs/HEs by thrower — no need to list each individually
                flashbangs_by_thrower: flashbangs.reduce((acc: any, f: any) => {
                    acc[f.thrower] = (acc[f.thrower] ?? 0) + 1; return acc;
                }, {}),
                he_grenades_by_thrower: heGrenades.reduce((acc: any, h: any) => {
                    acc[h.thrower] = (acc[h.thrower] ?? 0) + 1; return acc;
                }, {}),
                total_smokes:   smokes.length,
                total_molotovs: infernos.length,
                total_flashes:  flashbangs.length,
                total_he:       heGrenades.length,
            },
        };
    }

    return {
        context:  'demo',
        demo_id:  props.demoId,
    };
};

// ── Chat state ─────────────────────────────────────────────────────────────────
interface Message { role: 'user' | 'assistant'; content: string; }

const messages  = ref<Message[]>([]);
const input     = ref('');
const isLoading = ref(false);
const scrollRef = ref<HTMLElement | null>(null);
const inputRef  = ref<HTMLTextAreaElement | null>(null);

const getCsrf = () =>
    (document.querySelector('meta[name="csrf-token"]') as HTMLMetaElement)?.content ?? '';

const scrollToBottom = () => {
    nextTick(() => { if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight; });
};

const autoResize = () => {
    const ta = inputRef.value;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 80) + 'px';
};

const send = async () => {
    const text = input.value.trim();
    if (!text || isLoading.value) return;

    messages.value.push({ role: 'user', content: text });
    input.value = '';
    nextTick(autoResize);
    scrollToBottom();
    isLoading.value = true;

    try {
        const history = messages.value.slice(-11, -1);
        const res = await fetch(`/api/demos/${props.demoId}/chat`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': getCsrf() },
            body:    JSON.stringify({ message: text, history, context: buildContext() }),
        });

        const data = await res.json();
        messages.value.push({ role: 'assistant', content: data.reply ?? 'No response.' });
    } catch {
        messages.value.push({ role: 'assistant', content: 'Something went wrong. Please try again.' });
    } finally {
        isLoading.value = false;
        scrollToBottom();
    }
};

const sendSuggestion = (s: string) => { input.value = s; send(); };
const clearChat      = () => { messages.value = []; input.value = ''; };

// ── Markdown renderer ─────────────────────────────────────────────────────────
const renderMarkdown = (text: string): string => {
    if (!text) return '';
    let html = text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
        .replace(/__(.+?)__/g, '<strong class="text-white font-semibold">$1</strong>')
        .replace(/\*([^*\n]+?)\*/g, '<em class="text-white/70">$1</em>')
        .replace(/`([^`]+?)`/g, '<code class="text-primary font-mono text-[10px] bg-primary/10 px-1 rounded">$1</code>');

    const lines = html.split('\n');
    const result: string[] = [];
    let inList = false;

    for (const line of lines) {
        const ulMatch = line.match(/^[\s]*[-•–]\s+(.+)/);
        if (ulMatch) {
            if (!inList) { result.push('<ul class="space-y-0.5 my-1.5 pl-2">'); inList = true; }
            result.push(`<li class="flex gap-1.5 text-white/80"><span class="text-primary shrink-0">·</span><span>${ulMatch[1]}</span></li>`);
        } else {
            if (inList) { result.push('</ul>'); inList = false; }
            if (line.trim() === '') result.push('<div class="h-1.5"></div>');
            else result.push(`<p class="text-white/80 leading-relaxed">${line}</p>`);
        }
    }
    if (inList) result.push('</ul>');
    return result.join('');
};

watch(messages, scrollToBottom, { deep: true });
</script>

<style scoped>
.custom-track::-webkit-scrollbar       { width: 4px; }
.custom-track::-webkit-scrollbar-track { background: transparent; }
.custom-track::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.06); border-radius: 10px; }
</style>