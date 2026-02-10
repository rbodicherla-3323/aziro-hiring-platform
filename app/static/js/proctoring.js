/* ================= PROCTORING ================= */

const PATH = window.location.pathname;
const PATH_PARTS = PATH.split("/").filter(Boolean);
const SESSION_ID = PATH_PARTS.length >= 3 ? PATH_PARTS[PATH_PARTS.length - 1] : "";
const IS_START_PAGE = /^\/mcq\/start\/[^/]+\/?$/.test(PATH);
const IS_QUESTION_PAGE = /^\/mcq\/question\/[^/]+\/?$/.test(PATH);
const IS_COMPLETED_PAGE = /^\/mcq\/completed\/[^/]+\/?$/.test(PATH);
const IS_TEST_FLOW_PAGE = /^\/mcq\/(?:start|question|submit)\/[^/]+\/?$/.test(PATH);

const FULLSCREEN_REQUIRED_KEY = `mcq_fullscreen_required_${SESSION_ID}`;
const NAV_IN_PROGRESS_KEY = `mcq_nav_in_progress_${SESSION_ID}`;
const BASELINE_CAPTURE_KEY = `mcq_baseline_capture_${SESSION_ID}`;
const SESSION_START_LOG_KEY = `mcq_session_start_logged_${SESSION_ID}`;

const MAX_WARNINGS = 3;
const TAB_SWITCH_DEBOUNCE_MS = 1200;
const SCREENSHOT_THROTTLE_MS = 4000;
const PERIODIC_SCREENSHOT_INTERVAL_MS = 60 * 1000;
const TAB_SWITCH_CAPTURE_BURST_DELAYS_MS = [0, 120, 280];
const MULTI_MONITOR_CHECK_INTERVAL_MS = 4000;
const MULTI_MONITOR_DEBOUNCE_MS = 6000;
const MOUSE_OFF_PRIMARY_THRESHOLD_PX = 12;
const WEBCAM_DOCK_ID = "proctoringWebcamDock";
const WEBCAM_VIDEO_ID = "proctoringWebcamPreview";
const WEBCAM_RECORDING_TIMESLICE_MS = 5000;
const WEBCAM_RECORDING_TARGET_BPS = 250000;
const SCREEN_CAPTURE_VIDEO_ID = "proctoringScreenCaptureVideo";

function isExamPath() {
    return /^\/mcq\/question\/[^/]+\/?$/.test(window.location.pathname) ||
           /^\/mcq\/submit\/[^/]+\/?$/.test(window.location.pathname);
}

function applyPageClassNames() {
    if (!document.body) return;
    if (IS_START_PAGE) {
        document.body.classList.add("mcq-start-page");
    }
    if (IS_QUESTION_PAGE) {
        document.body.classList.add("mcq-question-page");
    }
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

console.log("PROCTORING ACTIVE");

function isFullscreenRequired() {
    try {
        return sessionStorage.getItem(FULLSCREEN_REQUIRED_KEY) === "1";
    } catch (_) {
        return false;
    }
}

function setFullscreenRequired(required) {
    try {
        if (required) {
            sessionStorage.setItem(FULLSCREEN_REQUIRED_KEY, "1");
        } else {
            sessionStorage.removeItem(FULLSCREEN_REQUIRED_KEY);
        }
    } catch (_) {
        // Ignore storage failures.
    }
}

function setSessionFlag(key, value) {
    try {
        if (value) {
            sessionStorage.setItem(key, "1");
        } else {
            sessionStorage.removeItem(key);
        }
    } catch (_) {
        // Ignore storage failures.
    }
}

function getSessionFlag(key) {
    try {
        return sessionStorage.getItem(key) === "1";
    } catch (_) {
        return false;
    }
}

function setNavInProgress(value) {
    setSessionFlag(NAV_IN_PROGRESS_KEY, value);
}

function isNavInProgress() {
    return getSessionFlag(NAV_IN_PROGRESS_KEY);
}

function shouldIgnoreProctoringEvent() {
    return suppressWarnings || isNavInProgress() || screenCapturePromptInFlight;
}

function isInFullscreen() {
    return !!document.fullscreenElement;
}

function requestAppFullscreen() {
    return document.documentElement.requestFullscreen();
}

function exitAppFullscreen() {
    if (document.fullscreenElement) {
        return document.exitFullscreen();
    }
    return Promise.resolve();
}

function sendJSON(url, payload, useBeacon = false) {
    const body = JSON.stringify(payload);

    if (useBeacon && navigator.sendBeacon) {
        const blob = new Blob([body], { type: "application/json" });
        navigator.sendBeacon(url, blob);
        return;
    }

    fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: useBeacon
    }).catch(() => {});
}

function sendViolation(type, details = {}, useBeacon = false) {
    if (!SESSION_ID) return;

    sendJSON("/mcq/proctoring/violation", {
        session_id: SESSION_ID,
        violation_type: type,
        details,
        ts: new Date().toISOString()
    }, useBeacon);
}

function sendScreenshot(eventType, imageData, details = {}) {
    if (!SESSION_ID || !imageData) return;

    sendJSON("/mcq/proctoring/screenshot", {
        session_id: SESSION_ID,
        event_type: eventType,
        image_data: imageData,
        details,
        ts: new Date().toISOString()
    });
}

function supportsDisplayCapture() {
    return !!(navigator.mediaDevices && typeof navigator.mediaDevices.getDisplayMedia === "function");
}

