const API_BASE = window.location.origin;
let activeCharts = [];
let chatHistory = [];
let queryCount = 0;
let totalQueryTime = 0;
let bookmarks = JSON.parse(localStorage.getItem("datachat_bookmarks") || "[]");
let currentTheme = localStorage.getItem("datachat_theme") || "dark";
let recognition = null;
let isRecording = false;
let currentSpeech = null;

// ── Session Management ──
let sessionId = localStorage.getItem("datachat_session_id");
if (!sessionId) {
    sessionId = "s_" + crypto.randomUUID().replace(/-/g, "").substring(0, 16);
    localStorage.setItem("datachat_session_id", sessionId);
}

document.addEventListener("DOMContentLoaded", () => {
    applyTheme(currentTheme);
    initParticleBackground();
    initTabs();
    initChat();
    initUpload();
    initKeyboardShortcuts();
    initThemeToggle();
    initVoiceInput();
    initBookmarks();
    initSessionDisplay();
    loadDatasetInfo();
    loadSchema();
    loadExamples();
    loadAnalytics();
    loadDataQuality();
});

function initSessionDisplay() {
    const badge = document.getElementById("session-id-display");
    if (badge) {
        badge.textContent = sessionId.substring(0, 10) + "...";
        badge.parentElement.title = "Session: " + sessionId;
    }
}

// ── Theme Toggle ──
function initThemeToggle() {
    document.getElementById("theme-toggle").addEventListener("click", () => {
        currentTheme = currentTheme === "dark" ? "light" : "dark";
        applyTheme(currentTheme);
        localStorage.setItem("datachat_theme", currentTheme);
        // Re-render active charts with updated theme colors
        activeCharts.forEach(chart => {
            if (chart && chart.canvas) {
                const theme = getChartThemeColors();
                const opts = chart.options;
                if (opts.plugins?.legend?.labels) opts.plugins.legend.labels.color = theme.textColor;
                if (opts.plugins?.tooltip) {
                    opts.plugins.tooltip.backgroundColor = theme.bgCard;
                    opts.plugins.tooltip.titleColor = theme.textPrimary;
                    opts.plugins.tooltip.bodyColor = theme.textColor;
                    opts.plugins.tooltip.borderColor = theme.borderColor;
                }
                if (opts.scales?.x?.ticks) opts.scales.x.ticks.color = theme.textColor;
                if (opts.scales?.x?.grid) opts.scales.x.grid.color = theme.gridColor;
                if (opts.scales?.y?.ticks) opts.scales.y.ticks.color = theme.textColor;
                if (opts.scales?.y?.grid) opts.scales.y.grid.color = theme.gridColor;
                if (opts.scales?.r?.ticks) opts.scales.r.ticks.color = theme.textColor;
                if (opts.scales?.r?.grid) opts.scales.r.grid.color = theme.gridColor;
                if (opts.scales?.r?.pointLabels) opts.scales.r.pointLabels.color = theme.textColor;
                chart.update();
            }
        });
    });
}

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const sunIcon = document.getElementById("theme-icon-sun");
    const moonIcon = document.getElementById("theme-icon-moon");
    const label = document.getElementById("theme-label");
    if (theme === "light") {
        sunIcon.style.display = "block";
        moonIcon.style.display = "none";
        label.textContent = "Light";
    } else {
        sunIcon.style.display = "none";
        moonIcon.style.display = "block";
        label.textContent = "Dark";
    }
}

// ── Voice Input (Speech-to-Text) ──
function initVoiceInput() {
    const voiceBtn = document.getElementById("voice-btn");
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    // Check browser support
    if (!SpeechRecognition) {
        voiceBtn.title = "Speech recognition not supported in this browser. Use Chrome or Edge.";
        voiceBtn.style.opacity = "0.4";
        voiceBtn.style.cursor = "not-allowed";
        voiceBtn.addEventListener("click", () => {
            showToast("Voice input requires Chrome, Edge, or Safari. Please switch browsers.", "error");
        });
        return;
    }

    // Check for secure context (HTTPS or localhost) — required for microphone access
    if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
        voiceBtn.title = "Voice input requires HTTPS or localhost";
        voiceBtn.style.opacity = "0.4";
        voiceBtn.style.cursor = "not-allowed";
        voiceBtn.addEventListener("click", () => {
            showToast("Voice input requires a secure connection (HTTPS). Please use HTTPS or localhost.", "error");
        });
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
        let finalTranscript = "";
        let interimTranscript = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const result = event.results[i];
            if (result.isFinal) {
                finalTranscript += result[0].transcript;
            } else {
                interimTranscript += result[0].transcript;
            }
        }
        const transcript = finalTranscript || interimTranscript;
        if (transcript) {
            document.getElementById("chat-input").value = transcript;
            document.getElementById("char-count").textContent = transcript.length;
        }
    };

    recognition.onend = () => {
        isRecording = false;
        voiceBtn.classList.remove("recording");
        voiceBtn.title = "Voice input (speech-to-text)";
        // Auto-submit after a short delay if we have finalized text
        const input = document.getElementById("chat-input");
        if (input.value.trim()) {
            setTimeout(() => {
                if (input.value.trim() && !isRecording) {
                    submitQuestion();
                }
            }, 500);
        }
    };

    recognition.onerror = (event) => {
        isRecording = false;
        voiceBtn.classList.remove("recording");
        voiceBtn.title = "Voice input (speech-to-text)";

        switch (event.error) {
            case "not-allowed":
            case "permission-denied":
                showToast("Microphone access denied. Please allow microphone permission in browser settings and reload.", "error");
                voiceBtn.style.opacity = "0.5";
                break;
            case "no-speech":
                showToast("No speech detected. Please try again.", "info");
                break;
            case "audio-capture":
                showToast("No microphone found. Please connect a microphone and try again.", "error");
                break;
            case "network":
                showToast("Network error during speech recognition. Check your connection.", "error");
                break;
            case "aborted":
                // User cancelled — no notification needed
                break;
            case "service-not-allowed":
                showToast("Speech recognition service unavailable. Try Chrome or Edge browser.", "error");
                break;
            default:
                showToast("Voice input error: " + event.error, "error");
        }
    };

    recognition.onaudiostart = () => {
        voiceBtn.title = "Recording... click to stop";
    };

    voiceBtn.addEventListener("click", async () => {
        if (isRecording) {
            recognition.stop();
            isRecording = false;
            voiceBtn.classList.remove("recording");
            voiceBtn.title = "Voice input (speech-to-text)";
            return;
        }

        // Pre-check microphone permission before starting recognition
        try {
            if (navigator.permissions && navigator.permissions.query) {
                const permResult = await navigator.permissions.query({ name: "microphone" });
                if (permResult.state === "denied") {
                    showToast("Microphone permission denied. Enable it in browser settings (click lock icon in address bar).", "error");
                    return;
                }
            }
        } catch (e) {
            // permissions.query may not support microphone in all browsers — proceed anyway
        }

        try {
            recognition.start();
            isRecording = true;
            voiceBtn.classList.add("recording");
            showToast("Listening... speak your question", "info");
        } catch (e) {
            isRecording = false;
            voiceBtn.classList.remove("recording");
            if (e.name === "NotAllowedError") {
                showToast("Microphone access denied. Allow microphone in browser settings.", "error");
            } else if (e.message && e.message.includes("already started")) {
                // Recognition already running — stop and restart
                recognition.stop();
            } else {
                showToast("Could not start voice input: " + e.message, "error");
            }
        }
    });
}

