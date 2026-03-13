/**
 * Interview Video Analyzer — Frontend Application
 * Handles upload, progress polling, and result rendering
 */

// ─── State ───────────────────────────────────────────────────
let currentJobId = null;
let pollInterval = null;

// ─── DOM Refs ────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const uploadSection = $('upload-section');
const progressSection = $('progress-section');
const resultsSection = $('results-section');
const errorBanner = $('error-banner');
const uploadZone = $('upload-zone');
const fileInput = $('file-input');
const browseBtn = $('browse-btn');

const progressFilename = $('progress-filename');
const progressFilesize = $('progress-filesize');
const uploadProgress = $('upload-progress');
const uploadLabel = $('upload-label');
const uploadPercent = $('upload-percent');
const uploadFill = $('upload-fill');
const analysisSpinner = $('analysis-spinner');
const spinnerText = $('spinner-text');
const spinnerSub = $('spinner-sub');

// Step indicators
const steps = {
    upload: $('step-upload'),
    extract: $('step-extract'),
    transcribe: $('step-transcribe'),
    frames: $('step-frames'),
    analyze: $('step-analyze'),
};

// ─── Utilities ───────────────────────────────────────────────
function showSection(section) {
    [uploadSection, progressSection, resultsSection].forEach(s => {
        s.classList.remove('active');
        s.style.display = '';
    });
    if (section === progressSection || section === resultsSection) {
        uploadSection.style.display = 'none';
    }
    section.classList.add('active');
}

function showError(msg) {
    errorBanner.textContent = msg;
    errorBanner.classList.add('active');
    setTimeout(() => errorBanner.classList.remove('active'), 10000);
}

function hideError() { errorBanner.classList.remove('active'); }

function formatSize(bytes) {
    const mb = bytes / (1024 * 1024);
    return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`;
}

function getScoreColor(score) {
    if (score >= 85) return 'var(--score-excellent)';
    if (score >= 70) return 'var(--score-good)';
    if (score >= 55) return 'var(--score-average)';
    if (score >= 40) return 'var(--score-poor)';
    return 'var(--score-bad)';
}

function getScoreClass(score) {
    if (score >= 85) return 'score-excellent';
    if (score >= 70) return 'score-good';
    if (score >= 55) return 'score-average';
    if (score >= 40) return 'score-poor';
    return 'score-bad';
}

function setStep(name, status) {
    const el = steps[name];
    if (!el) return;
    el.classList.remove('active', 'done');
    if (status) el.classList.add(status);
}

// Map backend stage names to step names
const stageToStep = {
    'upload': 'upload',
    'extract': 'extract',
    'transcribe': 'transcribe',
    'fluency': 'transcribe',
    'frames': 'frames',
    'analyze': 'analyze',
    'pipeline': null, // overall pipeline stage
};

const stageOrder = ['upload', 'extract', 'transcribe', 'frames', 'analyze'];

function updateStepsFromStage(stage) {
    const currentStep = stageToStep[stage];
    if (!currentStep && stage !== 'pipeline') return;

    const idx = currentStep ? stageOrder.indexOf(currentStep) : -1;

    stageOrder.forEach((name, i) => {
        if (i < idx) setStep(name, 'done');
        else if (i === idx) setStep(name, 'active');
        else setStep(name, null);
    });
}

// ─── Upload Handlers ─────────────────────────────────────────
uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
});

uploadZone.addEventListener('click', (e) => {
    if (e.target !== browseBtn && !browseBtn.contains(e.target)) fileInput.click();
});

browseBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
});

// ─── Main Flow ───────────────────────────────────────────────
async function handleFile(file) {
    if (!file.type.startsWith('video/')) {
        showError('Please select a video file (MP4, WebM, MOV, AVI, MKV).');
        return;
    }
    if (file.size > 2 * 1024 * 1024 * 1024) {
        showError('File too large. Maximum size is 2 GB.');
        return;
    }

    hideError();

    // Setup progress UI
    progressFilename.textContent = file.name;
    progressFilesize.textContent = formatSize(file.size);
    uploadProgress.style.display = '';
    uploadLabel.textContent = 'Uploading to server...';
    uploadFill.style.width = '0%';
    uploadPercent.textContent = '0%';
    analysisSpinner.classList.remove('active');

    setStep('upload', 'active');
    setStep('extract', null);
    setStep('transcribe', null);
    setStep('frames', null);
    setStep('analyze', null);

    showSection(progressSection);

    try {
        // Upload
        const jobId = await uploadFile(file);
        currentJobId = jobId;

        // Switch to analysis spinner
        setStep('upload', 'done');
        uploadProgress.style.display = 'none';
        analysisSpinner.classList.add('active');
        spinnerText.textContent = 'Starting analysis pipeline...';
        spinnerSub.textContent = 'This may take 10-30 minutes for longer videos';

        // Start polling progress
        startPolling(jobId);

    } catch (err) {
        showError(err.message || 'Upload failed. Please try again.');
        showSection(uploadSection);
    }
}

function uploadFile(file) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        formData.append('file', file);
        const xhr = new XMLHttpRequest();

        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                uploadFill.style.width = pct + '%';
                uploadPercent.textContent = pct + '%';
                if (pct >= 100) {
                    uploadLabel.textContent = 'Processing upload...';
                    uploadPercent.textContent = 'Done';
                }
            }
        });

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                const data = JSON.parse(xhr.responseText);
                resolve(data.job_id);
            } else {
                try { reject(new Error(JSON.parse(xhr.responseText).detail)); }
                catch { reject(new Error(`Upload failed (HTTP ${xhr.status})`)); }
            }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
        xhr.open('POST', '/api/upload');
        xhr.send(formData);
    });
}

// ─── Progress Polling ────────────────────────────────────────
function startPolling(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/progress/${jobId}`);
            const data = await res.json();

            // Update spinner text
            spinnerText.textContent = data.detail || 'Processing...';

            // Update steps
            updateStepsFromStage(data.stage);

            // Update subtitle based on stage
            const stageLabels = {
                extract: 'Extracting audio from video with FFmpeg',
                transcribe: 'Transcribing speech with Whisper (runs locally)',
                fluency: 'Analyzing speech fluency patterns',
                frames: 'Extracting and deduplicating screen frames',
                analyze: 'Sending to Gemini AI for comprehensive analysis',
                pipeline: 'Running analysis pipeline...',
            };
            spinnerSub.textContent = stageLabels[data.stage] || '';

            if (data.status === 'complete') {
                clearInterval(pollInterval);
                pollInterval = null;

                // Mark all steps done
                stageOrder.forEach(s => setStep(s, 'done'));
                analysisSpinner.classList.remove('active');

                renderResults(data.result);
            } else if (data.status === 'error') {
                clearInterval(pollInterval);
                pollInterval = null;
                showError(data.error || 'Analysis failed.');
                showSection(uploadSection);
            }

        } catch (err) {
            // Silently retry on network errors
            console.error('Poll error:', err);
        }
    }, 2000); // poll every 2 seconds
}

