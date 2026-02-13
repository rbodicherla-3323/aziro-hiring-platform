/* ================================================================
   AZIRO CODING FLOW — SPA Controller
   Mirrors mcq_flow.js: keeps media streams alive across
   start → editor transition so fullscreen is never broken.
   ================================================================ */

window.__CODING_AJAX_FLOW = true;

(function () {
    "use strict";

    // Only active on the coding start page
    if (!/^\/coding\/start\/[^/]+\/?$/.test(window.location.pathname)) return;

    const pathParts = window.location.pathname.split("/").filter(Boolean);
    const sessionId = pathParts.length >= 3 ? pathParts[pathParts.length - 1] : "";
    if (!sessionId) return;

    const page = document.querySelector(".page");
    if (!page) return;

    const startForm = document.getElementById("codingStartForm");
    if (!startForm) return;

    // ── Helpers ──────────────────────────────────────────────

    function escapeHtml(str) {
        return String(str || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function loadScript(src) {
        return new Promise(function (resolve) {
            var script = document.createElement("script");
            script.src = src;
            script.onload = resolve;
            script.onerror = resolve;
            document.body.appendChild(script);
        });
    }

    function loadCSS(href) {
        return new Promise(function (resolve) {
            var link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = href;
            link.onload = resolve;
            link.onerror = resolve;
            document.head.appendChild(link);
        });
    }

    // CodeMirror CDN resources to load in SPA flow
    var CM_BASE = "https://cdn.jsdelivr.net/npm/codemirror@5.65.18";
    var cmResources = {
        css: [
            CM_BASE + "/lib/codemirror.min.css",
            CM_BASE + "/addon/hint/show-hint.min.css"
        ],
        js: [
            CM_BASE + "/lib/codemirror.min.js",
            CM_BASE + "/mode/clike/clike.min.js",
            CM_BASE + "/addon/edit/closebrackets.min.js",
            CM_BASE + "/addon/edit/matchbrackets.min.js",
            CM_BASE + "/addon/selection/active-line.min.js",
            CM_BASE + "/addon/comment/comment.min.js"
        ]
    };

    // ── Start Form Interception (capture phase) ─────────────
    // This fires BEFORE coding_proctoring.js's handler and
    // prevents the traditional form submit (full page nav).

    startForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        e.stopImmediatePropagation();

        var startButton = startForm.querySelector("button");
        if (startButton) startButton.disabled = true;

        try {
            // ── 1. Acquire screen share + fullscreen ────────
            var proctoringReady = false;
            if (typeof window.ensureProctoringReady === "function") {
                proctoringReady = await window.ensureProctoringReady({
                    requireScreenShare: true,
                    requireFullscreen: true,
                    withOverlay: false
                });
            } else {
                // Fallback: just try fullscreen
                if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
                    try { await document.documentElement.requestFullscreen(); } catch (_) {}
                }
                proctoringReady = !!document.fullscreenElement;
            }

            if (!proctoringReady) {
                alert("Share Entire Screen and fullscreen are required to start the test.");
                if (startButton) startButton.disabled = false;
                return;
            }

            // ── 2. Acquire webcam (works inside fullscreen) ─
            if (navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function") {
                try {
                    var wStream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 180 } },
                        audio: false
                    });
                    if (typeof window.__proctoringSetWebcam === "function") {
                        window.__proctoringSetWebcam(wStream);
                    }
                } catch (_) {
                    // Webcam is optional — continue even if denied
                }
            }

            // ── 3. Mark fullscreen required in sessionStorage
            try {
                sessionStorage.setItem("coding_fullscreen_required_" + sessionId, "1");
            } catch (_) {}

            // ── 4. POST to begin endpoint (start session) ───
            var beginResp = await fetch("/coding/begin/" + encodeURIComponent(sessionId), {
                method: "POST",
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" }
            });
            if (!beginResp.ok) {
                console.warn("[CodingFlow] Begin POST returned:", beginResp.status);
            }

            // ── 5. GET editor page HTML ─────────────────────
            var resp = await fetch("/coding/editor/" + encodeURIComponent(sessionId), {
                credentials: "same-origin"
            });
            if (!resp.ok) throw new Error("Editor page returned HTTP " + resp.status);
            var html = await resp.text();
            if (!html || html.length < 100) throw new Error("Editor page returned empty/invalid HTML");

            // ── 6. Parse and inject editor content ──────────
            // Suppress content-change screenshots during legitimate page transition
            if (typeof window.suppressContentChangeDetection === "function") {
                window.suppressContentChangeDetection(3000);
            }

            var parser = new DOMParser();
            var doc = parser.parseFromString(html, "text/html");

            // Replace page content with editor content
            var newPage = doc.querySelector(".page");
            if (!newPage || !newPage.innerHTML.trim()) throw new Error("Parsed editor page has no .page content");
            page.innerHTML = newPage.innerHTML;

            // Apply editor-specific page styles (from editor.html extra_css)
            page.style.maxWidth = "100%";
            page.style.padding = "0";
            page.style.margin = "0";

            // Extract and inject header chips (timer, score, focus)
            var newChips = doc.querySelector(".coding-header-chips");
            if (newChips) {
                var oldChips = document.querySelector(".coding-header-chips");
                if (oldChips) oldChips.remove();

                var header = document.querySelector(".header");
                var candidate = header ? header.querySelector(".candidate") : null;
                if (header && candidate) {
                    header.insertBefore(newChips, candidate);
                } else if (header) {
                    header.appendChild(newChips);
                }
            }

            // ── 7. Update body class ────────────────────────
            document.body.classList.remove("coding-start-page");
            document.body.classList.add("coding-editor-page");

            // ── 8. Update URL (no history entry — can't go back)
            history.replaceState({}, "", "/coding/editor/" + sessionId);

            // ── 9. Load CodeMirror + coding_editor.js ─────────
            // Load CM CSS in parallel
            await Promise.all(cmResources.css.map(loadCSS));
            // Load CM JS sequentially (core first, then addons/modes)
            for (var i = 0; i < cmResources.js.length; i++) {
                await loadScript(cmResources.js[i]);
            }
            // Now load the editor controller which initialises CodeMirror
            await loadScript("/static/js/coding_editor.js?" + Date.now());

            // ── 10. Start exam proctoring ────────────────────
            // All streams are still alive (no page reload),
            // so setupExamProctoring finds everything active
            // and never exits fullscreen.
            if (typeof window.setupExamProctoring === "function") {
                window.setupExamProctoring();
            }

        } catch (err) {
            console.error("[CodingFlow] Start error:", err);
            alert("Unable to start the test. Please click Start Test again.\n\nReason: " + (err.message || err));
            if (startButton) startButton.disabled = false;
        }
    }, true); // ← capture phase: fires before proctoring.js handler

})();
