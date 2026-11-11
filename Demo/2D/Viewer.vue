<template>
    <!-- ── Canvas layer ──────────────────────────────────────────────────────── -->
    <div id="canvas-container" class="absolute inset-0 w-full h-full flex justify-center items-center overflow-hidden z-0">
        <canvas id="mapCanvas"        class="absolute block w-full h-full" style="z-index:1"></canvas>
        <canvas id="gameCanvas"       class="absolute block w-full h-full pointer-events-none" style="z-index:2"></canvas>
        <canvas id="annotationCanvas" class="absolute block w-full h-full pointer-events-none" style="z-index:3"></canvas>
    </div>

    <!-- Annotation draw overlay -->
    <div
        v-if="isDrawingMode"
        class="absolute inset-0 z-[5] cursor-crosshair"
        @mousedown="handleCanvasMouseDown"
        @mousemove="handleCanvasMouseMove"
        @mouseup="handleCanvasMouseUp"
    ></div>

    <!-- ── HUD overlay ───────────────────────────────────────────────────────── -->
    <div id="overlay" class="z-10 w-full h-[calc(100%-80px)] bottom-0 absolute flex flex-col pointer-events-none font-['Bai_Jamjuree',sans-serif] text-white">

        <!-- Top row -->
        <div class="relative w-full px-3 pt-3 sm:px-6 sm:pt-6 flex justify-between items-start">
            <div class="w-12"></div>

            <!-- Clock -->
            <div class="flex flex-col items-center absolute top-3 left-3 sm:top-6 sm:left-6">
                <div class="text-[9px] sm:text-[10px] font-bold tracking-[0.25em] sm:tracking-[0.3em] text-white/40 uppercase whitespace-nowrap">
                    <template v-if="!viewingMultipleRounds">ROUND {{ currentRound }}</template>
                    <template v-else>{{ activeRounds.length }} ROUNDS</template>
                </div>
                <div class="text-xl sm:text-3xl font-mono font-bold tabular-nums">
                    <template v-if="secondsRemaining !== null && !viewingMultipleRounds">{{ secondsToClock(secondsRemaining) }}</template>
                    <template v-else-if="!viewingMultipleRounds">1:55</template>
                    <template v-else>{{ secondsToClock(multiRoundSecondsRemaining) }}</template>
                </div>
            </div>

            <div id="demo-tools" class="relative flex flex-col gap-2 pointer-events-auto">
                <!-- ── View tools ── -->
                <div class="bg-card/80 backdrop-blur-md border border-primary/10 rounded-xl overflow-hidden">
                    <div class="text-[9px] font-black uppercase tracking-widest text-white/25 px-3 pt-2 pb-1">View</div>
                    <div class="flex flex-col px-1 pb-1 gap-0.5">

                        <!-- Multi-round compare -->
                        <button
                            v-tooltip="multiRoundMode ? 'Exit comparison mode' : 'Compare rounds across demos'"
                            class="flex items-center gap-2 px-2.5 py-2 rounded-lg text-[11px] font-semibold transition-all w-full text-left"
                            :class="multiRoundMode
                                ? 'bg-primary/20 text-primary'
                                : 'text-zinc-400 hover:text-white hover:bg-white/10'"
                            @click="toggleMultiRoundMode"
                        >
                            <Icon :icon="multiRoundMode ? 'lucide:grid' : 'lucide:layers'" class="text-sm shrink-0" />
                            <span>{{ multiRoundMode ? 'Comparing' : 'Compare' }}</span>
                            <span v-if="multiRoundMode && selectedRounds.length"
                                class="ml-auto bg-primary/20 text-primary text-[10px] rounded-full px-1.5 leading-4">
                                {{ selectedRounds.length }}
                            </span>
                        </button>
 
                        <!-- Filter (compare mode only) -->
                        <button
                            v-if="viewingMultipleRounds"
                            v-tooltip="'Filters'"
                            class="flex items-center gap-2 px-2.5 py-2 rounded-lg text-[11px] font-semibold transition-all w-full text-left"
                            :class="filterPanelOpen
                                ? 'bg-primary/20 text-primary'
                                : 'text-zinc-400 hover:text-white hover:bg-white/10'"
                            @click="filterPanelOpen = !filterPanelOpen"
                        >
                            <Icon icon="lucide:sliders-horizontal" class="text-sm shrink-0" />
                            <span>Filters</span>
                        </button>
 
                        <!-- Add demo -->
                        <button
                            v-tooltip="'Add demo to compare'"
                            class="flex items-center gap-2 px-2.5 py-2 rounded-lg text-[11px] font-semibold text-zinc-400 hover:text-white hover:bg-white/10 transition-all w-full text-left"
                            @click="showDemoSearch = true"
                        >
                            <Icon icon="lucide:square-plus" class="text-sm shrink-0" />
                            <span>Add demo</span>
                        </button>
                    </div>
                </div>
 
                <!-- ── Annotate tools ── -->
                <div v-if="!viewingMultipleRounds" class="bg-card/80 backdrop-blur-md border border-primary/10 rounded-xl overflow-hidden">
                    <div class="text-[9px] font-black uppercase tracking-widest text-white/25 px-3 pt-2 pb-1">Annotate</div>
                    <div class="flex flex-col px-1 pb-1 gap-0.5">
 
                        <!-- Notes -->
                        <button
                            v-tooltip="'Round notes & annotations'"
                            class="flex items-center gap-2 px-2.5 py-2 rounded-lg text-[11px] font-semibold transition-all w-full text-left"
                            :class="annotationPanelOpen
                                ? 'bg-primary/20 text-primary'
                                : 'text-zinc-400 hover:text-white hover:bg-white/10'"
                            @click="annotationPanelOpen = !annotationPanelOpen"
                        >
                            <Icon icon="lucide:notebook-pen" class="text-sm shrink-0" />
                            <span>Notes</span>
                            <span v-if="noteAnnotations.length"
                                class="ml-auto bg-primary/20 text-primary text-[10px] rounded-full px-1.5 leading-4">
                                {{ noteAnnotations.length }}
                            </span>
                        </button>
 
                        <!-- Drawing tools row -->
                        <div class="flex gap-1 px-1.5 pb-1 pt-0.5">
                            <button
                                v-for="tool in drawingTools" :key="tool.id"
                                v-tooltip="tool.label"
                                class="flex-1 h-8 flex items-center justify-center rounded-lg transition-all text-sm"
                                :class="activeTool === tool.id
                                    ? 'bg-primary text-white shadow-[0_0_8px_var(--color-primary)]'
                                    : 'text-zinc-500 hover:text-white hover:bg-white/10'"
                                @click="setTool(tool.id)"
                            >
                                <Icon :icon="tool.icon" />
                            </button>
                        </div>
 
                        <!-- Color picker (when tool active) -->
                        <div v-if="activeTool !== TOOL_NONE" class="flex gap-1 px-2.5 pb-1.5 flex-wrap">
                            <button
                                v-for="c in annotationColors" :key="c"
                                class="w-4 h-4 rounded-full border-2 transition-all"
                                :style="{ backgroundColor: c, borderColor: activeColor === c ? '#fff' : 'transparent' }"
                                @click="activeColor = c"
                            />
                        </div>
                    </div>
                </div>
 
                <!-- ── AI tools ── -->
                <div v-if="!viewingMultipleRounds" class="bg-card/80 backdrop-blur-md border border-primary/10 rounded-xl overflow-hidden">
                    <div class="text-[9px] font-black uppercase tracking-widest text-white/25 px-3 pt-2 pb-1">AI</div>
                    <div class="flex flex-col px-1 pb-1 gap-0.5">
                        <button
                            v-tooltip="'AI Chat — ask about this round or demo'"
                            class="flex items-center gap-2 px-2.5 py-2 rounded-lg text-[11px] font-semibold transition-all w-full text-left"
                            :class="aiChatOpen
                                ? 'bg-primary/20 text-primary'
                                : 'text-zinc-400 hover:text-white hover:bg-white/10'"
                            @click="aiChatOpen = !aiChatOpen"
                        >
                            <Icon icon="lucide:sparkles" class="text-sm shrink-0" />
                            <span>AI Chat</span>
                        </button>
                    </div>
                </div>
 
                <!-- ── Player focus badge ── -->
                <div v-if="focusedPlayer"
                    class="flex items-center justify-between gap-2 bg-primary border border-primary/30 rounded-xl px-3 py-2 backdrop-blur-md">
                    <div class="flex gap-2 items-center">
                        <div class="w-2 h-2 rounded-full animate-pulse" :style="{ backgroundColor: getTeamColor(focusedPlayerTeam) }" />
                        <span class="text-xs font-bold text-white/80 truncate max-w-[120px]">{{ focusedPlayerName }}</span>
                    </div>
                    <button class="text-white hover:text-white/60 transition-colors" @click="clearFocusedPlayer">
                        <Icon icon="lucide:x" class="text-sm" />
                    </button>
                </div>
 
                <!-- ── Floating panels (anchored to bottom of tools) ── -->
 
                <!-- Round selector (compare mode) -->
                <div v-if="multiRoundMode" class="dv-flyout">
                    <MultiDemoSelector
                        :loaded-demos="loadedDemos"
                        :primary-demo="demo"
                        :primary-rounds="demoRounds"
                        :selected-rounds="selectedRounds"
                        :is-round-selected="isRoundSelected"
                        :user-steam-id="userSteamId"
                        @toggle-round="({ externalId: eId, demoId: dId, demoName, roundIndex }) => toggleRoundSelection(eId, dId, demoName, roundIndex)"
                        @apply="applyMultiRoundView"
                        @cancel="toggleMultiRoundMode"
                        @add-demo="addDemo"
                        @remove-demo="removeDemo"
                    />
                </div>
 
                <!-- Filter panel -->
                <div v-if="viewingMultipleRounds && filterPanelOpen" class="dv-flyout">
                    <MultiRoundFilters
                        :show="true"
                        :players="multiRoundPlayers"
                        :model-team-filter="teamFilter"
                        :model-player-filter="playerFilter"
                        :model-show-util="showUtil"
                        @close="filterPanelOpen = false"
                        @update:model-team-filter="v => { setTeamFilter(v); render(true); }"
                        @update:model-player-filter="v => { setPlayerFilter(v); render(true); }"
                        @update:model-show-util="v => { setShowUtil(v); render(true); }"
                    />
                </div>
            </div>
 
        </div>

        <!-- Middle area -->
        <div class="flex-1 relative w-full px-3 sm:px-6">

            <!-- Kill feed -->
            <div v-if="!viewingMultipleRounds" id="round-feed" class="absolute top-3 sm:top-4 right-3 sm:right-6 flex flex-col items-end gap-1 max-w-[60%] sm:max-w-none">
                <div
                    v-for="event in currentEvents" :key="event.victim_steamid"
                    class="flex items-center gap-1.5 sm:gap-3 bg-card/90 backdrop-blur-sm border-r-2 sm:border-r-4 border-primary/80 px-2 py-1 sm:px-4 sm:py-1.5 text-[11px] sm:text-sm shadow-lg animate-in slide-in-from-right-4 whitespace-nowrap"
                >
                    <span class="hidden sm:inline text-[10px] font-mono opacity-50">{{ secondsToClock(tickToSecondsRemaining(event.tick)) }}</span>
                    <span class="font-bold uppercase tracking-tight truncate max-w-[80px] sm:max-w-none" :style="{ color: getTeamColor(event.attacker_side) }">{{ event.attacker_name }}</span>
                    <div class="flex items-center gap-1 sm:gap-1.5 opacity-90 brightness-150 shrink-0">
                        <img v-if="event.attackerblind" :src="demoIcons.blind_kill?.url" class="h-3 sm:h-3.5 invert" />
                        <img v-if="getWeapon(event.weapon).url" :src="getWeapon(event.weapon).url" class="h-3.5 sm:h-4 w-auto" />
                        <img v-if="event.headshot" :src="demoIcons.icon_headshot?.url" class="h-3 sm:h-3.5 invert" />
                    </div>
                    <span class="font-bold uppercase tracking-tight truncate max-w-[80px] sm:max-w-none" :style="{ color: getTeamColor(event.victim_side) }">{{ event.victim_name }}</span>
                </div>
            </div>

            <!-- Active rounds legend -->
            <div v-if="viewingMultipleRounds" class="absolute top-3 sm:top-4 right-3 sm:right-6 bg-card/80 backdrop-blur-md rounded-xl p-3 sm:p-4 border border-primary/10 shadow-2xl min-w-[180px] sm:min-w-[220px] max-w-[60%] sm:max-w-none">
                <div class="text-[10px] font-bold text-white/40 uppercase mb-3 tracking-widest">Active Rounds</div>
                <div class="flex flex-col gap-2">
                    <div v-for="(r, idx) in activeRounds" :key="`${r.demoId}_${r.roundIndex}`" class="flex items-center gap-3">
                        <div class="w-3 h-3 rounded-full shadow-[0_0_8px_rgba(255,255,255,0.3)]" :style="{ backgroundColor: getRoundColor(idx, activeRounds.length) }"></div>
                        <span class="text-sm font-medium">
                            Round {{ r.roundIndex }}
                            <span class="opacity-40 text-xs">({{ r.demoName ?? r.demoId }})</span>
                        </span>
                    </div>
                </div>
                <button @click="exitMultiRoundView" class="mt-4 w-full text-xs text-white/40 hover:text-white border border-white/10 rounded-lg py-1.5 transition-colors pointer-events-auto">
                    Exit comparison
                </button>
            </div>

            <!-- Annotation panel — z-[60] renders above scoreboards -->
            <Transition name="slide-panel" v-if="!viewingMultipleRounds">
                <div
                    v-if="annotationPanelOpen"
                    class="pointer-events-auto absolute top-3 sm:top-4 left-3 sm:left-6 right-3 sm:right-auto sm:w-80 max-h-[calc(100vh-220px)] bg-card/95 backdrop-blur-xl border border-primary/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden z-[60]"
                >
                    <div class="flex items-center justify-between px-5 py-4 border-b border-white/10 shrink-0">
                        <div>
                            <div class="text-sm font-bold text-white">Round Notes</div>
                            <div class="text-[10px] text-white/40 mt-0.5">Round {{ currentRound }} · {{ roundAnnotations.length }} item{{ roundAnnotations.length !== 1 ? 's' : '' }}</div>
                        </div>
                        <button class="w-8 h-8 rounded-lg hover:bg-white/10 flex items-center justify-center text-white/50 hover:text-white transition-colors" @click="annotationPanelOpen = false">
                            <Icon icon="lucide:x" class="w-4 h-4" />
                        </button>
                    </div>

                    <div class="px-4 pt-4 pb-3 border-b border-white/5 shrink-0">
                        <textarea
                            v-model="pendingNote"
                            placeholder="Add a note for this round…"
                            rows="3"
                            class="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder-white/25 resize-none focus:outline-none focus:border-[var(--color-primary)]/60 transition-colors custom-track"
                            @keydown.ctrl.enter="submitNote"
                            @keydown.meta.enter="submitNote"
                        ></textarea>
                        <div class="flex items-center justify-between mt-2">
                            <span class="text-[10px] text-white/25">⌘+Enter to save</span>
                            <button
                                :disabled="!pendingNote.trim()"
                                class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                                :class="pendingNote.trim() ? 'bg-[var(--color-primary)] text-white hover:opacity-90' : 'bg-white/10 text-white/50'"
                                @click="submitNote"
                            >Save note</button>
                        </div>
                    </div>

                    <div class="flex-1 overflow-y-auto px-4 py-3 space-y-2 custom-track">
                        <div v-if="!roundAnnotations.length" class="text-center py-8 text-white/25 text-sm">
                            No annotations yet.<br>Draw areas or write notes above.
                        </div>
                        <div
                            v-for="a in shapeAnnotations" :key="a.id"
                            class="flex items-start gap-2 bg-white/5 rounded-xl px-3 py-2.5 border border-transparent hover:border-white/10 transition-all group"
                        >
                            <div class="w-3 h-3 rounded-full mt-1 shrink-0" :style="{ backgroundColor: a.color }"></div>
                            <div class="flex-1 min-w-0">
                                <div class="text-[10px] font-bold text-white/40 uppercase tracking-wider">
                                    {{ shapeTypeLabel(a) }}
                                    <span v-if="a.tick" class="ml-1 normal-case font-normal text-white/25">@ {{ secondsToClock(tickToSecondsRemaining(a.tick)) }}</span>
                                </div>
                                <div v-if="a.label" class="text-xs text-white font-medium">{{ a.label }}</div>
                                <div v-if="a.content" class="text-xs text-white/60 mt-0.5 leading-relaxed">{{ a.content }}</div>
                            </div>
                            <button class="opacity-0 group-hover:opacity-100 transition-opacity text-white/30 hover:text-red-400" @click="deleteAnnotation(a.id)">
                                <Icon icon="lucide:trash-2" class="w-3.5 h-3.5" />
                            </button>
                        </div>
                        <div
                            v-for="a in noteAnnotations" :key="a.id"
                            class="relative bg-white/5 rounded-xl px-3 py-3 border border-transparent hover:border-white/10 transition-all group"
                        >
                            <div class="absolute left-0 top-0 bottom-0 w-1 rounded-l-xl" :style="{ backgroundColor: a.color }"></div>
                            <div class="pl-2">
                                <div class="text-xs text-white leading-relaxed">{{ a.content }}</div>
                                <div class="text-[10px] text-white/25 mt-1.5">{{ a.user?.name ?? 'You' }} · {{ formatAnnotationTime(a.created_at) }}</div>
                            </div>
                            <button class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-white/30 hover:text-red-400" @click="deleteAnnotation(a.id)">
                                <Icon icon="lucide:trash-2" class="w-3.5 h-3.5" />
                            </button>
                        </div>
                    </div>
                </div>
            </Transition>
            <!-- AI Chat panel -->
