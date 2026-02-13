/* ================= CODING PROCTORING ================= */
/* Adapted from MCQ proctoring for /coding/ routes       */

const PATH = window.location.pathname;
const PATH_PARTS = PATH.split("/").filter(Boolean);
const SESSION_ID = PATH_PARTS.length >= 3 ? PATH_PARTS[PATH_PARTS.length - 1] : "";
const IS_START_PAGE = /^\/coding\/start\/[^/]+\/?$/.test(PATH);
const IS_SUBMIT_PAGE = /^\/coding\/submit\/[^/]+\/?$/.test(PATH);
const IS_EDITOR_PAGE = /^\/coding\/editor\/[^/]+\/?$/.test(PATH);
const IS_COMPLETED_PAGE = /^\/coding\/completed\/[^/]+\/?$/.test(PATH);
const IS_TEST_FLOW_PAGE = /^\/coding\/(?:start|editor|submit)\/[^/]+\/?$/.test(PATH);

const FULLSCREEN_REQUIRED_KEY = `coding_fullscreen_required_${SESSION_ID}`;
const NAV_IN_PROGRESS_KEY = `coding_nav_in_progress_${SESSION_ID}`;
const BASELINE_CAPTURE_KEY = `coding_baseline_capture_${SESSION_ID}`;
const SESSION_START_LOG_KEY = `coding_session_start_logged_${SESSION_ID}`;

const MAX_WARNINGS = 3;
const TAB_SWITCH_DEBOUNCE_MS = 1200;
const SCREENSHOT_THROTTLE_MS = 4000;
const PERIODIC_SCREENSHOT_INTERVAL_MS = 60 * 1000;
const TAB_SWITCH_CAPTURE_BURST_DELAYS_MS = [0, 500, 1500, 3000, 5000, 8000, 12000];
const TAB_RETURN_CAPTURE_DELAYS_MS  = [0, 200, 600];
const CONTENT_CHANGE_SAMPLE_INTERVAL_MS = 750;
const CONTENT_CHANGE_DIFF_THRESHOLD = 0.12;
const CONTENT_CHANGE_CAPTURE_COOLDOWN_MS = 2000;
const CONTENT_CHANGE_SAMPLE_W = 64;
const CONTENT_CHANGE_SAMPLE_H = 36;
const MULTI_MONITOR_CHECK_INTERVAL_MS = 4000;
const MULTI_MONITOR_DEBOUNCE_MS = 6000;
const MOUSE_OFF_PRIMARY_THRESHOLD_PX = 12;
const WEBCAM_DOCK_ID = "proctoringWebcamDock";
const WEBCAM_VIDEO_ID = "proctoringWebcamPreview";
const WEBCAM_RECORDING_TIMESLICE_MS = 5000;
const WEBCAM_RECORDING_TARGET_BPS = 250000;
const SCREEN_CAPTURE_VIDEO_ID = "proctoringScreenCaptureVideo";

function isExamPath() {
    return /^\/coding\/editor\/[^/]+\/?$/.test(window.location.pathname) ||
           /^\/coding\/submit\/[^/]+\/?$/.test(window.location.pathname);
}

function applyPageClassNames() {
    if (!document.body) return;
    if (IS_START_PAGE || IS_SUBMIT_PAGE || IS_COMPLETED_PAGE) document.body.classList.add("coding-start-page");
    if (IS_EDITOR_PAGE) document.body.classList.add("coding-editor-page");
}

let proctoringActive = isExamPath();
let warningCount = 0;
let isHandlingWarning = false;
let suppressWarnings = false;
let tabSwitchCount = 0;
let lastTabSwitchAt = 0;
let examListenersAttached = false;
let periodicScreenshotTimer = null;
let fullscreenExitCount = 0;
let outsideFullscreenStartedAt = null;
let outsideFullscreenTotalMs = 0;
let forcedReentryAttempts = 0;
let screenshotInProgress = false;
let lastScreenshotAt = 0;
let tabSwitchCaptureBurstId = 0;
let lastTabReturnCaptureAt = 0;
let contentChangeTimer = null;
let contentChangeSampleCanvas = null;
let contentChangePrevPixels = null;
let lastContentChangeCaptureAt = 0;
let contentChangeSuppressedUntil = 0;
let webcamStream = null;
let webcamEnabledLogged = false;
let webcamRecorder = null;
let webcamRecordingMimeType = "video/webm";
let webcamRecordingId = "";
let webcamChunkIndex = 0;
let webcamUploadQueue = Promise.resolve();
let webcamRecordingStopPromise = null;
let webcamRecordingFinalized = false;
let lastShortcutWarningAt = 0;
let shortcutListenersAttached = false;
let fullscreenRecoveryArmed = false;
let fullscreenRecoveryHandler = null;
let keyboardShortcutBlockedCount = 0;
let copyBlockedCount = 0;
let pasteBlockedCount = 0;
let rightClickBlockedCount = 0;
let screenStream = null;
let screenCaptureVideo = null;
let screenCaptureCanvas = null;
let screenCaptureReady = false;
let deferredBlurTimer = null;
let screenCapturePromptInFlight = false;
let screenCaptureAutoInitTried = false;
let screenCaptureGestureAttempted = false;
let screenCaptureGestureListenersArmed = false;
let screenCaptureEnabledLogged = false;
let screenCaptureUnavailableLogged = false;
let screenCaptureSurface = "";
let multiMonitorCheckTimer = null;
let multiMonitorEventCount = 0;
let lastMouseOutsideDetectAt = 0;
let lastMultiMonitorDetectAt = 0;

console.log("CODING PROCTORING ACTIVE");

/* ── Session flags ─────────────────────────────────── */
function isFullscreenRequired() {
    try { return sessionStorage.getItem(FULLSCREEN_REQUIRED_KEY) === "1"; } catch (_) { return false; }
}
function setFullscreenRequired(r) {
    try { r ? sessionStorage.setItem(FULLSCREEN_REQUIRED_KEY, "1") : sessionStorage.removeItem(FULLSCREEN_REQUIRED_KEY); } catch (_) {}
}
function setSessionFlag(k, v) {
    try { v ? sessionStorage.setItem(k, "1") : sessionStorage.removeItem(k); } catch (_) {}
}
function getSessionFlag(k) {
    try { return sessionStorage.getItem(k) === "1"; } catch (_) { return false; }
}
function setNavInProgress(v) { setSessionFlag(NAV_IN_PROGRESS_KEY, v); }
function isNavInProgress() { return getSessionFlag(NAV_IN_PROGRESS_KEY); }
function shouldIgnoreProctoringEvent() { return suppressWarnings || isNavInProgress() || screenCapturePromptInFlight; }

