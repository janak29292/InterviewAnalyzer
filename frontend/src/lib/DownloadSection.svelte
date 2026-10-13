<script>
  import { createEventDispatcher } from 'svelte';
  export let sessionId;
  const dispatch = createEventDispatcher();
  
  const downloadUrl = `http://localhost:8002/api/sessions/${sessionId}/transcript`;
</script>

<div class="w-full flex flex-col items-center justify-center py-8">
  <div class="w-24 h-24 bg-emerald-500/20 text-emerald-400 border-[6px] border-emerald-500/30 rounded-full flex items-center justify-center mb-6 shadow-[0_0_30px_rgba(16,185,129,0.2)] animate-fade-in-down">
    <svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7" />
    </svg>
  </div>
  
  <h2 class="text-3xl font-extrabold text-white mb-3">Transcription Complete!</h2>
  <p class="text-slate-400 mb-8 max-w-md text-center">
    We've successfully extracted the audio and transcribed your session.
  </p>

  <div class="flex flex-col sm:flex-row gap-4 w-full justify-center">
    <a 
      href={downloadUrl} 
      download
      class="flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-500 to-blue-500 hover:from-indigo-600 hover:to-blue-600 text-white font-bold py-3 px-8 rounded-xl transition-all shadow-[0_0_20px_rgba(99,102,241,0.25)] hover:shadow-[0_0_30px_rgba(99,102,241,0.4)]"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
      </svg>
      Download .srt File
    </a>
    
    <button 
      on:click={() => dispatch('reset')}
      class="flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold py-3 px-8 rounded-xl transition-colors border border-slate-600"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
      Analyze Another
    </button>
  </div>
</div>