// ── Text-to-Speech ──
function speakText(text, btn) {
    if (currentSpeech) {
        window.speechSynthesis.cancel();
        currentSpeech = null;
        document.querySelectorAll(".tts-btn.speaking").forEach(b => b.classList.remove("speaking"));
        return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.volume = 1;

    utterance.onend = () => {
        currentSpeech = null;
        btn.classList.remove("speaking");
    };

    utterance.onerror = () => {
        currentSpeech = null;
        btn.classList.remove("speaking");
    };

    currentSpeech = utterance;
    btn.classList.add("speaking");
    window.speechSynthesis.speak(utterance);
}

// ── Bookmarks ──
function initBookmarks() {
    document.getElementById("bookmarks-toggle").addEventListener("click", toggleBookmarks);
    updateBookmarkCount();
    renderBookmarks();
}

function toggleBookmarks() {
    document.getElementById("bookmarks-panel").classList.toggle("active");
}

function addBookmark(question, response, metadata) {
    const bookmark = {
        id: Date.now(),
        question,
        response,
        metadata,
        timestamp: new Date().toISOString(),
    };
    bookmarks.unshift(bookmark);
    localStorage.setItem("datachat_bookmarks", JSON.stringify(bookmarks));
    updateBookmarkCount();
    renderBookmarks();
    showToast("Query saved to bookmarks", "success");
}

function removeBookmark(id) {
    bookmarks = bookmarks.filter(b => b.id !== id);
    localStorage.setItem("datachat_bookmarks", JSON.stringify(bookmarks));
    updateBookmarkCount();
    renderBookmarks();
}

function updateBookmarkCount() {
    document.getElementById("bookmark-count").textContent = bookmarks.length;
    document.getElementById("bookmark-count-header").textContent = bookmarks.length;
}

function renderBookmarks() {
    const list = document.getElementById("bookmarks-list");
    if (bookmarks.length === 0) {
        list.innerHTML = '<div class="empty-state" style="padding:30px"><p class="empty-title">No saved queries</p><p class="empty-subtitle">Bookmark responses to save them here</p></div>';
        return;
    }

    list.innerHTML = bookmarks.map(b => {
        const time = new Date(b.timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
        return `<div class="bookmark-item">
            <div class="bookmark-question">${escapeHtml(truncate(b.question, 60))}</div>
            <div class="bookmark-response">${escapeHtml(truncate(b.response, 100))}</div>
            <div class="bookmark-meta">
                <span class="bookmark-time">${time}</span>
                <div class="bookmark-actions">
                    <button class="bookmark-action-btn" onclick="rerunBookmark(${b.id})">Re-run</button>
                    <button class="bookmark-action-btn delete" onclick="removeBookmark(${b.id})">Remove</button>
                </div>
            </div>
        </div>`;
    }).join("");
}

function rerunBookmark(id) {
    const bookmark = bookmarks.find(b => b.id === id);
    if (bookmark) {
        toggleBookmarks();
        document.querySelector('[data-tab="tab-chat"]').click();
        submitQuestion(bookmark.question);
    }
}

function isBookmarked(question) {
    return bookmarks.some(b => b.question === question);
}

// ── Book Detail Modal ──
function openBookModal(bookData) {
    const modal = document.getElementById("book-modal");
    const title = document.getElementById("modal-title");
    const body = document.getElementById("modal-body");
    const actions = document.getElementById("modal-actions");

    const displayCol = Object.keys(bookData).find(k => k.toLowerCase().includes("title") || k.toLowerCase().includes("name")) || Object.keys(bookData)[0];
    title.textContent = bookData[displayCol] || "Details";

    body.innerHTML = Object.entries(bookData).map(([key, val]) => {
        if (val === null || val === undefined) return "";
        const isDesc = key.toLowerCase().includes("description") || String(val).length > 100;
        return `<div class="modal-field">
            <div class="modal-field-label">${escapeHtml(key.replace(/_/g, " "))}</div>
            <div class="modal-field-value${isDesc ? " description" : ""}">${escapeHtml(String(val))}</div>
        </div>`;
    }).join("");

    actions.innerHTML = `
        <button class="action-btn" onclick="speakText('${escapeAttr(bookData[displayCol] || "")}. ${escapeAttr(Object.entries(bookData).filter(([k,v]) => v && !k.toLowerCase().includes("isbn") && !k.toLowerCase().includes("description")).map(([k,v]) => k.replace(/_/g," ") + ": " + v).join(". "))}', this)">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M2 5v4l3 3V2L2 5zM7 3v8M9 4.5v5M11 5.5v3"/></svg>
            Read Aloud
        </button>
        <button class="action-btn" onclick="submitQuestion('Tell me more about ${escapeAttr(String(bookData[displayCol] || "").replace(/'/g, ""))}'); closeModal();">
            Ask About This
        </button>
    `;

    modal.classList.add("active");
}

function closeModal() {
    document.getElementById("book-modal").classList.remove("active");
    if (currentSpeech) {
        window.speechSynthesis.cancel();
        currentSpeech = null;
    }
}

// Click outside modal to close
document.addEventListener("click", (e) => {
    if (e.target.classList.contains("modal-overlay") && e.target.classList.contains("active")) {
        closeModal();
    }
});

// ── Particle Background ──
function initParticleBackground() {
    const canvas = document.getElementById("bg-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    const particles = Array.from({ length: 50 }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        r: Math.random() * 2 + 0.5,
    }));

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0) p.x = canvas.width;
            if (p.x > canvas.width) p.x = 0;
            if (p.y < 0) p.y = canvas.height;
            if (p.y > canvas.height) p.y = 0;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(168, 85, 247, 0.3)";
            ctx.fill();
        });

        particles.forEach((a, i) => {
            particles.slice(i + 1).forEach(b => {
                const dx = a.x - b.x;
                const dy = a.y - b.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < 120) {
                    ctx.beginPath();
                    ctx.moveTo(a.x, a.y);
                    ctx.lineTo(b.x, b.y);
                    ctx.strokeStyle = `rgba(168, 85, 247, ${0.1 * (1 - dist / 120)})`;
                    ctx.stroke();
                }
            });
        });
        requestAnimationFrame(draw);
    }
    draw();
}