/* ── Fullscreen ────────────────────────────────────── */
function isInFullscreen() { return !!document.fullscreenElement; }
function requestAppFullscreen() { return document.documentElement.requestFullscreen(); }
function exitAppFullscreen() { return document.fullscreenElement ? document.exitFullscreen() : Promise.resolve(); }

/* ── Network helpers ───────────────────────────────── */
function sendJSON(url, payload, useBeacon = false) {
    const body = JSON.stringify(payload);
    if (useBeacon && navigator.sendBeacon) {
        const blob = new Blob([body], { type: "application/json" });
        navigator.sendBeacon(url, blob);
        return;
    }
    fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: useBeacon }).catch(() => {});
}

function sendViolation(type, details = {}, useBeacon = false) {
    if (!SESSION_ID) return;
    sendJSON("/coding/proctoring/violation", {
        session_id: SESSION_ID,
        violation_type: type,
        details,
        ts: new Date().toISOString()
    }, useBeacon);
}

function sendScreenshot(eventType, imageData, details = {}) {
    if (!SESSION_ID || !imageData) return;
    sendJSON("/coding/proctoring/screenshot", {
        session_id: SESSION_ID,
        event_type: eventType,
        image_data: imageData,
        details,
        ts: new Date().toISOString()
    });
}

/* ── Screen capture ────────────────────────────────── */
function supportsDisplayCapture() {
    return !!(navigator.mediaDevices && typeof navigator.mediaDevices.getDisplayMedia === "function");
}
function getDisplaySurfaceFromTrack(t) {
    if (!t || typeof t.getSettings !== "function") return "";
    try { return String((t.getSettings() || {}).displaySurface || "").toLowerCase(); } catch (_) { return ""; }
}
function isEntireScreenSurface(s) { return s === "monitor"; }

function getOrCreateScreenCaptureVideo() {
    if (screenCaptureVideo) return screenCaptureVideo;
    let v = document.getElementById(SCREEN_CAPTURE_VIDEO_ID);
    if (!v) {
        v = document.createElement("video");
        v.id = SCREEN_CAPTURE_VIDEO_ID;
        v.autoplay = true; v.muted = true; v.playsInline = true; v.tabIndex = -1;
        v.setAttribute("aria-hidden", "true");
        v.style.cssText = "position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;";
        document.body.appendChild(v);
    }
    screenCaptureVideo = v;
    return v;
}

function stopScreenCaptureMonitor() {
    screenCaptureReady = false; screenCaptureSurface = "";
    const s = screenStream; screenStream = null;
    if (screenCaptureVideo) { try { screenCaptureVideo.pause(); } catch (_) {} screenCaptureVideo.srcObject = null; }
    if (s) s.getTracks().forEach(t => t.stop());
}

async function startScreenCaptureMonitor() {
    if (!IS_TEST_FLOW_PAGE) return false;
    if (screenStream && screenStream.active && screenCaptureReady) return true;
    if (screenCapturePromptInFlight) return false;
    if (!supportsDisplayCapture()) {
        if (!screenCaptureUnavailableLogged) { screenCaptureUnavailableLogged = true; sendViolation("Screen capture unavailable", { reason: "display_media_unsupported" }); }
        return false;
    }
    screenCapturePromptInFlight = true;
    try {
        const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: 10, max: 15 } }, audio: false });
        const [track] = stream.getVideoTracks();
        const ds = getDisplaySurfaceFromTrack(track);
        if (!track || !isEntireScreenSurface(ds)) {
            stream.getTracks().forEach(t => t.stop());
            screenCaptureReady = false; screenCaptureSurface = "";
            sendViolation("Screen capture rejected", { reason: "entire_screen_required", display_surface: ds || "unknown" });
            showBanner("Select 'Entire Screen' to continue the test.", "danger");
            return false;
        }
        stopScreenCaptureMonitor();
        screenStream = stream; screenCaptureSurface = ds;
        const video = getOrCreateScreenCaptureVideo();
        video.srcObject = stream;
        try { await video.play(); } catch (_) {}
        if (track) {
            track.addEventListener("ended", () => {
                if (screenStream !== stream) return;
                screenCaptureReady = false; screenCaptureSurface = ""; screenStream = null;
                if (screenCaptureVideo) screenCaptureVideo.srcObject = null;
                sendViolation("Screen capture ended", { reason: "track_ended" });
                if (isExamPath() && isFullscreenRequired()) { showLockOverlay(getProctoringRequirementMessage()); armFullscreenRecovery(); }
            });
        }
        screenCaptureReady = true; screenCaptureUnavailableLogged = false;
        if (!screenCaptureEnabledLogged) { screenCaptureEnabledLogged = true; sendViolation("Screen capture enabled", { video_track_count: stream.getVideoTracks().length, display_surface: screenCaptureSurface || ds || "unknown" }); }
        return true;
    } catch (error) {
        if (!screenCaptureUnavailableLogged) { screenCaptureUnavailableLogged = true; sendViolation("Screen capture unavailable", { reason: (error && error.name) || "permission_denied_or_aborted" }); }
        return false;
    } finally { screenCapturePromptInFlight = false; }
}

async function ensureProctoringReady(options = {}) {
    const rss = options.requireScreenShare !== false;
    const rfs = options.requireFullscreen !== false;
    const wo = options.withOverlay !== false;

    // If we need screen share and don't have it, we MUST exit fullscreen first
    // because the screen share picker dialog will break fullscreen anyway.
    if (rss && !screenCaptureReady) {
        if (isInFullscreen()) {
            suppressWarnings = true;
            try { await exitAppFullscreen(); } catch (_) {}
            await new Promise(r => setTimeout(r, 300));
        }
        const ok = await startScreenCaptureMonitor();
        if (!ok || !screenCaptureReady) {
            suppressWarnings = false;
            if (wo) { showLockOverlay(getProctoringRequirementMessage()); armFullscreenRecovery(); }
            return false;
        }
    }

    // Now enter fullscreen (all dialogs are done)
    if (rfs && !isInFullscreen()) {
        try { await requestAppFullscreen(); } catch (_) {
            suppressWarnings = false;
            if (wo) { showLockOverlay(getProctoringRequirementMessage()); armFullscreenRecovery(); }
            return false;
        }
    }

    suppressWarnings = false;
    const ready = (!rss || screenCaptureReady) && (!rfs || isInFullscreen());
    if (!ready) { if (wo) { showLockOverlay(getProctoringRequirementMessage()); armFullscreenRecovery(); } return false; }
    hideLockOverlay(); disarmFullscreenRecovery(); return true;
}

