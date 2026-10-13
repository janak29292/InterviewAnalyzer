<script>
  import { onMount, onDestroy } from 'svelte';
  import UploadSection from './lib/UploadSection.svelte';
  import QueueDashboard from './lib/QueueDashboard.svelte';

  const API_BASE = 'http://localhost:8002';

  let sessions = $state([]);
  let pollInterval = null;

  async function fetchSessions() {
    try {
      const res = await fetch(`${API_BASE}/api/sessions`);
      if (res.ok) {
        const data = await res.json();
        sessions = data.sessions;
      }
    } catch (err) {
      console.warn('Failed to fetch sessions:', err);
    }
  }

  function handleUploadSuccess() {
    // Immediately refresh session list after an upload completes
    fetchSessions();
  }

  onMount(() => {
    fetchSessions();
    pollInterval = setInterval(fetchSessions, 3000);
  });

  onDestroy(() => {
    if (pollInterval) clearInterval(pollInterval);
  });
</script>

<main class="w-full max-w-5xl mx-auto p-4 md:p-8 min-h-screen flex flex-col items-center">
  <div class="mb-10 text-center animate-fade-in-down w-full pt-8">
    <h1 class="text-5xl md:text-6xl mb-4 font-black tracking-tight drop-shadow-sm">
      <span>🎬</span> <span class="bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400">Video Transcriber</span>
    </h1>
    <p class="text-slate-400 text-lg max-w-2xl mx-auto font-medium">
      Upload videos to extract audio and generate transcripts automatically.
    </p>
  </div>

  <!-- Upload Area -->
  <div class="w-full bg-slate-800/40 backdrop-blur-xl border border-slate-700/50 rounded-3xl md:p-10 shadow-2xl p-6 ring-1 ring-white/10 animate-fade-in-up mb-8">
    <UploadSection onUploadSuccess={handleUploadSuccess} />
  </div>

  <!-- Queue Dashboard -->
  {#if sessions.length > 0}
    <div class="w-full bg-slate-800/40 backdrop-blur-xl border border-slate-700/50 rounded-3xl md:p-10 shadow-2xl p-6 ring-1 ring-white/10 animate-fade-in-up">
      <QueueDashboard {sessions} />
    </div>
  {/if}
</main>

<style>
  @keyframes fade-in-down {
    0% { opacity: 0; transform: translateY(-20px); }
    100% { opacity: 1; transform: translateY(0); }
  }
  @keyframes fade-in-up {
    0% { opacity: 0; transform: translateY(20px); }
    100% { opacity: 1; transform: translateY(0); }
  }
  :global(.animate-fade-in-down) {
    animation: fade-in-down 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }
  :global(.animate-fade-in-up) {
    animation: fade-in-up 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }
</style>