function getDisplaySurfaceFromTrack(track) {
    if (!track || typeof track.getSettings !== "function") return "";
    try {
        const settings = track.getSettings() || {};
        return String(settings.displaySurface || "").toLowerCase();
    } catch (_) {
        return "";
    }
}

function isEntireScreenSurface(surface) {
    return surface === "monitor";
}

function getOrCreateScreenCaptureVideo() {
    if (screenCaptureVideo) return screenCaptureVideo;

    let video = document.getElementById(SCREEN_CAPTURE_VIDEO_ID);
    if (!video) {
        video = document.createElement("video");
        video.id = SCREEN_CAPTURE_VIDEO_ID;
        video.autoplay = true;
        video.muted = true;
        video.playsInline = true;
        video.tabIndex = -1;
        video.setAttribute("aria-hidden", "true");
        video.style.cssText = `
            position: fixed;
            top: -9999px;
            left: -9999px;
            width: 1px;
            height: 1px;
            opacity: 0;
            pointer-events: none;
        `;
        document.body.appendChild(video);
    }

    screenCaptureVideo = video;
    return video;
}

function stopScreenCaptureMonitor() {
    screenCaptureReady = false;
    screenCaptureSurface = "";
    const streamToStop = screenStream;
    screenStream = null;

    if (screenCaptureVideo) {
        try {
            screenCaptureVideo.pause();
        } catch (_) {
            // Ignore pause failures.
        }
        screenCaptureVideo.srcObject = null;
    }

    if (streamToStop) {
        streamToStop.getTracks().forEach((track) => track.stop());
    }
}

async function startScreenCaptureMonitor() {
    if (!IS_TEST_FLOW_PAGE) return false;
    if (screenStream && screenStream.active && screenCaptureReady) return true;
    if (screenCapturePromptInFlight) return false;

    if (!supportsDisplayCapture()) {
        if (!screenCaptureUnavailableLogged) {
            screenCaptureUnavailableLogged = true;
            sendViolation("Screen capture unavailable", {
                reason: "display_media_unsupported"
            });
        }
        return false;
    }

    screenCapturePromptInFlight = true;
    try {
        const stream = await navigator.mediaDevices.getDisplayMedia({
            video: { frameRate: { ideal: 10, max: 15 } },
            audio: false
        });

        const [track] = stream.getVideoTracks();
        const displaySurface = getDisplaySurfaceFromTrack(track);
        if (!track || !isEntireScreenSurface(displaySurface)) {
            stream.getTracks().forEach((t) => t.stop());
            screenCaptureReady = false;
            screenCaptureSurface = "";

            sendViolation("Screen capture rejected", {
                reason: "entire_screen_required",
                display_surface: displaySurface || "unknown"
            });
            showBanner("Select 'Entire Screen' to continue the test.", "danger");
            return false;
        }

        stopScreenCaptureMonitor();
        screenStream = stream;
        screenCaptureSurface = displaySurface;

        const video = getOrCreateScreenCaptureVideo();
        video.srcObject = stream;
        try {
            await video.play();
        } catch (_) {
            // Ignore autoplay failures.
        }

        if (track) {
            track.addEventListener("ended", () => {
                if (screenStream !== stream) return;
                screenCaptureReady = false;
                screenCaptureSurface = "";
                screenStream = null;
                if (screenCaptureVideo) {
                    screenCaptureVideo.srcObject = null;
                }
                sendViolation("Screen capture ended", { reason: "track_ended" });
                if (isExamPath() && isFullscreenRequired()) {
                    showLockOverlay(getProctoringRequirementMessage());
                    armFullscreenRecovery();
                }
            });
        }

        screenCaptureReady = true;
        screenCaptureUnavailableLogged = false;
        if (!screenCaptureEnabledLogged) {
            screenCaptureEnabledLogged = true;
            sendViolation("Screen capture enabled", {
                video_track_count: stream.getVideoTracks().length,
                display_surface: screenCaptureSurface || displaySurface || "unknown"
            });
        }

        return true;
    } catch (error) {
        if (!screenCaptureUnavailableLogged) {
            screenCaptureUnavailableLogged = true;
            sendViolation("Screen capture unavailable", {
                reason: (error && error.name) || "permission_denied_or_aborted"
            });
        }
        return false;
    } finally {
        screenCapturePromptInFlight = false;
    }
}

async function ensureProctoringReady(options = {}) {
    const requireScreenShare = options.requireScreenShare !== false;
    const requireFullscreen = options.requireFullscreen !== false;
    const withOverlay = options.withOverlay !== false;

    if (requireScreenShare && !screenCaptureReady) {
        const started = await startScreenCaptureMonitor();
        if (!started || !screenCaptureReady) {
            if (withOverlay) {
                showLockOverlay(getProctoringRequirementMessage());
                armFullscreenRecovery();
            }
            return false;
        }
    }

    if (requireFullscreen && !isInFullscreen()) {
        try {
            await requestAppFullscreen();
        } catch (_) {
            if (withOverlay) {
                showLockOverlay(getProctoringRequirementMessage());
                armFullscreenRecovery();
            }
            return false;
        }
    }

    const ready = (!requireScreenShare || screenCaptureReady) && (!requireFullscreen || isInFullscreen());
    if (!ready) {
        if (withOverlay) {
            showLockOverlay(getProctoringRequirementMessage());
            armFullscreenRecovery();
        }
        return false;
    }

    hideLockOverlay();
    disarmFullscreenRecovery();
    return true;
}