// ── Keyboard Shortcuts ──
function initKeyboardShortcuts() {
    document.addEventListener("keydown", e => {
        if ((e.ctrlKey || e.metaKey) && e.key === "k") {
            e.preventDefault();
            document.getElementById("chat-input").focus();
            document.querySelector('[data-tab="tab-chat"]').click();
        }
        if (e.key === "Escape") {
            document.activeElement.blur();
            closeModal();
            if (document.getElementById("bookmarks-panel").classList.contains("active")) {
                toggleBookmarks();
            }
        }
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === "C") {
            e.preventDefault();
            clearChat();
        }
    });
}

function clearChat() {
    chatHistory = [];
    queryCount = 0;
    totalQueryTime = 0;
    const history = document.getElementById("chat-history");
    history.innerHTML = buildEmptyState("Start exploring your data", "Ask a question or click an example to begin");
    updateStats();
    loadExamples(); // Reload quick actions
}

// ── Tabs ──
function initTabs() {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            btn.classList.add("active");
            document.getElementById(btn.dataset.tab).classList.add("active");
        });
    });
}

// ── Chat ──
function initChat() {
    const input = document.getElementById("chat-input");
    const btn = document.getElementById("chat-submit");
    const charCount = document.getElementById("char-count");

    btn.addEventListener("click", () => submitQuestion());
    input.addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submitQuestion();
        }
    });
    input.addEventListener("input", () => {
        charCount.textContent = input.value.length;
    });
}

async function submitQuestion(question) {
    const input = document.getElementById("chat-input");
    const q = question || input.value.trim();
    if (!q) return;

    input.value = "";
    document.getElementById("char-count").textContent = "0";

    const history = document.getElementById("chat-history");

    // Remove empty state if present
    const empty = document.getElementById("empty-state");
    if (empty) empty.remove();

    // Add separator if there's already content
    if (chatHistory.length > 0) {
        const sep = document.createElement("div");
        sep.className = "chat-separator";
        sep.innerHTML = '<div class="sep-line"></div>';
        history.appendChild(sep);
    }

    // User message
    const userMsg = document.createElement("div");
    userMsg.className = "card card-user";
    userMsg.innerHTML = `<h3>You</h3><p class="response-text">${escapeHtml(q)}</p>`;
    history.appendChild(userMsg);

    // Typing indicator
    const typingEl = document.createElement("div");
    typingEl.className = "typing-indicator";
    typingEl.innerHTML = `
        <div class="typing-dots"><span></span><span></span><span></span></div>
        <span class="typing-text">Analyzing your question...</span>
    `;
    history.appendChild(typingEl);

    history.scrollTop = history.scrollHeight;

    const btn = document.getElementById("chat-submit");
    btn.disabled = true;
    const startTime = performance.now();

    try {
        const resp = await fetch(`${API_BASE}/ask`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: q, session_id: sessionId }),
        });

        const elapsed = Math.round(performance.now() - startTime);
        typingEl.remove();
        btn.disabled = false;

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: "Unknown error" }));
            showError(history, err.detail || `HTTP ${resp.status}`);
            return;
        }

        const data = await resp.json();

        // Track stats
        queryCount++;
        totalQueryTime += elapsed;
        chatHistory.push({ question: q, response: data, elapsed });
        updateStats();

        renderResponse(history, data, elapsed, q);
        history.scrollTop = history.scrollHeight;

        // Fetch follow-up suggestions asynchronously
        fetchFollowUps(q, data, history);

    } catch (err) {
        typingEl.remove();
        btn.disabled = false;
        showError(history, `Network error: ${err.message}`);
    }
}

function updateStats() {
    const el = document.getElementById("stats-display");
    if (!el) return;
    if (queryCount === 0) {
        el.textContent = "No queries yet";
    } else {
        const avg = Math.round(totalQueryTime / queryCount);
        el.textContent = `${queryCount} queries | Avg: ${avg}ms`;
    }
}

function renderResponse(container, data, elapsed, question) {
    // Response card with timing and actions
    const responseCard = document.createElement("div");
    responseCard.className = "card glow-pink";
    const timeTag = elapsed ? `<span class="time-badge">${elapsed}ms</span>` : "";
    const bookmarkClass = isBookmarked(question) ? " bookmarked" : "";
    const responseId = "resp-" + Date.now();

    responseCard.innerHTML = `
        <h3>Response ${timeTag}</h3>
        <p class="response-text" id="${responseId}">${escapeHtml(data.response)}</p>
        <div class="response-actions">
            <button class="action-btn tts-btn" onclick="speakText(document.getElementById('${responseId}').textContent, this)" title="Read aloud">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M2 5v4l3 3V2L2 5zM7 3v8M9 4.5v5M11 5.5v3"/></svg>
                Listen
            </button>
            <button class="action-btn${bookmarkClass}" data-action="bookmark" data-question="${escapeAttr(question)}" data-response="${escapeAttr(data.response)}" title="Save this query" data-metadata='${JSON.stringify(data.metadata || []).replace(/'/g, "&apos;")}'>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M1 1.5A1.5 1.5 0 012.5 0h9A1.5 1.5 0 0113 1.5V14l-6-3-6 3V1.5z"/></svg>
                Save
            </button>
            <button class="action-btn" onclick="copyResponseText('${responseId}')" title="Copy response">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="4" y="4" width="9" height="9" rx="1.5"/><path d="M10 4V2.5A1.5 1.5 0 008.5 1h-6A1.5 1.5 0 001 2.5v6A1.5 1.5 0 002.5 10H4"/></svg>
                Copy
            </button>
            <button class="action-btn" onclick="exportChatAsMarkdown()" title="Export chat">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M7 1v9M4 7l3 3 3-3M2 12h10"/></svg>
                Export Chat
            </button>
        </div>
    `;
    container.appendChild(responseCard);

    // JSON Output card
    const jsonCard = document.createElement("div");
    jsonCard.className = "card";
    const jsonId = "json-" + Date.now();
    const jsonStr = JSON.stringify(data, null, 2);
    jsonCard.innerHTML = `
        <h3>
            JSON Output
            <button class="json-copy-btn" onclick="copyJson('${jsonId}')">Copy</button>
            <button class="json-copy-btn" onclick="toggleJson('${jsonId}-wrap')">Toggle</button>
        </h3>
        <div id="${jsonId}-wrap" class="json-wrap">
            <pre class="json-output" id="${jsonId}">${syntaxHighlightJson(jsonStr)}</pre>
        </div>
    `;
    container.appendChild(jsonCard);

    if (data.metadata && data.metadata.length > 0) {
        // Data table card
        const tableCard = document.createElement("div");
        tableCard.className = "card";
        const exportId = "export-" + Date.now();
        tableCard.innerHTML = `
            <h3>
                Results <span class="row-count-badge">${data.metadata.length} rows</span>
                <span class="export-btns">
                    <button class="export-btn" onclick="exportCSV('${exportId}')">Export CSV</button>
                    <button class="export-btn" onclick="exportJSON('${exportId}')">Export JSON</button>
                </span>
            </h3>
            ${buildTable(data.metadata)}
        `;
        tableCard._metadata = data.metadata;
        tableCard.id = exportId;
        container.appendChild(tableCard);

        // Recommendation button
        if (data.metadata.length > 0) {
            const firstRow = data.metadata[0];
            const titleKey = Object.keys(firstRow).find(k => k.toLowerCase().includes("title") || k.toLowerCase().includes("name"));
            if (titleKey && firstRow[titleKey]) {
                const recCard = document.createElement("div");
                recCard.className = "card";
                const bookTitle = firstRow[titleKey];
                recCard.innerHTML = `
                    <h3>Discover More</h3>
                    <p class="response-text" style="margin-bottom:10px;">Want books similar to "${escapeHtml(truncate(String(bookTitle), 50))}"?</p>
                    <button class="recommend-btn" onclick="getRecommendations('${escapeAttr(String(bookTitle))}', this)">
                        Find Similar Books
                    </button>
                `;
                container.appendChild(recCard);
            }
        }

        // Visualization
        const chartData = analyzeForChart(data.metadata);
        if (chartData) {
            const vizCard = document.createElement("div");
            vizCard.className = "card glow-blue";
            const chartId = "chart-" + Date.now();
            vizCard.innerHTML = `
                <h3>Visualization</h3>
                <div class="chart-toggle" id="toggle-${chartId}">
                    <button class="active" data-type="bar">Bar</button>
                    <button data-type="doughnut">Doughnut</button>
                    <button data-type="line">Line</button>
                    ${chartData.labels.length <= 10 ? '<button data-type="polarArea">Polar</button>' : ''}
                </div>
                <div class="chart-container">
                    <canvas id="${chartId}"></canvas>
                </div>
            `;
            container.appendChild(vizCard);

            requestAnimationFrame(() => {
                const chart = createChart(chartId, chartData, "bar");
                initChartToggle(chartId, chartData, chart);
            });
        }
    }
}

