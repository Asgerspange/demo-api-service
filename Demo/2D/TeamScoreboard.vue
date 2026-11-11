<template>
  <div class="flex flex-col gap-1.5 w-full max-w-[320px]">
    <div class="flex justify-between items-center px-2 mb-1">
        <span class="text-xs font-black uppercase tracking-widest text-white/40">{{ name }}</span>
        <span class="text-2xl font-black italic tabular-nums" :class="teamType === 'ct' ? 'text-blue-500' : 'text-orange-500'">{{ score }}</span>
    </div>

    <div v-for="player in players" :key="player.steam_id" 
         class="group relative h-11 flex items-center px-3 rounded-lg overflow-hidden bg-slate-900/40 border transition-all cursor-pointer"
         :class="focusedPlayer === player.steamid
             ? (teamType === 'ct' ? 'border-blue-400/60 shadow-[0_0_8px_rgba(96,165,250,0.4)]' : 'border-orange-400/60 shadow-[0_0_8px_rgba(251,146,60,0.4)]')
             : 'border-white/5 hover:border-white/20'"
         @click="$emit('focus-player', { steamid: player.steamid, name: player.name, team: teamType })">
      
      <div class="absolute inset-0 transition-all duration-700 opacity-20"
           :class="teamType === 'ct' ? 'bg-blue-600' : 'bg-orange-600'"
           :style="{ width: player.health + '%' }">
      </div>

      <div class="relative flex items-center justify-between w-full z-10">
        <div class="flex items-center gap-3">
          <div class="w-8 text-sm font-mono font-bold" :class="player.health < 30 ? 'text-red-500 animate-pulse' : 'text-white/90'">
            {{ player.health > 0 ? player.health : 'DEAD' }}
          </div>
          <span class="font-bold text-sm tracking-tight truncate max-w-[120px]" :class="{ 'opacity-30 line-through': player.health <= 0 }">
            {{ player.name }}
          </span>
        </div>

        <div class="flex items-center gap-4">
          <span class="text-emerald-400 font-mono text-xs font-bold tabular-nums">${{ player.balance }}</span>
          <div class="w-10 flex justify-end">
            <img v-if="player.active_weapon_name && player.health > 0" 
                 :src="getWeapon(player.active_weapon_name).url" 
                 class="h-4 brightness-200 drop-shadow-md" />
          </div>
        </div>
      </div>

      <div v-if="player.health <= 0" class="absolute inset-0 bg-card/60 backdrop-grayscale z-0"></div>
    </div>
  </div>
</template>

<script setup>
defineProps({
    name:          { type: String,   default: '' },
    score:         { type: Number,   default: 0 },
    players:       { type: Array,    default: () => [] },
    getWeapon:     { type: Function, required: true },
    teamType:      { type: String,   default: 'ct' },
    focusedPlayer: { type: String,   default: null },
});
defineEmits(['focus-player']);
</script>