<Transition name="slide-panel" v-if="!viewingMultipleRounds">
            <div
                v-if="aiChatOpen"
                class="pointer-events-auto absolute top-4 z-[60] w-80 flex flex-col"
                :style="{
                    left: annotationPanelOpen ? 'calc(24px + 320px + 12px)' : '24px',
                    height: 'calc(100vh - 220px)',
                    maxHeight: '600px',
                }"
            >
                <ViewerAiChat
                    :demo-id="demoId"
                    :current-round="currentRound"
                    :round="round"
                    :current-tick="currentTick"
                    :current-events="currentEvents"
                    @close="aiChatOpen = false"
                />
            </div>
        </Transition>
            <!-- Pending shape popup -->
            <Transition name="slide-panel" v-if="!viewingMultipleRounds">
                <div
                    v-if="pendingShape"
                    class="pointer-events-auto absolute bottom-6 sm:bottom-8 left-1/2 -translate-x-1/2 w-[calc(100vw-1.5rem)] sm:w-96 max-w-md bg-card/98 backdrop-blur-xl border border-primary/20 rounded-2xl shadow-2xl p-4 sm:p-5"
                >
                    <div class="flex items-center gap-2 mb-4">
                        <div class="w-3 h-3 rounded-full shrink-0" :style="{ backgroundColor: pendingShape.color }"></div>
                        <span class="text-sm font-bold text-white">{{ shapeTypeLabel(pendingShape) }} drawn</span>
                        <span class="ml-auto text-[10px] text-white/30 font-mono">
                            {{ pendingTick ? secondsToClock(tickToSecondsRemaining(pendingTick)) : '' }}
                        </span>
                    </div>
                    <input
                        v-model="pendingLabel"
                        placeholder="Label (shown on map)…"
                        class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/25 focus:outline-none focus:border-[var(--color-primary)]/60 transition-colors mb-2"
                        autofocus
                        @keydown.enter="pendingComment ? null : confirmShape()"
                    />
                    <textarea
                        v-model="pendingComment"
                        placeholder="Add a comment (optional)…"
                        rows="2"
                        class="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-white/25 resize-none focus:outline-none focus:border-[var(--color-primary)]/60 transition-colors custom-track"
                        @keydown.ctrl.enter="confirmShape"
                        @keydown.meta.enter="confirmShape"
                    ></textarea>
                    <div class="flex items-center gap-2 mt-3">
                        <button @click="discardShape" class="px-3 py-1.5 rounded-lg text-xs text-white/40 hover:text-white hover:bg-white/10 transition-all">Discard</button>
                        <button @click="confirmShape" class="ml-auto px-4 py-1.5 rounded-lg text-xs font-bold bg-[var(--color-primary)] text-white hover:opacity-90 transition-all">Save shape</button>
                    </div>
                </div>
            </Transition>
        </div>

        <!-- Bottom bar -->
        <div class="w-full flex flex-col pointer-events-none">
            <!-- Scoreboards: side-by-side on desktop, togglable overlay on mobile -->
            <div
                v-if="!viewingMultipleRounds"
                class="hidden lg:flex justify-between items-end px-6 pb-6 gap-20"
            >
                <TeamScoreboard
                    team-type="ct" name="Counter-Terrorists"
                    :score="round.meta?.CT_score ?? 0"
                    :players="currentTick?.players.filter(p => p.team_name === 'ct')"
                    :getWeapon="getWeapon" :focused-player="focusedPlayer"
                    class="pointer-events-auto" @focus-player="onFocusPlayer"
                />
                <TeamScoreboard
                    team-type="t" name="Terrorists"
                    :score="round.meta?.T_score ?? 0"
                    :players="currentTick?.players.filter(p => p.team_name === 't')"
                    :getWeapon="getWeapon" :focused-player="focusedPlayer"
                    class="pointer-events-auto" @focus-player="onFocusPlayer"
                />
            </div>

            <!-- Mobile scoreboards overlay -->
            <Transition name="slide-panel">
                <div
                    v-if="!viewingMultipleRounds && showMobileScoreboards"
                    class="lg:hidden absolute inset-x-3 bottom-[120px] z-30 pointer-events-auto"
                >
                    <div class="bg-card/95 backdrop-blur-xl border border-white/10 rounded-xl p-3 max-h-[55vh] overflow-y-auto custom-track">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">Live scoreboard</span>
                            <button @click="showMobileScoreboards = false" class="w-7 h-7 flex items-center justify-center rounded-md hover:bg-white/10 text-zinc-400 hover:text-white transition-colors">
                                <Icon icon="lucide:x" class="w-4 h-4" />
                            </button>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <TeamScoreboard
                                team-type="ct" name="Counter-Terrorists"
                                :score="round.meta?.CT_score ?? 0"
                                :players="currentTick?.players.filter(p => p.team_name === 'ct')"
                                :getWeapon="getWeapon" :focused-player="focusedPlayer"
                                class="!max-w-full" @focus-player="onFocusPlayer"
                            />
                            <TeamScoreboard
                                team-type="t" name="Terrorists"
                                :score="round.meta?.T_score ?? 0"
                                :players="currentTick?.players.filter(p => p.team_name === 't')"
                                :getWeapon="getWeapon" :focused-player="focusedPlayer"
                                class="!max-w-full" @focus-player="onFocusPlayer"
                            />
                        </div>
                    </div>
                </div>
            </Transition>

            <!-- Playback bar -->
            <div class="flex items-center gap-2 sm:gap-4 px-3 sm:px-6 h-12 sm:h-14 backdrop-blur-xl pointer-events-auto">
                <button @click="togglePlayback()" class="w-9 h-9 sm:w-10 sm:h-10 flex items-center justify-center rounded-full hover:bg-white/10 transition-colors shrink-0">
                    <Icon :icon="playing ? 'lucide:pause' : 'lucide:play'" class="text-xl sm:text-2xl text-primary" />
                </button>
                <button @click="togglePlaybackSpeed" class="text-[10px] sm:text-xs font-black font-mono w-9 sm:w-10 text-white/60 hover:text-white tabular-nums shrink-0">
                    {{ playbackSpeed }}X
                </button>
                <Slider v-if="!viewingMultipleRounds" v-model="playableTickIndex" :round="playableRound" />
                <Slider v-else v-model="multiRoundTickIndex" :round="{ tickNumbers: multiRoundTickNumbers, meta: { freeze_end: 0 } }" />

                <!-- Mobile: scoreboard toggle -->
                <button
                    v-if="!viewingMultipleRounds"
                    @click="showMobileScoreboards = !showMobileScoreboards"
                    class="lg:hidden w-9 h-9 flex items-center justify-center rounded-full transition-colors shrink-0"
                    :class="showMobileScoreboards ? 'bg-primary/20 text-primary' : 'text-zinc-400 hover:text-white hover:bg-white/10'"
                    aria-label="Toggle scoreboard"
                >
                    <Icon icon="lucide:users" class="text-lg" />
                </button>
            </div>

            <!-- Round tabs -->
            <div class="flex border-t border-white/5 overflow-x-auto no-scrollbar pointer-events-auto">
                <template v-for="(r, i) in demoRounds" :key="r.round_index">
                    <div v-if="roundTabSeparators[i]" class="w-px bg-white/10 h-8 self-center shrink-0"></div>
                    <button
                        class="flex-1 min-w-[56px] sm:min-w-[70px] py-2 sm:py-3 flex flex-col items-center gap-0.5 transition-all hover:bg-white/5 border-b-2 relative shrink-0"
                        :class="[
                            currentRound === r.round_index && !viewingMultipleRounds ? 'bg-white/5 border-primary' : 'border-transparent',
                            multiRoundMode && isRoundSelected(externalId, r.round_index) ? 'bg-primary/20 border-primary' : '',
                        ]"
                        @click="multiRoundMode
                            ? toggleRoundSelection(externalId, demoId, demo?.name, r.round_index)
                            : loadRound(externalId, demoId, r.round_index)"
                    >
                        <div v-if="hasAnnotationsForRound(r.round_index)" class="absolute top-1 right-1 sm:top-1.5 sm:right-1.5 w-1.5 h-1.5 rounded-full bg-[var(--color-primary)]"></div>
                        <span class="text-[9px] sm:text-[10px] font-bold text-white/30 uppercase tabular-nums">R{{ r.round_index }}</span>
                        <div class="text-[11px] sm:text-xs font-bold tabular-nums">
                            <template v-if="roundTabSideSwapped[i]">
                                <span class="text-orange-400">{{ r?.meta.T_score }}</span><span class="text-white/30 mx-0.5">-</span><span class="text-blue-400">{{ r?.meta.CT_score }}</span>
                            </template>
                            <template v-else>
                                <span class="text-blue-400">{{ r?.meta.CT_score }}</span><span class="text-white/30 mx-0.5">-</span><span class="text-orange-400">{{ r?.meta.T_score }}</span>
                            </template>
                        </div>
                        <div
                            v-if="multiRoundMode"
                            class="w-3 h-3 sm:w-3.5 sm:h-3.5 rounded border flex items-center justify-center transition-all"
                            :class="isRoundSelected(externalId, r.round_index) ? 'bg-primary border-primary' : 'border-white/20'"
                        >
                            <Icon v-if="isRoundSelected(externalId, r.round_index)" icon="lucide:check" class="w-2.5 h-2.5 text-white" />
                        </div>
                    </button>
                </template>
            </div>
        </div>
    </div>

    <DemoSearchModal
        v-if="showDemoSearch"
        :loaded-demo-ids="[String(externalId), ...[...loadedDemos.keys()]]"
        @select="(id) => { addDemo(id); }"
        @close="showDemoSearch = false"
    />
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed, nextTick } from 'vue';
import { useRoute } from 'vue-router';
import { secondsToClock } from '@/helpers';
import { Icon } from '@iconify/vue';
import { useStore } from '@/store';
import { storeToRefs } from 'pinia';