// ── Follow-Up Suggestions ──
async function fetchFollowUps(question, data, container) {
    try {
        const resp = await fetch(`${API_BASE}/suggest-followups`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question,
                response: data.response,
                metadata_count: (data.metadata || []).length,
            }),
        });

        if (!resp.ok) return;
        const suggestions = await resp.json();

        if (suggestions.followups && suggestions.followups.length > 0) {
            const followupCard = document.createElement("div");
            followupCard.className = "followup-container";
            followupCard.innerHTML = `
                <div class="followup-label">Suggested follow-ups</div>
                <div class="followup-chips">
                    ${suggestions.followups.map(q =>
                        `<button class="followup-chip" onclick="submitQuestion('${escapeAttr(q)}')" title="${escapeAttr(q)}">${escapeHtml(truncate(q, 50))}</button>`
                    ).join("")}
                </div>
            `;
            // Insert after the last card in this conversation turn
            container.appendChild(followupCard);
            container.scrollTop = container.scrollHeight;
        }
    } catch {
        // Silently ignore - follow-ups are optional
    }
}

// ── Toggle Bookmark from Response ──
// Delegated click handler for bookmark buttons (avoids inline onclick escaping issues)
document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action='bookmark']");
    if (!btn) return;
    const question = btn.getAttribute("data-question");
    const response = btn.getAttribute("data-response");
    toggleBookmark(btn, question, response);
});

function toggleBookmark(btn, question, response) {
    const metadataStr = btn.getAttribute("data-metadata");
    let metadata = [];
    try { metadata = JSON.parse(metadataStr.replace(/&apos;/g, "'")); } catch {}

    if (btn.classList.contains("bookmarked")) {
        // Remove
        bookmarks = bookmarks.filter(b => b.question !== question);
        localStorage.setItem("datachat_bookmarks", JSON.stringify(bookmarks));
        btn.classList.remove("bookmarked");
        updateBookmarkCount();
        renderBookmarks();
        showToast("Removed from bookmarks", "info");
    } else {
        addBookmark(question, response, metadata);
        btn.classList.add("bookmarked");
    }
}

// ── Copy Response Text ──
function copyResponseText(id) {
    const el = document.getElementById(id);
    if (!el) return;
    navigator.clipboard.writeText(el.textContent).then(() => {
        showToast("Response copied", "success");
    }).catch(() => {
        showToast("Failed to copy", "error");
    });
}

// ── Export Chat as Markdown ──
function exportChatAsMarkdown() {
    if (chatHistory.length === 0) {
        showToast("No chat to export", "error");
        return;
    }

    let md = "# DataChat Export\n\n";
    md += `> Exported on ${new Date().toLocaleString()}\n\n---\n\n`;

    chatHistory.forEach((entry, i) => {
        md += `## Query ${i + 1}\n\n`;
        md += `**Question:** ${entry.question}\n\n`;
        md += `**Response:** ${entry.response.response}\n\n`;
        if (entry.response.metadata && entry.response.metadata.length > 0) {
            md += `**Results:** ${entry.response.metadata.length} rows\n\n`;
            const cols = Object.keys(entry.response.metadata[0]);
            md += `| ${cols.join(" | ")} |\n`;
            md += `| ${cols.map(() => "---").join(" | ")} |\n`;
            entry.response.metadata.slice(0, 10).forEach(row => {
                md += `| ${cols.map(c => String(row[c] ?? "")).join(" | ")} |\n`;
            });
            md += "\n";
        }
        md += `*Response time: ${entry.elapsed}ms*\n\n---\n\n`;
    });

    downloadFile(md, `datachat-export-${Date.now()}.md`, "text/markdown");
    showToast("Chat exported as Markdown", "success");
}