/* ── Screenshots ───────────────────────────────────── */
function captureScreenshot(eventType, details = {}, force = false) {
    if (!SESSION_ID) return;
    if (typeof window.html2canvas !== "function") return;
    if (!force && !proctoringActive) return;
    const now = Date.now();
    if (!force && (screenshotInProgress || (now - lastScreenshotAt) < SCREENSHOT_THROTTLE_MS)) return;
    screenshotInProgress = true;
    window.html2canvas(document.body, { backgroundColor: "#0d1117", scale: 0.5, logging: false, useCORS: true })
        .then(canvas => { const img = canvas.toDataURL("image/jpeg", 0.65); sendScreenshot(eventType, img, { ...details, capture_source: details.capture_source || "page_dom" }); lastScreenshotAt = Date.now(); })
        .catch(() => {})
        .finally(() => { screenshotInProgress = false; });
}

function captureScreenFrame(eventType, details = {}, force = false) {
    if (!SESSION_ID || !screenCaptureReady || !screenStream) return false;
    const video = getOrCreateScreenCaptureVideo();
    const w = Number(video.videoWidth) || 0, h = Number(video.videoHeight) || 0;
    if (!w || !h) return false;
    const now = Date.now();
    if (!force && (now - lastScreenshotAt) < SCREENSHOT_THROTTLE_MS) return false;
    if (!screenCaptureCanvas) screenCaptureCanvas = document.createElement("canvas");
    screenCaptureCanvas.width = w; screenCaptureCanvas.height = h;
    const ctx = screenCaptureCanvas.getContext("2d");
    if (!ctx) return false;
    try {
        ctx.drawImage(video, 0, 0, w, h);
        const img = screenCaptureCanvas.toDataURL("image/jpeg", 0.68);
        sendScreenshot(eventType, img, { ...details, capture_source: "screen_stream" });
        lastScreenshotAt = Date.now();
        return true;
    } catch (_) { return false; }
}

function captureTabSwitchEvidence(details = {}) {
    const burstId = ++tabSwitchCaptureBurstId;
    TAB_SWITCH_CAPTURE_BURST_DELAYS_MS.forEach((d, i) => {
        setTimeout(() => {
            if (burstId !== tabSwitchCaptureBurstId) return;
            const ok = captureScreenFrame("tab_switch", details, true);
            if (!ok && i === 0) captureScreenshot("tab_switch", { ...details, capture_source: "page_dom_fallback" }, true);
        }, d);
    });
}

function captureTabReturnEvidence() {
    const now = Date.now();
    if ((now - lastTabReturnCaptureAt) < TAB_SWITCH_DEBOUNCE_MS) return;
    lastTabReturnCaptureAt = now;
    TAB_RETURN_CAPTURE_DELAYS_MS.forEach((delayMs) => {
        setTimeout(() => {
            captureScreenFrame("tab_return", { capture_trigger: "tab_return" }, true);
        }, delayMs);
    });
}

/* ── Screen content-change detection ───────────────── */
function sampleScreenFrame() {
    try {
        const video = screenCaptureVideo;
        if (!video || !screenStream || !screenStream.active || !screenCaptureReady) return null;
        const vw = Number(video.videoWidth) || 0, vh = Number(video.videoHeight) || 0;
        if (!vw || !vh) return null;
        if (!contentChangeSampleCanvas) contentChangeSampleCanvas = document.createElement("canvas");
        contentChangeSampleCanvas.width = CONTENT_CHANGE_SAMPLE_W;
        contentChangeSampleCanvas.height = CONTENT_CHANGE_SAMPLE_H;
        const ctx = contentChangeSampleCanvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) return null;
        ctx.drawImage(video, 0, 0, CONTENT_CHANGE_SAMPLE_W, CONTENT_CHANGE_SAMPLE_H);
        return ctx.getImageData(0, 0, CONTENT_CHANGE_SAMPLE_W, CONTENT_CHANGE_SAMPLE_H).data;
    } catch (_) { return null; }
}

function computeFrameDiff(a, b) {
    if (!a || !b || a.length !== b.length) return 1;
    const totalPixels = a.length / 4;
    let changed = 0;
    for (let i = 0; i < a.length; i += 4) {
        const dr = Math.abs(a[i] - b[i]);
        const dg = Math.abs(a[i + 1] - b[i + 1]);
        const db = Math.abs(a[i + 2] - b[i + 2]);
        if (dr + dg + db > 60) changed++;
    }
    return changed / totalPixels;
}

function suppressContentChangeDetection(durationMs = 2000) {
    contentChangeSuppressedUntil = Date.now() + durationMs;
    contentChangePrevPixels = null;
}
window.suppressContentChangeDetection = suppressContentChangeDetection;

function contentChangeCheck() {
    if (!proctoringActive || shouldIgnoreProctoringEvent()) return;
    const now = Date.now();
    if (now < contentChangeSuppressedUntil) { contentChangePrevPixels = null; return; }
    const currentPixels = sampleScreenFrame();
    if (!currentPixels) { contentChangePrevPixels = null; return; }
    if (contentChangePrevPixels) {
        const diff = computeFrameDiff(contentChangePrevPixels, currentPixels);
        if (diff >= CONTENT_CHANGE_DIFF_THRESHOLD) {
            if ((now - lastContentChangeCaptureAt) >= CONTENT_CHANGE_CAPTURE_COOLDOWN_MS) {
                lastContentChangeCaptureAt = now;
                captureScreenFrame("content_change", {
                    capture_trigger: "screen_content_changed",
                    diff_ratio: Math.round(diff * 100) / 100
                }, true);
            }
        }
    }
    contentChangePrevPixels = currentPixels;
}

function startContentChangeDetection() {
    if (contentChangeTimer || !isExamPath()) return;
    contentChangePrevPixels = null;
    contentChangeTimer = setInterval(contentChangeCheck, CONTENT_CHANGE_SAMPLE_INTERVAL_MS);
}

function stopContentChangeDetection() {
    if (contentChangeTimer) { clearInterval(contentChangeTimer); contentChangeTimer = null; }
    contentChangePrevPixels = null;
    contentChangeSampleCanvas = null;
}

function captureEvidence(eventType, details = {}, force = true) {
    const ok = captureScreenFrame(eventType, details, force);
    if (!ok) captureScreenshot(eventType, { ...details, capture_source: "page_dom_fallback" }, force);
}

/* ── UI helpers ────────────────────────────────────── */
function showBanner(message, tone = "warning") {
    let banner = document.getElementById("proctoringBanner");
    if (!banner) {
        banner = document.createElement("div");
        banner.id = "proctoringBanner";
        banner.className = "coding-banner " + tone;
        banner.style.cssText = "position:fixed;top:56px;left:50%;transform:translateX(-50%);z-index:9999;padding:10px 24px;border-radius:8px;font-size:14px;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,0.4);pointer-events:none;";
        document.body.appendChild(banner);
    }
    banner.className = "coding-banner " + tone;
    banner.innerText = message;
    banner.style.display = "block";
    clearTimeout(banner._hideTimer);
    banner._hideTimer = setTimeout(() => { banner.style.display = "none"; }, 5000);
}

