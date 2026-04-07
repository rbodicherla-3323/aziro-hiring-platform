/* ================================================================
   AZIRO CODING EDITOR â€” JavaScript Flow Controller v4
   CodeMirror 5 integration: syntax highlighting, line numbers,
   bracket matching, auto-indent, auto-close brackets.
   Auto-save, timer, run, submit.
   ================================================================ */

(function () {
    "use strict";

    // â”€â”€ Bootstrap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    const view = document.getElementById("codingEditorView");
    if (!view) return;

    const sessionId      = view.dataset.sessionId;
    const language       = view.dataset.language;
    const saveUrl        = view.dataset.saveUrl;
    const runUrl         = view.dataset.runUrl;
    const submitUrl      = view.dataset.submitUrl;
    const completedUrl   = `/coding/completed/${encodeURIComponent(sessionId)}`;
    let remainingSeconds = parseInt(view.dataset.remainingSeconds, 10) || 0;

    const textarea       = document.getElementById("codingEditor");
    const timerEl        = document.getElementById("codingTimerValue");
    const timerWrap      = document.getElementById("codingTimer");
    const saveStatus     = document.getElementById("codingSaveStatus");
    const outputContent  = document.getElementById("codingOutputContent");
    const runBtn         = document.getElementById("codingRunBtn");
    const runHiddenBtn   = document.getElementById("codingRunHiddenBtn");
    const resetBtn       = document.getElementById("codingResetBtn");
    const submitBtn      = document.getElementById("codingSubmitBtn");
    const scoreEl        = document.getElementById("codingScore");

    const starterCode = textarea ? textarea.value : "";
    let autoSaveTimer = null;
    let lastSavedCode = textarea ? textarea.value : "";
    let isRunning = false;

    // â”€â”€ CodeMirror Language Mode Mapping â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    function getCMMode(lang) {
        const l = (lang || "").toLowerCase();
        if (l === "java")               return "text/x-java";
        if (l === "c")                  return "text/x-csrc";
        if (l === "cpp" || l === "c++") return "text/x-c++src";
        if (l === "python" || l === "py") return "python";
        if (l === "javascript" || l === "js") return "javascript";
        if (l === "csharp" || l === "c#") return "text/x-csharp";
        return "text/x-java"; // default
    }

    function isCMModeLoaded(modeName) {
        return !!(window.CodeMirror && CodeMirror.modes && CodeMirror.modes[modeName]);
    }

    function loadScriptOnce(src) {
        return new Promise(function (resolve, reject) {
            const existing = document.querySelector(`script[src="${src}"]`);
            if (existing) {
                if (existing.dataset.loaded === "1") return resolve();
                existing.addEventListener("load", function () { resolve(); }, { once: true });
                existing.addEventListener("error", function () { reject(new Error("Script load failed")); }, { once: true });
                return;
            }

            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.addEventListener("load", function () {
                script.dataset.loaded = "1";
                resolve();
            }, { once: true });
            script.addEventListener("error", function () {
                reject(new Error("Script load failed"));
            }, { once: true });
            document.head.appendChild(script);
        });
    }

    async function ensureDynamicMode(modeName) {
        if (!(modeName === "python" || modeName === "javascript")) return;
        if (isCMModeLoaded(modeName)) return;

        const fallbackSources = {
            python: [
                "https://cdn.jsdelivr.net/npm/codemirror@5.65.18/mode/python/python.min.js",
                "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/python/python.min.js",
            ],
            javascript: [
                "https://cdn.jsdelivr.net/npm/codemirror@5.65.18/mode/javascript/javascript.min.js",
                "https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.18/mode/javascript/javascript.min.js",
            ],
        };

        const sources = fallbackSources[modeName] || [];
        for (const src of sources) {
            try {
                await loadScriptOnce(src);
                if (isCMModeLoaded(modeName)) return;
            } catch (_) {
                // Try next fallback source.
            }
        }
    }

    // â”€â”€ Initialize CodeMirror â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    let cmEditor = null;

    if (textarea && typeof CodeMirror !== "undefined") {
        const cmMode = getCMMode(language);
        cmEditor = CodeMirror.fromTextArea(textarea, {
            mode:              cmMode,
            lineNumbers:       true,
            indentUnit:        4,
            tabSize:           4,
            indentWithTabs:    false,
            smartIndent:       true,
            electricChars:     true,
            autoCloseBrackets: true,
            matchBrackets:     true,
            styleActiveLine:   true,
            lineWrapping:      false,
            viewportMargin:    Infinity,
            scrollbarStyle:    "native",
            extraKeys: {
                "Tab": function (cm) {
                    if (cm.somethingSelected()) {
                        cm.indentSelection("add");
                    } else {
                        cm.replaceSelection("    ", "end");
                    }
                },
                "Shift-Tab": function (cm) {
                    cm.indentSelection("subtract");
                },
                "Ctrl-/":  "toggleComment",
                "Cmd-/":   "toggleComment",
                "Ctrl-S":  function () { doAutoSave(); },
                "Cmd-S":   function () { doAutoSave(); },
            }
        });

        // Sync size
        cmEditor.setSize("100%", "100%");

        // Listen for changes â†’ auto-save
        cmEditor.on("change", function () {
            scheduleAutoSave();
            updateSaveIndicator("unsaved");
        });

        // Ensure Python/JavaScript mode scripts are available even if primary CDN failed.
        ensureDynamicMode(cmMode).then(function () {
            if (cmEditor && isCMModeLoaded(cmMode)) {
                cmEditor.setOption("mode", cmMode);
                cmEditor.refresh();
            }
        });

        // Keep initial viewport pinned to top; focusing the editor can force-scroll down on long prompts.
        setTimeout(function () {
            cmEditor.refresh();
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
        }, 100);

    } else if (textarea) {
        // â”€â”€ Fallback: plain textarea with manual key handling â”€â”€
        textarea.addEventListener("keydown", function (e) {
            if (e.key === "Tab") {
                e.preventDefault();
                const start = this.selectionStart;
                const end = this.selectionEnd;
                const value = this.value;

                if (e.shiftKey) {
                    const beforeCaret = value.substring(0, start);
                    const lineStart = beforeCaret.lastIndexOf("\n") + 1;
                    const linePrefix = value.substring(lineStart, start);
                    if (linePrefix.startsWith("    ")) {
                        this.value = value.substring(0, lineStart) + value.substring(lineStart + 4);
                        this.selectionStart = this.selectionEnd = start - 4;
                    } else if (linePrefix.startsWith("\t")) {
                        this.value = value.substring(0, lineStart) + value.substring(lineStart + 1);
                        this.selectionStart = this.selectionEnd = start - 1;
                    }
                } else {
                    this.value = value.substring(0, start) + "    " + value.substring(end);
                    this.selectionStart = this.selectionEnd = start + 4;
                }
                scheduleAutoSave();
            }

            // Auto-close brackets
            const pairs = { "(": ")", "{": "}", "[": "]", '"': '"', "'": "'" };
            if (pairs[e.key]) {
                const pos = this.selectionStart;
                const val = this.value;
                if ((e.key === '"' || e.key === "'") && val[pos] === e.key) {
                    e.preventDefault();
                    this.selectionStart = this.selectionEnd = pos + 1;
                    return;
                }
                e.preventDefault();
                const close = pairs[e.key];
                this.value = val.substring(0, pos) + e.key + close + val.substring(pos);
                this.selectionStart = this.selectionEnd = pos + 1;
                scheduleAutoSave();
            }

            // Enter key: auto-indent
            if (e.key === "Enter") {
                e.preventDefault();
                const pos = this.selectionStart;
                const val = this.value;
                const beforeCaret = val.substring(0, pos);
                const lineStart = beforeCaret.lastIndexOf("\n") + 1;
                const currentLine = beforeCaret.substring(lineStart);
                const indent = currentLine.match(/^\s*/)[0];
                const lastChar = beforeCaret.trimEnd().slice(-1);
                const extraIndent = (lastChar === "{" || lastChar === "(") ? "    " : "";
                this.value = val.substring(0, pos) + "\n" + indent + extraIndent + val.substring(pos);
                this.selectionStart = this.selectionEnd = pos + 1 + indent.length + extraIndent.length;
                scheduleAutoSave();
            }
        });

        textarea.addEventListener("input", function () {
            scheduleAutoSave();
            updateSaveIndicator("unsaved");
        });
    }

    // â”€â”€ Helper: get / set current code from editor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    function getCode() {
        if (cmEditor) return cmEditor.getValue();
        if (textarea) return textarea.value;
        return "";
    }

    function setCode(code) {
        if (cmEditor) { cmEditor.setValue(code); }
        else if (textarea) { textarea.value = code; }
    }

    // â”€â”€ Auto-Save â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    function scheduleAutoSave() {
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(doAutoSave, 2000);
    }

    async function doAutoSave() {
        const code = getCode();
        if (code === lastSavedCode) return;

        updateSaveIndicator("saving");

        try {
            const resp = await fetch(saveUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ code }),
            });

            if (resp.ok) {
                lastSavedCode = code;
                updateSaveIndicator("saved");
            } else {
                updateSaveIndicator("unsaved");
            }
        } catch (_) {
            updateSaveIndicator("unsaved");
        }
    }

    function updateSaveIndicator(state) {
        if (!saveStatus) return;
        const dot = saveStatus.querySelector(".coding-save-dot");
        const label = saveStatus.querySelector(".coding-save-label");
        if (!dot) return;

        dot.className = "coding-save-dot " + state;
        const labels = { saved: "Saved", saving: "Savingâ€¦", unsaved: "Unsaved" };
        if (label) label.textContent = labels[state] || "";
    }

    function showInlineConfirm(message, options) {
        const opts = options || {};
        const confirmText = opts.confirmText || "Confirm";
        const cancelText = opts.cancelText || "Cancel";
        const dangerClass = opts.danger ? " danger" : "";

        return new Promise(function (resolve) {
            const backdrop = document.createElement("div");
            backdrop.className = "coding-confirm-backdrop";
            backdrop.innerHTML = `
                <div class="coding-confirm-modal${dangerClass}" role="dialog" aria-modal="true" aria-label="Confirmation">
                    <div class="coding-confirm-message">${message}</div>
                    <div class="coding-confirm-actions">
                        <button type="button" class="btn coding-confirm-btn secondary">${cancelText}</button>
                        <button type="button" class="btn coding-confirm-btn primary">${confirmText}</button>
                    </div>
                </div>
            `;
            document.body.appendChild(backdrop);

            const cancelBtn = backdrop.querySelector(".coding-confirm-btn.secondary");
            const confirmBtn = backdrop.querySelector(".coding-confirm-btn.primary");

            function close(result) {
                backdrop.remove();
                resolve(result);
            }

            cancelBtn.addEventListener("click", function () { close(false); });
            confirmBtn.addEventListener("click", function () { close(true); });
            backdrop.addEventListener("click", function (e) {
                if (e.target === backdrop) close(false);
            });

            function onKey(e) {
                if (!document.body.contains(backdrop)) {
                    document.removeEventListener("keydown", onKey);
                    return;
                }
                if (e.key === "Escape") {
                    e.preventDefault();
                    close(false);
                    document.removeEventListener("keydown", onKey);
                }
            }
            document.addEventListener("keydown", onKey);

            setTimeout(function () { confirmBtn.focus(); }, 0);
        });
    }
    async function readJsonResponse(resp, fallbackPrefix) {
        const raw = await resp.text();
        if (!raw) {
            return {
                status: "error",
                output: `${fallbackPrefix} (empty server response).`,
                test_results: [],
            };
        }

        try {
            return JSON.parse(raw);
        } catch (_) {
            const compact = raw
                .replace(/<[^>]+>/g, " ")
                .replace(/\s+/g, " ")
                .trim()
                .slice(0, 220);

            return {
                status: "error",
                output: compact
                    ? `${fallbackPrefix}: ${compact}`
                    : `${fallbackPrefix} (invalid server response).`,
                test_results: [],
            };
        }
    }

    // â”€â”€ Timer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    function formatTime(seconds) {
        const safe = Math.max(0, seconds);
        const m = Math.floor(safe / 60);
        const s = safe % 60;
        return `${m}:${String(s).padStart(2, "0")}`;
    }

    // -- Milestone notice system --
    const timerNoticePrefix = "coding_timer_notice_" + sessionId + "_";
    let noticeTimer = null;

    function hasShownNotice(key) {
        try { return sessionStorage.getItem(timerNoticePrefix + key) === "1"; } catch (_) { return false; }
    }
    function markNoticeShown(key) {
        try { sessionStorage.setItem(timerNoticePrefix + key, "1"); } catch (_) {}
    }

    function showTimerNotice(message, level) {
        const el = document.getElementById("codingTimerNotice");
        if (!el) return;

        el.textContent = message;
        el.className = "coding-timer-notice notice-" + level + " show";

        if (noticeTimer) clearTimeout(noticeTimer);
        noticeTimer = setTimeout(function () {
            el.classList.remove("show");
            noticeTimer = null;
        }, level === "critical" ? 4000 : 5000);
    }

    function checkTimerMilestones(secs) {
        if (secs <= 10 && !hasShownNotice("10s")) {
            markNoticeShown("10s");
            showTimerNotice("âš  Last 10 seconds!", "critical");
        } else if (secs <= 30 && !hasShownNotice("30s")) {
            markNoticeShown("30s");
            showTimerNotice("âš  Last 30 seconds!", "critical");
        } else if (secs <= 60 && !hasShownNotice("1m")) {
            markNoticeShown("1m");
            showTimerNotice("â± Last 1 minute remaining", "danger");
        } else if (secs <= 120 && !hasShownNotice("2m")) {
            markNoticeShown("2m");
            showTimerNotice("â± Last 2 minutes remaining", "danger");
        } else if (secs <= 300 && !hasShownNotice("5m")) {
            markNoticeShown("5m");
            showTimerNotice("ðŸ• 5 minutes remaining", "warning");
        }
    }

    // -- Timer visual tiers: warning â†’ danger â†’ critical --
    function applyTimerVisual(secs) {
        if (!timerWrap) return;
        timerWrap.classList.remove("warning", "danger", "critical");

        if (secs <= 30) {
            timerWrap.classList.add("critical");
        } else if (secs <= 120) {
            timerWrap.classList.add("danger");
        } else if (secs <= 300) {
            timerWrap.classList.add("warning");
        }
    }

    function updateTimer() {
        if (!timerEl) return;

        timerEl.textContent = formatTime(remainingSeconds);
        applyTimerVisual(remainingSeconds);
        checkTimerMilestones(remainingSeconds);

        if (remainingSeconds <= 0) {
            handleTimeExpired();
            return;
        }

        remainingSeconds--;
    }

    function handleTimeExpired() {
        doAutoSave().then(() => { autoSubmit(); });
    }

    async function autoSubmit() {
        try {
            const resp = await fetch(submitUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({ code: getCode() }),
            });

            if (resp.redirected && resp.url) {
                window.location.href = resp.url;
                return;
            }

            const data = await readJsonResponse(resp, "Could not submit test");
            if (data.redirect_url) {
                window.location.href = data.redirect_url;
            } else if (resp.ok) {
                window.location.href = completedUrl;
            } else {
                window.location.href = submitUrl;
            }
        } catch (_) {
            window.location.href = submitUrl;
        }
    }

    setInterval(updateTimer, 1000);
    updateTimer();

    // â”€â”€ Run Hidden Tests â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if (runHiddenBtn) {
        runHiddenBtn.addEventListener("click", async function () {
            if (isRunning) return;
            isRunning = true;

            const origText = runHiddenBtn.innerHTML;
            runHiddenBtn.innerHTML = '<span class="coding-spinner"></span> Running...';
            runHiddenBtn.disabled = true;

            if (outputContent) {
                outputContent.textContent = "Running hidden test cases...";
                outputContent.className = "coding-output-content";
            }

            try {
                const resp = await fetch(runUrl, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: JSON.stringify({
                        code: getCode(),
                        run_hidden: true,
                    }),
                });

                const data = await readJsonResponse(resp, "Error: Could not execute hidden tests");

                if (outputContent) {
                    if (data.status === "error") {
                        outputContent.textContent = data.output || "Error occurred.";
                        outputContent.className = "coding-output-content error";
                    } else if (data.test_results && data.test_results.length > 0) {
                        const passed = data.passed || 0;
                        const total = data.total || data.test_results.length;
                        const allPassed = passed === total;

                        let html = `<div class="coding-run-summary ${allPassed ? 'all-passed' : 'has-failures'}">`;
                        html += `<span class="coding-run-score">${passed}/${total} hidden test cases passed</span>`;
                        if (data.execution_time) html += `<span class="coding-run-time"> Â· ${data.execution_time}</span>`;
                        html += `</div>`;

                        data.test_results.forEach(function(tr) {
                            const icon = tr.passed ? 'âœ…' : 'âŒ';
                            const cls = tr.passed ? 'passed' : 'failed';
                            html += `<div class="coding-tc-result ${cls}">`;
                            html += `<div class="coding-tc-result-header">${icon} Test Case ${tr.index}</div>`;
                            html += `<div class="coding-tc-result-row"><span class="label">Input:</span> <code>${JSON.stringify(tr.input)}</code></div>`;
                            html += `<div class="coding-tc-result-row"><span class="label">Expected:</span> <code>${tr.expected}</code></div>`;
                            if (!tr.passed) {
                                html += `<div class="coding-tc-result-row actual"><span class="label">Actual:</span> <code>${tr.actual}</code></div>`;
                                if (tr.error) html += `<div class="coding-tc-result-row error"><span class="label">Error:</span> <code>${tr.error}</code></div>`;
                            }
                            if (tr.time_ms) html += `<div class="coding-tc-result-row time"><span class="label">Time:</span> ${tr.time_ms}ms</div>`;
                            html += `</div>`;
                        });

                        outputContent.innerHTML = html;
                        outputContent.className = "coding-output-content " + (allPassed ? "success" : "partial");

                        if (scoreEl) scoreEl.textContent = `${passed}/${total}`;
                    } else {
                        outputContent.textContent = data.output || "No output.";
                        outputContent.className = "coding-output-content success";
                    }
                }
            } catch (err) {
                if (outputContent) {
                    outputContent.textContent = "Error: Could not execute code. " + (err.message || "");
                    outputContent.className = "coding-output-content error";
                }
            } finally {
                isRunning = false;
                runHiddenBtn.innerHTML = origText;
                runHiddenBtn.disabled = false;
            }
        });
    }

    // â”€â”€ Run Code â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if (runBtn) {
        runBtn.addEventListener("click", async function () {
            if (isRunning) return;
            isRunning = true;

            const origText = runBtn.innerHTML;
            runBtn.innerHTML = '<span class="coding-spinner"></span> Running...';
            runBtn.disabled = true;

            if (outputContent) {
                outputContent.textContent = "Compiling and running...";
                outputContent.className = "coding-output-content";
            }

            const customInput = document.getElementById("codingCustomInput");

            try {
                const resp = await fetch(runUrl, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: JSON.stringify({
                        code: getCode(),
                        custom_input: customInput ? customInput.value : "",
                    }),
                });

                const data = await readJsonResponse(resp, "Error: Could not execute code");

                if (outputContent) {
                    if (data.status === "error") {
                        outputContent.textContent = data.output || "Error occurred.";
                        outputContent.className = "coding-output-content error";
                    } else if (data.test_results && data.test_results.length > 0) {
                        const passed = data.passed || 0;
                        const total = data.total || data.test_results.length;
                        const allPassed = passed === total;

                        let html = `<div class="coding-run-summary ${allPassed ? 'all-passed' : 'has-failures'}">`;
                        html += `<span class="coding-run-score">${passed}/${total} test cases passed</span>`;
                        if (data.execution_time) html += `<span class="coding-run-time"> Â· ${data.execution_time}</span>`;
                        html += `</div>`;

                        data.test_results.forEach(function(tr) {
                            const icon = tr.passed ? 'âœ…' : 'âŒ';
                            const cls = tr.passed ? 'passed' : 'failed';
                            html += `<div class="coding-tc-result ${cls}">`;
                            html += `<div class="coding-tc-result-header">${icon} Test Case ${tr.index}</div>`;
                            html += `<div class="coding-tc-result-row"><span class="label">Input:</span> <code>${JSON.stringify(tr.input)}</code></div>`;
                            html += `<div class="coding-tc-result-row"><span class="label">Expected:</span> <code>${tr.expected}</code></div>`;
                            if (!tr.passed) {
                                html += `<div class="coding-tc-result-row actual"><span class="label">Actual:</span> <code>${tr.actual}</code></div>`;
                                if (tr.error) html += `<div class="coding-tc-result-row error"><span class="label">Error:</span> <code>${tr.error}</code></div>`;
                            }
                            if (tr.time_ms) html += `<div class="coding-tc-result-row time"><span class="label">Time:</span> ${tr.time_ms}ms</div>`;
                            html += `</div>`;
                        });

                        outputContent.innerHTML = html;
                        outputContent.className = "coding-output-content " + (allPassed ? "success" : "partial");

                        if (scoreEl) scoreEl.textContent = `${passed}/${total}`;
                    } else {
                        outputContent.textContent = data.output || "No output.";
                        outputContent.className = "coding-output-content success";
                    }
                }
            } catch (err) {
                if (outputContent) {
                    outputContent.textContent = "Error: Could not execute code. " + (err.message || "");
                    outputContent.className = "coding-output-content error";
                }
            } finally {
                isRunning = false;
                runBtn.innerHTML = origText;
                runBtn.disabled = false;
            }
        });
    }

    // â”€â”€ Reset Code â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if (resetBtn) {
        resetBtn.addEventListener("click", async function () {
            const confirmed = await showInlineConfirm(
                "Reset your code to the starter template? This cannot be undone.",
                { confirmText: "Reset", cancelText: "Cancel" }
            );
            if (!confirmed) return;

            setCode(starterCode);
            scheduleAutoSave();
            updateSaveIndicator("unsaved");

            if (outputContent) {
                outputContent.textContent = "Code reset to template.";
                outputContent.className = "coding-output-content";
            }
        });
    }

    // â”€â”€ Submit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if (submitBtn) {
        submitBtn.addEventListener("click", async function () {
            const confirmed = await showInlineConfirm(
                "Submit your solution? You won't be able to edit after submission.",
                { confirmText: "Submit", cancelText: "Back", danger: true }
            );
            if (!confirmed) return;

            doAutoSave().then(function () {
                autoSubmit();
            });
        });
    }

    // â”€â”€ Expose CM editor for external access (proctoring) â”€â”€â”€
    window.__codingCMEditor = cmEditor;

})();