// ── JSON Syntax Highlighting ──
function syntaxHighlightJson(jsonStr) {
    return escapeHtml(jsonStr)
        .replace(/"([^"]+)":/g, '<span class="json-key">"$1"</span>:')
        .replace(/: "([^"]*)"/g, ': <span class="json-string">"$1"</span>')
        .replace(/: (\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
        .replace(/: (true|false)/g, ': <span class="json-bool">$1</span>')
        .replace(/: (null)/g, ': <span class="json-null">$1</span>');
}

function toggleJson(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle("collapsed");
}

function copyJson(id) {
    const el = document.getElementById(id);
    if (!el) return;
    navigator.clipboard.writeText(el.textContent).then(() => {
        showToast("JSON copied to clipboard", "success");
    }).catch(() => {
        const range = document.createRange();
        range.selectNodeContents(el);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand("copy");
        window.getSelection().removeAllRanges();
        showToast("JSON copied to clipboard", "success");
    });
}

// ── Export Functions ──
function exportCSV(id) {
    const card = document.getElementById(id);
    if (!card || !card._metadata) return;
    const rows = card._metadata;
    const cols = Object.keys(rows[0]);
    const header = cols.map(c => `"${c.replace(/"/g, '""')}"`).join(",");
    const body = rows.map(row =>
        cols.map(c => {
            const v = row[c];
            if (v === null || v === undefined) return "";
            return `"${String(v).replace(/"/g, '""')}"`;
        }).join(",")
    ).join("\n");
    downloadFile(header + "\n" + body, "results.csv", "text/csv");
    showToast("CSV downloaded", "success");
}

function exportJSON(id) {
    const card = document.getElementById(id);
    if (!card || !card._metadata) return;
    downloadFile(JSON.stringify(card._metadata, null, 2), "results.json", "application/json");
    showToast("JSON downloaded", "success");
}

function downloadFile(content, filename, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

// ── Recommendations ──
async function getRecommendations(title, btn) {
    btn.disabled = true;
    btn.textContent = "Finding...";

    try {
        const resp = await fetch(`${API_BASE}/recommend`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, count: 5 }),
        });

        if (!resp.ok) {
            btn.textContent = "No recommendations found";
            return;
        }

        const data = await resp.json();
        if (!data.recommendations || data.recommendations.length === 0) {
            btn.textContent = "No similar books found";
            return;
        }

        const parent = btn.parentElement;
        btn.remove();
        const recHtml = data.recommendations.map((book, i) => {
            const display = Object.keys(book).find(k => k.toLowerCase().includes("title") || k.toLowerCase().includes("name"));
            const name = display ? book[display] : `Book ${i + 1}`;
            const rating = Object.keys(book).find(k => k.toLowerCase().includes("rating") && !k.toLowerCase().includes("count"));
            const ratingVal = rating ? book[rating] : null;
            const author = Object.keys(book).find(k => k.toLowerCase().includes("author"));
            const authorVal = author ? book[author] : null;

            return `<div class="rec-item" onclick="submitQuestion('Tell me about ${escapeAttr(String(name).replace(/'/g, ""))}')">
                <span class="rec-rank">${i + 1}</span>
                <div class="rec-info">
                    <div class="rec-title">${escapeHtml(truncate(String(name), 50))}</div>
                    <div class="rec-meta">
                        ${authorVal ? escapeHtml(truncate(String(authorVal), 30)) : ""}
                        ${ratingVal ? ' &middot; Rating: ' + ratingVal : ""}
                    </div>
                </div>
            </div>`;
        }).join("");

        parent.innerHTML += `<div class="rec-list">${recHtml}</div>`;
    } catch {
        btn.textContent = "Error loading recommendations";
    }
}

// ── Chart Analysis & Rendering ──
const CHART_COLORS = [
    "rgba(168, 85, 247, 0.7)", "rgba(236, 72, 153, 0.7)", "rgba(99, 102, 241, 0.7)",
    "rgba(34, 211, 238, 0.7)", "rgba(34, 197, 94, 0.7)", "rgba(245, 158, 11, 0.7)",
    "rgba(239, 68, 68, 0.7)", "rgba(147, 51, 234, 0.7)", "rgba(249, 115, 22, 0.7)",
    "rgba(20, 184, 166, 0.7)", "rgba(244, 63, 94, 0.7)", "rgba(59, 130, 246, 0.7)",
];

const CHART_BORDERS = CHART_COLORS.map(c => c.replace("0.7", "1"));

function analyzeForChart(rows) {
    if (!rows || rows.length === 0 || rows.length === 1) return null;
    const cols = Object.keys(rows[0]);
    const SKIP_PATTERNS = ["isbn", "id", "index", "key", "num_pages", "page"];
    function shouldSkipCol(colName) {
        const lower = colName.toLowerCase().replace("__agg__", "");
        return SKIP_PATTERNS.some(p => lower.includes(p));
    }
    let labelCol = null;
    const valueCols = [];
    for (const col of cols) {
        const sampleVal = rows[0][col];
        if (shouldSkipCol(col)) continue;
        if (typeof sampleVal === "number") {
            const allVals = rows.map(r => r[col]).filter(v => typeof v === "number");
            const avg = allVals.reduce((a, b) => a + b, 0) / allVals.length;
            if (avg > 1000000) continue;
            valueCols.push(col);
        } else if (!labelCol && typeof sampleVal === "string") {
            labelCol = col;
        }
    }
    const prioritized = valueCols.sort((a, b) => {
        const aAgg = a.startsWith("__agg__") ? -2 : 0;
        const bAgg = b.startsWith("__agg__") ? -2 : 0;
        const aRating = a.toLowerCase().includes("rating") ? -1 : 0;
        const bRating = b.toLowerCase().includes("rating") ? -1 : 0;
        return (aAgg + aRating) - (bAgg + bRating);
    });
    const chartCols = prioritized.slice(0, 2);
    if (chartCols.length === 0) return null;
    const chartRows = rows.slice(0, 15);
    const labels = chartRows.map((r, i) => labelCol ? truncate(String(r[labelCol]), 20) : `#${i + 1}`);
    const datasets = chartCols.map((col, idx) => {
        const colLabel = col.startsWith("__agg__") ? col.replace("__agg__", "").replace(/_/g, " ") : col.replace(/_/g, " ");
        return {
            label: colLabel,
            data: chartRows.map(r => parseFloat(r[col]) || 0),
            backgroundColor: chartCols.length === 1 ? CHART_COLORS.slice(0, chartRows.length) : CHART_COLORS[idx % CHART_COLORS.length],
            borderColor: chartCols.length === 1 ? CHART_BORDERS.slice(0, chartRows.length) : CHART_BORDERS[idx % CHART_BORDERS.length],
            borderWidth: 1.5,
        };
    });
    return { labels, datasets };
}

function getChartThemeColors() {
    const style = getComputedStyle(document.documentElement);
    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    return {
        textColor: style.getPropertyValue("--text-secondary").trim() || (isDark ? "#9090b0" : "#4a4a6a"),
        textMuted: style.getPropertyValue("--text-muted").trim() || (isDark ? "#707090" : "#7a7a9a"),
        textPrimary: style.getPropertyValue("--text-primary").trim() || (isDark ? "#e0e0ff" : "#1a1a2e"),
        bgCard: style.getPropertyValue("--bg-card").trim() || (isDark ? "#1a1a2e" : "#ffffff"),
        borderColor: style.getPropertyValue("--border-color").trim() || (isDark ? "#2a2a40" : "#d0d0e0"),
        gridColor: isDark ? "rgba(42,42,64,0.3)" : "rgba(0,0,0,0.08)",
    };
}

