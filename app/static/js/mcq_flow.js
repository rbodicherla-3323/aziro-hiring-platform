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
        const base = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json"
        };
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

    function submitQuestionFormFallback(form, nav) {
        if (!form) return;

        const existingNav = form.querySelector('input[data-fallback-nav="1"]');
        if (existingNav) {
            existingNav.remove();
        }

        const navInput = document.createElement("input");
        navInput.type = "hidden";
        navInput.name = "nav";
        navInput.value = nav || "next";
        navInput.setAttribute("data-fallback-nav", "1");
        form.appendChild(navInput);
        setNavInProgressFlag(true);
        HTMLFormElement.prototype.submit.call(form);
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

    function bindSubmitConfirmation() {
        const submitForm = document.getElementById("mcqSubmitForm");
        const submitBtn = document.getElementById("mcqConfirmSubmitBtn");
        const backBtn = document.getElementById("mcqBackToTestBtn");
        if (!submitForm || !submitBtn) return;

        submitForm.action = state.submitUrl;
        if (submitForm.dataset.bound === "1") {
            return;
        }
        submitForm.dataset.bound = "1";

        submitForm.addEventListener("submit", (e) => {
            if (submitForm.dataset.submitting === "1") {
                e.preventDefault();
                return;
            }

            const confirmed = window.confirm(
                "Are you sure you want to submit the test? You will not be able to change your answers after submission."
            );
            if (!confirmed) {
                e.preventDefault();
                return;
            }

            submitForm.dataset.submitting = "1";
            submitBtn.disabled = true;
            if (backBtn) {
                backBtn.disabled = true;
            }
            setNavInProgressFlag(true);
        });
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
                ${isLast ? "Review & Submit" : "Next"}
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

    const STRUCTURED_HEADING_PATTERN = /^(directions?|statements?|courses? of action|conclusions?|assumptions?|arguments?|options?|alternatives?|facts?|data sufficiency|passage|information)$/i;
    const STRUCTURED_HEADING_SPLIT_PATTERN = /^(directions?|statements?|courses? of action|conclusions?|assumptions?|arguments?|options?|alternatives?|facts?|data sufficiency|passage|information)\s*:?\s*(.*)$/i;
    const SECTION_LABEL_INSERT_PATTERN = /\b(direction|directions|statements?|course(?:s)? of action|conclusions?|assumptions?|arguments?|options?|alternatives?|facts?|data sufficiency|passage|information)\b/gi;
    const STRUCTURED_ENUM_SECTION_HEADING = /^(statements?|courses? of action|conclusions?|assumptions?|arguments?|options?|alternatives?|facts?|data sufficiency)$/i;
    const INLINE_SECTION_WITH_COLON_PATTERN = /\b(Directions?|Statements?|Courses? of Action|Conclusions?|Assumptions?|Arguments?|Options?|Alternatives?|Facts?|Data Sufficiency|Passage|Information)\s*:/g;
    const INLINE_MARKER_WITH_COLON_PATTERN = /\b(Fact\s*\d+|S\d+|[PQRS]|I|II|III|IV|V|VI|VII|VIII|IX|X)\s*:/g;
    const NUMBER_WORD_TO_INT = {
        a: 1,
        an: 1,
        one: 1,
        two: 2,
        three: 3,
        four: 4,
        five: 5
    };

    function normalizeWhitespace(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    const SENTENCE_DOT_PLACEHOLDER = "__MCQ_DOT__";

    function protectSentenceAbbreviationDots(value) {
        let text = String(value || "");
        const abbreviationPatterns = [
            /\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Std|vs|etc)\./gi,
            /\be\.g\./gi,
            /\bi\.e\./gi
        ];
        abbreviationPatterns.forEach((pattern) => {
            text = text.replace(pattern, (match) => match.replace(/\./g, SENTENCE_DOT_PLACEHOLDER));
        });
        return text;
    }

    function restoreSentenceAbbreviationDots(value) {
        return String(value || "").replace(new RegExp(SENTENCE_DOT_PLACEHOLDER, "g"), ".");
    }

    function splitReadableSentences(value) {
        const normalized = normalizeWhitespace(value);
        const protectedText = protectSentenceAbbreviationDots(normalized);
        return protectedText
            .split(/(?<=[.?!])\s+(?=[A-Z0-9"'(])/)
            .map((item) => normalizeWhitespace(restoreSentenceAbbreviationDots(item)))
            .filter((item) => item.length > 0);
    }

    function coalesceFragmentedItems(items) {
        const merged = [];
        for (let i = 0; i < (items || []).length; i += 1) {
            const current = normalizeWhitespace(items[i]);
            if (!current) continue;
            const next = normalizeWhitespace((items || [])[i + 1] || "");

            if (
                next &&
                (/^(yes|no)\.?$/i.test(current) ||
                    /^(?:I|II|III|IV|V|VI|VII|VIII|IX|X|[A-H]|S\d+|Fact\s*\d+)[.)]?$/.test(current))
            ) {
                merged.push(normalizeWhitespace(`${current.replace(/[.)]$/, ".")} ${next}`));
                i += 1;
                continue;
            }

            merged.push(current);
        }

        while (merged.length > 1 && merged[merged.length - 1].length <= 12) {
            const tail = merged.pop();
            merged[merged.length - 1] = normalizeWhitespace(`${merged[merged.length - 1]} ${tail}`);
        }
        return merged;
    }

    function extractYesNoArgumentItems(text, expectedCount) {
        const source = normalizeWhitespace(text);
        if (!source) return null;
        const pattern = /(?:^|\s)(Yes|No)\.\s*([\s\S]*?)(?=(?:\s(?:Yes|No)\.\s*)|$)/gi;
        const items = [];
        let match = null;
        while ((match = pattern.exec(source)) !== null) {
            const stance = normalizeWhitespace(match[1] || "");
            const body = normalizeWhitespace(match[2] || "");
            if (!stance || !body) continue;
            items.push(`${stance}. ${body}`);
        }
        if (items.length < 2) return null;
        if (expectedCount && items.length !== expectedCount) return null;
        return items;
    }

    function titleCaseHeading(value) {
        const normalized = normalizeWhitespace(value).toLowerCase();
        if (!normalized) return "";
        return normalized.replace(/\b\w/g, (ch) => ch.toUpperCase());
    }

    function getCanonicalSectionKey(heading) {
        const normalized = normalizeWhitespace(heading).toLowerCase();
        if (!normalized) return "";
        if (/^directions?$/.test(normalized)) return "direction";
        if (/^statements?$/.test(normalized)) return "statement";
        if (/^courses? of action$/.test(normalized)) return "course_of_action";
        if (/^conclusions?$/.test(normalized)) return "conclusion";
        if (/^assumptions?$/.test(normalized)) return "assumption";
        if (/^arguments?$/.test(normalized)) return "argument";
        if (/^options?$/.test(normalized)) return "option";
        if (/^alternatives?$/.test(normalized)) return "alternative";
        if (/^facts?$/.test(normalized)) return "fact";
        if (/^data sufficiency$/.test(normalized)) return "data_sufficiency";
        if (/^passage$/.test(normalized)) return "passage";
        if (/^information$/.test(normalized)) return "information";
        return normalized.replace(/\s+/g, "_");
    }

    function parseExpectedCountToken(token) {
        const normalized = normalizeWhitespace(token).toLowerCase();
        if (!normalized) return null;
        if (NUMBER_WORD_TO_INT[normalized] !== undefined) {
            return NUMBER_WORD_TO_INT[normalized];
        }
        const numeric = Number(normalized);
        if (!Number.isNaN(numeric) && numeric >= 1 && numeric <= 5) {
            return numeric;
        }
        return null;
    }

    function buildExpectedSectionCounts(rawText) {
        const text = normalizeQuestionText(rawText);
        const counts = {};
        const ambiguousKeys = new Set();
        const ambiguousSpecs = [
            { key: "course_of_action", regex: /\b(a|an|one|two|three|four|five|\d+)\s+or\s+(a|an|one|two|three|four|five|\d+)\s+courses?\s+of\s+action\b/gi },
            { key: "conclusion", regex: /\b(a|an|one|two|three|four|five|\d+)\s+or\s+(a|an|one|two|three|four|five|\d+)\s+conclusions?\b/gi },
            { key: "assumption", regex: /\b(a|an|one|two|three|four|five|\d+)\s+or\s+(a|an|one|two|three|four|five|\d+)\s+assumptions?\b/gi },
            { key: "argument", regex: /\b(a|an|one|two|three|four|five|\d+)\s+or\s+(a|an|one|two|three|four|five|\d+)\s+arguments?\b/gi },
            { key: "statement", regex: /\b(a|an|one|two|three|four|five|\d+)\s+or\s+(a|an|one|two|three|four|five|\d+)\s+statements?\b/gi },
            { key: "option", regex: /\b(a|an|one|two|three|four|five|\d+)\s+or\s+(a|an|one|two|three|four|five|\d+)\s+(?:options?|alternatives?|choices?)\b/gi }
        ];
        const specs = [
            { key: "course_of_action", regex: /\b(a|an|one|two|three|four|five|\d+)\s+courses?\s+of\s+action\b/gi },
            { key: "conclusion", regex: /\b(a|an|one|two|three|four|five|\d+)\s+conclusions?\b/gi },
            { key: "assumption", regex: /\b(a|an|one|two|three|four|five|\d+)\s+assumptions?\b/gi },
            { key: "argument", regex: /\b(a|an|one|two|three|four|five|\d+)\s+arguments?\b/gi },
            { key: "statement", regex: /\b(a|an|one|two|three|four|five|\d+)\s+statements?\b/gi },
            { key: "option", regex: /\b(a|an|one|two|three|four|five|\d+)\s+(?:options?|alternatives?|choices?)\b/gi }
        ];

        ambiguousSpecs.forEach((spec) => {
            if (spec.regex.test(text)) {
                ambiguousKeys.add(spec.key);
            }
        });

        specs.forEach((spec) => {
            let match = null;
            while ((match = spec.regex.exec(text)) !== null) {
                const parsed = parseExpectedCountToken(match[1]);
                if (!parsed) continue;
                counts[spec.key] = parsed;
            }
        });

        ambiguousKeys.forEach((key) => {
            if (key in counts) {
                delete counts[key];
            }
        });
        return counts;
    }

    function normalizeStructuredQuestionText(rawText) {
        let text = normalizeQuestionText(rawText)
            .replace(/\t/g, " ")
            .replace(/[ \f\v]+/g, " ")
            .replace(/[ ]+\n/g, "\n")
            .replace(/\n[ ]+/g, "\n");

        // Guard against malformed pasted tokens like "Statement s:" / "Argument s:"
        text = text.replace(/\b(Statement|Conclusion|Argument|Assumption)\s+s\s*:/gi, "$1s:");

        text = text.replace(/^\[\s*(Direction|Directions)\s*:\s*([\s\S]*?)\]\s*/i, (_, heading, body) => {
            const cleanBody = normalizeWhitespace(body || "");
            return `${titleCaseHeading(heading)}:\n${cleanBody}\n\n`;
        });

        text = text.replace(INLINE_SECTION_WITH_COLON_PATTERN, (match, heading, offset, source) => {
            if (offset === 0) return `${heading}:`;
            const prev = source[offset - 1] || "";
            if (prev === "\n") return `${heading}:`;
            return `\n${heading}:`;
        });

        text = text.replace(INLINE_MARKER_WITH_COLON_PATTERN, (match, marker, offset, source) => {
            if (offset === 0) return `${marker}:`;
            const prev = source[offset - 1] || "";
            if (prev === "\n") return `${marker}:`;
            return `\n${marker}:`;
        });

        // Keep "Give answer (A)...(B)..." style instructions readable.
        text = text.replace(/\b(Give answer)\s*:?\s*((?:\([A-E]\)\s*[^()\n]+){2,})/gi, (_, prefix, choices) => {
            const normalizedChoices = String(choices || "")
                .replace(/\s*\(([A-E])\)\s*/g, "\n($1) ")
                .trim();
            return `${prefix}:\n${normalizedChoices}`;
        });

        // Normalize "mark your answer as (A) ..." variants so A/B/C/D/E render as list items.
        text = text.replace(
            /\b((?:mark\s+your\s+answer|mark\s+answer|give\s+answer)(?:\s+as)?)\s*:?\s*\(([A-E])\)\s*/gi,
            (_, prefix, firstMarker) => `${normalizeWhitespace(prefix)}:\n(${String(firstMarker || "").toUpperCase()}) `
        );

        // Split inline list markers only when they begin a new clause after strong punctuation.
        // This avoids breaking instructional prose like "numbered I and II".
        text = text.replace(
            /([.:;!?])\s+((?:\([A-H]\)|\([IVX]{1,5}\)|\(?[IVX]{1,5}\)?[.):]|[A-H][.)]|S\d+[.)]|Fact\s*\d+[.)]|[PQRS][.)]|[1-5][.)]))\s+(?=[A-Za-z(])/g,
            "$1\n$2 "
        );

        text = text.replace(SECTION_LABEL_INSERT_PATTERN, (match, label, offset, source) => {
            const lower = String(label || "").toLowerCase();
            const prefix = source.slice(Math.max(0, offset - 12), offset);
            const shouldBreak = offset > 0 &&
                !/\n\s*$/.test(prefix) &&
                /[.?!:]\s*$/.test(prefix);
            if (!shouldBreak) {
                return match;
            }
            return `\n${titleCaseHeading(lower)}`;
        });

        return text.replace(/\n{3,}/g, "\n\n").trim();
    }

    function splitListMarker(line, inEnumeratedSection) {
        const text = String(line || "").trim();
        if (!text) return null;

        const explicitMarker = text.match(/^(\([A-H]\)|\([IVX]{1,5}\)|\(?[IVX]{1,5}\)?[.):]|[A-H][.)]|S\d+[.):]|Fact\s*\d+[.):]|[PQRS][.):]|[1-5][.)])\s*(.+)$/i);
        if (explicitMarker) {
            return {
                marker: explicitMarker[1],
                content: explicitMarker[2]
            };
        }

        if (inEnumeratedSection) {
            const romanMarker = text.match(/^(I|II|III|IV|V|VI|VII|VIII|IX|X)\s+(.*)$/);
            if (romanMarker) {
                return {
                    marker: romanMarker[1],
                    content: romanMarker[2]
                };
            }
        }

        // Fallback for malformed imports where markers exist but ":" or ")" is missing.
        if (inEnumeratedSection) {
            const bareMarker = text.match(/^(S\d+|[PQRS]|I|II|III|IV|V|VI|VII|VIII|IX|X)\b\s+(.+)$/i);
            if (bareMarker) {
                return {
                    marker: bareMarker[1],
                    content: bareMarker[2]
                };
            }
        }
        return null;
    }

    function getAutoListMarkers(sectionHeading, count) {
        const heading = String(sectionHeading || "").toLowerCase();
        if (!count || count <= 0) return [];
        const roman = ["I.", "II.", "III.", "IV.", "V."];
        const alpha = ["(A)", "(B)", "(C)", "(D)", "(E)"];
        const numeric = ["1.", "2.", "3.", "4.", "5."];
        if (/option|alternative/.test(heading)) {
            return alpha.slice(0, count);
        }
        if (/courses?\s+of\s+action|conclusion|assumption|argument/.test(heading)) {
            return roman.slice(0, count);
        }
        if (/statement|fact|data sufficiency/.test(heading)) {
            return numeric.slice(0, count);
        }
        return [];
    }

    function expandParagraphToImplicitList(paragraphText, sectionHeading, expectedCount) {
        const text = normalizeWhitespace(paragraphText);
        const heading = String(sectionHeading || "").toLowerCase();
        if (!text || !heading) return null;
        if (!/(statement|courses?\s+of\s+action|conclusion|assumption|argument|option|alternative|fact|data sufficiency)/.test(heading)) return null;
        if (/^(none follows|none is implicit|none of these)$/i.test(text)) return null;
        if (/[A-H][.)]\s|[PQRS]:|Fact\s*\d+:|\b(?:I|II|III|IV|V)\b[.):]/i.test(text)) return null;

        if (/argument/.test(heading)) {
            const yesNoItems = extractYesNoArgumentItems(text, expectedCount);
            if (yesNoItems && yesNoItems.length > 0) {
                const markers = getAutoListMarkers(sectionHeading, yesNoItems.length);
                if (markers.length === yesNoItems.length) {
                    return yesNoItems.map((item, index) => ({
                        marker: markers[index],
                        text: item
                    }));
                }
            }
        }

        let items = coalesceFragmentedItems(splitReadableSentences(text));

        if (items.length < 2) {
            items = text
                .split(/\s*;\s+/)
                .map((item) => normalizeWhitespace(item))
                .filter((item) => item.length > 0);
        }

        if (items.length < 2 && text.length >= 90) {
            // Last-resort split for marker-less imported content:
            // e.g. "Statement ... Statement ... Statement ..." with no punctuation.
            items = text
                .split(/\s+(?=(?:All|Some|No|The|A|An|This|That|These|Those|People|Government|Company|State|Farmers|Students|Teachers|Police|Many|Few|Most|None)\b)/)
                .map((item) => normalizeWhitespace(item))
                .filter((item) => item.length >= 18);
        }

        if (expectedCount && items.length !== expectedCount) {
            const starterSplit = text
                .split(/\s+(?=(?:All|Some|No|The|A|An|This|That|These|Those|People|Government|Company|State|Farmers|Students|Teachers|Police|Many|Few|Most)\b)/)
                .map((item) => normalizeWhitespace(item))
                .filter((item) => item.length >= 10);
            if (starterSplit.length >= expectedCount) {
                items = starterSplit;
            }
        }

        if (
            expectedCount &&
            items.length === expectedCount + 1 &&
            /^(none follows|none is implicit|none of these|none)$/i.test(items[items.length - 1] || "")
        ) {
            items.pop();
        }

        if (expectedCount && items.length !== expectedCount) {
            if (items.length > expectedCount) {
                while (items.length > expectedCount) {
                    const tail = items.pop();
                    if (!tail) break;
                    if (!items.length) {
                        items.push(tail);
                        break;
                    }
                    items[items.length - 1] = normalizeWhitespace(`${items[items.length - 1]} ${tail}`);
                }
            } else if (items.length < expectedCount) {
                const aggressive = text
                    .split(/(?<=[.?!;])\s+|(?=\b(?:All|Some|No|The|A|An|This|That|These|Those|People|Government|Company|State|Farmers|Students|Teachers|Police|Many|Few|Most)\b)/)
                    .map((item) => normalizeWhitespace(item))
                    .filter((item) => item.length >= 10);
                if (aggressive.length >= expectedCount) {
                    items = aggressive.slice(0, expectedCount - 1);
                    items.push(normalizeWhitespace(aggressive.slice(expectedCount - 1).join(" ")));
                }
            }
        }

        items = coalesceFragmentedItems(items);

        if (items.length < 2 || items.length > 5) return null;
        if (items.some((item) => item.length < 10)) return null;
        if (expectedCount && items.length !== expectedCount) return null;

        const markers = getAutoListMarkers(sectionHeading, items.length);
        if (!markers.length || markers.length !== items.length) return null;

        return items.map((item, index) => ({
            marker: markers[index],
            text: item
        }));
    }

    function parseStructuredTextBlocks(rawText) {
        const normalized = normalizeStructuredQuestionText(rawText);
        if (!normalized) return [];
        const expectedCountsBySection = buildExpectedSectionCounts(rawText);

        const lines = normalized.split("\n").map((line) => String(line || "").trim());
        const blocks = [];
        let currentParagraph = "";
        let currentList = null;
        let inEnumeratedSection = false;
        let currentSectionHeading = "";
        let currentExpectedCount = null;

        function flushParagraph() {
            const text = normalizeWhitespace(currentParagraph);
            if (text) {
                const autoItems = expandParagraphToImplicitList(text, currentSectionHeading, currentExpectedCount);
                if (autoItems && autoItems.length > 0) {
                    blocks.push({
                        type: "list",
                        items: autoItems
                    });
                } else {
                    blocks.push({ type: "paragraph", text });
                }
            }
            currentParagraph = "";
        }

        function flushList() {
            if (currentList && currentList.items.length > 0) {
                blocks.push(currentList);
            }
            currentList = null;
        }

        function appendParagraph(line) {
            if (!line) return;
            currentParagraph = currentParagraph ? `${currentParagraph} ${line}` : line;
        }

        lines.forEach((line) => {
            if (!line) {
                flushParagraph();
                flushList();
                return;
            }

            const headingSplit = line.match(STRUCTURED_HEADING_SPLIT_PATTERN);
            if (headingSplit && STRUCTURED_HEADING_PATTERN.test(headingSplit[1] || "")) {
                flushParagraph();
                flushList();
                const headingText = titleCaseHeading(headingSplit[1]);
                blocks.push({ type: "heading", text: headingText });
                inEnumeratedSection = STRUCTURED_ENUM_SECTION_HEADING.test(headingText);
                currentSectionHeading = headingText;
                currentExpectedCount = expectedCountsBySection[getCanonicalSectionKey(headingText)] || null;
                const remainder = normalizeWhitespace(headingSplit[2] || "");
                if (remainder) {
                    appendParagraph(remainder);
                }
                return;
            }

            const listMatch = splitListMarker(line, inEnumeratedSection);
            if (listMatch) {
                flushParagraph();
                if (!currentList) {
                    currentList = { type: "list", items: [] };
                }
                currentList.items.push({
                    marker: listMatch.marker,
                    text: normalizeWhitespace(listMatch.content)
                });
                return;
            }

            if (currentList && currentList.items.length > 0) {
                const mergedLine = normalizeWhitespace(line);
                currentList.items[currentList.items.length - 1].text = normalizeWhitespace(
                    `${currentList.items[currentList.items.length - 1].text} ${mergedLine}`
                );
                return;
            }

            appendParagraph(line);
        });

        flushParagraph();
        flushList();
        return blocks;
    }

    function _tokenizeForSimilarity(value) {
        return String(value || "")
            .toLowerCase()
            .replace(/[^a-z0-9\s]/g, " ")
            .split(/\s+/)
            .filter(Boolean);
    }

    function _phraseSimilarity(a, b) {
        const at = _tokenizeForSimilarity(a);
        const bt = _tokenizeForSimilarity(b);
        if (!at.length || !bt.length) return 0;
        const aset = new Set(at);
        const bset = new Set(bt);
        let common = 0;
        aset.forEach((token) => {
            if (bset.has(token)) common += 1;
        });
        let score = common / Math.max(aset.size, bset.size);
        if (at[0] === bt[0]) score += 0.22;
        if (at[at.length - 1] === bt[bt.length - 1]) score += 0.18;
        return score;
    }

    function deriveSentenceImprovementTarget(rawText, options) {
        const text = normalizeQuestionText(rawText);
        if (!/italicised and underlined/i.test(text) || !/improve the sentence/i.test(text)) {
            return null;
        }

        const optionList = (options || [])
            .map((item) => normalizeWhitespace(item))
            .filter((item) => item.length > 0)
            .filter((item) => !/^no improvement$/i.test(item));
        if (!optionList.length) return null;

        const lines = text
            .split("\n")
            .map((line) => String(line || "").trim())
            .filter((line) => line.length > 0)
            .filter((line) => !/^\[?\s*direction/i.test(line));
        if (!lines.length) return null;

        const sentence = normalizeWhitespace(lines[lines.length - 1]);
        if (!sentence) return null;

        for (const option of optionList) {
            if (sentence.toLowerCase().includes(option.toLowerCase())) {
                return option;
            }
        }

        const words = sentence.match(/[A-Za-z0-9']+/g) || [];
        if (words.length < 2) return null;

        let bestPhrase = null;
        let bestScore = 0;
        for (let start = 0; start < words.length; start += 1) {
            for (let length = 1; length <= 4 && start + length <= words.length; length += 1) {
                const candidate = words.slice(start, start + length).join(" ");
                if (!candidate || candidate.length < 3) continue;
                const maxScore = optionList.reduce(
                    (acc, option) => Math.max(acc, _phraseSimilarity(candidate, option)),
                    0
                );
                if (maxScore > bestScore) {
                    bestScore = maxScore;
                    bestPhrase = candidate;
                }
            }
        }
        if (bestScore < 0.72) return null;
        return bestPhrase;
    }

    function highlightSentenceFragment(text, fragment) {
        const source = String(text || "");
        const target = String(fragment || "").trim();
        if (!source || !target) return null;
        const idx = source.toLowerCase().indexOf(target.toLowerCase());
        if (idx < 0) return null;
        const before = escapeHtml(source.slice(0, idx));
        const match = escapeHtml(source.slice(idx, idx + target.length));
        const after = escapeHtml(source.slice(idx + target.length));
        return `${before}<span class="mcq-emphasis-target">${match}</span>${after}`;
    }

    function normalizeLegendComparable(value) {
        return normalizeWhitespace(value)
            .toLowerCase()
            .replace(/^[("'\[]+|[)"'\].,:;!?]+$/g, "")
            .replace(/^\s*if\s+/, "")
            .replace(/\s+/g, " ");
    }

    function isDescriptiveOptionSet(optionTexts) {
        const options = (optionTexts || []).map((item) => normalizeWhitespace(item)).filter(Boolean);
        if (!options.length) return false;
        const symbolicOnly = options.every((item) => /^[(]?[A-E][)]?$/i.test(item));
        if (symbolicOnly) return false;
        return options.some((item) => item.split(/\s+/).length >= 3);
    }

    function isDirectionAnswerLegendList(item, optionTexts) {
        if (!item || item.type !== "list" || !Array.isArray(item.items) || item.items.length < 2) return false;
        if (!isDescriptiveOptionSet(optionTexts)) return false;

        const markersValid = item.items.every((entry) => /^(\([A-E]\)|[A-E][.)])$/i.test(normalizeWhitespace(entry.marker || "")));
        if (!markersValid) return false;

        const normalizedOptions = (optionTexts || [])
            .map((opt) => normalizeLegendComparable(opt))
            .filter(Boolean);
        if (!normalizedOptions.length) return false;

        let matches = 0;
        item.items.forEach((entry) => {
            const legendText = normalizeLegendComparable(entry.text || "");
            if (!legendText) return;
            const hit = normalizedOptions.some((opt) =>
                opt === legendText ||
                opt.includes(legendText) ||
                legendText.includes(opt)
            );
            if (hit) matches += 1;
        });

        return matches >= Math.min(2, item.items.length);
    }

    function isDirectionAnswerLegendParagraph(item, optionTexts) {
        if (!item || item.type !== "paragraph" || !isDescriptiveOptionSet(optionTexts)) return false;
        const text = normalizeWhitespace(item.text || "");
        if (!text) return false;
        if (!/\b(?:give answer|mark your answer|mark answer)\b/i.test(text)) return false;
        if (!/\([A-E]\)/i.test(text)) return false;
        return true;
    }

    function renderStructuredTextBlocksHtml(rawText, renderContext = {}) {
        const blocks = parseStructuredTextBlocks(rawText);
        if (!blocks.length) {
            return `<p class="mcq-question-paragraph">${escapeHtml(normalizeWhitespace(rawText))}</p>`;
        }
        const sentenceTarget = normalizeWhitespace(renderContext.sentenceTarget || "");
        const normalizedOptionSet = new Set(
            (renderContext.optionTexts || [])
                .map((item) => normalizeWhitespace(item).replace(/[“”"'`]/g, "").replace(/[.;:!?]+$/g, "").toLowerCase())
                .filter((item) => item.length > 0)
        );
        const blocksFiltered = blocks.filter((block, index) => {
            if (block.type !== "paragraph" || !normalizedOptionSet.size) return true;
            const cleaned = normalizeWhitespace(block.text || "")
                .replace(/[“”"'`]/g, "")
                .replace(/[.;:!?]+$/g, "")
                .toLowerCase();
            if (!cleaned || cleaned.length < 20) return true;
            if (!normalizedOptionSet.has(cleaned)) return true;
            // Drop only when it appears as trailing leaked answer text in the stem.
            return index < blocks.length - 2;
        });
        let sentenceHighlightUsed = false;

        const sections = [];
        let currentSection = null;
        blocksFiltered.forEach((block) => {
            if (block.type === "heading") {
                if (currentSection) {
                    sections.push(currentSection);
                }
                currentSection = { heading: block.text, items: [] };
                return;
            }
            if (!currentSection) {
                sections.push({ heading: "", items: [block] });
                return;
            }
            currentSection.items.push(block);
        });
        if (currentSection) {
            sections.push(currentSection);
        }

        function splitReadableNarrativeSentences(text) {
            const normalized = normalizeWhitespace(text);
            if (!normalized || normalized.length < 120) return null;
            if (/\b(?:If only|If either|If neither|If both)\b/i.test(normalized)) return null;
            if (/\b(?:I|II|III|IV|V)\b\s+(?:and|or)\s+\b(?:I|II|III|IV|V)\b/i.test(normalized)) return null;
            if (/[A-H][.)]\s|S\d+[.):]|Fact\s*\d+[.):]/i.test(normalized)) return null;

            const sentences = splitReadableSentences(normalized);

            if (sentences.length < 2) return null;
            const substantive = sentences.filter((item) => item.length >= 25).length;
            if (substantive < 2) return null;
            return sentences;
        }

            function shouldForceLineSplit(sectionHeading) {
                const heading = normalizeWhitespace(sectionHeading).toLowerCase();
                return /(statement|courses?\s+of\s+action|conclusion|assumption|argument|option|alternative|fact|data sufficiency)/.test(heading);
            }

            function splitParagraphIntoSectionLines(text, sectionHeading) {
                const normalized = normalizeWhitespace(text);
                if (!normalized) return null;
                if (!shouldForceLineSplit(sectionHeading)) return null;

                let lines = coalesceFragmentedItems(splitReadableSentences(normalized));

                if (lines.length < 2) {
                    lines = normalized
                        .split(/\s*;\s+|\s+(?=(?:Yes|No)\.)/i)
                        .map((item) => normalizeWhitespace(item))
                        .filter((item) => item.length > 0);
                }

                lines = coalesceFragmentedItems(lines);

                if (lines.length < 2 || lines.length > 6) return null;
                if (lines.some((item) => item.length < 8)) return null;
                return lines;
            }

            function splitDirectionPointLines(text) {
                const normalized = normalizeWhitespace(text);
                if (!normalized) return null;
                if (!/(?:^|\s)(?:\d+[.)]|\([0-9]+\))\s+/.test(normalized)) return null;

                const lines = normalized
                    .split(/\s+(?=(?:\d+[.)]|\([0-9]+\))\s+)/)
                    .map((item) => normalizeWhitespace(item).replace(/^(?:\d+[.)]|\([0-9]+\))\s*/, ""))
                    .filter((item) => item.length > 0);

                if (lines.length < 2 || lines.length > 8) return null;
                if (lines.some((item) => item.length < 10)) return null;
                return lines;
            }

            function buildLineMarker(sectionHeading, index) {
                const heading = normalizeWhitespace(sectionHeading).toLowerCase();
                const roman = ["I.", "II.", "III.", "IV.", "V.", "VI."];
                const alpha = ["(A)", "(B)", "(C)", "(D)", "(E)", "(F)"];
                if (/option|alternative/.test(heading)) return alpha[index] || `${index + 1}.`;
                if (/courses?\s+of\s+action|conclusion|assumption|argument/.test(heading)) return roman[index] || `${index + 1}.`;
                return `${index + 1}.`;
            }

            const renderBlock = (block, sectionHeading) => {
            const heading = normalizeWhitespace(sectionHeading).toLowerCase();
            if (block.type === "list") {
                const itemsHtml = block.items.map((item) => `
                    <div class="mcq-question-list-item">
                        <span class="mcq-question-list-marker">${escapeHtml(item.marker)}</span>
                        <span class="mcq-question-list-text">${escapeHtml(item.text)}</span>
                    </div>
                `).join("");
                return `<div class="mcq-question-list">${itemsHtml}</div>`;
            }
            const forcedLines = splitParagraphIntoSectionLines(block.text, sectionHeading);
            if (forcedLines) {
                const itemsHtml = forcedLines.map((line, index) => {
                    const markerMatch = line.match(/^(\([A-E]\)|[IVX]{1,6}[.)]|[1-6][.)])/i);
                    const textMatch = line.match(/^(?:\([A-E]\)|[IVX]{1,6}[.)]|[1-6][.)])\s*(.*)$/i);
                    const marker = markerMatch ? markerMatch[1] : (buildLineMarker(sectionHeading, index) || "");
                    const itemText = textMatch ? textMatch[1] : line;
                    return `
                    <div class="mcq-question-list-item">
                        <span class="mcq-question-list-marker">${escapeHtml(marker)}</span>
                        <span class="mcq-question-list-text">${escapeHtml(itemText)}</span>
                    </div>
                `;
                }).join("");
                return `<div class="mcq-question-list">${itemsHtml}</div>`;
            }
            if (/^directions?$/.test(heading)) {
                const directionLines = splitDirectionPointLines(block.text);
                if (directionLines) {
                    const lines = directionLines
                        .map((line) => `<p class="mcq-question-passage-line">${escapeHtml(line)}</p>`)
                        .join("");
                    return `<div class="mcq-question-passage">${lines}</div>`;
                }
            }
            if (sentenceTarget && !sentenceHighlightUsed) {
                if (!heading || /^statements?$/.test(heading) || heading.includes("sentence")) {
                    const highlighted = highlightSentenceFragment(block.text, sentenceTarget);
                    if (highlighted) {
                        sentenceHighlightUsed = true;
                        return `<p class="mcq-question-paragraph">${highlighted}</p>`;
                    }
                }
            }
            const narrativeSentences = splitReadableNarrativeSentences(block.text);
            if (narrativeSentences) {
                const lines = narrativeSentences
                    .map((sentence) => `<p class="mcq-question-passage-line">${escapeHtml(sentence)}</p>`)
                    .join("");
                return `<div class="mcq-question-passage">${lines}</div>`;
            }
            return `<p class="mcq-question-paragraph">${escapeHtml(block.text)}</p>`;
        };

        return `<div class="mcq-question-structured">${
            sections.map((section) => {
                const heading = normalizeWhitespace(section.heading).toLowerCase();
                const filteredItems = section.items.filter((item) => {
                    if (!/^directions?$/.test(heading)) return true;
                    if (isDirectionAnswerLegendList(item, renderContext.optionTexts || [])) return false;
                    if (isDirectionAnswerLegendParagraph(item, renderContext.optionTexts || [])) return false;
                    return true;
                });
                if (section.heading && filteredItems.length === 0) {
                    return "";
                }
                const headingHtml = section.heading
                    ? `<div class="mcq-question-heading">${escapeHtml(section.heading)}</div>`
                    : "";
                const bodyHtml = filteredItems.map((item) => renderBlock(item, section.heading)).join("");
                if (!section.heading) {
                    return filteredItems.map((item) => renderBlock(item, "")).join("");
                }
                return `<section class="mcq-question-section">${headingHtml}<div class="mcq-question-section-body">${bodyHtml}</div></section>`;
            }).join("")
        }</div>`;
    }

    function isLikelyNarrativeLine(line) {
        const text = String(line || "").trim();
        if (!text) return false;
        if (!/^[A-Za-z][A-Za-z0-9 ,.'"():!?+\-_/&[\]]+$/.test(text)) return false;
        return /[?.!:]$/.test(text);
    }

    function hasEndpointExampleProse(value) {
        const text = String(value || "").trim();
        if (!text) return false;
        if (/\b(?:e\.g\.|for example)\b/i.test(text) && /\/[A-Za-z][A-Za-z0-9_/-]*/.test(text)) {
            return true;
        }
        if (
            /\b(?:endpoint|resource|route|url|uri|nouns?|verbs?)\b/i.test(text) &&
            /\/[A-Za-z][A-Za-z0-9_/-]*/.test(text) &&
            !/[{}=]/.test(text)
        ) {
            return true;
        }
        return false;
    }

    function looksLikeCodeAssignment(text) {
        const line = String(text || "").trim();
        if (!/^[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+$/.test(line)) return false;
        if (/^\w+\s*=\s*\w+\s*(?:and|or)\s*\w+/i.test(line)) return false;
        const rhs = line.replace(/^[A-Za-z_][A-Za-z0-9_]*\s*=\s*/, "").trim();
        if (!rhs) return false;
        if (/^[A-Za-z ]+$/.test(rhs) && rhs.split(/\s+/).length > 3) return false;
        return /[()\[\]{}'"0-9.+\-*/%]|^[A-Za-z_][A-Za-z0-9_]*$/.test(rhs);
    }

    function isProseHeavyCandidate(text) {
        const value = String(text || "").trim();
        if (!value) return false;
        if (/[{};]|=>|::|->/.test(value)) return false;
        if (/^(from\s+\w+|import\s+\w+|def\s+\w+|class\s+\w+|if\b|for\b|while\b|elif\b|else\b|try\b|except\b|finally\b|return\b|using\b|namespace\b|#include\b)/i.test(value)) return false;
        const words = value.match(/[A-Za-z][A-Za-z'-]*/g) || [];
        const lower = value.toLowerCase();
        const hasPromptTerms = /\b(?:which|what|why|how|choose|select|statement|conclusion|assumption|argument|direction|following|correct|best answer|question)\b/.test(lower);
        const sentenceLike = /[.?!]$/.test(value);
        if (words.length >= 8 && sentenceLike && hasPromptTerms) return true;
        if (words.length >= 12 && /[,]/.test(value) && !/[=()]/.test(value)) return true;
        return false;
    }

    function isLikelyCodeLine(line) {
        const text = String(line || "").trim();
        if (!text) return false;
        if (hasEndpointExampleProse(text)) return false;
        if (isProseHeavyCandidate(text)) return false;

        if (isLikelyNarrativeLine(text) && !/[{}();=<>[\]]/.test(text)) {
            return false;
        }

        if (/^(from\s+[A-Za-z_][A-Za-z0-9_.]*\s+import\s+.+|import\s+[A-Za-z_][A-Za-z0-9_.]*(\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?)$/.test(text)) return true;
        if (/^(\/\/|\/\*|\*|#include\b|#\s|using\s+[A-Za-z0-9_.]+;?|namespace\b|import\s+[A-Za-z0-9_.]+;?)/.test(text)) return true;
        if (/^(class|interface|enum|struct|public|private|protected|static|final|const|let|var|def|try|catch|finally|return|throw|new|void|int|long|float|double|char|bool|string)\b/.test(text)) return true;
        if (/^(if|for|while|switch)\s*\(.*\)\s*(\{|$)/.test(text)) return true;
        if (/^(if|for|while|elif|except)\b.+:\s*$/.test(text)) return true;
        if (/^(else|try|finally)\s*:\s*$/.test(text)) return true;
        if (/^(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\s*(\([^)]*\))?\s*:\s*$/.test(text)) return true;
        if (/\b(Console\.WriteLine|System\.out\.println|console\.log|printf|scanf|print)\s*\(/.test(text)) return true;
        if (/^\w+\s*\(.*\)\s*(\{|=>|;)$/.test(text)) return true;
        if (/=>|::|->/.test(text)) return true;
        if (/[{}]/.test(text)) return true;
        if (/^[A-Za-z_][A-Za-z0-9_<>,\[\]\s]*\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+/.test(text)) return true;
        if (looksLikeCodeAssignment(text)) return true;
        if (/^\w+\.\w+\s*\(/.test(text)) return true;
        if (/(\+\+|--|==|!=|<=|>=|\+=|-=|\*=|%=)/.test(text)) return true;
        return false;
    }

    function isStrongCodeLine(line) {
        const text = String(line || "").trim();
        if (!text) return false;
        if (hasEndpointExampleProse(text)) return false;
        if (isProseHeavyCandidate(text)) return false;
        if (/^(#include\b|using\s+[A-Za-z0-9_.]+;?|namespace\b|class\b|public\b|private\b|protected\b|interface\b|enum\b|struct\b|import\s+[A-Za-z0-9_.]+;?)/.test(text)) return true;
        if (/\b(Console\.WriteLine|System\.out\.println|console\.log|printf|scanf|print)\s*\(/.test(text)) return true;
        if (/^(if|for|while|switch)\s*\(.*\)\s*\{?$/.test(text)) return true;
        if (/^(if|for|while|elif|except)\b.+:\s*$/.test(text)) return true;
        if (/^(else|try|finally)\s*:\s*$/.test(text)) return true;
        if (/^(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\s*(\([^)]*\))?\s*:\s*$/.test(text)) return true;
        if (looksLikeCodeAssignment(text)) return true;
        return /[{}=]|=>|::|->/.test(text);
    }

    function looksLikeInlineCodePayload(text) {
        const value = String(text || "").trim();
        if (!value) return false;
        if (hasEndpointExampleProse(value)) return false;
        if (isProseHeavyCandidate(value)) return false;
        if (isStrongCodeLine(value)) return true;
        if (/^#\s*[A-Za-z_][A-Za-z0-9_]*/.test(value)) return true;
        if (/\b(Console\.WriteLine|System\.out\.println|console\.log|printf|scanf|print)\s*\(/.test(value)) return true;
        if (/[{}=]|=>|::|->/.test(value)) return true;
        if (/^(?:[A-Za-z_][A-Za-z0-9_]*\.)?[A-Za-z_][A-Za-z0-9_]*\([^)\n]*\)\s*;?$/.test(value)) return true;
        if (/^(if|for|while|elif|except)\b.+:\s*$/.test(value)) return true;
        if (/^(else|try|finally)\s*:\s*$/.test(value)) return true;
        if (/^(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\s*(\([^)]*\))?\s*:\s*$/.test(value)) return true;
        if (looksLikeCodeAssignment(value)) return true;
        if (/\b(int|long|float|double|char|bool|string|var|let|const|def|class|public|private|protected)\b/.test(value) && /[=;]/.test(value)) return true;
        return false;
    }

    function extractSingleInlineCodeFragment(text) {
        const source = String(text || "");
        const patterns = [
            /#\s*[A-Za-z_][A-Za-z0-9_]*\s*(?:<[^>]+>|\"[^\"]+\")?/g,
            /\b(?:[A-Za-z_][A-Za-z0-9_<>\[\]]*\s+)?[A-Za-z_][A-Za-z0-9_<>.\[\]]*\s*=\s*[^.?!\n]+?;/g,
            /\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?=[^.\n]*[(){}\[\]'\"0-9+\-*/%])[^.?!\n]+/g,
            /\b(?:[A-Za-z_][A-Za-z0-9_<>.\[\]]*\.)?[A-Za-z_][A-Za-z0-9_<>.\[\]]*\([^)\n]*\)\s*;?/g,
            /\b(?:if|for|while|elif|except)\b[^.\n]*:\s*/g,
            /\b[A-Za-z_][A-Za-z0-9_<>.\[\]]*::[A-Za-z_][A-Za-z0-9_<>.\[\]]*\b/g
        ];

        let best = null;
        patterns.forEach((pattern) => {
            let match = null;
            while ((match = pattern.exec(source)) !== null) {
                const fragment = trimSurroundingBlankLines(match[0] || "");
                if (!fragment) continue;
                if (hasEndpointExampleProse(fragment)) continue;
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

    function splitSemicolonStatements(line) {
        const source = String(line || "");
        const parts = [];
        let current = "";
        let parenDepth = 0;
        let bracketDepth = 0;
        let braceDepth = 0;
        let inSingle = false;
        let inDouble = false;
        let inBacktick = false;
        let escaped = false;

        for (let i = 0; i < source.length; i += 1) {
            const ch = source[i];
            current += ch;

            if (escaped) {
                escaped = false;
                continue;
            }
            if (ch === "\\") {
                escaped = true;
                continue;
            }

            if (!inDouble && !inBacktick && ch === "'") {
                inSingle = !inSingle;
                continue;
            }
            if (!inSingle && !inBacktick && ch === "\"") {
                inDouble = !inDouble;
                continue;
            }
            if (!inSingle && !inDouble && ch === "`") {
                inBacktick = !inBacktick;
                continue;
            }

            if (inSingle || inDouble || inBacktick) {
                continue;
            }

            if (ch === "(") parenDepth += 1;
            if (ch === ")") parenDepth = Math.max(0, parenDepth - 1);
            if (ch === "[") bracketDepth += 1;
            if (ch === "]") bracketDepth = Math.max(0, bracketDepth - 1);
            if (ch === "{") braceDepth += 1;
            if (ch === "}") braceDepth = Math.max(0, braceDepth - 1);

            if (ch === ";" && parenDepth === 0 && bracketDepth === 0 && braceDepth === 0) {
                const chunk = current.trim();
                if (chunk) {
                    parts.push(chunk);
                }
                current = "";
            }
        }

        const tail = current.trim();
        if (tail) {
            parts.push(tail);
        }
        return parts;
    }

    function splitInlinePythonSuite(line) {
        const source = String(line || "");
        const suite = source.match(/^(\s*(?:if|elif|for|while|def|class|with|try|except)\b[^:]*:)\s+(.+)$/);
        if (!suite) {
            return [source];
        }

        const header = suite[1];
        const body = suite[2];
        if (
            !looksLikeInlineCodePayload(body) &&
            !/\b(?:return|raise|yield|pass|break|continue|await|print)\b/.test(body) &&
            !/[A-Za-z_][A-Za-z0-9_.]*\([^)\n]*\)/.test(body)
        ) {
            return [source];
        }

        const bodyParts = body
            .split(/\s+(?=(?:return|raise|yield|pass|break|continue|await|print)\b|[A-Za-z_][A-Za-z0-9_.]*\([^)\n]*\))/g)
            .map((item) => String(item || "").trim())
            .filter((item) => item.length > 0);
        if (!bodyParts.length) {
            return [source];
        }

        return [header, ...bodyParts.map((item) => `    ${item}`)];
    }

    function formatCodeSegmentForDisplay(text) {
        const normalized = normalizeQuestionText(text).replace(/\t/g, "    ");
        const inputLines = normalized.split("\n");
        const formatted = [];

        inputLines.forEach((rawLine) => {
            const line = String(rawLine || "").replace(/\s+$/, "");
            if (!line.trim()) {
                formatted.push("");
                return;
            }

            const pythonSplit = splitInlinePythonSuite(line);
            pythonSplit.forEach((candidateLine) => {
                const candidate = String(candidateLine || "").replace(/\s+$/, "");
                if (!candidate.trim()) {
                    formatted.push("");
                    return;
                }

                const leading = (candidate.match(/^\s*/) || [""])[0];
                const body = candidate.slice(leading.length);
                const statements = splitSemicolonStatements(body);
                if (statements.length > 1) {
                    statements.forEach((stmt) => {
                        const row = `${leading}${stmt}`.trimEnd();
                        if (row) {
                            formatted.push(row);
                        }
                    });
                    return;
                }

                formatted.push(candidate);
            });
        });

        return trimSurroundingBlankLines(formatted.join("\n"));
    }

    function isEmbeddedCodeCandidate(text) {
        const value = String(text || "").trim();
        if (!value) return false;
        if (looksLikeInlineCodePayload(value)) return true;
        if (/^(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\s*(\([^)\n]*\))?\s*:/.test(value)) return true;
        if (/^(public|private|protected|static)\b[\s\S]*\(/.test(value) && /[{}=;]|=>/.test(value)) return true;
        if (/^(if|for|while)\s*\([^)\n]*\)/.test(value) && /[{};=]|=>/.test(value)) return true;
        if (/^(?:int|long|float|double|char|bool|string|var|let|const)\s+[A-Za-z_][A-Za-z0-9_]*\s*=/.test(value)) return true;
        return false;
    }

    function expandMixedProseCodeLines(lines) {
        const expanded = [];
        const embeddedCodePattern = /\b(?:from\s+[A-Za-z_][A-Za-z0-9_.]*\s+import|import\s+[A-Za-z_][A-Za-z0-9_.]*|def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(|class\s+[A-Za-z_][A-Za-z0-9_]*|public\b|private\b|protected\b|static\b|void\s+[A-Za-z_][A-Za-z0-9_]*\s*\(|(?:int|long|float|double|char|bool|string|var|let|const)\s+[A-Za-z_][A-Za-z0-9_]*\s*=|if\s*\(|for\s*\(|while\s*\(|try\s*\{?)/i;

        lines.forEach((rawLine) => {
            const source = String(rawLine || "");
            const trimmed = source.trim();
            if (!trimmed) {
                expanded.push("");
                return;
            }

            if (isLikelyCodeLine(trimmed) || isStrongCodeLine(trimmed)) {
                expanded.push(trimmed);
                return;
            }

            const embeddedMatch = trimmed.match(embeddedCodePattern);
            if (embeddedMatch && typeof embeddedMatch.index === "number" && embeddedMatch.index > 0) {
                const before = trimSurroundingBlankLines(trimmed.slice(0, embeddedMatch.index));
                let code = trimSurroundingBlankLines(trimmed.slice(embeddedMatch.index));
                let tail = "";

                const promptTail = code.match(/^(.*?)(\s+\b(?:what|which|why|how|choose|select|correct|output|result|answer)\b[\s\S]*)$/i);
                if (promptTail) {
                    const codeCandidate = trimSurroundingBlankLines(promptTail[1]);
                    const tailCandidate = trimSurroundingBlankLines(promptTail[2]);
                    if (codeCandidate && isEmbeddedCodeCandidate(codeCandidate)) {
                        code = codeCandidate;
                        tail = tailCandidate;
                    }
                }

                if (code && isEmbeddedCodeCandidate(code)) {
                    if (before) {
                        expanded.push(before.replace(/[:\-]\s*$/, "").trim());
                    }
                    expanded.push(code);
                    if (tail) {
                        expanded.push(tail);
                    }
                    return;
                }
            }

            const extracted = extractSingleInlineCodeFragment(trimmed);
            if (!extracted) {
                expanded.push(trimmed);
                return;
            }

            const before = trimSurroundingBlankLines(trimmed.slice(0, extracted.start));
            const code = trimSurroundingBlankLines(extracted.fragment);
            const after = trimSurroundingBlankLines(trimmed.slice(extracted.end));

            if (!code || !looksLikeInlineCodePayload(code)) {
                expanded.push(trimmed);
                return;
            }

            const safeBefore = before ? before.replace(/[:\-]\s*$/, "").trim() : "";
            if (safeBefore) {
                expanded.push(safeBefore);
            }
            expanded.push(code);
            if (after) {
                expanded.push(after);
            }
        });

        return expanded;
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
        const promptCodeMatch = normalized.match(
            /^(.*?(?:Which output is correct\?|What is the output of:?|What does this output\?|Debug this(?:\s+code)?[:?]))\s*(.+)$/i
        );
        if (promptCodeMatch) {
            const prompt = trimSurroundingBlankLines(promptCodeMatch[1]);
            let remainder = trimSurroundingBlankLines(promptCodeMatch[2]);
            remainder = trimSurroundingBlankLines(remainder.replace(/\?+$/, ""));
            if (
                prompt &&
                remainder &&
                (looksLikeInlineCodePayload(remainder) ||
                    /\b(?:print|printf|console\.log|System\.out\.println|WriteLine)\s*\(/.test(remainder) ||
                    /[=+\-*/%]|[()[\]{}]|::|=>|->|\b(?:if|for|while|def|class|return|try|catch)\b/.test(remainder))
            ) {
                return [
                    { type: "text", text: prompt },
                    { type: "code", text: remainder }
                ];
            }
        }

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

        const lines = expandMixedProseCodeLines(normalized.split("\n"));
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

    function renderQuestionTextHtml(rawText, options = []) {
        const segments = splitQuestionSegments(rawText);
        if (!segments.length) {
            return `<p class="mcq-question-paragraph"></p>`;
        }
        const renderContext = {
            sentenceTarget: deriveSentenceImprovementTarget(rawText, options),
            optionTexts: Array.isArray(options) ? options : [],
        };

        return segments.map((segment) => {
            if (segment.type === "code") {
                return `<pre class="mcq-question-code"><code>${escapeHtml(formatCodeSegmentForDisplay(segment.text))}</code></pre>`;
            }
            return renderStructuredTextBlocksHtml(segment.text, renderContext);
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

    function resetViewportToTop() {
        if (typeof window !== "undefined" && "scrollRestoration" in window.history) {
            try {
                window.history.scrollRestoration = "manual";
            } catch (_) {
                // Ignore browser restrictions and continue with explicit top reset.
            }
        }

        const scrollTargets = [];
        if (document && document.documentElement) scrollTargets.push(document.documentElement);
        if (document && document.body) scrollTargets.push(document.body);
        if (page) scrollTargets.push(page);
        try {
            const shell = document && document.getElementById("mcqQuestionView");
            if (shell) scrollTargets.push(shell);
        } catch (_) {
            // Ignore lookup failures.
        }

        const applyTop = () => {
            try {
                window.scrollTo(0, 0);
            } catch (_) {
                // Ignore if browser blocks programmatic scrolling.
            }
            scrollTargets.forEach((node) => {
                try {
                    node.scrollTop = 0;
                } catch (_) {
                    // Ignore non-scrollable targets.
                }
            });

            try {
                const active = document && document.activeElement;
                if (active && typeof active.blur === "function") {
                    active.blur();
                }
            } catch (_) {
                // Ignore blur errors.
            }
        };

        applyTop();
        if (typeof window !== "undefined" && typeof window.requestAnimationFrame === "function") {
            window.requestAnimationFrame(applyTop);
        } else {
            setTimeout(applyTop, 0);
        }
        setTimeout(applyTop, 60);
        setTimeout(applyTop, 180);
        setTimeout(applyTop, 360);
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
                ${renderQuestionTextHtml(questionData.question_text, questionData.options || [])}
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
        resetViewportToTop();

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
            <form id="mcqSubmitForm" method="POST" action="${escapeHtml(state.submitUrl)}">
                <button id="mcqConfirmSubmitBtn" type="submit" class="btn btn-danger">Confirm & Submit</button>
            </form>
        </div>
    </div>
</div>`;

        history.replaceState({}, "", state.submitUrl);
        resetViewportToTop();

        const backBtn = document.getElementById("mcqBackToTestBtn");
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
        bindSubmitConfirmation();

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
                submitQuestionFormFallback(form, nav);
                return;
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
        resetViewportToTop();
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

        bindSubmitConfirmation();
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