function formatCount(v, s, p) { return `${v} ${v === 1 ? s : p}`; }
function formatShortcut(e) {
    const keys = [];
    if (e.ctrlKey) keys.push("Ctrl"); if (e.altKey) keys.push("Alt"); if (e.metaKey) keys.push("Meta"); if (e.shiftKey) keys.push("Shift");
    const k = String(e.key || "").trim(), n = k.toLowerCase();
    if (k && !["control","alt","meta","shift"].includes(n)) keys.push(k.length === 1 ? k.toUpperCase() : k);
    return keys.length ? keys.join("+") : "Unknown key";
}
function formatTabSwitchSource(s) { return s === "visibility_hidden" ? "tab hidden" : s === "window_blur" ? "window blur" : s; }
function getProctoringRequirementMessage() {
    if (!screenCaptureReady) return "Share Entire Screen permission is required to continue the test.";
    if (!isInFullscreen()) return "You must remain in full screen to continue the test.";
    return "";
}
function hasProctoringRequirements() { return screenCaptureReady && isInFullscreen(); }

/* ── Lock Overlay ──────────────────────────────────── */
function getOrCreateLockOverlay() {
    let o = document.getElementById("proctoringLockOverlay");
    if (o) return o;
    o = document.createElement("div");
    o.id = "proctoringLockOverlay";
    o.style.display = "none";
    o.innerHTML = `<div class="lock-message" style="text-align:center;max-width:640px;padding:24px;">
        <div id="proctoringLockText">You must remain in full screen to continue the test.</div>
        <button id="resumeFullscreenBtn" type="button" style="margin-top:14px;padding:10px 18px;border:none;border-radius:6px;background:#ffffff;color:#8b0000;font-weight:700;cursor:pointer;">Resume Proctoring</button>
    </div>`;
    document.body.appendChild(o);
    const resume = async () => {
        forcedReentryAttempts += 1;
        sendViolation("Fullscreen re-entry attempt", { forced_reentry_attempts: forcedReentryAttempts, fullscreen_exit_count: fullscreenExitCount, screen_capture_ready: screenCaptureReady, in_fullscreen: isInFullscreen() });
        const ready = await ensureProctoringReady({ requireScreenShare: true, requireFullscreen: true, withOverlay: true });
        if (!ready) showLockOverlay(getProctoringRequirementMessage());
    };
    o.addEventListener("click", resume);
    const btn = o.querySelector("#resumeFullscreenBtn");
    if (btn) btn.addEventListener("click", e => { e.stopPropagation(); resume(); });
    return o;
}

function showLockOverlay(msg) {
    const o = getOrCreateLockOverlay();
    const t = o.querySelector("#proctoringLockText");
    if (t) t.textContent = msg;
    document.body.classList.add("proctoring-violation");
    o.style.display = "flex";
}

function hideLockOverlay() {
    const o = document.getElementById("proctoringLockOverlay");
    if (o) o.style.display = "none";
    document.body.classList.remove("proctoring-violation");
}

function disarmFullscreenRecovery() {
    if (!fullscreenRecoveryArmed || !fullscreenRecoveryHandler) return;
    ["pointerdown","mousedown","touchstart","keydown","click"].forEach(e => window.removeEventListener(e, fullscreenRecoveryHandler, true));
    fullscreenRecoveryHandler = null; fullscreenRecoveryArmed = false;
}

function armFullscreenRecovery() {
    if (fullscreenRecoveryArmed) return;
    fullscreenRecoveryArmed = true;
    fullscreenRecoveryHandler = async (e) => {
        if (hasProctoringRequirements()) { hideLockOverlay(); disarmFullscreenRecovery(); return; }
        if (!isFullscreenRequired() || !isExamPath()) { disarmFullscreenRecovery(); return; }
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        const ready = await ensureProctoringReady({ requireScreenShare: true, requireFullscreen: true, withOverlay: true });
        if (!ready) showLockOverlay(getProctoringRequirementMessage());
    };
    ["pointerdown","mousedown","touchstart","keydown","click"].forEach(e => window.addEventListener(e, fullscreenRecoveryHandler, true));
}

/* ── Webcam ────────────────────────────────────────── */
function getOrCreateWebcamDock() {
    let dock = document.getElementById(WEBCAM_DOCK_ID);
    if (dock) return dock;
    dock = document.createElement("div");
    dock.id = WEBCAM_DOCK_ID;
    dock.innerHTML = `<video id="${WEBCAM_VIDEO_ID}" autoplay muted playsinline></video>`;
    const header = document.querySelector(".header");
    if (header) {
        header.appendChild(dock);
    } else {
        document.body.appendChild(dock);
    }
    return dock;
}