// ─── Render Results ──────────────────────────────────────────
function renderResults(data) {
    // Handle raw/unparsed analysis
    if (data.raw_analysis && !data.coding_quality) {
        renderRawResults(data);
        showSection(resultsSection);
        return;
    }

    // Overall score
    const score = data.overall_score || 0;
    $('overall-score').textContent = score;
    $('overall-score').style.color = getScoreColor(score);
    $('overall-summary').textContent = data.overall_summary || '';

    // Animate score ring
    const circumference = 2 * Math.PI * 70;
    const offset = circumference - (score / 100) * circumference;
    const ring = $('score-ring');
    ring.style.stroke = getScoreColor(score);
    setTimeout(() => { ring.style.strokeDashoffset = offset; }, 100);

    // Verdict
    const readiness = data.interview_readiness || {};
    const verdict = $('overall-verdict');
    verdict.textContent = `🎯 ${readiness.verdict || 'N/A'}`;
    verdict.style.background = `color-mix(in srgb, ${getScoreColor(readiness.score || score)} 12%, transparent)`;
    verdict.style.color = getScoreColor(readiness.score || score);

    // Local metrics bar
    renderMetricsBar(data._local_metrics || {});

    // Category cards
    renderCategoryCards(data);

    // Strengths & Improvements
    renderStrengthsImprovements(data);

    // Question breakdown
    renderQuestions(data.question_breakdown || []);

    // Readiness
    renderReadiness(readiness);

    showSection(resultsSection);
}

function renderRawResults(data) {
    $('overall-score').textContent = '—';
    $('overall-summary').textContent = data.overall_summary || 'Analysis completed. See raw output below.';
    $('cards-grid').innerHTML = `<div class="card" style="grid-column: 1/-1;"><pre style="white-space:pre-wrap;color:var(--text-secondary);font-size:0.85rem;">${data.raw_analysis || ''}</pre></div>`;
    $('strengths-improvements').innerHTML = '';
    $('questions-section').style.display = 'none';
    $('readiness-section').innerHTML = '';
    $('metrics-bar').innerHTML = '';
}