function createChart(canvasId, chartData, type) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const existing = Chart.getChart(canvas);
    if (existing) existing.destroy();
    const isRadial = type === "doughnut" || type === "polarArea";
    const numLabels = chartData.labels.length;
    const theme = getChartThemeColors();
    const config = {
        type,
        data: {
            labels: chartData.labels,
            datasets: chartData.datasets.map(ds => ({
                ...ds,
                backgroundColor: isRadial ? CHART_COLORS.slice(0, numLabels) : ds.backgroundColor,
                borderColor: isRadial ? CHART_BORDERS.slice(0, numLabels) : ds.borderColor,
            })),
        },
        options: {
            responsive: true, maintainAspectRatio: true,
            devicePixelRatio: window.devicePixelRatio || 1,
            layout: { padding: isRadial ? 10 : { left: 5, right: 15, top: 10, bottom: 5 } },
            plugins: {
                legend: {
                    display: isRadial || chartData.datasets.length > 1,
                    position: isRadial ? "right" : "top",
                    labels: {
                        color: theme.textColor, font: { family: "'Inter', sans-serif", size: 10 }, boxWidth: 12, padding: 8,
                        generateLabels: isRadial ? function(chart) {
                            return chart.data.labels.map((label, i) => ({
                                text: truncate(label, 18), fillStyle: CHART_COLORS[i % CHART_COLORS.length],
                                strokeStyle: CHART_BORDERS[i % CHART_BORDERS.length], lineWidth: 1, index: i, hidden: false,
                                fontColor: theme.textColor,
                            }));
                        } : undefined,
                    },
                },
                tooltip: {
                    backgroundColor: theme.bgCard, titleColor: theme.textPrimary, bodyColor: theme.textColor,
                    borderColor: theme.borderColor, borderWidth: 1, cornerRadius: 8, padding: 10,
                    callbacks: { title: items => items.length ? chartData.labels[items[0].dataIndex] : "" },
                },
            },
            scales: isRadial ? (type === "polarArea" ? {
                r: {
                    ticks: { color: theme.textColor, font: { size: 10 }, backdropColor: "transparent" },
                    grid: { color: theme.gridColor },
                    pointLabels: { color: theme.textColor, font: { size: 10 } },
                },
            } : {}) : {
                x: {
                    ticks: {
                        color: theme.textColor, font: { size: numLabels > 10 ? 9 : 10 },
                        maxRotation: numLabels > 8 ? 45 : 0, autoSkip: true, maxTicksLimit: 15,
                        callback: function(value) { return truncate(this.getLabelForValue(value), 15); },
                    },
                    grid: { color: theme.gridColor },
                },
                y: {
                    ticks: { color: theme.textColor, font: { size: 10 } },
                    grid: { color: theme.gridColor }, beginAtZero: true,
                },
            },
        },
    };
    if (type === "polarArea" && numLabels > 10) {
        config.data.labels = chartData.labels.slice(0, 10);
        config.data.datasets = config.data.datasets.map(ds => ({
            ...ds, data: ds.data.slice(0, 10),
            backgroundColor: CHART_COLORS.slice(0, 10), borderColor: CHART_BORDERS.slice(0, 10),
        }));
    }
    const chart = new Chart(canvas, config);
    activeCharts.push(chart);
    return chart;
}

function initChartToggle(chartId, chartData) {
    const toggleContainer = document.getElementById(`toggle-${chartId}`);
    if (!toggleContainer) return;
    toggleContainer.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", () => {
            toggleContainer.querySelectorAll("button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            createChart(chartId, chartData, btn.dataset.type);
        });
    });
}

function truncate(str, len) {
    return str.length > len ? str.substring(0, len) + "..." : str;
}

// ── Upload ──
function initUpload() {
    const area = document.getElementById("upload-area");
    const input = document.getElementById("file-input");
    area.addEventListener("click", () => input.click());
    area.addEventListener("dragover", e => { e.preventDefault(); area.classList.add("drag-over"); });
    area.addEventListener("dragleave", () => { area.classList.remove("drag-over"); });
    area.addEventListener("drop", e => {
        e.preventDefault(); area.classList.remove("drag-over");
        if (e.dataTransfer.files.length > 0) uploadFile(e.dataTransfer.files[0]);
    });
    input.addEventListener("change", () => {
        if (input.files.length > 0) { uploadFile(input.files[0]); input.value = ""; }
    });
}

async function uploadFile(file) {
    const progressEl = document.getElementById("upload-progress");
    const fillEl = document.getElementById("progress-fill");
    const statusEl = document.getElementById("upload-status");
    progressEl.classList.remove("hidden");
    fillEl.style.width = "30%";
    statusEl.textContent = `Uploading ${file.name}...`;
    const formData = new FormData();
    formData.append("file", file);
    try {
        fillEl.style.width = "60%";
        const resp = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData });
        fillEl.style.width = "90%";
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: "Upload failed" }));
            fillEl.style.width = "100%"; fillEl.style.background = "var(--error)";
            statusEl.textContent = err.detail || "Upload failed";
            showToast(err.detail || "Upload failed", "error");
            setTimeout(() => { progressEl.classList.add("hidden"); fillEl.style.background = ""; fillEl.style.width = "0%"; }, 3000);
            return;
        }
        const data = await resp.json();
        fillEl.style.width = "100%";
        statusEl.textContent = `Loaded ${data.filename}: ${data.rows} rows, ${data.columns} columns`;
        showToast(`Dataset loaded: ${data.rows} rows, ${data.columns} columns`, "success");
        loadDatasetInfo(); loadSchema(); loadExamples(); loadAnalytics();
        clearChat();
        setTimeout(() => { progressEl.classList.add("hidden"); fillEl.style.width = "0%"; }, 2000);
    } catch (err) {
        fillEl.style.width = "100%"; fillEl.style.background = "var(--error)";
        statusEl.textContent = `Error: ${err.message}`;
        showToast(`Upload error: ${err.message}`, "error");
        setTimeout(() => { progressEl.classList.add("hidden"); fillEl.style.background = ""; fillEl.style.width = "0%"; }, 3000);
    }
}

// ── Dataset Info ──
async function loadDatasetInfo() {
    const nameEl = document.getElementById("dataset-name");
    try {
        const resp = await fetch(`${API_BASE}/dataset-info`);
        if (resp.ok) {
            const data = await resp.json();
            nameEl.textContent = `${data.name} (${data.rows.toLocaleString()} rows, ${data.columns} cols)`;
        }
    } catch { nameEl.textContent = "Not connected"; }
}

// ── Table Builder ──
function buildTable(rows) {
    if (!rows.length) return "<p>No data</p>";
    const cols = Object.keys(rows[0]);
    let html = `<div class="metadata-table-wrap"><table><thead><tr>`;
    cols.forEach(c => {
        const label = c.startsWith("__agg__") ? c.replace("__agg__", "").replace(/_/g, " ") : c;
        html += `<th>${escapeHtml(label)}</th>`;
    });
    html += `</tr></thead><tbody>`;
    rows.forEach((row, idx) => {
        html += `<tr onclick="openBookModal(JSON.parse(decodeURIComponent('${encodeURIComponent(JSON.stringify(row))}')))">`;
        cols.forEach(c => {
            const val = row[c];
            const display = val === null || val === undefined ? "\u2014" : String(val);
            html += `<td title="${escapeAttr(display)}">${escapeHtml(truncate(display, 50))}</td>`;
        });
        html += `</tr>`;
    });
    html += `</tbody></table></div>`;
    return html;
}