function buildWebcamRecordingId() { return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`; }

function getSupportedWebcamRecordingMimeType() {
    if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return "";
    for (const m of ["video/webm;codecs=vp9,opus","video/webm;codecs=vp8,opus","video/webm"]) { if (MediaRecorder.isTypeSupported(m)) return m; }
    return "";
}

function enqueueWebcamChunkUpload(chunkBlob) {
    if (!chunkBlob || !chunkBlob.size || !SESSION_ID || !webcamRecordingId) return Promise.resolve();
    const ci = webcamChunkIndex; webcamChunkIndex += 1;
    const ts = new Date().toISOString();
    const mt = webcamRecordingMimeType || chunkBlob.type || "video/webm";
    webcamUploadQueue = webcamUploadQueue.then(() => {
        const fd = new FormData();
        fd.append("session_id", SESSION_ID); fd.append("recording_id", webcamRecordingId);
        fd.append("chunk_index", String(ci)); fd.append("mime_type", mt); fd.append("ts", ts);
        fd.append("chunk", chunkBlob, `chunk_${String(ci).padStart(6, "0")}.webm`);
        return fetch("/coding/proctoring/webcam", { method: "POST", body: fd, credentials: "same-origin" }).catch(() => {});
    }).catch(() => {});
    return webcamUploadQueue;
}

function finalizeWebcamRecordingUpload() {
    if (!SESSION_ID || !webcamRecordingId || webcamRecordingFinalized) return Promise.resolve();
    const fd = new FormData();
    fd.append("session_id", SESSION_ID); fd.append("recording_id", webcamRecordingId);
    fd.append("mime_type", webcamRecordingMimeType || "video/webm"); fd.append("final", "1");
    fd.append("chunk_count", String(webcamChunkIndex)); fd.append("ts", new Date().toISOString());
    return fetch("/coding/proctoring/webcam", { method: "POST", body: fd, credentials: "same-origin" })
        .then(() => { webcamRecordingFinalized = true; }).catch(() => {});
}

async function startWebcamRecording() {
    if (!isExamPath() || !webcamStream || !webcamStream.active) return;
    if (typeof MediaRecorder === "undefined") { sendViolation("Webcam recording unavailable", { reason: "media_recorder_unsupported" }); return; }
    if (webcamRecorder && webcamRecorder.state !== "inactive") return;
    webcamRecordingMimeType = getSupportedWebcamRecordingMimeType() || "video/webm";
    if (!webcamRecordingId) webcamRecordingId = buildWebcamRecordingId();
    webcamChunkIndex = 0; webcamUploadQueue = Promise.resolve(); webcamRecordingFinalized = false; webcamRecordingStopPromise = null;
    try {
        webcamRecorder = webcamRecordingMimeType !== "video/webm"
            ? new MediaRecorder(webcamStream, { mimeType: webcamRecordingMimeType, videoBitsPerSecond: WEBCAM_RECORDING_TARGET_BPS })
            : new MediaRecorder(webcamStream, { videoBitsPerSecond: WEBCAM_RECORDING_TARGET_BPS });
    } catch (_) {
        try { webcamRecorder = new MediaRecorder(webcamStream); webcamRecordingMimeType = webcamRecorder.mimeType || webcamRecordingMimeType; }
        catch (_) { sendViolation("Webcam recording unavailable", { reason: "media_recorder_init_failed" }); webcamRecorder = null; return; }
    }
    webcamRecorder.addEventListener("dataavailable", e => { if (e.data && e.data.size) enqueueWebcamChunkUpload(e.data); });
    webcamRecorder.addEventListener("error", () => { sendViolation("Webcam recording error", { state: webcamRecorder ? webcamRecorder.state : "unknown" }); });
    try { webcamRecorder.start(WEBCAM_RECORDING_TIMESLICE_MS); sendViolation("Webcam recording started", { recording_id: webcamRecordingId, mime_type: webcamRecordingMimeType, chunk_timeslice_ms: WEBCAM_RECORDING_TIMESLICE_MS }); }
    catch (_) { webcamRecorder = null; sendViolation("Webcam recording unavailable", { reason: "media_recorder_start_failed" }); }
}

function stopWebcamRecording(options = {}) {
    const finalize = options.final === true;
    if (webcamRecordingStopPromise) return webcamRecordingStopPromise;
    const rec = webcamRecorder;
    webcamRecordingStopPromise = (async () => {
        if (rec && rec.state !== "inactive") {
            await new Promise(resolve => {
                rec.addEventListener("stop", () => resolve(), { once: true });
                try { rec.requestData(); } catch (_) {}
                try { rec.stop(); } catch (_) { resolve(); }
            });
        }
        await webcamUploadQueue.catch(() => {});
        if (finalize) { await finalizeWebcamRecordingUpload(); if (webcamRecordingId) sendViolation("Webcam recording saved", { recording_id: webcamRecordingId, chunk_count: webcamChunkIndex, mime_type: webcamRecordingMimeType }); }
        webcamRecorder = null;
    })().finally(() => { webcamRecordingStopPromise = null; });
    return webcamRecordingStopPromise;
}

function stopWebcamPreview(options = {}) {
    stopWebcamRecording({ final: options.final === true });
    const v = document.getElementById(WEBCAM_VIDEO_ID);
    if (v) v.srcObject = null;
    if (webcamStream) { webcamStream.getTracks().forEach(t => t.stop()); webcamStream = null; }
}

async function startWebcamPreview() {
    if (!isExamPath()) return;
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") { sendViolation("Webcam unavailable", { reason: "media_devices_unsupported" }); return; }
    const dock = getOrCreateWebcamDock();
    dock.style.display = "block";
    if (webcamStream && webcamStream.active) {
        const ev = document.getElementById(WEBCAM_VIDEO_ID);
        if (ev && ev.srcObject !== webcamStream) { ev.srcObject = webcamStream; try { await ev.play(); } catch (_) {} }
        await startWebcamRecording(); return;
    }
    try {
        webcamStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 180 } }, audio: false });
        const video = document.getElementById(WEBCAM_VIDEO_ID);
        if (video) { video.srcObject = webcamStream; try { await video.play(); } catch (_) {} }
        if (!webcamEnabledLogged) { webcamEnabledLogged = true; sendViolation("Webcam preview enabled", { video_track_count: webcamStream.getVideoTracks().length }); }
        await startWebcamRecording();
    } catch (_) {
        dock.style.display = "none";
        sendViolation("Webcam access denied", { path: window.location.pathname });
        showBanner("Webcam access is required for live proctoring.", "danger");
    }
}

function armScreenCaptureMonitorFromGesture() {
    if (!isExamPath() || screenCaptureGestureAttempted || screenCaptureReady || screenCaptureGestureListenersArmed || !supportsDisplayCapture()) return;
    screenCaptureGestureListenersArmed = true;
    const handler = () => { if (screenCaptureGestureAttempted || screenCaptureReady) return; screenCaptureGestureAttempted = true; startScreenCaptureMonitor(); };
    ["pointerdown","mousedown","touchstart","keydown","click"].forEach(e => window.addEventListener(e, handler, { capture: true, once: true }));
}

/* ── Warning engine ────────────────────────────────── */
function updateFocusChip() {
    const el = document.getElementById("codingFocusCount");
    if (el) el.textContent = warningCount;
    const chip = document.getElementById("codingFocusChip");
    if (chip) {
        chip.style.color = warningCount > 0 ? "#f59e0b" : "";
        chip.style.borderColor = warningCount > 0 ? "rgba(245,158,11,0.35)" : "";
        chip.style.background = warningCount > 0 ? "rgba(245,158,11,0.1)" : "";
    }
}
function issueWarning(reason, details = {}, options = {}) {
    if (!proctoringActive || isHandlingWarning || shouldIgnoreProctoringEvent()) return;
    isHandlingWarning = true;
    const inc = options.incrementWarning !== false;
    if (inc) warningCount += 1;
    updateFocusChip();
    showBanner(options.bannerMessage || `Warning ${warningCount}/${MAX_WARNINGS}: ${reason}`, options.bannerTone || "warning");
    sendViolation(reason, { warning_count: warningCount, ...details });
    if (inc && warningCount >= MAX_WARNINGS) { window.location.href = `/coding/submit/${SESSION_ID}`; return; }
    setTimeout(() => { isHandlingWarning = false; }, 800);
}

function recordFullscreenRestored() {
    if (!outsideFullscreenStartedAt) return;
    const ms = Date.now() - outsideFullscreenStartedAt;
    outsideFullscreenStartedAt = null; outsideFullscreenTotalMs += ms;
    sendViolation("Fullscreen restored", { fullscreen_exit_count: fullscreenExitCount, outside_fullscreen_ms: ms, total_outside_fullscreen_ms: outsideFullscreenTotalMs, forced_reentry_attempts: forcedReentryAttempts });
    disarmFullscreenRecovery();
}

function handleFullscreenExit() {
    fullscreenExitCount += 1;
    if (!outsideFullscreenStartedAt) outsideFullscreenStartedAt = Date.now();
    showLockOverlay("You must remain in full screen to continue the test.");
    armFullscreenRecovery();
    issueWarning("Fullscreen exited", { fullscreen_exit_count: fullscreenExitCount, forced_reentry_attempts: forcedReentryAttempts }, {
        bannerMessage: `Fullscreen exited (${formatCount(fullscreenExitCount, "time", "times")}). You must remain in full screen to continue the test.`,
        bannerTone: "danger"
    });
    captureScreenshot("fullscreen_exit", { fullscreen_exit_count: fullscreenExitCount });
}

function handleTabSwitch(source) {
    const now = Date.now();
    if ((now - lastTabSwitchAt) < TAB_SWITCH_DEBOUNCE_MS) return;
    lastTabSwitchAt = now; tabSwitchCount += 1;
    document.body.classList.add("proctoring-warning");
    issueWarning("Tab switching detected", { source, tab_switch_count: tabSwitchCount }, {
        incrementWarning: false,
        bannerMessage: `Tab switching detected (${formatCount(tabSwitchCount, "time", "times")}). Source: ${formatTabSwitchSource(source)}. Activity logged.`,
        bannerTone: "warning"
    });
    captureTabSwitchEvidence({ source, tab_switch_count: tabSwitchCount });
}

/* ── Periodic capture & multi-monitor ──────────────── */
function startPeriodicScreenshotCapture() {
    if (!isExamPath() || periodicScreenshotTimer) return;
    periodicScreenshotTimer = setInterval(() => {
        if (!proctoringActive || shouldIgnoreProctoringEvent()) return;
        captureEvidence("interval_1min", { interval_seconds: 60, path: window.location.pathname }, true);
    }, PERIODIC_SCREENSHOT_INTERVAL_MS);
}
function stopPeriodicScreenshotCapture() { if (periodicScreenshotTimer) { clearInterval(periodicScreenshotTimer); periodicScreenshotTimer = null; } }

function isMouseOutsidePrimaryScreen(e) {
    const x = Number(e.screenX), y = Number(e.screenY);
    if (Number.isNaN(x) || Number.isNaN(y)) return false;
    const pw = Number(window.screen && window.screen.width) || 0;
    const ph = Number(window.screen && window.screen.height) || 0;
    if (!pw || !ph) return false;
    return x < -MOUSE_OFF_PRIMARY_THRESHOLD_PX || y < -MOUSE_OFF_PRIMARY_THRESHOLD_PX || x > (pw + MOUSE_OFF_PRIMARY_THRESHOLD_PX) || y > (ph + MOUSE_OFF_PRIMARY_THRESHOLD_PX);
}

function handleMultiMonitorDetected(source, details = {}) {
    const now = Date.now();
    if ((now - lastMultiMonitorDetectAt) < MULTI_MONITOR_DEBOUNCE_MS) return;
    lastMultiMonitorDetectAt = now; multiMonitorEventCount += 1;
    issueWarning("Multi-monitor activity detected", { source, multi_monitor_event_count: multiMonitorEventCount, ...details }, {
        incrementWarning: false,
        bannerMessage: `Multi-monitor activity detected (${formatCount(multiMonitorEventCount, "time", "times")}). Source: ${source}. Activity logged.`,
        bannerTone: "warning"
    });
    captureEvidence("multi_monitor", { source, multi_monitor_event_count: multiMonitorEventCount, ...details }, true);
}

function checkExtendedDisplay(reason = "periodic_check") {
    if (!proctoringActive || shouldIgnoreProctoringEvent()) return;
    if (!window.screen || typeof window.screen.isExtended !== "boolean" || !window.screen.isExtended) return;
    handleMultiMonitorDetected("screen_extended", { reason });
}

function startMultiMonitorDetection() {
    if (!isExamPath() || multiMonitorCheckTimer) return;
    multiMonitorCheckTimer = setInterval(() => checkExtendedDisplay("interval"), MULTI_MONITOR_CHECK_INTERVAL_MS);
    checkExtendedDisplay("init");
}
function stopMultiMonitorDetection() { if (multiMonitorCheckTimer) { clearInterval(multiMonitorCheckTimer); multiMonitorCheckTimer = null; } }

/* ── Keyboard shortcut blocking ────────────────────── */
function shouldBlockShortcutKey(e) {
    const k = String(e.key || ""), n = k.toLowerCase();
    if (e.ctrlKey || e.metaKey || e.altKey) return true;
    if (/^f([1-9]|1[0-2])$/i.test(k)) return true;
    if (["tab","escape","printscreen","contextmenu","meta","alt","control"].includes(n)) return true;
    return false;
}

function handleShortcutBlock(e) {
    if (!IS_TEST_FLOW_PAGE || !shouldBlockShortcutKey(e)) return;
    if (e.__codingShortcutHandled) return;

    // IMPORTANT: Allow Tab key in code editor textarea
    if (e.key === "Tab" && e.target && e.target.id === "codingEditor") return;

    e.__codingShortcutHandled = true;
    e.preventDefault(); e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
    const now = Date.now();
    if ((now - lastShortcutWarningAt) < 700) return;
    lastShortcutWarningAt = now;
    if (proctoringActive && !shouldIgnoreProctoringEvent()) {
        keyboardShortcutBlockedCount += 1;
        const shortcut = formatShortcut(e);
        issueWarning("Keyboard shortcut blocked", { shortcut, shortcut_block_count: keyboardShortcutBlockedCount, key: e.key, ctrl: !!e.ctrlKey, alt: !!e.altKey, meta: !!e.metaKey, shift: !!e.shiftKey }, {
            incrementWarning: false,
            bannerMessage: `Keyboard shortcut blocked (${formatCount(keyboardShortcutBlockedCount, "time", "times")}): ${shortcut}. Activity logged.`,
            bannerTone: "warning"
        });
        captureEvidence("keyboard_shortcut_block", { shortcut, shortcut_block_count: keyboardShortcutBlockedCount }, true);
    }
}

function setupKeyboardShortcutBlocking() {
    if (!IS_TEST_FLOW_PAGE || shortcutListenersAttached) return;
    shortcutListenersAttached = true;
    window.addEventListener("keydown", handleShortcutBlock, true);
    window.addEventListener("keyup", handleShortcutBlock, true);
    window.addEventListener("keypress", handleShortcutBlock, true);
    document.addEventListener("keydown", handleShortcutBlock, true);
}

function captureBaselineScreenshot() {
    if (getSessionFlag(BASELINE_CAPTURE_KEY)) return;
    setSessionFlag(BASELINE_CAPTURE_KEY, true);
    captureScreenshot("baseline_start", { page: window.location.pathname }, true);
}

function logSessionStartIfNeeded() {
    if (getSessionFlag(SESSION_START_LOG_KEY)) return;
    setSessionFlag(SESSION_START_LOG_KEY, true);
    sendViolation("Session monitoring started", { path: window.location.pathname, user_agent: navigator.userAgent });
}

/* ── Start page fullscreen gate ────────────────────── */
function setupStartFullscreenGate() {
    if (!IS_START_PAGE) return;
    if (window.__CODING_AJAX_FLOW) return;  // SPA flow (coding_flow.js) handles this
    const beginForm = document.querySelector("form[action*='/coding/begin/']");
    if (!beginForm) return;
    let bypass = false;
    beginForm.addEventListener("submit", async (e) => {
        if (bypass) return;
        e.preventDefault();
        try {
            // All permission dialogs MUST happen BEFORE fullscreen.
            // Browsers exit fullscreen whenever a system dialog appears.
            suppressWarnings = true;

            // Step 1: Request screen share (system dialog)
            if (!screenCaptureReady) {
                const scOk = await startScreenCaptureMonitor();
                if (!scOk || !screenCaptureReady) {
                    suppressWarnings = false;
                    alert("You must share your Entire Screen to start the test.");
                    return;
                }
            }

            // Step 2: Request webcam (system dialog)
            // Must happen here, NOT on editor page, or it will break fullscreen
            if (!webcamStream || !webcamStream.active) {
                try {
                    webcamStream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 180 } },
                        audio: false
                    });
                    if (!webcamEnabledLogged) {
                        webcamEnabledLogged = true;
                        sendViolation("Webcam preview enabled", { video_track_count: webcamStream.getVideoTracks().length });
                    }
                } catch (_) {
                    // Webcam is optional — continue even if denied
                    sendViolation("Webcam access denied", { page: "start" });
                }
            }

            // Step 3: NOW enter fullscreen (no more dialogs will interrupt it)
            if (!isInFullscreen()) {
                try {
                    await requestAppFullscreen();
                    await new Promise(r => setTimeout(r, 400));
                } catch (_) {
                    // Fullscreen may fail if user gesture expired during dialogs.
                    // Proceed anyway — editor page will enforce fullscreen via lock overlay.
                    console.warn("[Proctoring] Fullscreen request failed on start page, editor page will handle it.");
                }
            }

            suppressWarnings = false;
            setFullscreenRequired(true);
            bypass = true;
            beginForm.submit();
        } catch (_) {
            suppressWarnings = false;
            alert("Share Entire Screen and fullscreen are required to start the test.");
        }
    });
}

/* ── Exam proctoring setup ─────────────────────────── */
function setupExamProctoring() {
    if (!isExamPath()) return;
    proctoringActive = true;
    setNavInProgress(false); setFullscreenRequired(true);
    logSessionStartIfNeeded();
    startPeriodicScreenshotCapture(); startContentChangeDetection(); startMultiMonitorDetection();

    // ── CRITICAL FIX ─────────────────────────────────────
    // Browsers exit fullscreen whenever a system permission dialog appears
    // (screen-share picker, webcam prompt). Therefore the correct order is:
    //   1. Acquire screen share  (may show dialog — NOT in fullscreen)
    //   2. Acquire webcam        (may show dialog — NOT in fullscreen)
    //   3. THEN enter fullscreen (no more dialogs will interrupt it)
    // All of this happens while warnings are suppressed so the temporary
    // absence of fullscreen does not trigger violations.
    // ─────────────────────────────────────────────────────
    suppressWarnings = true;

    setTimeout(async () => {
        try {
            // Only exit fullscreen when screen share (getDisplayMedia) needs
            // to be acquired — it shows a system-level picker dialog that the
            // browser will force-exit fullscreen for.  getUserMedia (webcam)
            // works fine INSIDE fullscreen so we never need to leave for it.
            const needScreenShare = !screenCaptureReady;
            const needWebcam = !webcamStream || !webcamStream.active;

            if (needScreenShare && isInFullscreen()) {
                try { await exitAppFullscreen(); } catch (_) {}
                await new Promise(r => setTimeout(r, 300));
            }

            // Step 2: Acquire screen share (system dialog — must happen BEFORE fullscreen)
            if (needScreenShare) {
                screenCaptureAutoInitTried = true;
                const scOk = await startScreenCaptureMonitor();
                if (!scOk || !screenCaptureReady) {
                    // Screen share failed — we'll show the lock overlay after fullscreen
                    console.warn("[Proctoring] Screen share not acquired on editor page");
                }
            }

            // Step 3: Acquire webcam (system dialog — must happen BEFORE fullscreen)
            if (webcamStream && webcamStream.active) {
                const dock = getOrCreateWebcamDock();
                dock.style.display = "block";
                const video = document.getElementById(WEBCAM_VIDEO_ID);
                if (video && video.srcObject !== webcamStream) {
                    video.srcObject = webcamStream;
                    try { await video.play(); } catch (_) {}
                }
                await startWebcamRecording();
            } else {
                try {
                    webcamStream = await navigator.mediaDevices.getUserMedia({
                        video: { facingMode: "user", width: { ideal: 320 }, height: { ideal: 180 } },
                        audio: false
                    });
                    const dock = getOrCreateWebcamDock();
                    dock.style.display = "block";
                    const video = document.getElementById(WEBCAM_VIDEO_ID);
                    if (video) { video.srcObject = webcamStream; try { await video.play(); } catch (_) {} }
                    if (!webcamEnabledLogged) {
                        webcamEnabledLogged = true;
                        sendViolation("Webcam preview enabled", { video_track_count: webcamStream.getVideoTracks().length });
                    }
                    await startWebcamRecording();
                } catch (_) {
                    sendViolation("Webcam access denied", { page: "editor" });
                }
            }

            // Step 4: NOW enter fullscreen — all dialogs are done
            if (!isInFullscreen()) {
                try {
                    await requestAppFullscreen();
                    await new Promise(r => setTimeout(r, 400));
                } catch (_) {
                    console.warn("[Proctoring] Could not enter fullscreen on editor page");
                }
            }
        } catch (err) {
            console.error("[Proctoring] Setup error:", err);
        }

        // Step 5: Stop suppressing and start real monitoring
        suppressWarnings = false;
        captureBaselineScreenshot();

        // Step 6: Check requirements after everything settles
        setTimeout(() => {
            if (!hasProctoringRequirements()) {
                showLockOverlay(getProctoringRequirementMessage());
                armFullscreenRecovery();
            }
        }, 500);
    }, 600);

    if (examListenersAttached) return;
    examListenersAttached = true;

    document.addEventListener("submit", () => { suppressWarnings = true; setNavInProgress(true); setTimeout(() => { suppressWarnings = false; setNavInProgress(false); }, 1200); }, true);

    window.addEventListener("beforeunload", () => {
        if (!proctoringActive) return;
        stopWebcamPreview({ final: true }); stopScreenCaptureMonitor(); stopPeriodicScreenshotCapture(); stopContentChangeDetection(); stopMultiMonitorDetection();
        sendViolation("Session page unload", { path: window.location.pathname, warning_count: warningCount, tab_switch_count: tabSwitchCount, fullscreen_exit_count: fullscreenExitCount, multi_monitor_event_count: multiMonitorEventCount,
            total_outside_fullscreen_ms: outsideFullscreenTotalMs + (outsideFullscreenStartedAt ? (Date.now() - outsideFullscreenStartedAt) : 0)
        }, true);
    });

    // Block copy — all copy actions blocked exactly like MCQ rounds
    document.addEventListener("copy", (e) => {
        e.preventDefault(); copyBlockedCount += 1;
        issueWarning("Copy blocked", { copy_block_count: copyBlockedCount }, { incrementWarning: false, bannerMessage: `Copy action blocked (${formatCount(copyBlockedCount, "time", "times")}). Activity logged.`, bannerTone: "warning" });
        captureEvidence("copy_block", { copy_block_count: copyBlockedCount }, true);
    });

    document.addEventListener("paste", (e) => {
        e.preventDefault(); pasteBlockedCount += 1;
        issueWarning("Paste blocked", { paste_block_count: pasteBlockedCount }, { incrementWarning: false, bannerMessage: `Paste action blocked (${formatCount(pasteBlockedCount, "time", "times")}). Activity logged.`, bannerTone: "warning" });
        captureEvidence("paste_block", { paste_block_count: pasteBlockedCount }, true);
    });

    document.addEventListener("contextmenu", (e) => {
        e.preventDefault(); rightClickBlockedCount += 1;
        issueWarning("Right click blocked", { right_click_block_count: rightClickBlockedCount }, { incrementWarning: false, bannerMessage: `Right click blocked (${formatCount(rightClickBlockedCount, "time", "times")}). Activity logged.`, bannerTone: "warning" });
    });

    // Block text selection — exactly like MCQ rounds
    document.addEventListener("selectstart", (e) => {
        // Allow selection only inside the code editor textarea
        if (e.target && e.target.id === "codingEditor") return;
        e.preventDefault();
    });

    document.addEventListener("visibilitychange", () => {
        if (shouldIgnoreProctoringEvent()) return;
        if (document.hidden) handleTabSwitch("visibility_hidden");
        else {
            document.body.classList.remove("proctoring-warning");
            captureTabReturnEvidence();
        }
    });

    window.addEventListener("blur", () => {
        if (shouldIgnoreProctoringEvent()) return;
        // Defer: browser-native UI (e.g. "Your screen is being shared" bar)
        // causes a momentary blur→focus cycle — wait before counting it.
        if (deferredBlurTimer) clearTimeout(deferredBlurTimer);
        deferredBlurTimer = setTimeout(() => {
            deferredBlurTimer = null;
            if (!document.hasFocus()) handleTabSwitch("window_blur");
        }, 350);
    });
    window.addEventListener("focus", () => {
        if (deferredBlurTimer) { clearTimeout(deferredBlurTimer); deferredBlurTimer = null; }
        document.body.classList.remove("proctoring-warning");
        captureTabReturnEvidence();
    });
    window.addEventListener("resize", () => { checkExtendedDisplay("resize"); });

    document.addEventListener("mousemove", (e) => {
        if (!proctoringActive || shouldIgnoreProctoringEvent() || !isMouseOutsidePrimaryScreen(e)) return;
        const now = Date.now();
        if ((now - lastMouseOutsideDetectAt) < TAB_SWITCH_DEBOUNCE_MS) return;
        lastMouseOutsideDetectAt = now;
        handleMultiMonitorDetected("mouse_outside_primary", { screen_x: e.screenX, screen_y: e.screenY });
    }, { passive: true });

    document.addEventListener("fullscreenchange", () => {
        if (!isFullscreenRequired() || shouldIgnoreProctoringEvent()) return;
        if (!isInFullscreen()) handleFullscreenExit();
        else { recordFullscreenRestored(); hideLockOverlay(); }
    });
}

function finalizeFullscreenOnCompletion() {
    if (!IS_COMPLETED_PAGE) return;
    if (outsideFullscreenStartedAt) recordFullscreenRestored();
    sendViolation("Session completed", { warning_count: warningCount, tab_switch_count: tabSwitchCount, fullscreen_exit_count: fullscreenExitCount, total_outside_fullscreen_ms: outsideFullscreenTotalMs }, true);
    setFullscreenRequired(false); setNavInProgress(false); setSessionFlag(SESSION_START_LOG_KEY, false);
    hideLockOverlay(); disarmFullscreenRecovery();
    stopWebcamPreview({ final: true }); stopScreenCaptureMonitor(); stopPeriodicScreenshotCapture(); stopContentChangeDetection(); stopMultiMonitorDetection();
    exitAppFullscreen().catch(() => {});
}

/* ── Init ──────────────────────────────────────────── */
applyPageClassNames();
setupKeyboardShortcutBlocking();
setupStartFullscreenGate();
setupExamProctoring();
finalizeFullscreenOnCompletion();

window.setupExamProctoring = setupExamProctoring;
window.requestAppFullscreen = requestAppFullscreen;
window.ensureProctoringReady = ensureProctoringReady;

// Allow coding_flow.js to hand the webcam stream acquired on the start page
// to the proctoring module so setupExamProctoring() finds it already active.
window.__proctoringSetWebcam = function (stream) {
    if (!stream || !stream.active) return;
    webcamStream = stream;
    if (!webcamEnabledLogged) {
        webcamEnabledLogged = true;
        sendViolation("Webcam preview enabled", {
            video_track_count: stream.getVideoTracks().length,
            source: "start_page_handoff"
        });
    }
};