function captureScreenshot(eventType, details = {}, force = false) {
    if (!SESSION_ID) return;
    if (typeof window.html2canvas !== "function") return;
    if (!force && !proctoringActive) return;

    const now = Date.now();
    if (!force && (screenshotInProgress || (now - lastScreenshotAt) < SCREENSHOT_THROTTLE_MS)) {
        return;
    }

    screenshotInProgress = true;

    window.html2canvas(document.body, {
        backgroundColor: "#ffffff",
        scale: 0.5,
        logging: false,
        useCORS: true
    })
        .then((canvas) => {
            const imageData = canvas.toDataURL("image/jpeg", 0.65);
            sendScreenshot(eventType, imageData, {
                ...details,
                capture_source: details.capture_source || "page_dom"
            });
            lastScreenshotAt = Date.now();
        })
        .catch(() => {})
        .finally(() => {
            screenshotInProgress = false;
        });
}

function captureScreenFrame(eventType, details = {}, force = false) {
    if (!SESSION_ID) return false;
    if (!screenCaptureReady || !screenStream) return false;

    const video = getOrCreateScreenCaptureVideo();
    const width = Number(video.videoWidth) || 0;
    const height = Number(video.videoHeight) || 0;
    if (!width || !height) return false;

    const now = Date.now();
    if (!force && (now - lastScreenshotAt) < SCREENSHOT_THROTTLE_MS) {
        return false;
    }

    if (!screenCaptureCanvas) {
        screenCaptureCanvas = document.createElement("canvas");
    }
    screenCaptureCanvas.width = width;
    screenCaptureCanvas.height = height;

    const context = screenCaptureCanvas.getContext("2d");
    if (!context) return false;

    try {
        context.drawImage(video, 0, 0, width, height);
        const imageData = screenCaptureCanvas.toDataURL("image/jpeg", 0.68);
        sendScreenshot(eventType, imageData, {
            ...details,
            capture_source: "screen_stream"
        });
        lastScreenshotAt = Date.now();
        return true;
    } catch (_) {
        return false;
    }
}

function captureTabSwitchEvidence(details = {}) {
    const burstId = ++tabSwitchCaptureBurstId;

    TAB_SWITCH_CAPTURE_BURST_DELAYS_MS.forEach((delayMs, index) => {
        setTimeout(() => {
            if (burstId !== tabSwitchCaptureBurstId) return;

            const captured = captureScreenFrame("tab_switch", details, true);
            if (!captured && index === 0) {
                captureScreenshot("tab_switch", {
                    ...details,
                    capture_source: "page_dom_fallback"
                }, true);
            }
        }, delayMs);
    });
}

function captureEvidence(eventType, details = {}, force = true) {
    const captured = captureScreenFrame(eventType, details, force);
    if (captured) return;

    captureScreenshot(eventType, {
        ...details,
        capture_source: "page_dom_fallback"
    }, force);
}

function showBanner(message, tone = "warning") {
    let banner = document.getElementById("proctoringBanner");
    if (!banner) {
        banner = document.createElement("div");
        banner.id = "proctoringBanner";
        banner.style.cssText = `
            width: min(1200px, calc(100% - 40px));
            margin: 8px auto 0;
            text-align: center;
            padding: 10px 12px;
            font-weight: 600;
            border: 1px solid rgba(0, 0, 0, 0.12);
            border-radius: 8px;
        `;
        const page = document.querySelector(".page");
        if (page && page.parentNode) {
            page.parentNode.insertBefore(banner, page);
        } else {
            document.body.appendChild(banner);
        }
    }

    if (tone === "danger") {
        banner.style.background = "#b71c1c";
        banner.style.color = "#ffffff";
    } else {
        banner.style.background = "#ffb300";
        banner.style.color = "#1f2937";
    }

    banner.innerText = message;
}

function formatCount(value, singular, plural) {
    return `${value} ${value === 1 ? singular : plural}`;
}

function formatShortcut(e) {
    const keys = [];
    if (e.ctrlKey) keys.push("Ctrl");
    if (e.altKey) keys.push("Alt");
    if (e.metaKey) keys.push("Meta");
    if (e.shiftKey) keys.push("Shift");

    const baseKey = String(e.key || "").trim();
    const normalized = baseKey.toLowerCase();
    if (baseKey && !["control", "alt", "meta", "shift"].includes(normalized)) {
        if (baseKey.length === 1) {
            keys.push(baseKey.toUpperCase());
        } else {
            keys.push(baseKey);
        }
    }

    return keys.length ? keys.join("+") : "Unknown key";
}

function formatTabSwitchSource(source) {
    if (source === "visibility_hidden") return "tab hidden";
    if (source === "window_blur") return "window blur";
    return source;
}

function getProctoringRequirementMessage() {
    if (!screenCaptureReady) {
        return "Share Entire Screen permission is required to continue the test.";
    }
    if (!isInFullscreen()) {
        return "You must remain in full screen to continue the test.";
    }
    return "";
}

function hasProctoringRequirements() {
    return screenCaptureReady && isInFullscreen();
}