function renderMetricsBar(metrics) {
    const bar = $('metrics-bar');
    if (!metrics || !metrics.fluency) { bar.innerHTML = ''; return; }

    const f = metrics.fluency;
    bar.innerHTML = `
    <div class="metric-chip">
      <span class="metric-chip__icon">⏱️</span>
      <span class="metric-chip__label">Duration</span>
      <span class="metric-chip__value">${f.total_duration_formatted || '0:00'}</span>
    </div>
    <div class="metric-chip">
      <span class="metric-chip__icon">💬</span>
      <span class="metric-chip__label">Words</span>
      <span class="metric-chip__value">${(f.total_words || 0).toLocaleString()}</span>
    </div>
    <div class="metric-chip">
      <span class="metric-chip__icon">🏃</span>
      <span class="metric-chip__label">Pace</span>
      <span class="metric-chip__value">${f.overall_wpm || 0} wpm</span>
    </div>
    <div class="metric-chip">
      <span class="metric-chip__icon">🔇</span>
      <span class="metric-chip__label">Fillers</span>
      <span class="metric-chip__value">${f.filler_words?.total_count || 0} (${f.filler_words?.per_minute || 0}/min)</span>
    </div>
    <div class="metric-chip">
      <span class="metric-chip__icon">⏸️</span>
      <span class="metric-chip__label">Long Pauses</span>
      <span class="metric-chip__value">${f.pauses?.count || 0}</span>
    </div>
    <div class="metric-chip">
      <span class="metric-chip__icon">🖼️</span>
      <span class="metric-chip__label">Frames</span>
      <span class="metric-chip__value">${metrics.unique_frames_kept || 0} unique / ${metrics.total_raw_frames || 0}</span>
    </div>
  `;
}

function renderCategoryCards(data) {
    const grid = $('cards-grid');
    grid.innerHTML = '';

    const categories = [
        {
            key: 'coding_quality', icon: '💻', title: 'Code Quality',
            details: ['code_correctness', 'code_cleanliness', 'efficiency', 'debugging_skills'],
            labels: { code_correctness: 'Correctness', code_cleanliness: 'Cleanliness', efficiency: 'Efficiency', debugging_skills: 'Debugging' }
        },
        {
            key: 'problem_solving', icon: '🧩', title: 'Problem Solving',
            details: ['approach', 'clarifying_questions', 'edge_cases', 'time_management'],
            labels: { approach: 'Approach', clarifying_questions: 'Clarifying Q\'s', edge_cases: 'Edge Cases', time_management: 'Time Mgmt' }
        },
        {
            key: 'communication', icon: '🗣️', title: 'Communication',
            details: ['think_aloud', 'clarity', 'technical_vocabulary', 'interaction_with_interviewer'],
            labels: { think_aloud: 'Think Aloud', clarity: 'Clarity', technical_vocabulary: 'Tech Vocab', interaction_with_interviewer: 'Interaction' }
        },
        {
            key: 'speech_fluency', icon: '🎙️', title: 'Speech Fluency',
            details: ['overall_assessment', 'filler_word_impact', 'pause_analysis', 'confidence_from_voice'],
            labels: { overall_assessment: 'Overall', filler_word_impact: 'Fillers Impact', pause_analysis: 'Pauses', confidence_from_voice: 'Confidence' }
        },
    ];

    categories.forEach((cat, idx) => {
        const catData = data[cat.key] || {};
        const score = catData.score || 0;
        const suggestions = catData.suggestions || [];

        const card = document.createElement('div');
        card.className = 'card animate-in';
        card.style.animationDelay = `${idx * 0.1}s`;

        let detailsHTML = cat.details.map(d => `
      <div class="card__detail">
        <span class="card__detail-label">${cat.labels[d]}</span>
        <span class="card__detail-value">${catData[d] || 'N/A'}</span>
      </div>
    `).join('');

        let suggestionsHTML = '';
        if (suggestions.length > 0) {
            suggestionsHTML = `
        <div class="card__suggestions">
          <p class="card__suggestion-title">Suggestions</p>
          <ul class="card__suggestion-list">
            ${suggestions.map(s => `<li class="card__suggestion-item">${s}</li>`).join('')}
          </ul>
        </div>`;
        }

        card.innerHTML = `
      <div class="card__header">
        <div class="card__title-group">
          <span class="card__icon">${cat.icon}</span>
          <span class="card__title">${cat.title}</span>
        </div>
        <span class="card__score ${getScoreClass(score)}">${score}</span>
      </div>
      <div class="card__details">${detailsHTML}</div>
      ${suggestionsHTML}
    `;

        grid.appendChild(card);
    });
}

