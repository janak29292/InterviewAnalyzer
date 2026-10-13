<script>
  import { onMount, onDestroy } from 'svelte';

  const { sessions } = $props();
  const API_BASE = 'http://localhost:8002';
  const WS_BASE = 'ws://localhost:8002';

  // WebSocket tracking for currently-processing sessions
  let activeWs = $state({});      // sessionId -> WebSocket
  let liveProgress = $state({});   // sessionId -> { stage, detail, pct }

  // Track which session IDs we've connected to
  let connectedIds = new Set();

  $effect(() => {
    // Connect WebSocket for any session that is "processing" or "queued"
    for (const s of sessions) {
      if ((s.state === 'processing' || s.state === 'queued') && !connectedIds.has(s.id)) {
        connectWs(s.id);
        connectedIds.add(s.id);
      }
    }

    // Disconnect WebSockets for sessions that are done
    for (const id of connectedIds) {
      const session = sessions.find(s => s.id === id);
      if (session && (session.state === 'completed' || session.state === 'failed')) {
        if (activeWs[id]) {
          activeWs[id].close();
          const { [id]: _, ...rest } = activeWs;
          activeWs = rest;
        }
        connectedIds.delete(id);
      }
    }
  });

  onDestroy(() => {
    for (const ws of Object.values(activeWs)) {
      ws.close();
    }
  });

  function connectWs(sessionId) {
    try {
      const ws = new WebSocket(`${WS_BASE}/ws/${sessionId}`);
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'progress') {
            liveProgress = {
              ...liveProgress,
              [sessionId]: {
                stage: data.stage || 'extract',
                detail: data.detail || '',
                pct: data.pct >= 0 ? data.pct : 0,
              }
            };
          } else if (data.type === 'completed') {
            liveProgress = {
              ...liveProgress,
              [sessionId]: { stage: 'complete', detail: 'Done!', pct: 100 }
            };
          } else if (data.type === 'error') {
            liveProgress = {
              ...liveProgress,
              [sessionId]: { stage: 'error', detail: data.error || 'Failed', pct: 0 }
            };
          }
        } catch (e) {
          console.error('WS parse error', e);
        }
      };

      ws.onerror = () => {};
      ws.onclose = () => {
        connectedIds.delete(sessionId);
      };

      activeWs = { ...activeWs, [sessionId]: ws };
    } catch (err) {
      console.error('WS connect error:', err);
    }
  }

  function getStatusConfig(state) {
    switch (state) {
      case 'queued':
        return { label: 'Queued', color: 'amber', bgClass: 'bg-amber-500/15', textClass: 'text-amber-400', borderClass: 'border-amber-500/30', icon: '⏳' };
      case 'processing':
        return { label: 'Processing', color: 'blue', bgClass: 'bg-blue-500/15', textClass: 'text-blue-400', borderClass: 'border-blue-500/30', icon: '⚙️' };
      case 'completed':
        return { label: 'Completed', color: 'emerald', bgClass: 'bg-emerald-500/15', textClass: 'text-emerald-400', borderClass: 'border-emerald-500/30', icon: '✅' };
      case 'failed':
        return { label: 'Failed', color: 'red', bgClass: 'bg-red-500/15', textClass: 'text-red-400', borderClass: 'border-red-500/30', icon: '❌' };
      default:
        return { label: state, color: 'slate', bgClass: 'bg-slate-500/15', textClass: 'text-slate-400', borderClass: 'border-slate-500/30', icon: '📄' };
    }
  }

  function getQueuePosition(session) {
    if (session.state !== 'queued') return null;
    const queued = sessions.filter(s => s.state === 'queued');
    // Sessions are ordered desc by created_at, so for queue position we want ascending
    const sortedQueued = [...queued].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    const pos = sortedQueued.findIndex(s => s.id === session.id) + 1;
    return pos;
  }

  function formatTime(dateStr) {
    // Server sends UTC timestamps without Z suffix (SQLite strips tzinfo)
    const d = new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z');
    const now = new Date();
    const diffMs = now - d;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMin / 60);

    if (diffMin < 1) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    return d.toLocaleDateString();
  }

  function truncateFilename(name, maxLen = 35) {
    if (name.length <= maxLen) return name;
    const ext = name.lastIndexOf('.') > 0 ? name.slice(name.lastIndexOf('.')) : '';
    const base = name.slice(0, name.lastIndexOf('.') > 0 ? name.lastIndexOf('.') : name.length);
    const truncLen = maxLen - ext.length - 3;
    return base.slice(0, truncLen) + '...' + ext;
  }
</script>