import TeamScoreboard    from './TeamScoreboard.vue';
import Slider            from './Slider.vue';
import MultiDemoSelector from './MultiDemoSelector.vue';
import MultiRoundFilters from './MultiRoundFilters.vue';
import DemoSearchModal   from './DemoSearchModal.vue';
import ViewerAiChat      from './ViewerAiChat.vue';

import { useDemo }      from './composables/useDemo';
import { useRoundData } from './composables/useRoundData';
import { useMultiDemo } from './composables/useMultiDemo';
import { useCanvas }    from './composables/useCanvas';
import { useRenderer }  from './composables/useRenderer';
import { usePlayback }  from './composables/usePlayback';
import { useWeapons }   from './composables/useWeapons';
import {
    useAnnotations,
    TOOL_NONE, TOOL_RECT, TOOL_CIRCLE, TOOL_FREEHAND
} from './composables/useAnnotations';

const route      = useRoute();
const externalId = computed(() => route.params.id);

const _store = useStore();
const { user: _storeUser } = storeToRefs(_store);
const userSteamId = computed(() => _storeUser.value?.user_info?.steam_id ?? null);
const aiChatOpen = ref(false);

const { demo, demoId, mapMetadata, demoRounds, version, demoIcons } = useDemo(externalId);
const { getWeapon, checkWeaponFilter } = useWeapons();