function renderStrengthsImprovements(data) {
    const container = $('strengths-improvements');
    container.innerHTML = '';

    const strengths = data.top_strengths || [];
    const improvements = data.areas_for_improvement || [];

    const strengthsPanel = document.createElement('div');
    strengthsPanel.className = 'panel animate-in';
    strengthsPanel.innerHTML = `
    <h3 class="panel__title">💚 Top Strengths</h3>
    ${strengths.map(s => `<div class="strength-item">${s}</div>`).join('')}
  `;

    const improvementsPanel = document.createElement('div');
    improvementsPanel.className = 'panel animate-in';
    improvementsPanel.innerHTML = `
    <h3 class="panel__title">🔧 Areas for Improvement</h3>
    ${improvements.map(imp => `
      <div class="improvement-item">
        <div class="improvement-item__header">
          <span class="improvement-item__area">${imp.area || ''}</span>
          <span class="improvement-item__priority ${(imp.priority || '').toLowerCase()}">${(imp.priority || '').toUpperCase()}</span>
        </div>
        <p class="improvement-item__detail"><strong>Current:</strong> ${imp.current_behavior || ''}</p>
        <p class="improvement-item__detail"><strong>Action:</strong> ${imp.recommended_action || ''}</p>
      </div>
    `).join('')}
  `;

    container.appendChild(strengthsPanel);
    container.appendChild(improvementsPanel);
}

function renderQuestions(questions) {
    const section = $('questions-section');
    const list = $('questions-list');
    list.innerHTML = '';

    if (!questions.length) { section.style.display = 'none'; return; }
    section.style.display = '';

    questions.forEach((q, idx) => {
        const score = q.score || 0;
        const card = document.createElement('div');
        card.className = 'question-card';

        card.innerHTML = `
      <div class="question-card__header">
        <div class="question-card__left">
          <span class="question-card__number">${q.question_number || idx + 1}</span>
          <span class="question-card__topic">${q.question_topic || 'Question ' + (idx + 1)}</span>
          <span class="question-card__timestamp">${q.approximate_timestamp || ''}</span>
        </div>
        <span class="question-card__score ${getScoreClass(score)}">${score}</span>
        <span class="question-card__toggle">▼</span>
      </div>
      <div class="question-card__body">
        <div class="question-card__feedback">
          <div class="feedback-block feedback-block--good">
            <p class="feedback-block__title">✅ What Went Well</p>
            <p class="feedback-block__text">${q.what_went_well || 'N/A'}</p>
          </div>
          <div class="feedback-block feedback-block--improve">
            <p class="feedback-block__title">🔶 What to Improve</p>
            <p class="feedback-block__text">${q.what_to_improve || 'N/A'}</p>
          </div>
        </div>
        ${q.approach_used ? `
          <div class="question-card__approach" style="margin-top:12px;">
            <p class="question-card__approach-title">🔍 Approach Used</p>
            <p class="question-card__approach-text">${q.approach_used}</p>
          </div>` : ''}
        ${q.code_feedback ? `
          <div class="question-card__approach" style="margin-top:12px;">
            <p class="question-card__approach-title">💻 Code Feedback</p>
            <p class="question-card__approach-text">${q.code_feedback}</p>
          </div>` : ''}
        ${q.suggested_approach ? `
          <div class="question-card__approach" style="margin-top:12px;">
            <p class="question-card__approach-title">💡 Better Approach</p>
            <p class="question-card__approach-text">${q.suggested_approach}</p>
          </div>` : ''}
      </div>
    `;

        card.querySelector('.question-card__header').addEventListener('click', () => {
            card.classList.toggle('open');
        });

        list.appendChild(card);
    });
}

function renderReadiness(readiness) {
    const section = $('readiness-section');
    const score = readiness.score || 0;
    const st = readiness.next_steps || [];

    section.innerHTML = `
    <p class="readiness__score ${getScoreClass(score)}">${score}/100</p>
    <p class="readiness__verdict">Interview Readiness: <strong>${readiness.verdict || 'N/A'}</strong></p>
    ${st.length ? `
      <p class="readiness__steps-title">Your Next Steps</p>
      <div class="readiness__steps">
        ${st.map((s, i) => `
          <div class="readiness__step">
            <span class="readiness__step-num">${i + 1}</span>
            <span>${s}</span>
          </div>
        `).join('')}
      </div>
    ` : ''}
  `;
}

// ─── New Analysis ────────────────────────────────────────────
$('new-analysis-btn').addEventListener('click', () => {
    currentJobId = null;
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    fileInput.value = '';
    showSection(uploadSection);
    hideError();
});