// ── Error Display ──
function showError(container, msg) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<h3 style="color: var(--error);">Error</h3><p class="response-text">${escapeHtml(msg)}</p>`;
    container.appendChild(el);
}

// ── Toast Notifications ──
function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3200);
}

// ── Empty State Builder ──
function buildEmptyState(title, subtitle) {
    return `<div class="empty-state" id="empty-state">
        <div class="empty-icon">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
                <circle cx="32" cy="32" r="28" stroke="url(#empty-grad)" stroke-width="2" stroke-dasharray="6 4"/>
                <path d="M22 28h20M22 34h14M22 40h8" stroke="url(#empty-grad)" stroke-width="2" stroke-linecap="round"/>
                <defs><linearGradient id="empty-grad" x1="0" y1="0" x2="64" y2="64"><stop stop-color="#a855f7" stop-opacity="0.5"/><stop offset="1" stop-color="#ec4899" stop-opacity="0.5"/></linearGradient></defs>
            </svg>
        </div>
        <p class="empty-title">${title}</p>
        <p class="empty-subtitle">${subtitle}</p>
        <div class="quick-actions" id="quick-actions"></div>
    </div>`;
}

// ── Schema Tab ──
async function loadSchema() {
    const container = document.getElementById("schema-content");
    try {
        const resp = await fetch(`${API_BASE}/schema`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        let html = `<div class="card" style="margin-bottom:16px;">
            <h3>Dataset Overview</h3>
            <p class="schema-overview-text">
                <strong>${data.row_count.toLocaleString()}</strong> rows &middot;
                <strong>${data.columns.length}</strong> columns &middot;
                Display column: <strong>${escapeHtml(data.display_column)}</strong>
            </p>
        </div>`;
        html += `<div class="schema-grid">`;
        data.columns.forEach(col => {
            const typeColor = { string: "var(--accent-pink)", number: "var(--accent-cyan)", date: "var(--warning)", bool: "var(--accent-green)" }[col.dtype] || "var(--accent-blue)";
            html += `<div class="schema-card">
                    <span class="col-name">${escapeHtml(col.name)}</span>
                    <span class="col-type" style="color:${typeColor}">${col.dtype}</span>
                    <div class="detail">${col.unique_count.toLocaleString()} unique &middot; ${col.missing_pct}% missing</div>
                    <div class="sample-values">
                        ${col.sample_values.slice(0, 3).map(v =>
                            `<span class="sample-tag" title="${escapeAttr(String(v))}">${escapeHtml(truncate(String(v), 20))}</span>`
                        ).join("")}
                    </div>
                </div>`;
        });
        html += `</div>`;
        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<p style="color:var(--error)">Failed to load schema: ${escapeHtml(err.message)}</p>`;
    }
}