const {
    rounds, currentRound, currentTickIndex, allowPlay, loadingRounds,
    round, firstPlayableTickIndex, playableRound, playableTickIndex,
    currentTick, currentEvents, secondsRemaining, steamIdTeamLookup,
    tickToSecondsRemaining, roundTabSeparators, roundTabSideSwapped,
    loadRound: _loadRound,
    setPinnedRoundKeys,           // ← ADD THIS
} = useRoundData({ demoId, demoRounds, version, externalId });

function loadRound(extId, intId, roundIndex, background = false) {
    return _loadRound(extId ?? externalId.value, intId ?? demoId.value, roundIndex, background);
}

const {
    loadedDemos, addDemo, removeDemo,
    selectedRounds, multiRoundMode, toggleMultiRoundMode, isRoundSelected, toggleRoundSelection,
    viewingMultipleRounds, activeRounds,
    multiRoundTickIndex, multiRoundTickNumbers, multiRoundSecondsRemaining,
    applyMultiRoundView, exitMultiRoundView,
    teamFilter, playerFilter, weaponFilter, showUtil,
    setTeamFilter, setPlayerFilter, setShowUtil,
    multiRoundPlayers,
    getRoundColor, getActiveRoundColor,
} = useMultiDemo({ rounds, loadRound, allowPlay, setPinnedRoundKeys }); // ← ADD setPinnedRoundKeys
 