function getOrCreateLockOverlay() {
    let overlay = document.getElementById("proctoringLockOverlay");
    if (overlay) {
        return overlay;
    }

    overlay = document.createElement("div");
    overlay.id = "proctoringLockOverlay";
    overlay.style.display = "none";
    overlay.innerHTML = `
        <div class="lock-message" style="text-align:center; max-width:640px; padding:24px;">
            <div id="proctoringLockText">You must remain in full screen to continue the test.</div>
            <button id="resumeFullscreenBtn" type="button" style="margin-top:14px; padding:10px 18px; border:none; border-radius:6px; background:#ffffff; color:#8b0000; font-weight:700; cursor:pointer;">
                Resume Proctoring
            </button>
        </div>
    `;

    document.body.appendChild(overlay);

    const resume = async () => {
        forcedReentryAttempts += 1;
        sendViolation("Fullscreen re-entry attempt", {
            forced_reentry_attempts: forcedReentryAttempts,
            fullscreen_exit_count: fullscreenExitCount,
            screen_capture_ready: screenCaptureReady,
            in_fullscreen: isInFullscreen()
        });

        const ready = await ensureProctoringReady({
            requireScreenShare: true,
            requireFullscreen: true,
            withOverlay: true
        });
        if (!ready) {
            showLockOverlay(getProctoringRequirementMessage());
        }
    };

    overlay.addEventListener("click", resume);
    const resumeBtn = overlay.querySelector("#resumeFullscreenBtn");
    if (resumeBtn) {
        resumeBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            resume();
        });
    }

    return overlay;
}

function showLockOverlay(message) {
    const overlay = getOrCreateLockOverlay();
    const text = overlay.querySelector("#proctoringLockText");
    if (text) {
        text.textContent = message;
    }
    document.body.classList.add("proctoring-violation");
    overlay.style.display = "flex";
}

function hideLockOverlay() {
    const overlay = document.getElementById("proctoringLockOverlay");
    if (overlay) {
        overlay.style.display = "none";
    }
    document.body.classList.remove("proctoring-violation");
}

function disarmFullscreenRecovery() {
    if (!fullscreenRecoveryArmed || !fullscreenRecoveryHandler) return;
    ["pointerdown", "mousedown", "touchstart", "keydown", "click"].forEach((eventName) => {
        window.removeEventListener(eventName, fullscreenRecoveryHandler, true);
    });
    fullscreenRecoveryHandler = null;
    fullscreenRecoveryArmed = false;
}

function armFullscreenRecovery() {
    if (fullscreenRecoveryArmed) return;
    fullscreenRecoveryArmed = true;

    fullscreenRecoveryHandler = async (e) => {
        if (hasProctoringRequirements()) {
            hideLockOverlay();
            disarmFullscreenRecovery();
            return;
        }

        if (!isFullscreenRequired() || !isExamPath()) {
            disarmFullscreenRecovery();
            return;
        }

        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") {
            e.stopImmediatePropagation();
        }

        const ready = await ensureProctoringReady({
            requireScreenShare: true,
            requireFullscreen: true,
            withOverlay: true
        });
        if (!ready) {
            showLockOverlay(getProctoringRequirementMessage());
        }
    };

    ["pointerdown", "mousedown", "touchstart", "keydown", "click"].forEach((eventName) => {
        window.addEventListener(eventName, fullscreenRecoveryHandler, true);
    });
}

function getOrCreateWebcamDock() {
    let dock = document.getElementById(WEBCAM_DOCK_ID);
    if (dock) {
        return dock;
    }

    dock = document.createElement("div");
    dock.id = WEBCAM_DOCK_ID;
    dock.innerHTML = `
        <video id="${WEBCAM_VIDEO_ID}" autoplay muted playsinline></video>
    `;
    const header = document.querySelector(".header");
    if (header) {
        header.appendChild(dock);
    } else {
        document.body.appendChild(dock);
    }
    return dock;
}