// ── Examples Tab ──
async function loadExamples() {
    const container = document.getElementById("examples-content");
    try {
        const resp = await fetch(`${API_BASE}/examples`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        let html = `<div class="examples-list">`;
        data.examples.forEach(ex => {
            const intent = (ex.rationale || "").split(":")[0] || "Query";
            html += `<div class="example-item" onclick="runExample(this)" data-question="${escapeAttr(ex.question)}">
                    <div class="question">${escapeHtml(ex.question)}</div>
                    <div class="rationale">${escapeHtml(ex.rationale || "")}</div>
                    <span class="intent-tag">${escapeHtml(intent)}</span>
                </div>`;
        });
        html += `</div>`;
        container.innerHTML = html;
        const quickActions = document.getElementById("quick-actions");
        if (quickActions && data.examples.length > 0) {
            quickActions.innerHTML = data.examples.slice(0, 4).map(ex =>
                `<button class="quick-action-btn" onclick="runQuickAction(this)" data-question="${escapeAttr(ex.question)}">${escapeHtml(truncate(ex.question, 40))}</button>`
            ).join("");
        }
    } catch (err) {
        container.innerHTML = `<p style="color:var(--error)">Failed to load examples: ${escapeHtml(err.message)}</p>`;
    }
}

// ── Analytics Tab ──
async function loadAnalytics() {
    const container = document.getElementById("analytics-content");
    try {
        const resp = await fetch(`${API_BASE}/analytics`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        let html = `<div class="analytics-grid">`;
        html += buildAnalyticsStat(data.total_books?.toLocaleString() || "0", "Total Books");
        html += buildAnalyticsStat(data.total_authors?.toLocaleString() || "0", "Unique Authors");
        html += buildAnalyticsStat(data.total_categories?.toLocaleString() || "0", "Categories");
        html += buildAnalyticsStat(data.avg_rating?.toFixed(2) || "N/A", "Avg Rating");
        html += buildAnalyticsStat(data.avg_pages?.toFixed(0) || "N/A", "Avg Pages");
        html += buildAnalyticsStat(data.year_range || "N/A", "Year Range");
        html += `</div>`;

        // Top authors chart
        const chartsToRender = [];

        if (data.top_authors && data.top_authors.length > 0) {
            const topAuthorsId = "analytics-authors-" + Date.now();
            html += `<div class="card glow-blue">
                <h3>Top Authors by Book Count</h3>
                <div class="chart-container"><canvas id="${topAuthorsId}"></canvas></div>
            </div>`;
            chartsToRender.push(() => {
                createChart(topAuthorsId, {
                    labels: data.top_authors.map(a => truncate(a.name, 20)),
                    datasets: [{
                        label: "Books",
                        data: data.top_authors.map(a => a.count),
                        backgroundColor: CHART_COLORS.slice(0, data.top_authors.length),
                        borderColor: CHART_BORDERS.slice(0, data.top_authors.length),
                        borderWidth: 1.5,
                    }],
                }, "bar");
            });
        }

        // Rating distribution chart
        if (data.rating_distribution && data.rating_distribution.length > 0) {
            const ratingChartId = "analytics-rating-" + Date.now();
            html += `<div class="card glow-blue">
                <h3>Rating Distribution</h3>
                <div class="chart-container"><canvas id="${ratingChartId}"></canvas></div>
            </div>`;
            chartsToRender.push(() => {
                createChart(ratingChartId, {
                    labels: data.rating_distribution.map(r => r.range),
                    datasets: [{
                        label: "Books",
                        data: data.rating_distribution.map(r => r.count),
                        backgroundColor: CHART_COLORS.slice(0, data.rating_distribution.length),
                        borderColor: CHART_BORDERS.slice(0, data.rating_distribution.length),
                        borderWidth: 1.5,
                    }],
                }, "bar");
            });
        }

        container.innerHTML = html;
        if (chartsToRender.length > 0) {
            requestAnimationFrame(() => chartsToRender.forEach(fn => fn()));
        }
    } catch (err) {
        container.innerHTML = `<div class="card">
            <h3>Analytics</h3>
            <p class="response-text">Analytics will be available once the backend is running. Error: ${escapeHtml(err.message)}</p>
        </div>`;
    }
}

function buildAnalyticsStat(value, label) {
    return `<div class="analytics-stat">
        <div class="analytics-stat-value">${value}</div>
        <div class="analytics-stat-label">${label}</div>
    </div>`;
}

// ── Data Quality Tab ──
async function loadDataQuality() {
    const container = document.getElementById("quality-content");
    try {
        const resp = await fetch(`${API_BASE}/data-quality`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        let html = `<div class="card" style="margin-bottom:16px;">
            <h3>Data Quality Report</h3>
            <p class="schema-overview-text">
                <strong>${escapeHtml(data.dataset)}</strong> &mdash;
                ${data.rows.toLocaleString()} rows, ${data.columns} columns
            </p>
        </div>`;

        if (data.profile && typeof data.profile === "object") {
            const profile = data.profile;

            // Overall score + dimension scores
            html += `<div class="analytics-grid" style="margin-bottom:20px;">`;
            if (profile.overall_score !== undefined) {
                const scoreClass = profile.overall_score >= 80 ? "score-green" : profile.overall_score >= 60 ? "score-yellow" : "score-red";
                html += `<div class="analytics-stat" style="border-color:${profile.overall_score >= 80 ? 'var(--accent-green)' : profile.overall_score >= 60 ? 'var(--warning)' : 'var(--error)'}">
                    <div class="analytics-stat-value ${scoreClass}" style="font-size:2rem;">${profile.overall_score}%</div>
                    <div class="analytics-stat-label">Overall Score</div>
                </div>`;
            }
            if (profile.dimensions) {
                const dims = profile.dimensions;
                const dimItems = [
                    { key: "completeness", label: "Completeness" },
                    { key: "consistency", label: "Consistency" },
                    { key: "uniqueness", label: "Uniqueness" },
                    { key: "validity", label: "Validity" },
                ];
                for (const item of dimItems) {
                    const val = dims[item.key];
                    if (val !== undefined && val !== null) {
                        const dimClass = val >= 80 ? "score-green" : val >= 60 ? "score-yellow" : "score-red";
                        html += `<div class="analytics-stat">
                            <div class="analytics-stat-value ${dimClass}" style="font-size:1.5rem;">${val}%</div>
                            <div class="analytics-stat-label">${item.label}</div>
                        </div>`;
                    }
                }
            }
            html += `</div>`;

            // Warnings
            if (profile.warnings && profile.warnings.length > 0) {
                html += `<div class="card" style="border-color:var(--warning);margin-bottom:16px;">
                    <h3 style="color:var(--warning)">Warnings (${profile.warnings.length})</h3>`;
                for (const w of profile.warnings) {
                    const icon = w.level === "critical" ? "!!!" : "!";
                    const color = w.level === "critical" ? "var(--error)" : "var(--warning)";
                    html += `<div style="padding:6px 0;border-bottom:1px solid var(--border-color);font-size:0.88rem;">
                        <span style="color:${color};font-weight:600;margin-right:6px;">[${icon}]</span>
                        <span style="color:var(--text-secondary);">${escapeHtml(w.message)}</span>
                        ${w.column ? `<span class="col-type" style="margin-left:6px;">${escapeHtml(w.column)}</span>` : ""}
                    </div>`;
                }
                html += `</div>`;
            }

            // Anomalies
            if (profile.anomalies && profile.anomalies.length > 0) {
                html += `<div class="card" style="border-color:var(--accent-pink);margin-bottom:16px;">
                    <h3 style="color:var(--accent-pink)">Anomalies Detected (${profile.anomalies.length})</h3>`;
                for (const a of profile.anomalies) {
                    html += `<div style="padding:6px 0;border-bottom:1px solid var(--border-color);font-size:0.88rem;">
                        <span style="color:var(--accent-pink);font-weight:600;margin-right:6px;">${escapeHtml(a.type || "anomaly")}</span>
                        <span style="color:var(--text-secondary);">${escapeHtml(a.message)}</span>
                    </div>`;
                }
                html += `</div>`;
            }

            // Column-level profiles
            if (profile.column_profiles && profile.column_profiles.length > 0) {
                html += `<div class="card" style="margin-bottom:16px;"><h3>Column Profiles</h3></div>`;
                html += `<div class="schema-grid">`;
                for (const col of profile.column_profiles) {
                    const missingPct = col.missing_pct || 0;
                    const missingColor = missingPct > 50 ? "var(--error)" : missingPct > 20 ? "var(--warning)" : "var(--accent-green)";
                    html += `<div class="schema-card">
                        <span class="col-name">${escapeHtml(col.column || "")}</span>
                        <span class="col-type" style="color:var(--accent-blue)">${escapeHtml(col.dtype || "")}</span>
                        <div class="detail" style="margin-top:8px;">
                            <span style="color:${missingColor}">${missingPct.toFixed(1)}% missing</span>
                            &middot; ${(col.unique_count || 0).toLocaleString()} unique (${(col.unique_pct || 0).toFixed(1)}%)
                        </div>
                        <div class="detail">
                            Consistency: ${(col.consistency || 0).toFixed(0)}% &middot; Validity: ${(col.validity || 0).toFixed(0)}%
                        </div>
                        ${col.stats ? `<div class="detail" style="margin-top:4px;font-family:var(--font-mono);font-size:0.72rem;">
                            ${col.stats.mean !== undefined ? `Mean: ${col.stats.mean} | Med: ${col.stats.median}` : ""}
                            ${col.stats.avg_length !== undefined ? `Avg len: ${col.stats.avg_length}` : ""}
                            ${col.stats.outlier_count ? ` | Outliers: ${col.stats.outlier_count}` : ""}
                        </div>` : ""}
                        ${col.cardinality ? `<div class="detail" style="margin-top:2px;">Cardinality: <span class="sample-tag">${col.cardinality}</span></div>` : ""}
                    </div>`;
                }
                html += `</div>`;
            }

            // Correlations
            if (profile.correlations && profile.correlations.length > 0) {
                html += `<div class="card" style="margin-top:16px;">
                    <h3>Column Correlations</h3>
                    <div class="metadata-table-wrap"><table><thead><tr>
                        <th>Column A</th><th>Column B</th><th>Correlation</th><th>Strength</th>
                    </tr></thead><tbody>`;
                for (const c of profile.correlations) {
                    const strengthColor = c.strength === "strong" ? "var(--accent-green)" : c.strength === "moderate" ? "var(--warning)" : "var(--text-muted)";
                    html += `<tr>
                        <td>${escapeHtml(c.column_a)}</td>
                        <td>${escapeHtml(c.column_b)}</td>
                        <td>${c.correlation}</td>
                        <td style="color:${strengthColor};font-weight:600;">${c.strength}</td>
                    </tr>`;
                }
                html += `</tbody></table></div></div>`;
            }
        }

        container.innerHTML = html;
    } catch (err) {
        container.innerHTML = `<div class="card">
            <h3>Data Quality</h3>
            <p class="response-text">Data quality analysis will be available once the backend is running. Error: ${escapeHtml(err.message)}</p>
        </div>`;
    }
}

function runExample(el) {
    document.querySelector('[data-tab="tab-chat"]').click();
    document.getElementById("chat-input").value = el.dataset.question;
    submitQuestion(el.dataset.question);
}

function runQuickAction(el) { submitQuestion(el.dataset.question); }

// ── Utilities ──
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/'/g, "&#39;");
}