const filterPanelOpen = ref(false);

// ─── Player hover focus (canvas) ──────────────────────────────────────────────
// { steamid, team, roundKey } | null — set by the canvas hover handler, read by
// the renderer to dim everyone outside the hovered player's round + team.
const hoveredPlayer = ref(null);

const {
    cachedImage, mapPosition,
    getCanvases, drawMap,
    toWorldCoords, toGameCoords,
    refreshMapPixelCacheIfNeeded, getPixelCache,
    attachListeners, detachListeners, onPositionChange,
} = useCanvas({ mapMetadata, demo });

const { render, cancelRender, getTeamColor, playerHitboxes } = useRenderer({
    getCanvases, toWorldCoords, toGameCoords, mapPosition, cachedImage,
    refreshMapPixelCacheIfNeeded, getPixelCache,
    round, currentTickIndex, currentTick, steamIdTeamLookup, mapMetadata,
    getWeapon,
    viewingMultipleRounds, activeRounds, rounds,
    multiRoundTickIndex,
    teamFilter, playerFilter, weaponFilter, showUtil,
    checkWeaponFilter,
    getRoundColor,
    hoveredPlayer,
});

onPositionChange(() => { if (!playing.value) render(true); });

const { playing, playbackSpeed, togglePlayback, togglePlaybackSpeed, playDemo, pauseDemo } =
    usePlayback({
        currentTickIndex, firstPlayableTickIndex,
        currentRound, round, demoRounds, rounds, loadingRounds, allowPlay, loadRound,
        viewingMultipleRounds, multiRoundTickIndex, multiRoundTickNumbers,
        render, demoId, externalId,
    });