<div class="w-full">
  <div class="flex items-center justify-between mb-6">
    <h2 class="text-xl font-bold text-slate-100 flex items-center gap-2">
      <svg class="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" /></svg>
      Transcription Queue
    </h2>
    <span class="text-sm text-slate-500">{sessions.length} session{sessions.length !== 1 ? 's' : ''}</span>
  </div>

  <div class="space-y-3">
    {#each sessions as session (session.id)}
      {@const status = getStatusConfig(session.state)}
      {@const progress = liveProgress[session.id]}
      {@const queuePos = getQueuePosition(session)}

      <div class="group relative rounded-2xl border transition-all duration-300 overflow-hidden {status.borderClass} {session.state === 'processing' ? 'bg-slate-800/80 shadow-lg shadow-blue-500/5' : 'bg-slate-800/40 hover:bg-slate-800/60'}">
        
        <!-- Progress bar background for processing items -->
        {#if session.state === 'processing' && progress}
          <div class="absolute inset-0 pointer-events-none">
            <div
              class="h-full bg-gradient-to-r from-blue-500/8 to-indigo-500/5 transition-all duration-500 ease-out"
              style="width: {progress.pct || 0}%"
            ></div>
          </div>
        {/if}

        <div class="relative flex items-center gap-4 p-4 md:p-5">
          <!-- Status icon -->
          <div class="shrink-0 w-11 h-11 rounded-xl flex items-center justify-center text-lg {status.bgClass} transition-all duration-300">
            {#if session.state === 'processing'}
              <div class="animate-spin-slow">{status.icon}</div>
            {:else}
              {status.icon}
            {/if}
          </div>

          <!-- File info -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="text-sm font-semibold text-slate-200 truncate" title={session.filename}>
                {truncateFilename(session.filename)}
              </span>
              {#if session.size_mb}
                <span class="text-xs text-slate-500 shrink-0">{session.size_mb} MB</span>
              {/if}
            </div>

            <div class="flex items-center gap-3">
              <!-- Status badge -->
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold {status.bgClass} {status.textClass} border {status.borderClass}">
                {#if session.state === 'processing'}
                  <span class="relative flex h-1.5 w-1.5">
                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                    <span class="relative inline-flex rounded-full h-1.5 w-1.5 bg-blue-400"></span>
                  </span>
                {/if}
                {status.label}
              </span>

              {#if queuePos}
                <span class="text-xs text-amber-400/80">#{queuePos} in queue</span>
              {/if}

              <!-- Live detail for processing -->
              {#if session.state === 'processing' && progress}
                <span class="text-xs text-slate-400 truncate hidden sm:inline">{progress.detail}</span>
              {/if}

              <span class="text-xs text-slate-600">{formatTime(session.created_at)}</span>
            </div>

            <!-- Progress bar for processing -->
            {#if session.state === 'processing' && progress && progress.stage === 'transcribe'}
              <div class="mt-3 flex items-center gap-3">
                <div class="flex-1 bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-700/50">
                  <div class="bg-gradient-to-r from-blue-400 to-indigo-500 h-1.5 rounded-full transition-all duration-500 ease-out" style="width: {progress.pct}%"></div>
                </div>
                <span class="text-xs font-bold text-blue-400 shrink-0 w-10 text-right">{progress.pct}%</span>
              </div>
            {/if}

            <!-- Error message -->
            {#if session.state === 'failed' && session.error_message}
              <p class="mt-2 text-xs text-red-400/80 truncate" title={session.error_message}>{session.error_message}</p>
            {/if}
          </div>

          <!-- Action button -->
          <div class="shrink-0">
            {#if session.state === 'completed'}
              <a
                href="{API_BASE}/api/sessions/{session.id}/transcript"
                download
                class="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white text-sm font-bold rounded-xl transition-all shadow-lg shadow-emerald-500/20 hover:shadow-emerald-500/30 hover:scale-105 active:scale-95"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" /></svg>
                <span class="hidden sm:inline">.srt</span>
              </a>
            {:else if session.state === 'processing'}
              <div class="w-10 h-10 flex items-center justify-center">
                <svg class="w-5 h-5 text-blue-400 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </div>
            {:else if session.state === 'queued'}
              <div class="w-10 h-10 flex items-center justify-center">
                <div class="w-2.5 h-2.5 rounded-full bg-amber-400/60 animate-pulse"></div>
              </div>
            {/if}
          </div>
        </div>
      </div>
    {/each}
  </div>
</div>

<style>
  @keyframes spin-slow {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
  :global(.animate-spin-slow) {
    animation: spin-slow 3s linear infinite;
  }
</style>