function buildWebcamRecordingId() {
    return `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function getSupportedWebcamRecordingMimeType() {
    if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
        return "";
    }

    const preferred = [
        "video/webm;codecs=vp9,opus",
        "video/webm;codecs=vp8,opus",
        "video/webm"
    ];

    for (const mime of preferred) {
        if (MediaRecorder.isTypeSupported(mime)) {
            return mime;
        }
    }

    return "";
}

function enqueueWebcamChunkUpload(chunkBlob) {
    if (!chunkBlob || !chunkBlob.size || !SESSION_ID || !webcamRecordingId) {
        return Promise.resolve();
    }

    const chunkIndex = webcamChunkIndex;
    webcamChunkIndex += 1;
    const ts = new Date().toISOString();
    const mimeType = webcamRecordingMimeType || chunkBlob.type || "video/webm";

    webcamUploadQueue = webcamUploadQueue
        .then(() => {
            const formData = new FormData();
            formData.append("session_id", SESSION_ID);
            formData.append("recording_id", webcamRecordingId);
            formData.append("chunk_index", String(chunkIndex));
            formData.append("mime_type", mimeType);
            formData.append("ts", ts);
            formData.append("chunk", chunkBlob, `chunk_${String(chunkIndex).padStart(6, "0")}.webm`);

            return fetch("/mcq/proctoring/webcam", {
                method: "POST",
                body: formData,
                credentials: "same-origin"
            }).catch(() => {});
        })
        .catch(() => {});

    return webcamUploadQueue;
}

function finalizeWebcamRecordingUpload() {
    if (!SESSION_ID || !webcamRecordingId || webcamRecordingFinalized) {
        return Promise.resolve();
    }

    const formData = new FormData();
    formData.append("session_id", SESSION_ID);
    formData.append("recording_id", webcamRecordingId);
    formData.append("mime_type", webcamRecordingMimeType || "video/webm");
    formData.append("final", "1");
    formData.append("chunk_count", String(webcamChunkIndex));
    formData.append("ts", new Date().toISOString());

    return fetch("/mcq/proctoring/webcam", {
        method: "POST",
        body: formData,
        credentials: "same-origin"
    })
        .then(() => {
            webcamRecordingFinalized = true;
        })
        .catch(() => {});
}

async function startWebcamRecording() {
    if (!isExamPath()) return;
    if (!webcamStream || !webcamStream.active) return;
    if (typeof MediaRecorder === "undefined") {
        sendViolation("Webcam recording unavailable", {
            reason: "media_recorder_unsupported"
        });
        return;
    }

    if (webcamRecorder && webcamRecorder.state !== "inactive") {
        return;
    }

    webcamRecordingMimeType = getSupportedWebcamRecordingMimeType() || "video/webm";
    if (!webcamRecordingId) {
        webcamRecordingId = buildWebcamRecordingId();
    }
    webcamChunkIndex = 0;
    webcamUploadQueue = Promise.resolve();
    webcamRecordingFinalized = false;
    webcamRecordingStopPromise = null;

    try {
        webcamRecorder = webcamRecordingMimeType !== "video/webm"
            ? new MediaRecorder(webcamStream, {
                mimeType: webcamRecordingMimeType,
                videoBitsPerSecond: WEBCAM_RECORDING_TARGET_BPS
            })
            : new MediaRecorder(webcamStream, {
                videoBitsPerSecond: WEBCAM_RECORDING_TARGET_BPS
            });
    } catch (_) {
        try {
            webcamRecorder = new MediaRecorder(webcamStream);
            webcamRecordingMimeType = webcamRecorder.mimeType || webcamRecordingMimeType;
        } catch (_) {
            sendViolation("Webcam recording unavailable", {
                reason: "media_recorder_init_failed"
            });
            webcamRecorder = null;
            return;
        }
    }

    webcamRecorder.addEventListener("dataavailable", (event) => {
        if (!event.data || !event.data.size) return;
        enqueueWebcamChunkUpload(event.data);
    });

    webcamRecorder.addEventListener("error", () => {
        sendViolation("Webcam recording error", {
            state: webcamRecorder ? webcamRecorder.state : "unknown"
        });
    });

    try {
        webcamRecorder.start(WEBCAM_RECORDING_TIMESLICE_MS);
        sendViolation("Webcam recording started", {
            recording_id: webcamRecordingId,
            mime_type: webcamRecordingMimeType,
            chunk_timeslice_ms: WEBCAM_RECORDING_TIMESLICE_MS
        });
    } catch (_) {
        webcamRecorder = null;
        sendViolation("Webcam recording unavailable", {
            reason: "media_recorder_start_failed"
        });
    }
}

function stopWebcamRecording(options = {}) {
    const finalize = options.final === true;
    if (webcamRecordingStopPromise) {
        return webcamRecordingStopPromise;
    }

    const recorder = webcamRecorder;
    webcamRecordingStopPromise = (async () => {
        if (recorder && recorder.state !== "inactive") {
            await new Promise((resolve) => {
                const onStop = () => resolve();
                recorder.addEventListener("stop", onStop, { once: true });
                try {
                    recorder.requestData();
                } catch (_) {
                    // Ignore requestData failures.
                }
                try {
                    recorder.stop();
                } catch (_) {
                    resolve();
                }
            });
        }

        await webcamUploadQueue.catch(() => {});

        if (finalize) {
            await finalizeWebcamRecordingUpload();
            if (webcamRecordingId) {
                sendViolation("Webcam recording saved", {
                    recording_id: webcamRecordingId,
                    chunk_count: webcamChunkIndex,
                    mime_type: webcamRecordingMimeType
                });
            }
        }

        webcamRecorder = null;
    })().finally(() => {
        webcamRecordingStopPromise = null;
    });

    return webcamRecordingStopPromise;
}

function stopWebcamPreview(options = {}) {
    const finalize = options.final === true;
    stopWebcamRecording({ final: finalize });

    const video = document.getElementById(WEBCAM_VIDEO_ID);
    if (video) {
        video.srcObject = null;
    }

    if (webcamStream) {
        webcamStream.getTracks().forEach((track) => track.stop());
        webcamStream = null;
    }
}

async function startWebcamPreview() {
    if (!isExamPath()) return;
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
        sendViolation("Webcam unavailable", { reason: "media_devices_unsupported" });
        return;
    }

    const dock = getOrCreateWebcamDock();
    dock.style.display = "block";

    if (webcamStream && webcamStream.active) {
        const existingVideo = document.getElementById(WEBCAM_VIDEO_ID);
        if (existingVideo && existingVideo.srcObject !== webcamStream) {
            existingVideo.srcObject = webcamStream;
            try {
                await existingVideo.play();
            } catch (_) {
                // Ignore autoplay failures.
            }
        }
        await startWebcamRecording();
        return;
    }

    try {
        webcamStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: "user",
                width: { ideal: 320 },
                height: { ideal: 180 }
            },
            audio: false
        });

        const video = document.getElementById(WEBCAM_VIDEO_ID);
        if (video) {
            video.srcObject = webcamStream;
            try {
                await video.play();
            } catch (_) {
                // Ignore autoplay failures.
            }
        }

        if (!webcamEnabledLogged) {
            webcamEnabledLogged = true;
            sendViolation("Webcam preview enabled", {
                video_track_count: webcamStream.getVideoTracks().length
            });
        }

        await startWebcamRecording();
    } catch (_) {
        dock.style.display = "none";
        sendViolation("Webcam access denied", {
            path: window.location.pathname
        });
        showBanner("Webcam access is required for live proctoring.", "danger");
    }
}

function armScreenCaptureMonitorFromGesture() {
    if (!isExamPath()) return;
    if (screenCaptureGestureAttempted || screenCaptureReady) return;
    if (screenCaptureGestureListenersArmed) return;
    if (!supportsDisplayCapture()) return;
    screenCaptureGestureListenersArmed = true;

    const gestureHandler = () => {
        if (screenCaptureGestureAttempted || screenCaptureReady) return;
        screenCaptureGestureAttempted = true;
        startScreenCaptureMonitor();
    };

    ["pointerdown", "mousedown", "touchstart", "keydown", "click"].forEach((eventName) => {
        window.addEventListener(eventName, gestureHandler, { capture: true, once: true });
    });
}

function issueWarning(reason, details = {}, options = {}) {
    if (!proctoringActive || isHandlingWarning || shouldIgnoreProctoringEvent()) return;

    isHandlingWarning = true;
    const incrementWarning = options.incrementWarning !== false;
    if (incrementWarning) {
        warningCount += 1;
    }

    const bannerMessage = options.bannerMessage || `Warning ${warningCount}/${MAX_WARNINGS}: ${reason}`;
    const bannerTone = options.bannerTone || "warning";
    showBanner(bannerMessage, bannerTone);

    sendViolation(reason, {
        warning_count: warningCount,
        ...details
    });

    if (incrementWarning && warningCount >= MAX_WARNINGS) {
        window.location.href = `/mcq/submit/${SESSION_ID}`;
        return;
    }

    setTimeout(() => {
        isHandlingWarning = false;
    }, 800);
}

function recordFullscreenRestored() {
    if (!outsideFullscreenStartedAt) return;

    const outMs = Date.now() - outsideFullscreenStartedAt;
    outsideFullscreenStartedAt = null;
    outsideFullscreenTotalMs += outMs;

    sendViolation("Fullscreen restored", {
        fullscreen_exit_count: fullscreenExitCount,
        outside_fullscreen_ms: outMs,
        total_outside_fullscreen_ms: outsideFullscreenTotalMs,
        forced_reentry_attempts: forcedReentryAttempts
    });
    disarmFullscreenRecovery();
}

function handleFullscreenExit() {
    fullscreenExitCount += 1;
    if (!outsideFullscreenStartedAt) {
        outsideFullscreenStartedAt = Date.now();
    }

    showLockOverlay("You must remain in full screen to continue the test.");
    armFullscreenRecovery();

    issueWarning("Fullscreen exited", {
        fullscreen_exit_count: fullscreenExitCount,
        forced_reentry_attempts: forcedReentryAttempts
    }, {
        bannerMessage: `Fullscreen exited (${formatCount(fullscreenExitCount, "time", "times")}). You must remain in full screen to continue the test.`,
        bannerTone: "danger"
    });

    captureScreenshot("fullscreen_exit", {
        fullscreen_exit_count: fullscreenExitCount
    });
}

function handleTabSwitch(source) {
    const now = Date.now();
    if ((now - lastTabSwitchAt) < TAB_SWITCH_DEBOUNCE_MS) return;
    lastTabSwitchAt = now;

    tabSwitchCount += 1;
    document.body.classList.add("proctoring-warning");

    issueWarning("Tab switching detected", {
        source,
        tab_switch_count: tabSwitchCount
    }, {
        incrementWarning: false,
        bannerMessage: `Tab switching detected (${formatCount(tabSwitchCount, "time", "times")}). Source: ${formatTabSwitchSource(source)}. Activity logged.`,
        bannerTone: "warning"
    });

    const screenshotDetails = {
        source,
        tab_switch_count: tabSwitchCount
    };
    captureTabSwitchEvidence(screenshotDetails);
}

function startPeriodicScreenshotCapture() {
    if (!isExamPath()) return;
    if (periodicScreenshotTimer) return;

    periodicScreenshotTimer = setInterval(() => {
        if (!proctoringActive || shouldIgnoreProctoringEvent()) return;

        captureEvidence("interval_1min", {
            interval_seconds: 60,
            path: window.location.pathname
        }, true);
    }, PERIODIC_SCREENSHOT_INTERVAL_MS);
}

function stopPeriodicScreenshotCapture() {
    if (!periodicScreenshotTimer) return;
    clearInterval(periodicScreenshotTimer);
    periodicScreenshotTimer = null;
}

function isMouseOutsidePrimaryScreen(e) {
    const x = Number(e.screenX);
    const y = Number(e.screenY);
    if (Number.isNaN(x) || Number.isNaN(y)) return false;

    const primaryWidth = Number(window.screen && window.screen.width) || 0;
    const primaryHeight = Number(window.screen && window.screen.height) || 0;
    if (!primaryWidth || !primaryHeight) return false;

    return (
        x < -MOUSE_OFF_PRIMARY_THRESHOLD_PX ||
        y < -MOUSE_OFF_PRIMARY_THRESHOLD_PX ||
        x > (primaryWidth + MOUSE_OFF_PRIMARY_THRESHOLD_PX) ||
        y > (primaryHeight + MOUSE_OFF_PRIMARY_THRESHOLD_PX)
    );
}

function handleMultiMonitorDetected(source, details = {}) {
    const now = Date.now();
    if ((now - lastMultiMonitorDetectAt) < MULTI_MONITOR_DEBOUNCE_MS) return;
    lastMultiMonitorDetectAt = now;

    multiMonitorEventCount += 1;

    issueWarning("Multi-monitor activity detected", {
        source,
        multi_monitor_event_count: multiMonitorEventCount,
        ...details
    }, {
        incrementWarning: false,
        bannerMessage: `Multi-monitor activity detected (${formatCount(multiMonitorEventCount, "time", "times")}). Source: ${source}. Activity logged.`,
        bannerTone: "warning"
    });

    captureEvidence("multi_monitor", {
        source,
        multi_monitor_event_count: multiMonitorEventCount,
        ...details
    }, true);
}

function checkExtendedDisplay(reason = "periodic_check") {
    if (!proctoringActive || shouldIgnoreProctoringEvent()) return;
    if (!window.screen || typeof window.screen.isExtended !== "boolean") return;
    if (!window.screen.isExtended) return;

    handleMultiMonitorDetected("screen_extended", { reason });
}

function startMultiMonitorDetection() {
    if (!isExamPath()) return;
    if (multiMonitorCheckTimer) return;

    multiMonitorCheckTimer = setInterval(() => {
        checkExtendedDisplay("interval");
    }, MULTI_MONITOR_CHECK_INTERVAL_MS);

    checkExtendedDisplay("init");
}

function stopMultiMonitorDetection() {
    if (!multiMonitorCheckTimer) return;
    clearInterval(multiMonitorCheckTimer);
    multiMonitorCheckTimer = null;
}

function shouldBlockShortcutKey(e) {
    const key = String(e.key || "");
    const normalized = key.toLowerCase();

    if (e.ctrlKey || e.metaKey || e.altKey) {
        return true;
    }

    if (/^f([1-9]|1[0-2])$/i.test(key)) {
        return true;
    }

    if ([
        "tab",
        "escape",
        "printscreen",
        "contextmenu",
        "meta",
        "alt",
        "control"
    ].includes(normalized)) {
        return true;
    }

    return false;
}

function handleShortcutBlock(e) {
    if (!IS_TEST_FLOW_PAGE) return;
    if (!shouldBlockShortcutKey(e)) return;
    if (e.__mcqShortcutHandled) return;

    e.__mcqShortcutHandled = true;
    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function") {
        e.stopImmediatePropagation();
    }

    // Do not spam warnings on key repeat or when both window/document handlers fire.
    const now = Date.now();
    if ((now - lastShortcutWarningAt) < 700) return;
    lastShortcutWarningAt = now;

    if (proctoringActive && !shouldIgnoreProctoringEvent()) {
        keyboardShortcutBlockedCount += 1;
        const shortcut = formatShortcut(e);
        const normalizedKey = String(e.key || "").toLowerCase();
        const isCopyShortcut = (e.ctrlKey || e.metaKey) && normalizedKey === "c";
        const isPasteShortcut = (e.ctrlKey || e.metaKey) && normalizedKey === "v";

        issueWarning("Keyboard shortcut blocked", {
            shortcut,
            shortcut_block_count: keyboardShortcutBlockedCount,
            key: e.key,
            ctrl: !!e.ctrlKey,
            alt: !!e.altKey,
            meta: !!e.metaKey,
            shift: !!e.shiftKey
        }, {
            incrementWarning: false,
            bannerMessage: `Keyboard shortcut blocked (${formatCount(keyboardShortcutBlockedCount, "time", "times")}): ${shortcut}. Activity logged.`,
            bannerTone: "warning"
        });

        captureEvidence("keyboard_shortcut_block", {
            shortcut,
            shortcut_block_count: keyboardShortcutBlockedCount,
            key: e.key,
            ctrl: !!e.ctrlKey,
            alt: !!e.altKey,
            meta: !!e.metaKey,
            shift: !!e.shiftKey
        }, true);

        if (isCopyShortcut) {
            captureEvidence("copy_shortcut_block", {
                shortcut,
                shortcut_block_count: keyboardShortcutBlockedCount
            }, true);
        } else if (isPasteShortcut) {
            captureEvidence("paste_shortcut_block", {
                shortcut,
                shortcut_block_count: keyboardShortcutBlockedCount
            }, true);
        }
    }

}

function setupKeyboardShortcutBlocking() {
    if (!IS_TEST_FLOW_PAGE) return;
    if (shortcutListenersAttached) return;
    shortcutListenersAttached = true;

    // Capture-phase listeners improve blocking reliability for browser shortcuts.
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
    sendViolation("Session monitoring started", {
        path: window.location.pathname,
        user_agent: navigator.userAgent
    });
}

function setupStartFullscreenGate() {
    if (!IS_START_PAGE || window.__MCQ_AJAX_FLOW) return;

    const beginForm = document.querySelector("form[action*='/mcq/begin/']");
    if (!beginForm) return;

    let bypassGate = false;
    beginForm.addEventListener("submit", async (e) => {
        if (bypassGate) return;

        try {
            e.preventDefault();
            const ready = await ensureProctoringReady({
                requireScreenShare: true,
                requireFullscreen: true,
                withOverlay: false
            });
            if (!ready) {
                alert("Share Entire Screen and fullscreen are required to start the test.");
                return;
            }

            setFullscreenRequired(true);
            bypassGate = true;
            beginForm.submit();
        } catch (_) {
            e.preventDefault();
            alert("Share Entire Screen and fullscreen are required to start the test.");
        }
    });
}

function setupExamProctoring() {
    if (!isExamPath()) return;

    proctoringActive = true;
    suppressWarnings = false;
    setNavInProgress(false);
    setFullscreenRequired(true);

    logSessionStartIfNeeded();
    captureBaselineScreenshot();
    startPeriodicScreenshotCapture();
    startMultiMonitorDetection();
    startWebcamPreview();
    armScreenCaptureMonitorFromGesture();
    if (!screenCaptureAutoInitTried) {
        screenCaptureAutoInitTried = true;
        startScreenCaptureMonitor();
    }

    if (!hasProctoringRequirements()) {
        showLockOverlay(getProctoringRequirementMessage());
        armFullscreenRecovery();
        ensureProctoringReady({
            requireScreenShare: true,
            requireFullscreen: true,
            withOverlay: true
        });
    }

    if (examListenersAttached) return;
    examListenersAttached = true;

    document.addEventListener("submit", () => {
        suppressWarnings = true;
        setNavInProgress(true);
        setTimeout(() => {
            suppressWarnings = false;
            setNavInProgress(false);
        }, 1200);
    }, true);

    window.addEventListener("beforeunload", () => {
        if (!proctoringActive) return;

        stopWebcamPreview({ final: true });
        stopScreenCaptureMonitor();
        stopPeriodicScreenshotCapture();
        stopMultiMonitorDetection();

        sendViolation("Session page unload", {
            path: window.location.pathname,
            warning_count: warningCount,
            tab_switch_count: tabSwitchCount,
            fullscreen_exit_count: fullscreenExitCount,
            multi_monitor_event_count: multiMonitorEventCount,
            total_outside_fullscreen_ms: outsideFullscreenTotalMs + (
                outsideFullscreenStartedAt ? (Date.now() - outsideFullscreenStartedAt) : 0
            )
        }, true);
    });

    document.addEventListener("copy", (e) => {
        e.preventDefault();
        copyBlockedCount += 1;
        issueWarning("Copy blocked", {
            copy_block_count: copyBlockedCount
        }, {
            incrementWarning: false,
            bannerMessage: `Copy action blocked (${formatCount(copyBlockedCount, "time", "times")}). Activity logged.`,
            bannerTone: "warning"
        });
        captureEvidence("copy_block", {
            copy_block_count: copyBlockedCount
        }, true);
    });

    document.addEventListener("paste", (e) => {
        e.preventDefault();
        pasteBlockedCount += 1;
        issueWarning("Paste blocked", {
            paste_block_count: pasteBlockedCount
        }, {
            incrementWarning: false,
            bannerMessage: `Paste action blocked (${formatCount(pasteBlockedCount, "time", "times")}). Activity logged.`,
            bannerTone: "warning"
        });
        captureEvidence("paste_block", {
            paste_block_count: pasteBlockedCount
        }, true);
    });

    document.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        rightClickBlockedCount += 1;
        issueWarning("Right click blocked", {
            right_click_block_count: rightClickBlockedCount
        }, {
            incrementWarning: false,
            bannerMessage: `Right click blocked (${formatCount(rightClickBlockedCount, "time", "times")}). Activity logged.`,
            bannerTone: "warning"
        });
    });

    document.addEventListener("selectstart", (e) => {
        e.preventDefault();
    });

    document.addEventListener("visibilitychange", () => {
        if (shouldIgnoreProctoringEvent()) return;

        if (document.hidden) {
            handleTabSwitch("visibility_hidden");
        } else {
            document.body.classList.remove("proctoring-warning");
        }
    });

    window.addEventListener("blur", () => {
        if (shouldIgnoreProctoringEvent()) return;
        handleTabSwitch("window_blur");
    });

    window.addEventListener("focus", () => {
        document.body.classList.remove("proctoring-warning");
    });

    window.addEventListener("resize", () => {
        checkExtendedDisplay("resize");
    });

    document.addEventListener("mousemove", (e) => {
        if (!proctoringActive || shouldIgnoreProctoringEvent()) return;
        if (!isMouseOutsidePrimaryScreen(e)) return;

        const now = Date.now();
        if ((now - lastMouseOutsideDetectAt) < TAB_SWITCH_DEBOUNCE_MS) return;
        lastMouseOutsideDetectAt = now;

        handleMultiMonitorDetected("mouse_outside_primary", {
            screen_x: e.screenX,
            screen_y: e.screenY
        });
    }, { passive: true });

    document.addEventListener("fullscreenchange", () => {
        if (!isFullscreenRequired()) return;
        if (shouldIgnoreProctoringEvent()) return;

        if (!isInFullscreen()) {
            handleFullscreenExit();
        } else {
            recordFullscreenRestored();
            hideLockOverlay();
        }
    });
}

function finalizeFullscreenOnCompletion() {
    if (!IS_COMPLETED_PAGE) return;

    if (outsideFullscreenStartedAt) {
        recordFullscreenRestored();
    }

    sendViolation("Session completed", {
        warning_count: warningCount,
        tab_switch_count: tabSwitchCount,
        fullscreen_exit_count: fullscreenExitCount,
        total_outside_fullscreen_ms: outsideFullscreenTotalMs
    }, true);

    setFullscreenRequired(false);
    setNavInProgress(false);
    setSessionFlag(SESSION_START_LOG_KEY, false);
    hideLockOverlay();
    disarmFullscreenRecovery();
    stopWebcamPreview({ final: true });
    stopScreenCaptureMonitor();
    stopPeriodicScreenshotCapture();
    stopMultiMonitorDetection();

    exitAppFullscreen().catch(() => {});
}

applyPageClassNames();
setupKeyboardShortcutBlocking();
setupStartFullscreenGate();
setupExamProctoring();
finalizeFullscreenOnCompletion();

window.setupExamProctoring = setupExamProctoring;
window.requestAppFullscreen = requestAppFullscreen;
window.ensureProctoringReady = ensureProctoringReady;