const showDemoSearch = ref(false);
const showMobileScoreboards = ref(false);

function handleKeyDown(e) {
    if (e.target.tagName === 'TEXTAREA') return;
    if (e.code === 'Space')  { e.preventDefault(); togglePlayback(); }
    if (e.code === 'Escape') { cancelDraw(); clearFocusedPlayer(); }
    if (e.code === 'ArrowRight' && !playing.value) {
        currentTickIndex.value = Math.min(currentTickIndex.value + 1, (round.value?.tickNumbers.length ?? 1) - 1);
    }
    if (e.code === 'ArrowLeft' && !playing.value) {
        currentTickIndex.value = Math.max(currentTickIndex.value - 1, firstPlayableTickIndex.value);
    }
}

watch(currentTick,         () => { if (!playing.value) render(true); });
watch(multiRoundTickIndex, () => { if (!playing.value) render(true); });

// Drop a stale hover focus when playback starts or the view context changes.
watch(playing, (p) => { if (p) setHoveredPlayer(null); });
watch([currentRound, viewingMultipleRounds], () => { setHoveredPlayer(null); });

watch(demoId, async (newDemoId) => {
    if (newDemoId) {
        let startRound = 1;
        const params   = new URLSearchParams(window.location.search);
        if (params.has('round')) {
            const p = parseInt(params.get('round'), 10);
            if (!isNaN(p)) startRound = p;
        }
        await loadRound(externalId.value, newDemoId, startRound);
        drawMap();
    }
}, { immediate: true });

