window.__MCQ_AJAX_FLOW = false;

(function () {
    function getSessionIdFromPath() {
        const parts = window.location.pathname.split("/").filter(Boolean);
        const mcqIndex = parts.indexOf("mcq");
        if (mcqIndex >= 0 && parts.length >= (mcqIndex + 3)) {
            return parts[mcqIndex + 2];
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
    const proctoringEnabled = window.__AZIRO_PROCTORING_ENABLED === true;

    window.__MCQ_AJAX_FLOW = true;

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

    function normalizeQuestionText(value) {
        return String(value || "").replace(/\r\n?/g, "\n");
    }

    function trimSurroundingBlankLines(value) {
        return String(value || "")
            .replace(/^\s*\n+/, "")
            .replace(/\n+\s*$/, "");
    }

    function isLikelyNarrativeLine(line) {
        const text = String(line || "").trim();
        if (!text) return false;
        if (!/^[A-Za-z][A-Za-z0-9 ,.'"():!?+\-_/&[\]]+$/.test(text)) return false;
        return /[?.!:]$/.test(text);
    }

    function isLikelyCodeLine(line) {
        const text = String(line || "").trim();
        if (!text) return false;

        if (isLikelyNarrativeLine(text) && !/[{}();=<>[\]]/.test(text)) {
            return false;
        }

        if (/^(\/\/|\/\*|\*|#include\b|#\s|using\s+[A-Za-z0-9_.]+;?|namespace\b|import\s+[A-Za-z0-9_.]+;?)/.test(text)) return true;
        if (/^(class|interface|enum|struct|public|private|protected|static|final|const|let|var|def|if|else|elif|for|while|try|catch|finally|return|throw|new|void|int|long|float|double|char|bool|string)\b/.test(text)) return true;
        if (/\b(Console\.WriteLine|System\.out\.println|console\.log|printf|scanf|print)\s*\(/.test(text)) return true;
        if (/^\w+\s*\(.*\)\s*(\{|=>|;)$/.test(text)) return true;
        if (/=>|::|->/.test(text)) return true;
        if (/[{}]/.test(text)) return true;
        if (/;/.test(text) && (/[=(){}]/.test(text) || /^(return|break|continue|throw)\b/.test(text))) return true;
        if (/^[A-Za-z_][A-Za-z0-9_<>,\[\]\s]*\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+/.test(text)) return true;
        if (/^\w+\.\w+\s*\(/.test(text)) return true;
        // Slash-only endpoint examples inside prose should not be treated as code operators.
        if (/\(.*\)/.test(text) && /[=+\-*%]/.test(text)) return true;
        return false;
    }

    function isStrongCodeLine(line) {
        const text = String(line || "").trim();
        if (!text) return false;
        if (/^(#include\b|using\s+[A-Za-z0-9_.]+;?|namespace\b|class\b|public\b|private\b|protected\b|interface\b|enum\b|struct\b|import\s+[A-Za-z0-9_.]+;?)/.test(text)) return true;
        if (/\b(Console\.WriteLine|System\.out\.println|console\.log|printf|scanf|print)\s*\(/.test(text)) return true;
        if (/[{}]|=>|::|->/.test(text)) return true;
        if (/\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^=]/.test(text)) return true;
        if (/;/.test(text) && (/[=(){}]/.test(text) || /^(return|break|continue|throw)\b/.test(text))) return true;
        return false;
    }

    function looksLikeInlineCodePayload(text) {
        const value = String(text || "").trim();
        if (!value) return false;
        if (isStrongCodeLine(value)) return true;
        if (/^#\s*[A-Za-z_][A-Za-z0-9_]*/.test(value)) return true;
        if (/\b(Console\.WriteLine|System\.out\.println|console\.log|printf|scanf|print)\s*\(/.test(value)) return true;
        if (/[{}]|=>|::|->/.test(value)) return true;
        if (/\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^=]/.test(value)) return true;
        if (/;/.test(value) && (/[=(){}]/.test(value) || /^(return|break|continue|throw)\b/.test(value))) return true;

        // Avoid false positives for prose fragments like:
        // "nouns (e.g., /createUser, /getUser)"
        const hasEndpointStylePath = /\/[A-Za-z][A-Za-z0-9_/-]*/.test(value);
        const hasProseCue = /\b(e\.g\.|i\.e\.|for example|for instance)\b/i.test(value);
        const wordCount = value.split(/\s+/).filter(Boolean).length;
        if (hasEndpointStylePath && (hasProseCue || wordCount >= 4) && !/[{};=]|=>|::|->/.test(value)) {
            return false;
        }

        // Treat function-call style text as code only when identifier is immediately
        // followed by "(" (no prose spacing before bracket).
        if (/^[A-Za-z_][A-Za-z0-9_]*\([^)\n]*\)\s*;?$/.test(value)) return true;
        if (/^[A-Za-z_][A-Za-z0-9_.]*\([^)\n]*\)\s*;?$/.test(value)) return true;

        if (/\b(int|long|float|double|char|bool|string|var|let|const|def|class|public|private|protected)\b/.test(value) && /[()=]/.test(value)) return true;
        return false;
    }

    function extractSingleInlineCodeFragment(text) {
        const source = String(text || "");
        const patterns = [
            /#\s*[A-Za-z_][A-Za-z0-9_]*\s*(?:<[^>]+>|\"[^\"]+\")?/g,
            /\b(?:[A-Za-z_][A-Za-z0-9_<>\[\]]*\s+)?[A-Za-z_][A-Za-z0-9_<>.\[\]]*\s*=\s*[^.?!\n]+?;/g,
            /\b[A-Za-z_][A-Za-z0-9_<>.\[\]]*\([^)\n]*\)\s*;?/g,
            /\b[A-Za-z_][A-Za-z0-9_<>.\[\]]*::[A-Za-z_][A-Za-z0-9_<>.\[\]]*\b/g
        ];

        let best = null;
        patterns.forEach((pattern) => {
            let match = null;
            while ((match = pattern.exec(source)) !== null) {
                const fragment = trimSurroundingBlankLines(match[0] || "");
                if (!fragment) continue;
                if (!looksLikeInlineCodePayload(fragment)) continue;
                if (!best || fragment.length > best.fragment.length) {
                    best = {
                        start: match.index,
                        end: match.index + match[0].length,
                        fragment
                    };
                }
            }
        });
        return best;
    }

    function splitFencedQuestionSegments(text) {
        if (!text.includes("```")) {
            return null;
        }

        const segments = [];
        const fencePattern = /```[^\n`]*\n?([\s\S]*?)```/g;
        let match = null;
        let start = 0;

        while ((match = fencePattern.exec(text)) !== null) {
            const before = trimSurroundingBlankLines(text.slice(start, match.index));
            if (before) {
                segments.push({ type: "text", text: before });
            }

            const code = trimSurroundingBlankLines(match[1] || "");
            if (code) {
                segments.push({ type: "code", text: code });
            }
            start = fencePattern.lastIndex;
        }

        const after = trimSurroundingBlankLines(text.slice(start));
        if (after) {
            segments.push({ type: "text", text: after });
        }

        return segments.length ? segments : null;
    }

    function splitSingleLineQuestionWithInlineCode(text) {
        const normalized = trimSurroundingBlankLines(text);
        const colonIndex = normalized.indexOf(":");
        if (colonIndex >= 0) {
            const prose = trimSurroundingBlankLines(normalized.slice(0, colonIndex + 1));
            let remainder = trimSurroundingBlankLines(normalized.slice(colonIndex + 1));
            if (prose && remainder && looksLikeInlineCodePayload(remainder)) {
                let code = remainder;
                let tail = "";
                const lastSemicolon = remainder.lastIndexOf(";");
                if (lastSemicolon >= 0 && lastSemicolon < remainder.length - 1) {
                    code = trimSurroundingBlankLines(remainder.slice(0, lastSemicolon + 1));
                    tail = trimSurroundingBlankLines(remainder.slice(lastSemicolon + 1));
                } else {
                    const trailingBoundary = Math.max(remainder.lastIndexOf("}"), remainder.lastIndexOf(")"));
                    if (trailingBoundary >= 0 && trailingBoundary < remainder.length - 1) {
                        const possibleTail = trimSurroundingBlankLines(remainder.slice(trailingBoundary + 1));
                        if (possibleTail && !looksLikeInlineCodePayload(possibleTail)) {
                            code = trimSurroundingBlankLines(remainder.slice(0, trailingBoundary + 1));
                            tail = possibleTail;
                        }
                    }
                }

                code = trimSurroundingBlankLines(code.replace(/\?+$/, ""));
                tail = trimSurroundingBlankLines(tail.replace(/^\?+/, ""));
                if (code && looksLikeInlineCodePayload(code)) {
                    const segments = [
                        { type: "text", text: prose },
                        { type: "code", text: code }
                    ];
                    if (tail) {
                        segments.push({ type: "text", text: tail });
                    }
                    return segments;
                }
            }
        }

        const extracted = extractSingleInlineCodeFragment(normalized);
        if (!extracted) {
            return null;
        }

        const prefix = trimSurroundingBlankLines(normalized.slice(0, extracted.start));
        const code = trimSurroundingBlankLines(extracted.fragment.replace(/\?+$/, ""));
        const suffix = trimSurroundingBlankLines(normalized.slice(extracted.end).replace(/^\?+/, ""));
        if (!code || !looksLikeInlineCodePayload(code)) {
            return null;
        }

        const segments = [];
        if (prefix) segments.push({ type: "text", text: prefix });
        segments.push({ type: "code", text: code });
        if (suffix) segments.push({ type: "text", text: suffix });
        return segments.length ? segments : null;
    }

    function findFirstCodeStartIndex(lines) {
        for (let i = 0; i < lines.length; i += 1) {
            const line = String(lines[i] || "").trim();
            if (!line || !isLikelyCodeLine(line)) {
                continue;
            }

            const lookahead = lines.slice(i, i + 7)
                .map((item) => String(item || "").trim())
                .filter((item) => item !== "");
            const strongCount = lookahead.filter((item) => isStrongCodeLine(item)).length;
            const codeLikeCount = lookahead.filter((item) => isLikelyCodeLine(item)).length;
            if (strongCount >= 1 || codeLikeCount >= 2) {
                return i;
            }
        }
        return -1;
    }

    function findLastCodeEndIndex(lines, startIndex) {
        for (let i = lines.length - 1; i >= startIndex; i -= 1) {
            const line = String(lines[i] || "").trim();
            if (!line) {
                continue;
            }
            if (isLikelyCodeLine(line) || isStrongCodeLine(line)) {
                return i;
            }
            if (isLikelyNarrativeLine(line)) {
                continue;
            }
            if (looksLikeInlineCodePayload(line)) {
                return i;
            }
        }
        return -1;
    }

    function splitQuestionSegments(rawText) {
        const normalized = normalizeQuestionText(rawText);
        const fenced = splitFencedQuestionSegments(normalized);
        if (fenced) {
            return fenced;
        }

        if (!normalized.includes("\n")) {
            const inline = splitSingleLineQuestionWithInlineCode(normalized);
            if (inline) {
                return inline;
            }
            return [{ type: "text", text: trimSurroundingBlankLines(normalized) }];
        }

        const lines = normalized.split("\n");
        const codeStart = findFirstCodeStartIndex(lines);
        if (codeStart < 0) {
            return [{ type: "text", text: trimSurroundingBlankLines(normalized) }];
        }

        const codeEnd = findLastCodeEndIndex(lines, codeStart);
        if (codeEnd < codeStart) {
            return [{ type: "text", text: trimSurroundingBlankLines(normalized) }];
        }

        const prefix = trimSurroundingBlankLines(lines.slice(0, codeStart).join("\n"));
        const code = trimSurroundingBlankLines(lines.slice(codeStart, codeEnd + 1).join("\n"));
        const suffix = trimSurroundingBlankLines(lines.slice(codeEnd + 1).join("\n"));

        const nonEmptyCodeLines = code.split("\n").filter((line) => String(line || "").trim() !== "");
        const strongCount = nonEmptyCodeLines.filter((line) => isStrongCodeLine(line)).length;
        const codeLikeCount = nonEmptyCodeLines.filter((line) => isLikelyCodeLine(line)).length;
        if (!code || (strongCount === 0 && codeLikeCount < 2)) {
            return [{ type: "text", text: trimSurroundingBlankLines(normalized) }];
        }

        const segments = [];
        if (prefix) {
            segments.push({ type: "text", text: prefix });
        }
        segments.push({ type: "code", text: code });
        if (suffix) {
            segments.push({ type: "text", text: suffix });
        }
        return segments;
    }

    function _normalizeSectionLabel(label) {
        const raw = String(label || "").trim().toLowerCase();
        const map = {
            "direction": "Direction",
            "directions": "Direction",
            "statement": "Statements",
            "statements": "Statements",
            "conclusion": "Conclusions",
            "conclusions": "Conclusions",
            "assumption": "Assumptions",
            "assumptions": "Assumptions",
            "premise": "Premises",
            "premises": "Premises",
            "question": "Question",
            "data sufficiency": "Data Sufficiency",
            "argument": "Arguments",
            "arguments": "Arguments",
            "course of action": "Courses of Action",
            "courses of action": "Courses of Action",
            "fact": "Facts",
            "facts": "Facts"
        };
        return map[raw] || String(label || "").trim();
    }

    function _extractLeadingDirectionBlock(text) {
        const source = trimSurroundingBlankLines(String(text || ""));
        if (!source) return null;

        const match = source.match(/^\s*\[\s*(Direction|Directions)\s*:\s*([\s\S]*?)\]\s*([\s\S]*)$/i);
        if (!match) return null;

        const directionBody = trimSurroundingBlankLines(match[2] || "");
        const remainder = trimSurroundingBlankLines(match[3] || "");
        if (!directionBody) return null;

        return {
            direction: directionBody,
            remainder
        };
    }

    function _renderReadableText(rawText) {
        let text = trimSurroundingBlankLines(String(rawText || ""));
        if (!text) return "";

        text = text.replace(/\t+/g, " ");
        if (!text.includes("\n") && text.length >= 220) {
            const punctuationCount = (text.match(/[.?!]/g) || []).length;
            if (punctuationCount >= 2) {
                text = text.replace(/([.?!])\s+(?=[A-Z(])/g, "$1\n\n");
            }
        }

        return escapeHtml(text).replace(/\n/g, "<br>");
    }

    function _supportsSentenceList(label) {
        const normalized = String(label || "").trim().toLowerCase();
        return [
            "statements",
            "conclusions",
            "assumptions",
            "premises",
            "arguments",
            "courses of action",
            "facts"
        ].includes(normalized);
    }

    function _splitSentenceItems(text, label) {
        if (!_supportsSentenceList(label)) return [];

        const source = trimSurroundingBlankLines(String(text || ""));
        if (!source) return [];

        const compact = source.replace(/\s+/g, " ").trim();
        if (!compact) return [];

        // Prefer semicolon-delimited items when present.
        let candidates = [];
        if (compact.includes(";")) {
            candidates = compact.split(/\s*;\s*/g);
        } else {
            // Split by sentence boundaries for unnumbered statement-style blocks.
            const separated = compact.replace(/([.?!])\s+(?=[A-Z(“"'])/g, "$1\n");
            candidates = separated.split(/\n+/g);
        }

        const rawItems = candidates
            .map((part) => trimSurroundingBlankLines(part))
            .filter((part) => part && part.length >= 8);

        const items = [];
        const isContinuationFragment = (part) => {
            const text = trimSurroundingBlankLines(String(part || ""));
            if (!text) return false;

            // Merge only genuinely orphaned tails, e.g. "facts." after a bad split.
            // Do not merge valid short conclusions like "None follows".
            const tokenCount = text.split(/\s+/).filter(Boolean).length;
            const startsLowercase = /^[a-z]/.test(text);
            const veryShort = text.length <= 14;
            return startsLowercase && (veryShort || tokenCount <= 3);
        };

        rawItems.forEach((part) => {
            if (items.length > 0 && isContinuationFragment(part)) {
                items[items.length - 1] = `${items[items.length - 1]} ${part}`.trim();
                return;
            }
            items.push(part);
        });

        if (items.length >= 2) {
            return items;
        }
        return [];
    }

    function _toRoman(value) {
        const num = Math.max(1, Number(value) || 1);
        const table = [
            [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"],
            [100, "C"], [90, "XC"], [50, "L"], [40, "XL"],
            [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]
        ];

        let n = num;
        let out = "";
        table.forEach(([base, symbol]) => {
            while (n >= base) {
                out += symbol;
                n -= base;
            }
        });
        return out || "I";
    }

    function _hasExplicitLeadingMarker(item) {
        const text = trimSurroundingBlankLines(String(item || ""));
        if (!text) return false;
        const markerRegex = /^(?:(?:statement|conclusion|assumption|premise|argument|fact|course of action)\s*)?(?:[ivxlcdm]+|\d+|[pqrs]|s\d+)\s*[:.)-]\s*/i;
        const verbalMarkerRegex = /^(?:statement|conclusion|assumption|premise|argument|fact|course of action)\s*(?:[ivxlcdm]+|\d+)\b/i;
        const yesNoMarkerRegex = /^(?:yes|no)\s*[:.)-]\s*/i;
        return markerRegex.test(text) || verbalMarkerRegex.test(text) || yesNoMarkerRegex.test(text);
    }

    function _splitStructuredSections(text) {
        const raw = trimSurroundingBlankLines(normalizeQuestionText(text));
        if (!raw) return null;

        const sections = [];
        let preface = "";
        let normalized = raw;
        const bracketedDirection = _extractLeadingDirectionBlock(normalized);
        if (bracketedDirection) {
            sections.push({ label: "Direction", body: bracketedDirection.direction });
            normalized = bracketedDirection.remainder;
            if (!normalized) {
                return { preface: "", sections };
            }
        }

        const sectionLabelPattern = /(Direction|Directions|Statements?|Conclusions?|Assumptions?|Premises?|Question|Data\s+Sufficiency|Arguments?|Courses?\s+of\s+Action|Facts?|Fact\s+\d+)\s*(?::|[-–—])/ig;
        const sectionStartHints = /(Direction|Directions|Statements?|Conclusions?|Assumptions?|Premises?|Question|Data\s+Sufficiency|Arguments?|Courses?\s+of\s+Action|Facts?|Fact\s+\d+)\s*(?::|[-–—])/ig;

        // If headings are inline, split them onto new lines for stable parsing.
        normalized = normalized.replace(/\s+(?=(Direction|Directions|Statements?|Conclusions?|Assumptions?|Premises?|Question|Data\s+Sufficiency|Arguments?|Courses?\s+of\s+Action|Facts?|Fact\s+\d+)\s*(?::|[-–—]))/ig, "\n");

        const matches = [...normalized.matchAll(sectionLabelPattern)];
        if (!matches.length) {
            const markerItems = _splitStructuredItems(normalized);
            if (markerItems.length >= 2) {
                sections.push({ label: "Question", body: normalized });
                return { preface: "", sections };
            }
            if (sections.length && normalized) {
                sections.push({ label: "Question", body: normalized });
                return { preface: "", sections };
            }
            return null;
        }

        const hasStructuredSignal = sectionStartHints.test(normalized);
        if (!hasStructuredSignal) {
            return sections.length ? { preface: "", sections } : null;
        }
        const firstMatch = matches[0];
        preface = trimSurroundingBlankLines(normalized.slice(0, firstMatch.index));

        for (let i = 0; i < matches.length; i += 1) {
            const current = matches[i];
            const next = matches[i + 1];
            const label = _normalizeSectionLabel(current[1]);
            const start = current.index + current[0].length;
            const end = next ? next.index : normalized.length;
            const body = trimSurroundingBlankLines(normalized.slice(start, end));
            if (!body) continue;
            sections.push({ label, body });
        }

        if (!sections.length) return null;
        return { preface, sections };
    }

    function _splitStructuredItems(text) {
        const source = trimSurroundingBlankLines(String(text || ""));
        if (!source) return [];

        const markerPrefix = "(?:statements?|conclusions?|assumptions?|premises?|arguments?|facts?|courses? of action)";
        const markerRegex = new RegExp(`^(?:${markerPrefix}\\b\\s*)?(?:[ivxlcdm]+|\\d+|[pqrs]|s\\d+)\\s*[:.)-]\\s*`, "i");
        const verbalMarkerRegex = new RegExp(`^(?:${markerPrefix})\\b\\s*(?:[ivxlcdm]+|\\d+)\\b`, "i");
        const yesNoMarkerRegex = /^(?:yes|no)\s*[:.)-]\s*/i;

        const numericMarkerCount = (source.match(/\b\d+\s*[:.)-]/g) || []).length;
        let injected = source.replace(
            /\s+(?=(?:(?:statements?|conclusions?|assumptions?|premises?|arguments?|facts?|courses? of action)\b\s*)?(?:[ivxlcdm]+|[pqrs]|s\d+)\s*[:.)-])/ig,
            "\n"
        );
        injected = injected.replace(
            /\s+(?=(?:statements?|conclusions?|assumptions?|premises?|arguments?|facts?|courses? of action)\b\s*(?:[ivxlcdm]+|\d+)\b)/ig,
            "\n"
        );
        if (numericMarkerCount >= 2) {
            injected = injected.replace(
                /\s+(?=(?:(?:statements?|conclusions?|assumptions?|premises?|arguments?|facts?|courses? of action)\b\s*)?\d+\s*[:.)-])/ig,
                "\n"
            );
        }
        const yesNoMarkerCount = (source.match(/\b(?:yes|no)\s*[:.)-]/ig) || []).length;
        if (yesNoMarkerCount >= 2) {
            injected = injected.replace(
                /\s+(?=(?:yes|no)\s*[:.)-])/ig,
                "\n"
            );
        }

        const lines = injected
            .split(/\n+/)
            .map((line) => trimSurroundingBlankLines(line))
            .filter(Boolean);

        const items = [];
        let current = "";
        lines.forEach((line) => {
            if (markerRegex.test(line) || verbalMarkerRegex.test(line) || yesNoMarkerRegex.test(line)) {
                if (current) items.push(current);
                current = line;
                return;
            }
            if (current) {
                current = `${current} ${line}`.trim();
            } else {
                items.push(line);
            }
        });
        if (current) items.push(current);

        for (let i = 0; i < items.length - 1; i += 1) {
            items[i] = items[i].replace(/\s+(and|or)\s*$/i, "").trim();
        }

        const markerHits = items.filter((item) => markerRegex.test(item) || verbalMarkerRegex.test(item) || yesNoMarkerRegex.test(item)).length;
        if (items.length >= 2 && markerHits >= 2) {
            return items;
        }
        return [];
    }

    function renderStructuredQuestionHtml(rawText) {
        const structured = _splitStructuredSections(rawText);
        if (!structured) return "";

        const blocks = [];
        if (structured.preface) {
            blocks.push(
                `<p class="mcq-question-paragraph">${_renderReadableText(structured.preface)}</p>`
            );
        }

        structured.sections.forEach((section) => {
            const label = escapeHtml(section.label);
            const body = section.body;
            const lowerLabel = section.label.toLowerCase();

            if (lowerLabel === "direction") {
                blocks.push(
                    `<section class="mcq-question-section mcq-question-direction">` +
                    `<div class="mcq-question-section-title">${label}</div>` +
                    `<p class="mcq-question-paragraph">${_renderReadableText(body)}</p>` +
                    `</section>`
                );
                return;
            }

            const items = _splitStructuredItems(body);
            const sentenceItems = items.length >= 2 ? items : _splitSentenceItems(body, lowerLabel);
            if (sentenceItems.length >= 2) {
                const shouldAutoEnumerate = _supportsSentenceList(lowerLabel) && sentenceItems.every((item) => !_hasExplicitLeadingMarker(item));
                const listItems = sentenceItems
                    .map((item, index) => {
                        const rendered = shouldAutoEnumerate
                            ? `${_toRoman(index + 1)}. ${item}`
                            : item;
                        return `<li class="mcq-question-list-item">${_renderReadableText(rendered)}</li>`;
                    })
                    .join("");
                blocks.push(
                    `<section class="mcq-question-section">` +
                    `<div class="mcq-question-section-title">${label}</div>` +
                    `<ul class="mcq-question-list">${listItems}</ul>` +
                    `</section>`
                );
                return;
            }

            blocks.push(
                `<section class="mcq-question-section">` +
                `<div class="mcq-question-section-title">${label}</div>` +
                `<p class="mcq-question-paragraph">${_renderReadableText(body)}</p>` +
                `</section>`
            );
        });

        return blocks.join("");
    }

    function renderQuestionTextHtml(rawText) {
        const segments = splitQuestionSegments(rawText);
        if (!segments.length) {
            return `<p class="mcq-question-paragraph"></p>`;
        }

        return segments.map((segment) => {
            if (segment.type === "code") {
                return `<pre class="mcq-question-code"><code>${escapeHtml(segment.text)}</code></pre>`;
            }
            const structuredHtml = renderStructuredQuestionHtml(segment.text);
            if (structuredHtml) {
                return structuredHtml;
            }
            return `<p class="mcq-question-paragraph">${_renderReadableText(segment.text)}</p>`;
        }).join("");
    }

    function applyQuestionTextFormattingToDom() {
        const questionTextEl = document.getElementById("mcqQuestionText");
        if (!questionTextEl) return;

        let rawText = questionTextEl.dataset.rawQuestion || "";
        if (!rawText) {
            const rawJsonNode = document.getElementById("mcqQuestionTextRaw");
            if (rawJsonNode && rawJsonNode.textContent) {
                try {
                    rawText = JSON.parse(rawJsonNode.textContent);
                } catch (_) {
                    rawText = rawJsonNode.textContent;
                }
                rawJsonNode.remove();
            }
        }
        if (!rawText) {
            rawText = questionTextEl.textContent || "";
        }
        questionTextEl.dataset.rawQuestion = rawText;
        questionTextEl.innerHTML = renderQuestionTextHtml(rawText);
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
            <div id="mcqQuestionText" class="mcq-question-title">
                ${renderQuestionTextHtml(questionData.question_text)}
            </div>
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

        if (proctoringEnabled && typeof window.setupExamProctoring === "function") {
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

        if (proctoringEnabled && typeof window.setupExamProctoring === "function") {
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
                let proctoringReady = true;
                if (proctoringEnabled) {
                    proctoringReady = false;
                    if (typeof window.ensureProctoringReady === "function") {
                        proctoringReady = await window.ensureProctoringReady({
                            requireScreenShare: true,
                            requireFullscreen: true,
                            requireWebcam: true,
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
                }
                if (!proctoringReady) {
                    // Screen share was declined or failed — do NOT start the test.
                    if (startButton) startButton.disabled = false;
                    return;
                }

                if (proctoringEnabled) {
                    try {
                        sessionStorage.setItem(`mcq_fullscreen_required_${sessionId}`, "1");
                    } catch (_) {
                        // Ignore storage failures.
                    }
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

        applyQuestionTextFormattingToDom();

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
