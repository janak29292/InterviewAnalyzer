<script>
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  export let sessionId;
  
  const dispatch = createEventDispatcher();
  
  let ws;
  let currentStage = 'extract'; // 'extract' | 'transcribe'
  let pct = 0;
  let detailText = 'Connecting to server...';
  let failure = '';

  const stages = [
    { id: 'extract', label: 'Extract Audio', icon: '🎵' },
    { id: 'transcribe', label: 'Transcribe Speech', icon: '📝' },
    { id: 'complete', label: 'Done', icon: '✅' }
  ];

  function getStageIndex(stageId) {
    return stages.findIndex(s => s.id === stageId) === -1 ? 0 : stages.findIndex(s => s.id === stageId);
  }

  onMount(async () => {
    try {
      // 1. Fetch current status from the Database first!
      const res = await fetch(`http://localhost:8002/api/sessions/${sessionId}`);
      if (res.ok) {
        const sessionData = await res.json();
        
        // If it's already finished in the DB, jump straight to the end
        if (sessionData.state === 'COMPLETED') {
            currentStage = 'complete';
            pct = 100;
            detailText = 'Transcription finished!';
            setTimeout(() => { dispatch('complete'); }, 800);
            return; // Don't even connect WebSocket
        } else if (sessionData.state === 'FAILED') {
            failure = sessionData.error_message || 'Pipeline failed during processing.';
            return;
        }
      }
    } catch (err) {
      console.warn("Failed to retrieve session from database", err);
    }
    
    // 2. If it's still UPLOADED or PROCESSING, connect WS to listen for real-time updates
    connectWS();
  });

  onDestroy(() => {
    if (ws) ws.close();
  });

  function connectWS() {
    detailText = 'Initializing pipeline...';
    try {
      ws = new WebSocket(`ws://localhost:8002/ws/${sessionId}`);
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          if (data.type === 'progress') {
            currentStage = data.stage || 'extract';
            pct = data.pct >= 0 ? data.pct : 0;
            if (data.detail) detailText = data.detail;
          } else if (data.type === 'completed') {
            currentStage = 'complete';
            pct = 100;
            detailText = 'Transcription finished!';
            setTimeout(() => {
              dispatch('complete');
            }, 1000);
          } else if (data.type === 'error') {
            failure = data.error || 'Server error occurred.';
            if (ws) ws.close();
          }
        } catch (e) {
          console.error('WS parse error', e);
        }
      };

      ws.onerror = () => {};
      ws.onclose = () => {};
    } catch (err) {
      failure = 'Failed to connect to progress WebSocket.';
    }
  }
</script>

<div class="w-full flex flex-col items-center">
  {#if failure}
      <div class="w-full bg-red-900/40 border border-red-500/50 text-red-200 px-6 py-4 rounded-xl mb-6">
        <h3 class="font-bold mb-1 text-lg">Processing Failed</h3>
        <p>{failure}</p>
        <button class="mt-4 px-4 py-2 bg-red-500/20 hover:bg-red-500/40 border border-red-500 border-opacity-50 rounded-lg transition-colors" on:click={() => location.reload()}>
          Try Again
        </button>
      </div>
  {:else}
    <div class="relative w-32 h-32 mb-8 flex justify-center items-center">
      <div class="absolute inset-0 rounded-full border-[6px] border-slate-700"></div>
      <div class="absolute inset-0 rounded-full border-[6px] border-indigo-500 border-t-transparent animate-spin"></div>
      <div class="text-3xl animate-pulse">
        {stages[getStageIndex(currentStage)]?.icon || '⏳'}
      </div>
    </div>
    
    <h2 class="text-2xl font-bold text-slate-100 mb-2">{detailText}</h2>
    
    <div class="w-full max-w-lg mt-8">
      <div class="flex justify-between items-center mb-10 px-4 relative">
        <div class="absolute left-8 right-8 top-1/2 -z-10 h-1 bg-slate-700 -translate-y-1/2 rounded"></div>
        {#each stages as stage, i}
          {@const isActive = getStageIndex(currentStage) === i}
          {@const isDone = getStageIndex(currentStage) > i}
          <div class="flex flex-col items-center gap-2 relative">
            <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm transition-all duration-300 {isDone ? 'bg-indigo-500 text-white shadow-[0_0_15px_rgba(99,102,241,0.5)]' : isActive ? 'bg-slate-800 border-2 border-indigo-400 text-indigo-400 shadow-[0_0_15px_rgba(99,102,241,0.3)]' : 'bg-slate-800 border border-slate-600 text-slate-500'}">
              {isDone ? '✓' : i + 1}
            </div>
            <span class="text-xs font-semibold whitespace-nowrap absolute -bottom-6 {isActive ? 'text-indigo-400' : isDone ? 'text-slate-300' : 'text-slate-500'}">
              {stage.label}
            </span>
          </div>
        {/each}
      </div>

      {#if currentStage === 'transcribe'}
        <div class="bg-slate-800/80 border border-slate-700 p-5 rounded-2xl animate-fade-in-up">
           <div class="flex justify-between text-sm mb-2">
             <span class="text-slate-400 font-medium tracking-wide text-xs uppercase">Transcription Progress</span>
             <span class="text-indigo-300 font-bold">{pct.toFixed(1)}%</span>
           </div>
           <div class="w-full bg-slate-900 rounded-full h-2 overflow-hidden border border-slate-700">
             <div class="bg-gradient-to-r from-blue-400 to-indigo-500 h-2 transition-all duration-300 ease-out" style="width: {pct}%"></div>
           </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