onMounted(() => {
    attachListeners();
    window.addEventListener('keydown', handleKeyDown);
    const cc = document.getElementById('canvas-container');
    if (cc) {
        cc.addEventListener('mousemove', handleCanvasHover);
        cc.addEventListener('mouseleave', handleCanvasLeave);
    }
});
onUnmounted(() => {
    pauseDemo();
    cancelRender();
    detachListeners();
    window.removeEventListener('keydown', handleKeyDown);
    const cc = document.getElementById('canvas-container');
    if (cc) {
        cc.removeEventListener('mousemove', handleCanvasHover);
        cc.removeEventListener('mouseleave', handleCanvasLeave);
    }
    rounds.value      = null;
    cachedImage.value = null;
});

// ─── Player focus ─────────────────────────────────────────────────────────────
const focusedPlayer     = ref(null);
const focusedPlayerName = ref('');
const focusedPlayerTeam = ref('ct');

function onFocusPlayer({ steamid, name, team }) {
    if (focusedPlayer.value === steamid) { clearFocusedPlayer(); return; }
    focusedPlayer.value     = steamid;
    focusedPlayerName.value = name ?? steamid;
    focusedPlayerTeam.value = team;
}
function clearFocusedPlayer() { focusedPlayer.value = null; }

// ─── Canvas player hover ──────────────────────────────────────────────────────
// Hit-tests the cursor against the renderer's per-frame player hitboxes and
// drives `hoveredPlayer`, which the renderer uses to dim non-teammates.
function handleCanvasHover(e) {
    const boxes = playerHitboxes.value;
    if (!boxes.length) { setHoveredPlayer(null); return; }
    const container = document.getElementById('canvas-container');
    const rect = container?.getBoundingClientRect();
    if (!rect) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best = null, bestDist = 22;
    for (const b of boxes) {
        const s = gameToScreen(b.X, b.Y);
        const d = Math.hypot(s.x - mx, s.y - my);
        if (d < bestDist) { bestDist = d; best = b; }
    }
    setHoveredPlayer(best
        ? { steamid: best.steamid, team: best.team, roundKey: best.roundKey ?? null }
        : null);
}

function setHoveredPlayer(next) {
    const cur = hoveredPlayer.value;
    const same = (!cur && !next) ||
        (cur && next && cur.steamid === next.steamid && (cur.roundKey ?? null) === (next.roundKey ?? null));
    if (same) return;
    hoveredPlayer.value = next;
    if (!playing.value) render(true);
}

function handleCanvasLeave() { setHoveredPlayer(null); }

