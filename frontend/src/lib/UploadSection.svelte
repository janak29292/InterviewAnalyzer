<script>
  const { onUploadSuccess } = $props();

  const API_BASE = 'http://localhost:8002';

  let fileInput = $state(null);
  let isDragging = $state(false);
  let uploads = $state([]); // { id, file, progress, status, error }
  let errorMessage = $state('');

  function handleDrop(e) {
    e.preventDefault();
    isDragging = false;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  }

  function handleFileSelect(e) {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files));
      // Reset input so re-selecting the same files triggers change
      e.target.value = '';
    }
  }

  function addFiles(files) {
    errorMessage = '';
    const validFiles = [];

    for (const file of files) {
      if (!file.type.startsWith('video/')) {
        errorMessage = `Skipped "${file.name}" — not a video file.`;
        continue;
      }
      validFiles.push(file);
    }

    // Upload each valid file in parallel
    for (const file of validFiles) {
      uploadFile(file);
    }
  }

  function uploadFile(file) {
    const uploadId = crypto.randomUUID();
    const entry = { id: uploadId, file, progress: 0, status: 'uploading', error: '' };
    uploads = [...uploads, entry];

    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        uploads = uploads.map(u => u.id === uploadId ? { ...u, progress: pct } : u);
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        uploads = uploads.map(u => u.id === uploadId ? { ...u, status: 'done', progress: 100 } : u);
        // Remove from upload list after brief delay
        setTimeout(() => {
          uploads = uploads.filter(u => u.id !== uploadId);
        }, 1500);
        onUploadSuccess?.();
      } else {
        let errMsg = `Upload failed (HTTP ${xhr.status})`;
        try {
          const err = JSON.parse(xhr.responseText);
          errMsg = err.detail || errMsg;
        } catch {}
        uploads = uploads.map(u => u.id === uploadId ? { ...u, status: 'error', error: errMsg } : u);
      }
    });

    xhr.addEventListener('error', () => {
      uploads = uploads.map(u => u.id === uploadId ? { ...u, status: 'error', error: 'Network error' } : u);
    });

    xhr.open('POST', `${API_BASE}/api/upload`);
    xhr.send(formData);
  }

  function dismissUpload(uploadId) {
    uploads = uploads.filter(u => u.id !== uploadId);
  }

  function formatFileSize(bytes) {
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
    return `${(bytes / 1024).toFixed(0)} KB`;
  }
</script>

<div class="flex flex-col items-center justify-center w-full">
  {#if errorMessage}
    <div class="w-full bg-amber-900/40 border border-amber-500/50 text-amber-200 px-4 py-3 rounded-xl mb-5 flex items-center gap-3 text-sm">
      <svg class="w-5 h-5 text-amber-400 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>
      <span>{errorMessage}</span>
    </div>
  {/if}

  <!-- Drop zone — always visible -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div 
    class="w-full flex flex-col items-center justify-center h-52 border-2 border-dashed rounded-3xl cursor-pointer transition-all duration-300 ease-in-out hover:bg-slate-800/80 hover:border-indigo-500 hover:shadow-[0_0_20px_rgba(99,102,241,0.2)] {isDragging ? 'bg-slate-800/80 border-indigo-500 shadow-[0_0_30px_rgba(99,102,241,0.3)] scale-[1.02]' : 'border-slate-600 bg-slate-800/30'}"
    ondragenter={(e) => { e.preventDefault(); isDragging = true; }}
    ondragleave={(e) => { e.preventDefault(); isDragging = false; }}
    ondragover={(e) => e.preventDefault()}
    ondrop={handleDrop}
    onclick={() => fileInput?.click()}
    onkeydown={(e) => e.key === 'Enter' && fileInput?.click()}
  >
    <input 
      type="file" 
      class="hidden" 
      accept="video/*" 
      multiple
      bind:this={fileInput}
      onchange={handleFileSelect}
    />
    <div class="p-4 bg-indigo-500/20 rounded-2xl mb-3 transition-transform">
      <svg class="w-9 h-9 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" /></svg>
    </div>
    <p class="mb-1 text-lg font-semibold text-slate-200">
      Drop videos here or click to browse
    </p>
    <p class="text-sm text-slate-500 font-medium">MP4, WebM, MOV, AVI, MKV — Multiple files supported</p>
  </div>

  <!-- Active uploads progress -->
  {#if uploads.length > 0}
    <div class="w-full mt-5 space-y-3">
      {#each uploads as upload (upload.id)}
        <div class="flex items-center gap-4 p-4 bg-slate-800/60 border border-slate-700/50 rounded-2xl transition-all duration-300">
          <!-- File icon -->
          <div class="shrink-0 w-10 h-10 flex items-center justify-center rounded-xl {upload.status === 'error' ? 'bg-red-500/20' : upload.status === 'done' ? 'bg-emerald-500/20' : 'bg-indigo-500/20'}">
            {#if upload.status === 'error'}
              <svg class="w-5 h-5 text-red-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
            {:else if upload.status === 'done'}
              <svg class="w-5 h-5 text-emerald-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" /></svg>
            {:else}
              <svg class="w-5 h-5 text-indigo-400 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            {/if}
          </div>

          <!-- File info & progress bar -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between mb-1">
              <span class="text-sm text-slate-200 font-medium truncate mr-4">{upload.file.name}</span>
              <span class="text-xs text-slate-500 shrink-0">
                {formatFileSize(upload.file.size)}
              </span>
            </div>
            {#if upload.status === 'uploading'}
              <div class="w-full bg-slate-900 rounded-full h-1.5 overflow-hidden border border-slate-700/50">
                <div class="bg-gradient-to-r from-indigo-500 to-purple-500 h-1.5 rounded-full transition-all duration-300 ease-out" style="width: {upload.progress}%"></div>
              </div>
            {:else if upload.status === 'error'}
              <p class="text-xs text-red-400">{upload.error}</p>
            {:else if upload.status === 'done'}
              <p class="text-xs text-emerald-400">Queued for transcription</p>
            {/if}
          </div>

          <!-- Progress / dismiss -->
          <div class="shrink-0">
            {#if upload.status === 'uploading'}
              <span class="text-sm font-bold text-indigo-400">{upload.progress}%</span>
            {:else if upload.status === 'error'}
              <button onclick={() => dismissUpload(upload.id)} class="text-slate-500 hover:text-slate-300 transition-colors p-1" aria-label="Dismiss error">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
              </button>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
