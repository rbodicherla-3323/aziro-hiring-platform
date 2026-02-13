window.__MCQ_AJAX_FLOW = true;

(function () {
    function getSessionIdFromPath() {
        const parts = window.location.pathname.split("/").filter(Boolean);
        if (parts.length >= 3 && parts[0] === "mcq") {
            return parts[2];
        }
        return "";
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatTime(sec) {
        const safe = Math.max(0, Number(sec) || 0);
        const m = Math.floor(safe / 60);
        const s = safe % 60;
        return `${m}:${String(s).padStart(2, "0")}`;
    }

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        if (!response.ok) {
            throw new Error(`Request failed: ${response.status}`);
        }
        return response.json();
    }

    function ajaxHeaders(extra) {
        const base = { "X-Requested-With": "XMLHttpRequest" };
        return Object.assign(base, extra || {});
    }

    const sessionId = getSessionIdFromPath();
    if (!sessionId) {
        return;
    }

    const page = document.querySelector(".page");
    if (!page) {
        return;
    }

    const state = {
        sessionId,
        qIndex: null,
        totalQuestions: null,
        remainingSeconds: null,
        submitUrl: `/mcq/submit/${sessionId}`,
        timerId: null,
        answeredQuestions: new Set(),
        reviewedQuestions: new Set(),
        timerNoticeTimer: null
    };

    const lastQuestionIndexKey = `mcq_last_q_index_${sessionId}`;
    const reviewedQuestionsKey = `mcq_reviewed_questions_${sessionId}`;
    const timerNoticePrefix = `mcq_timer_notice_${sessionId}_`;
    const navInProgressKey = `mcq_nav_in_progress_${sessionId}`;
    const timeExpiredKey = `mcq_time_expired_${sessionId}`;

    function persistLastQuestionIndex(index) {
        try {
            sessionStorage.setItem(lastQuestionIndexKey, String(Math.max(0, Number(index) || 0)));
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function getLastQuestionIndex() {
        try {
            const raw = sessionStorage.getItem(lastQuestionIndexKey);
            if (raw === null || raw === "") return null;
            const parsed = Number(raw);
            return Number.isNaN(parsed) ? null : Math.max(0, parsed);
        } catch (_) {
            return null;
        }
    }

    function buildQuestionUrl(index) {
        const safeIndex = Math.max(0, Number(index) || 0);
        return `/mcq/question/${encodeURIComponent(sessionId)}?q=${safeIndex}`;
    }

    function setNavInProgressFlag(value) {
        try {
            if (value) {
                sessionStorage.setItem(navInProgressKey, "1");
            } else {
                sessionStorage.removeItem(navInProgressKey);
            }
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function setTimeExpiredFlag(value) {
        try {
            if (value) {
                sessionStorage.setItem(timeExpiredKey, "1");
            } else {
                sessionStorage.removeItem(timeExpiredKey);
            }
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function isTimeExpired() {
        try {
            return sessionStorage.getItem(timeExpiredKey) === "1";
        } catch (_) {
            return false;
        }
    }

    function loadReviewedQuestions() {
        try {
            const raw = sessionStorage.getItem(reviewedQuestionsKey);
            if (!raw) return;
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
                parsed.forEach((index) => {
                    const safe = Number(index);
                    if (!Number.isNaN(safe) && safe >= 0) {
                        state.reviewedQuestions.add(safe);
                    }
                });
            }
        } catch (_) {
            // Ignore storage/JSON failures.
        }
    }

    function persistReviewedQuestions() {
        try {
            const payload = Array.from(state.reviewedQuestions).sort((a, b) => a - b);
            sessionStorage.setItem(reviewedQuestionsKey, JSON.stringify(payload));
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function hasShownTimerNotice(milestoneKey) {
        try {
            return sessionStorage.getItem(`${timerNoticePrefix}${milestoneKey}`) === "1";
        } catch (_) {
            return false;
        }
    }

    function markTimerNoticeShown(milestoneKey) {
        try {
            sessionStorage.setItem(`${timerNoticePrefix}${milestoneKey}`, "1");
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function showTimerNotice(message) {
        const notice = document.getElementById("mcqTimerNotice");
        if (!notice) return;

        notice.textContent = message;
        notice.classList.add("show");

        if (state.timerNoticeTimer) {
            window.clearTimeout(state.timerNoticeTimer);
        }

        state.timerNoticeTimer = window.setTimeout(() => {
            notice.classList.remove("show");
            state.timerNoticeTimer = null;
        }, 5000);
    }

    function maybeShowTimerMilestoneNotice(remainingSeconds) {
        if (remainingSeconds <= 10 && !hasShownTimerNotice("10s")) {
            markTimerNoticeShown("10s");
            showTimerNotice("Last 10 secs left");
            return;
        }

        if (remainingSeconds <= 60 && !hasShownTimerNotice("1m")) {
            markTimerNoticeShown("1m");
            showTimerNotice("Last 1 min left");
            return;
        }

        if (remainingSeconds <= 120 && !hasShownTimerNotice("2m")) {
            markTimerNoticeShown("2m");
            showTimerNotice("Last 2 mins left");
            return;
        }

        if (remainingSeconds <= 300 && !hasShownTimerNotice("5m")) {
            markTimerNoticeShown("5m");
            showTimerNotice("Last 5 mins left");
        }
    }

    function applySubmitBackButtonState() {
        const backBtn = document.getElementById("mcqBackToTestBtn");
        if (!backBtn) return;

        const expired = isTimeExpired();
        backBtn.disabled = expired;
        backBtn.classList.toggle("is-disabled", expired);
        backBtn.title = expired ? "Timer completed. Going back is disabled." : "";
    }

    function setBodyView(view) {
        const body = document.body;
        if (!body) return;

        body.classList.remove("mcq-start-page", "mcq-question-page", "mcq-submit-page", "mcq-question-screen");
        if (view === "start") {
            body.classList.add("mcq-start-page");
            return;
        }
        if (view === "question") {
            body.classList.add("mcq-question-page", "mcq-question-screen");
            return;
        }
        if (view === "submit") {
            body.classList.add("mcq-submit-page");
        }
    }

    function setPageMode(mode) {
        page.classList.remove("mcq-page-wide", "mcq-page-centered");
        if (mode === "wide") {
            page.classList.add("mcq-page-wide");
        } else {
            page.classList.add("mcq-page-centered");
        }
    }

    function applyTimerVisual(timerEl, remainingSeconds) {
        if (!timerEl) {
            return;
        }

        timerEl.classList.remove("timer-warn", "timer-danger", "timer-critical");

        if (remainingSeconds <= 30) {
            timerEl.classList.add("timer-critical");
            return;
        }

        if (remainingSeconds <= 120) {
            timerEl.classList.add("timer-danger");
            return;
        }

        if (remainingSeconds <= 300) {
            timerEl.classList.add("timer-warn");
        }
    }

    function updateProgressSummary() {
        if (state.qIndex === null || state.totalQuestions === null) {
            return;
        }

        const answered = Math.min(state.totalQuestions, state.answeredQuestions.size);
        const reviewed = Math.min(state.totalQuestions, state.reviewedQuestions.size);
        const remaining = Math.max(0, state.totalQuestions - answered);
        const summary = `Question ${state.qIndex + 1} of ${state.totalQuestions} | Answered ${answered} | Review ${reviewed} | Remaining ${remaining}`;

        const progress = document.getElementById("mcqProgress");
        if (progress) {
            progress.innerText = summary;
        }

        const progressBar = document.getElementById("mcqProgressBar");
        if (progressBar) {
            const pct = state.totalQuestions > 0 ? Math.round((answered / state.totalQuestions) * 100) : 0;
            progressBar.style.width = `${pct}%`;
        }
    }

    function seedAnsweredFromPalette() {
        document.querySelectorAll(".mcq-nav-btn.answered[data-go]").forEach((btn) => {
            const idx = Number(btn.dataset.go || "0");
            if (!Number.isNaN(idx)) {
                state.answeredQuestions.add(idx);
            }
        });
    }

    function syncPaletteButtonStates() {
        const buttons = document.querySelectorAll(".mcq-nav-btn[data-go]");
        buttons.forEach((btn) => {
            const idx = Number(btn.dataset.go || "0");
            if (Number.isNaN(idx)) return;

            btn.classList.toggle("active", idx === Number(state.qIndex));
            btn.classList.toggle("answered", state.answeredQuestions.has(idx));
            btn.classList.toggle("reviewed", state.reviewedQuestions.has(idx));
        });
    }

    function updateReviewButtonLabel() {
        const reviewBtn = document.getElementById("mcqReviewBtn");
        if (!reviewBtn || state.qIndex === null) return;

        const reviewed = state.reviewedQuestions.has(Number(state.qIndex));
        reviewBtn.textContent = reviewed ? "Unmark Review" : "Mark for Review";
        reviewBtn.classList.toggle("is-reviewed", reviewed);
    }

    function toggleReviewForCurrentQuestion() {
        if (state.qIndex === null) return;

        const idx = Number(state.qIndex);
        if (state.reviewedQuestions.has(idx)) {
            state.reviewedQuestions.delete(idx);
        } else {
            state.reviewedQuestions.add(idx);
        }

        persistReviewedQuestions();
        updateReviewButtonLabel();
        syncPaletteButtonStates();
        updateProgressSummary();
    }

    function startOrSyncTimer(remainingSeconds) {
        const incoming = Math.max(0, Number(remainingSeconds) || 0);
        if (state.remainingSeconds === null) {
            state.remainingSeconds = incoming;
        } else {
            state.remainingSeconds = Math.min(state.remainingSeconds, incoming);
        }

        if (state.remainingSeconds > 0) {
            setTimeExpiredFlag(false);
        }

        const update = () => {
            const timer = document.getElementById("timer");
            if (timer) {
                timer.innerText = `Time left: ${formatTime(state.remainingSeconds)}`;
                applyTimerVisual(timer, state.remainingSeconds);
            }
            maybeShowTimerMilestoneNotice(state.remainingSeconds);
        };

        update();

        if (state.timerId) {
            return;
        }

        state.timerId = window.setInterval(() => {
            state.remainingSeconds = Math.max(0, (state.remainingSeconds || 0) - 1);
            update();

            if (state.remainingSeconds <= 0) {
                window.clearInterval(state.timerId);
                state.timerId = null;
                setTimeExpiredFlag(true);
                window.location.href = state.submitUrl;
            }
        }, 1000);
    }

    function buildOptionsHtml(options, selectedAnswer) {
        return options.map((option) => {
            const selected = selectedAnswer === option ? "checked" : "";
            const escaped = escapeHtml(option);
            return `
            <label class="mcq-option">
                <input type="radio"
                       name="answer"
                       value="${escaped}"
                       ${selected}>
                <span class="mcq-option-text">${escaped}</span>
            </label>`;
        }).join("");
    }

    function buildPaletteHtml(totalQuestions, currentIndex) {
        const buttons = [];
        for (let i = 0; i < totalQuestions; i += 1) {
            const active = i === currentIndex ? " active" : "";
            const answered = state.answeredQuestions.has(i) ? " answered" : "";
            const reviewed = state.reviewedQuestions.has(i) ? " reviewed" : "";
            buttons.push(`
                <button type="button"
                        class="mcq-nav-btn${active}${answered}${reviewed}"
                        data-go="${i}"
                        aria-label="Go to question ${i + 1}">
                    ${i + 1}
                </button>`);
        }
        return buttons.join("");
    }

    function buildActionsHtml(qIndex, totalQuestions) {
        const isLast = qIndex + 1 === totalQuestions;
        const prev = qIndex > 0 ? `
            <button type="submit"
                    name="nav"
                    value="prev"
                    class="btn btn-danger px-4">
                Previous
            </button>` : "";
        const isReviewed = state.reviewedQuestions.has(Number(qIndex));
        const reviewLabel = isReviewed ? "Unmark Review" : "Mark for Review";
        const reviewClass = isReviewed ? "btn btn-secondary px-4 is-reviewed" : "btn btn-secondary px-4";

        return `
        <div id="mcqActions" class="mcq-actions">
            ${prev}
            <button type="button" id="mcqReviewBtn" class="${reviewClass}">
                ${reviewLabel}
            </button>
            <button type="submit"
                    name="nav"
                    value="next"
                    class="btn btn-primary px-4">
                ${isLast ? "Submit" : "Next"}
            </button>
        </div>`;
    }

    function rememberAnswer(questionData) {
        if (questionData && questionData.selected_answer) {
            state.answeredQuestions.add(Number(questionData.q_index));
        }
    }

    function renderQuestion(questionData) {
        // Suppress content-change screenshots during legitimate question navigation
        if (typeof window.suppressContentChangeDetection === "function") {
            window.suppressContentChangeDetection(2000);
        }

        state.qIndex = questionData.q_index;
        state.totalQuestions = questionData.total_questions;
        state.submitUrl = questionData.submit_url || state.submitUrl;
        persistLastQuestionIndex(state.qIndex);
        rememberAnswer(questionData);

        setPageMode("wide");
        setBodyView("question");

        page.innerHTML = `
<div id="mcqQuestionView"
     data-session-id="${escapeHtml(sessionId)}"
     data-q-index="${questionData.q_index}"
     data-total-questions="${questionData.total_questions}"
     data-remaining-seconds="${questionData.remaining_seconds}"
     data-submit-url="${escapeHtml(state.submitUrl)}"
     class="mcq-shell">

    <aside class="mcq-nav-panel">
        <h4 class="mcq-nav-title">Question Palette</h4>
        <div id="mcqProgress" class="mcq-nav-subtitle">
            Question ${questionData.q_index + 1} of ${questionData.total_questions}
        </div>
        <div class="mcq-progress-track" aria-hidden="true">
            <div id="mcqProgressBar" class="mcq-progress-fill"></div>
        </div>
        <div id="mcqNavGrid" class="mcq-nav-grid">
            ${buildPaletteHtml(questionData.total_questions, questionData.q_index)}
        </div>
        <div class="mcq-nav-legend">
            <span class="legend-chip current">Current</span>
            <span class="legend-chip answered">Answered</span>
            <span class="legend-chip reviewed">Marked</span>
        </div>
    </aside>

    <section class="mcq-main-panel">
        <div class="mcq-top-strip">
            <span class="mcq-top-chip">Aziro Enterprise Assessment</span>
            <div id="timer" class="mcq-top-timer">Time left: --</div>
            <div id="mcqTimerNotice" class="mcq-timer-notice" role="status" aria-live="polite"></div>
        </div>

        <div class="card mcq-question-card">
            <div class="mcq-question-number">Question ${questionData.q_index + 1}</div>
            <h3 id="mcqQuestionText" class="mcq-question-title">
                ${escapeHtml(questionData.question_text)}
            </h3>
            <div class="mcq-question-help">
                Select the best answer. You can revisit questions using the palette.
            </div>

            <form id="mcqQuestionForm"
                  method="POST"
                  action="/mcq/question/${encodeURIComponent(sessionId)}?q=${questionData.q_index}">
                <div id="mcqOptionsContainer" class="mcq-options">
                    ${buildOptionsHtml(questionData.options || [], questionData.selected_answer)}
                </div>
                ${buildActionsHtml(questionData.q_index, questionData.total_questions)}
            </form>
        </div>
    </section>
</div>`;

        updateProgressSummary();
        startOrSyncTimer(questionData.remaining_seconds);
        history.replaceState({}, "", questionData.question_url || `/mcq/question/${sessionId}?q=${questionData.q_index}`);
        syncPaletteButtonStates();
        bindQuestionForm();
        bindPaletteEvents();
        updateReviewButtonLabel();

        if (typeof window.setupExamProctoring === "function") {
            window.setupExamProctoring();
        }
    }

    function renderSubmitCard() {
        // Suppress content-change screenshots during legitimate navigation
        if (typeof window.suppressContentChangeDetection === "function") {
            window.suppressContentChangeDetection(2000);
        }

        setPageMode("centered");
        setBodyView("submit");

        const total = Math.max(0, Number(state.totalQuestions) || 0);
        const answered = Math.min(total, state.answeredQuestions.size);
        const reviewed = Math.min(total, state.reviewedQuestions.size);
        const unanswered = Math.max(0, total - answered);
        const metrics = total > 0 ? `
        <div class="mcq-submit-metrics">
            <span class="mcq-metric-chip">Answered: ${answered}</span>
            <span class="mcq-metric-chip">Marked: ${reviewed}</span>
            <span class="mcq-metric-chip">Unanswered: ${unanswered}</span>
        </div>` : "";

        page.innerHTML = `
<div class="mcq-submit-shell">
    <div class="card mcq-submit-card">
        <div class="mcq-brand-row" style="justify-content:center;">
            <img class="mcq-inline-logo" src="/static/images/azirotech_logo.jpg" alt="Aziro logo">
            <div class="mcq-brand-copy">Aziro Enterprise Hiring Platform</div>
        </div>

        <h2 class="mcq-submit-title">Review & Submit</h2>
        ${metrics}

        <p class="mcq-submit-text" style="margin-top:10px;">
            You have reached the end of this assessment.
        </p>

        <p class="mcq-submit-text" style="margin-top:8px;">
            Once submitted, you will <strong>not</strong> be able to change your answers.
        </p>

        <div class="mcq-submit-warning">
            Final check: confirm you have reviewed all attempted questions.
        </div>

        <div class="actions mcq-submit-actions">
            <button id="mcqBackToTestBtn" type="button" class="btn btn-secondary">Back to Test</button>
            <button id="mcqConfirmSubmitBtn" class="btn btn-danger">Confirm & Submit</button>
        </div>
    </div>
</div>`;

        history.replaceState({}, "", state.submitUrl);

        const backBtn = document.getElementById("mcqBackToTestBtn");
        const submitBtn = document.getElementById("mcqConfirmSubmitBtn");
        applySubmitBackButtonState();
        if (backBtn) {
            backBtn.addEventListener("click", async () => {
                if (isTimeExpired()) return;
                const saved = getLastQuestionIndex();
                const target = state.qIndex !== null ? state.qIndex : (saved !== null ? saved : 0);
                try {
                    const data = await fetchJson(buildQuestionUrl(target), {
                        method: "GET",
                        headers: ajaxHeaders(),
                        credentials: "same-origin"
                    });

                    if (data.done) {
                        setNavInProgressFlag(true);
                        window.location.href = buildQuestionUrl(target);
                        return;
                    }

                    renderQuestion(data.question);
                } catch (_) {
                    setNavInProgressFlag(true);
                    window.location.href = buildQuestionUrl(target);
                }
            });
        }

        if (!submitBtn) return;

        submitBtn.addEventListener("click", async () => {
            submitBtn.disabled = true;
            try {
                const data = await fetchJson(state.submitUrl, {
                    method: "POST",
                    headers: ajaxHeaders(),
                    credentials: "same-origin"
                });
                window.location.href = data.redirect_url || `/mcq/completed/${sessionId}`;
            } catch (_) {
                window.location.href = state.submitUrl;
            }
        });

        if (typeof window.setupExamProctoring === "function") {
            window.setupExamProctoring();
        }
    }

    async function navigateQuestion(nav, answer) {
        const url = `/mcq/question/${encodeURIComponent(sessionId)}?q=${state.qIndex || 0}`;
        const body = new URLSearchParams();
        body.set("nav", nav);
        if (answer) {
            body.set("answer", answer);
            if (state.qIndex !== null) {
                state.answeredQuestions.add(Number(state.qIndex));
            }
        }

        const data = await fetchJson(url, {
            method: "POST",
            headers: ajaxHeaders({
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
            }),
            credentials: "same-origin",
            body: body.toString()
        });

        if (data.done) {
            state.submitUrl = data.submit_url || state.submitUrl;
            renderSubmitCard();
            return;
        }

        renderQuestion(data.question);
    }

    async function saveCurrentAnswerBeforeJump(targetIndex) {
        const form = document.getElementById("mcqQuestionForm");
        if (!form || state.qIndex === null || targetIndex === state.qIndex) return;

        const selected = form.querySelector('input[name="answer"]:checked');
        if (!selected) return;

        const body = new URLSearchParams();
        body.set("answer", selected.value);
        body.set("nav", targetIndex < state.qIndex ? "prev" : "next");

        try {
            state.answeredQuestions.add(Number(state.qIndex));
            await fetchJson(`/mcq/question/${encodeURIComponent(sessionId)}?q=${state.qIndex}`, {
                method: "POST",
                headers: ajaxHeaders({
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                }),
                credentials: "same-origin",
                body: body.toString()
            });
        } catch (_) {
            // Ignore pre-save failures and continue jump.
        }
    }

    async function goToQuestion(targetIndex) {
        if (state.totalQuestions === null) return;
        if (targetIndex < 0 || targetIndex >= state.totalQuestions) return;
        if (targetIndex === state.qIndex) return;

        await saveCurrentAnswerBeforeJump(targetIndex);

        const data = await fetchJson(`/mcq/question/${encodeURIComponent(sessionId)}?q=${targetIndex}`, {
            method: "GET",
            headers: ajaxHeaders(),
            credentials: "same-origin"
        });

        if (data.done) {
            state.submitUrl = data.submit_url || state.submitUrl;
            renderSubmitCard();
            return;
        }

        renderQuestion(data.question);
    }

    function bindPaletteEvents() {
        document.querySelectorAll(".mcq-nav-btn[data-go]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const target = Number(btn.dataset.go || "0");
                if (Number.isNaN(target)) return;

                btn.disabled = true;
                try {
                    await goToQuestion(target);
                } catch (_) {
                    window.location.href = `/mcq/question/${encodeURIComponent(sessionId)}?q=${target}`;
                } finally {
                    btn.disabled = false;
                }
            });
        });
    }

    function bindQuestionForm() {
        const form = document.getElementById("mcqQuestionForm");
        if (!form) return;

        const reviewBtn = document.getElementById("mcqReviewBtn");
        if (reviewBtn) {
            reviewBtn.addEventListener("click", (e) => {
                e.preventDefault();
                toggleReviewForCurrentQuestion();
            });
        }

        form.querySelectorAll('input[name="answer"]').forEach((input) => {
            input.addEventListener("change", () => {
                if (state.qIndex === null) return;
                state.answeredQuestions.add(Number(state.qIndex));
                syncPaletteButtonStates();
                updateProgressSummary();
            });
        });

        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            e.stopImmediatePropagation();

            const submitter = e.submitter;
            const nav = submitter && submitter.value === "prev" ? "prev" : "next";
            const selected = form.querySelector('input[name="answer"]:checked');

            if (submitter) {
                submitter.disabled = true;
            }

            try {
                await navigateQuestion(nav, selected ? selected.value : "");
            } catch (_) {
                window.location.href = form.action;
            } finally {
                if (submitter) {
                    submitter.disabled = false;
                }
            }
        }, true);
    }

    async function bootstrapFromStartPage() {
        const startForm = document.getElementById("mcqStartForm");
        if (!startForm) {
            return false;
        }

        setPageMode("centered");
        setBodyView("start");

        startForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            e.stopImmediatePropagation();

            const startButton = startForm.querySelector("button[type='submit']");
            if (startButton) {
                startButton.disabled = true;
            }

            try {
                let proctoringReady = false;
                if (typeof window.ensureProctoringReady === "function") {
                    proctoringReady = await window.ensureProctoringReady({
                        requireScreenShare: true,
                        requireFullscreen: true,
                        withOverlay: false
                    });
                } else {
                    if (typeof window.requestAppFullscreen === "function" && !document.fullscreenElement) {
                        await window.requestAppFullscreen();
                    } else if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
                        await document.documentElement.requestFullscreen();
                    }
                    proctoringReady = !!document.fullscreenElement;
                }

                if (!proctoringReady) {
                    alert("Share Entire Screen and fullscreen are required to start the test.");
                    if (startButton) {
                        startButton.disabled = false;
                    }
                    return;
                }

                // Acquire webcam NOW (inside fullscreen) so that
                // setupExamProctoring() finds it already active and
                // never needs to exit fullscreen for it.
                if (navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function") {
                    try {
                        const wStream = await navigator.mediaDevices.getUserMedia({
                            video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 180 } },
                            audio: false
                        });
                        // Store on the proctoring module's global so
                        // setupExamProctoring sees it as already active.
                        if (typeof window.__proctoringSetWebcam === "function") {
                            window.__proctoringSetWebcam(wStream);
                        }
                    } catch (_) {
                        // Webcam is optional — continue even if denied
                    }
                }

                try {
                    sessionStorage.setItem(`mcq_fullscreen_required_${sessionId}`, "1");
                } catch (_) {
                    // Ignore storage failures.
                }

                const data = await fetchJson(
                    `/mcq/question/${encodeURIComponent(sessionId)}?q=0`,
                    {
                        method: "GET",
                        headers: ajaxHeaders(),
                        credentials: "same-origin"
                    }
                );

                if (data.done) {
                    state.submitUrl = data.submit_url || state.submitUrl;
                    renderSubmitCard();
                    return;
                }

                renderQuestion(data.question);
            } catch (_) {
                alert("Unable to start the test. Please click Start Test again.");
                if (startButton) {
                    startButton.disabled = false;
                }
            }
        }, true);

        return true;
    }

    function bootstrapFromQuestionPage() {
        const view = document.getElementById("mcqQuestionView");
        if (!view) {
            return;
        }

        setPageMode("wide");
        setBodyView("question");

        state.qIndex = Number(view.dataset.qIndex || 0);
        state.totalQuestions = Number(view.dataset.totalQuestions || 0);
        state.submitUrl = view.dataset.submitUrl || state.submitUrl;
        persistLastQuestionIndex(state.qIndex);
        seedAnsweredFromPalette();

        const selected = document.querySelector('#mcqQuestionForm input[name="answer"]:checked');
        if (selected) {
            state.answeredQuestions.add(Number(state.qIndex));
        }

        syncPaletteButtonStates();
        updateReviewButtonLabel();
        updateProgressSummary();
        startOrSyncTimer(Number(view.dataset.remainingSeconds || 0));
        bindQuestionForm();
        bindPaletteEvents();
    }

    function bootstrapFromSubmitPage() {
        const submitView = document.getElementById("mcqSubmitView");
        if (!submitView) {
            return false;
        }

        setPageMode("centered");
        setBodyView("submit");

        const backBtn = document.getElementById("mcqBackToTestBtn");
        applySubmitBackButtonState();
        if (backBtn) {
            backBtn.addEventListener("click", async () => {
                if (isTimeExpired()) return;
                const saved = getLastQuestionIndex();
                const target = saved !== null ? saved : 0;
                try {
                    const data = await fetchJson(buildQuestionUrl(target), {
                        method: "GET",
                        headers: ajaxHeaders(),
                        credentials: "same-origin"
                    });

                    if (data.done) {
                        setNavInProgressFlag(true);
                        window.location.href = buildQuestionUrl(target);
                        return;
                    }

                    renderQuestion(data.question);
                } catch (_) {
                    setNavInProgressFlag(true);
                    window.location.href = buildQuestionUrl(target);
                }
            });
        }

        return true;
    }

    (async function init() {
        loadReviewedQuestions();
        if (window.location.pathname.includes("/mcq/start/")) {
            setTimeExpiredFlag(false);
        }
        const fromStart = await bootstrapFromStartPage();
        if (!fromStart) {
            const fromSubmit = bootstrapFromSubmitPage();
            if (!fromSubmit) {
                bootstrapFromQuestionPage();
            }
        }
    })();
})();