function drawFocusOverlay(ctx) {
    if (!focusedPlayer.value || !currentTick.value) return;
    const player = currentTick.value.players.find(p => p.steamid === focusedPlayer.value);
    if (!player || player.health <= 0) return;
    const screen = gameToScreen(player.X, player.Y);
    const color  = focusedPlayerTeam.value === 'ct' ? '#60a5fa' : '#fb923c';
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth   = 3;
    ctx.shadowBlur  = 12;
    ctx.shadowColor = color;
    ctx.beginPath();
    ctx.arc(screen.x, screen.y, 18, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
}

// ─── Annotations ──────────────────────────────────────────────────────────────
const {
    annotations, roundAnnotations, noteAnnotations, shapeAnnotations,
    activeTool, activeColor, pendingNote, isDrawingMode,
    pendingShape, pendingComment, pendingLabel, pendingTick,
    setTool, cancelDraw, submitNote, confirmShape, discardShape, deleteAnnotation,
    onMouseDown, onMouseMove, onMouseUp,
    drawAnnotationLayer, setDrawCallback,
} = useAnnotations({ demoId, currentRound });

const annotationPanelOpen = ref(false);

const drawingTools = [
    { id: TOOL_RECT,     label: 'Rectangle area', icon: 'lucide:square-dashed' },
    { id: TOOL_CIRCLE,   label: 'Circle area',     icon: 'lucide:circle-dashed' },
    { id: TOOL_FREEHAND, label: 'Freehand',        icon: 'lucide:pencil' },
];
const annotationColors = ['#5D3FD3', '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#ec4899', '#ffffff'];

function shapeTypeLabel(a) {
    if (a.type === 'area')     return a.shape_data?.shape === 'circle' ? 'Circle area' : 'Rectangle';
    if (a.type === 'freehand') return 'Freehand';
    return a.type;
}
function formatAnnotationTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
function hasAnnotationsForRound(roundNumber) {
    return annotations.value.some(a => a.round_number === roundNumber);
}

// ─── Coordinate helpers ───────────────────────────────────────────────────────
function gameToScreen(gameX, gameY) {
    const imgPx = toGameCoords(gameX, gameY);
    return {
        x: imgPx.x * mapPosition.value.scale + mapPosition.value.x,
        y: imgPx.y * mapPosition.value.scale + mapPosition.value.y,
    };
}
function clientToGame(clientX, clientY) {
    const container = document.getElementById('canvas-container');
    const rect = container?.getBoundingClientRect() ?? { left: 0, top: 0 };
    const imgSpace = toWorldCoords(clientX - rect.left, clientY - rect.top);
    const m = mapMetadata.value;
    if (!m) return { x: 0, y: 0 };
    return {
        x: imgSpace.x * m.scale + m.pos_x,
        y: m.pos_y - imgSpace.y * m.scale,
    };
}

// ─── Annotation canvas ────────────────────────────────────────────────────────
function repaintAnnotationCanvas() {
    const canvas = document.getElementById('annotationCanvas');
    if (!canvas || !(canvas instanceof HTMLCanvasElement)) return;
    const container = document.getElementById('canvas-container');
    if (!container) return;
    if (canvas.width  !== container.clientWidth)  canvas.width  = container.clientWidth;
    if (canvas.height !== container.clientHeight) canvas.height = container.clientHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawAnnotationLayer(ctx, gameToScreen, viewingMultipleRounds.value);
    drawFocusOverlay(ctx);
}
setDrawCallback(repaintAnnotationCanvas);

watch([currentTick, multiRoundTickIndex, focusedPlayer], () => { nextTick(repaintAnnotationCanvas); });

function handleCanvasMouseDown(e) { onMouseDown(e.clientX, e.clientY, clientToGame); }
function handleCanvasMouseMove(e) { onMouseMove(e.clientX, e.clientY, clientToGame); }
function handleCanvasMouseUp(e) {
    onMouseUp(e.clientX, e.clientY, clientToGame);
    nextTick(repaintAnnotationCanvas);
}
watch(pendingShape, (shape) => {
    if (shape) pendingTick.value = round.value?.tickNumbers?.[currentTickIndex.value] ?? null;
});
</script>

<style scoped>
.slide-panel-enter-active,
.slide-panel-leave-active {
    transition: opacity 0.2s ease, transform 0.2s ease;
}
.slide-panel-enter-from,
.slide-panel-leave-to {
    opacity: 0;
    transform: translateX(-12px);
}

.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { scrollbar-width: none; }

.custom-track::-webkit-scrollbar { width: 6px; }
.custom-track::-webkit-scrollbar-track { background: transparent; }
.custom-track::-webkit-scrollbar-thumb { background-color: var(--color-primary); opacity: 0.4; border-radius: 10px; }

/* Toolbar flyout panels (round selector / filters).
   Anchored to the TOP of #demo-tools and flown out to the left. The flyout owns
   the height cap (viewport-relative) and is a flex column, so the panel inside
   shrinks to fit and scrolls internally instead of running off the page —
   `top-full` previously dropped it below the whole tool stack and overflowed.
   Mobile: a fixed bottom sheet. */
.dv-flyout {
    position: absolute;
    top: 0;
    right: 100%;
    margin-right: 10px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    max-height: calc(100dvh - 200px);
}
@media (max-width: 640px) {
    .dv-flyout {
        position: fixed;
        inset: auto 0 0 0;
        margin: 0;
        max-height: none;
    }
}
</style>