/* ================= AI PROCTORING (MediaPipe FaceMesh) ================= */
/* Non-invasive client-side face monitoring with weighted suspicion scoring */

(function () {
    const PATH = window.location.pathname;
    const IS_TEST_FLOW_PAGE = /^\/mcq\/(?:start|question|submit)\/[^/]+\/?$/.test(PATH);
    if (!IS_TEST_FLOW_PAGE) return;

    const PATH_PARTS = PATH.split("/").filter(Boolean);
    const SESSION_ID = PATH_PARTS.length >= 3 ? PATH_PARTS[PATH_PARTS.length - 1] : "";
    if (!SESSION_ID) return;

    const WEBCAM_VIDEO_ID = "proctoringWebcamPreview";
    const SCORE_STORAGE_KEY = `mcq_suspicion_score_${SESSION_ID}`;
    const SCORE_THRESHOLD_LATCH_KEY = `mcq_suspicion_latched_${SESSION_ID}`;

    const MEDIAPIPE_LOCAL_FACE_MESH_SRC = "/static/vendor/mediapipe/face_mesh/face_mesh.js";
    const MEDIAPIPE_LOCAL_BASE_URL = "/static/vendor/mediapipe/face_mesh";
    const MEDIAPIPE_CDN_FACE_MESH_SRC = "https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/face_mesh.js";
    const MEDIAPIPE_CDN_BASE_URL = "https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh";

    const AI_LOOP_MIN_INTERVAL_MS = 160;
    const AI_BOOTSTRAP_RETRY_MS = 1500;
    const AI_ANALYSIS_FRAME_WIDTH = 96;
    const AI_ANALYSIS_FRAME_HEIGHT = 54;
    const AI_INFERENCE_MAX_WIDTH = 640;
    const AI_INFERENCE_MAX_HEIGHT = 360;
    const LOW_LIGHT_LUMA_THRESHOLD = 88;
    const VERY_LOW_LIGHT_LUMA_THRESHOLD = 58;
    const LOW_LIGHT_STDDEV_THRESHOLD = 28;
    const VERY_LOW_LIGHT_STDDEV_THRESHOLD = 18;
    const LIGHTING_SMOOTH_ALPHA = 0.2;
    const DYNAMIC_CONFIDENCE_UPDATE_INTERVAL_MS = 1200;
    const CONFIDENCE_PROFILE_DEFAULT = Object.freeze({ minDetectionConfidence: 0.68, minTrackingConfidence: 0.65 });
    const CONFIDENCE_PROFILE_LOW_LIGHT = Object.freeze({ minDetectionConfidence: 0.56, minTrackingConfidence: 0.58 });
    const CONFIDENCE_PROFILE_VERY_LOW_LIGHT = Object.freeze({ minDetectionConfidence: 0.48, minTrackingConfidence: 0.52 });
    const NO_FACE_GRACE_MS = 4500;
    const NO_FACE_EVENT_COOLDOWN_MS = 12000;
    const MAX_TRACKED_FACES = 5;
    const MULTI_FACE_EVENT_COOLDOWN_MS = 10000;
    const MULTI_FACE_GRACE_MS = 1800;
    const MULTI_FACE_MIN_CONSECUTIVE_FRAMES = 4;
    const PARTIAL_MULTI_FACE_GRACE_MS = 850;
    const PARTIAL_MULTI_FACE_MIN_CONSECUTIVE_FRAMES = 4;
    const FAST_MULTI_FACE_GRACE_MS = 620;
    const FAST_MULTI_FACE_MIN_CONSECUTIVE_FRAMES = 3;
    const MIN_VALID_FACE_BOUNDS_AREA = 0.005;
    const MIN_PARTIAL_FACE_BOUNDS_AREA = 0.0009;
    const MIN_SECOND_FACE_AREA_RATIO = 0.16;
    const MIN_PARTIAL_SECOND_FACE_AREA_RATIO = 0.06;
    const MIN_PARTIAL_SECOND_FACE_CENTER_DISTANCE = 0.08;
    const FAST_MULTI_FACE_MIN_AREA_RATIO = 0.35;
    const FAST_MULTI_FACE_MIN_CENTER_DISTANCE = 0.2;
    const MIN_PRIMARY_FACE_LANDMARK_POINTS = 80;
    const MIN_PARTIAL_FACE_LANDMARK_POINTS = 28;
    const MIN_FACE_EDGE_MARGIN = 0.015;
    const MAX_PARTIAL_FACE_EDGE_TOUCHES = 4;
    const MIN_FACE_ASPECT_RATIO = 0.42;
    const MAX_FACE_ASPECT_RATIO = 2.35;
    const MAX_DUPLICATE_FACE_IOU = 0.62;
    const MAX_DUPLICATE_FACE_CENTER_DISTANCE = 0.12;
    const MULTI_FACE_STABILITY_WINDOW_MS = 1600;
    const MULTI_FACE_STABILITY_MIN_SAMPLES = 4;
    const MULTI_FACE_STABILITY_REQUIRED_RATIO = 0.72;
    const ATTENTION_EVENT_COOLDOWN_MS = 9000;
    const HEAD_DEVIATION_GRACE_MS = 2500;
    const HEAD_DEVIATION_RATIO_THRESHOLD = 0.22;
    const HEAD_DEVIATION_MIN_CONSECUTIVE_FRAMES = 4;
    const AI_VIOLATION_DEDUPE_WINDOW_MS = 900;

    const SUSPICION_THRESHOLD = 60;
    const SCORE_DEFAULT_EVENT_COOLDOWN_MS = 2500;
    const SCORE_EVENT_COOLDOWN_MS = {
        tab_switch: 7000,
        shortcut_block: 3000,
        no_face_detected: 12000,
        multi_face_detected: 10000,
        attention_deviation: 9000
    };

    const SUSPICION_WEIGHTS = {
        tab_switch: 10,
        no_face_detected: 15,
        multi_face_detected: 25,
        attention_deviation: 5,
        shortcut_block: 5
    };

    let faceMesh = null;
    let faceMeshReady = false;
    let aiMonitoringStarted = false;
    let aiLoopRafId = null;
    let aiLastLoopAt = 0;
    let faceSendInFlight = false;
    let aiBootstrapTimer = null;
    let mediaPipeUnavailableLogged = false;
    let pendingBootstrap = false;
    let aiAnalysisCanvas = null;
    let aiAnalysisCtx = null;
    let aiInferenceCanvas = null;
    let aiInferenceCtx = null;
    let smoothedLuma = 120;
    let smoothedStdDev = 36;
    let lastConfidenceUpdateAt = 0;
    let currentConfidenceProfile = "default";

    let noFaceStartedAt = null;
    let lastNoFaceEventAt = 0;
    let lastMultiFaceEventAt = 0;
    let multiFaceStartedAt = null;
    let multiFaceConsecutiveFrames = 0;
    let multiFaceFastConsecutiveFrames = 0;
    const multiFaceHistory = [];
    let headDeviationStartedAt = null;
    let headDeviationConsecutiveFrames = 0;
    let lastAttentionEventAt = 0;
    let attentionYawBaseline = 0;
    let attentionYawBaselineSamples = 0;
    let noFaceEventCount = 0;
    let multipleFaceEventCount = 0;
    let attentionDeviationCount = 0;

    let suspicionScore = loadSuspicionScore();
    let suspicionThresholdTriggered = loadThresholdLatch();
    const scoreEventLastAt = {};
    const aiViolationLastAt = new Map();

    function isActiveExamPath() {
        return /^\/mcq\/question\/[^/]+\/?$/.test(window.location.pathname)
            || /^\/mcq\/submit\/[^/]+\/?$/.test(window.location.pathname);
    }

    function loadSuspicionScore() {
        try {
            const raw = sessionStorage.getItem(SCORE_STORAGE_KEY);
            if (!raw) return 0;
            const parsed = Number(raw);
            return Number.isNaN(parsed) ? 0 : Math.max(0, parsed);
        } catch (_) {
            return 0;
        }
    }

    function persistSuspicionScore() {
        try {
            sessionStorage.setItem(SCORE_STORAGE_KEY, String(Math.max(0, Math.round(suspicionScore))));
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function loadThresholdLatch() {
        try {
            return sessionStorage.getItem(SCORE_THRESHOLD_LATCH_KEY) === "1";
        } catch (_) {
            return false;
        }
    }

    function persistThresholdLatch(latched) {
        try {
            if (latched) {
                sessionStorage.setItem(SCORE_THRESHOLD_LATCH_KEY, "1");
            } else {
                sessionStorage.removeItem(SCORE_THRESHOLD_LATCH_KEY);
            }
        } catch (_) {
            // Ignore storage failures.
        }
    }

    function sendViolation(type, details = {}, useBeacon = false) {
        const safeDetails = (details && typeof details === "object") ? details : {};
        const violationKey = stableStringify({
            type: normalizeViolationType(type),
            source: safeDetails.source || "",
            reason: safeDetails.reason || "",
            face_count: safeDetails.face_count || "",
            shortcut: safeDetails.shortcut || ""
        });
        const now = Date.now();
        const lastAt = Number(aiViolationLastAt.get(violationKey) || 0);
        if ((now - lastAt) < AI_VIOLATION_DEDUPE_WINDOW_MS) {
            return;
        }
        aiViolationLastAt.set(violationKey, now);

        if (typeof window.__proctoringSendViolation === "function") {
            window.__proctoringSendViolation(type, safeDetails, useBeacon);
            return;
        }

        const payload = {
            session_id: SESSION_ID,
            violation_type: type,
            details: safeDetails,
            ts: new Date().toISOString()
        };

        const body = JSON.stringify(payload);
        if (useBeacon && navigator.sendBeacon) {
            try {
                const blob = new Blob([body], { type: "application/json" });
                navigator.sendBeacon("/mcq/proctoring/violation", blob);
                return;
            } catch (_) {
                // Fall through to fetch.
            }
        }

        fetch("/mcq/proctoring/violation", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body,
            keepalive: useBeacon
        }).catch(() => {
            if (!navigator.sendBeacon) return;
            try {
                const blob = new Blob([body], { type: "application/json" });
                navigator.sendBeacon("/mcq/proctoring/violation", blob);
            } catch (_) {
                // Best-effort fallback.
            }
        });
    }

    function stableStringify(value) {
        if (Array.isArray(value)) {
            return `[${value.map((item) => stableStringify(item)).join(",")}]`;
        }
        if (value && typeof value === "object") {
            const keys = Object.keys(value).sort();
            return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
        }
        return JSON.stringify(value);
    }

    function captureEvidence(eventType, details = {}) {
        if (typeof window.__proctoringCaptureEvidence === "function") {
            window.__proctoringCaptureEvidence(eventType, details, true);
        }
    }

    function getWebcamVideo() {
        if (typeof window.__proctoringGetWebcamVideo === "function") {
            const video = window.__proctoringGetWebcamVideo();
            if (video) return video;
        }
        return document.getElementById(WEBCAM_VIDEO_ID);
    }

    function hasActiveVideoStream(video) {
        if (!video) return false;
        if (!video.srcObject) return false;
        if (video.readyState < 2) return false;
        const tracks = typeof video.srcObject.getVideoTracks === "function"
            ? video.srcObject.getVideoTracks()
            : [];
        if (!tracks || tracks.length === 0) return false;
        return tracks.some((track) => track.readyState === "live" && track.enabled !== false);
    }

    function isAIMonitoringSuppressed() {
        if (document.hidden) return true;
        if (!isActiveExamPath()) return true;
        if (typeof window.__proctoringShouldIgnoreProctoringEvent === "function") {
            try {
                if (window.__proctoringShouldIgnoreProctoringEvent()) return true;
            } catch (_) {
                // Ignore bridge errors.
            }
        }
        return false;
    }

    function ensureAIAnalysisCanvas() {
        if (aiAnalysisCanvas && aiAnalysisCtx) return;
        aiAnalysisCanvas = document.createElement("canvas");
        aiAnalysisCanvas.width = AI_ANALYSIS_FRAME_WIDTH;
        aiAnalysisCanvas.height = AI_ANALYSIS_FRAME_HEIGHT;
        aiAnalysisCtx = aiAnalysisCanvas.getContext("2d", { willReadFrequently: true });
    }

    function ensureAIInferenceCanvas(width, height) {
        const safeWidth = Math.max(1, Math.floor(width));
        const safeHeight = Math.max(1, Math.floor(height));
        if (!aiInferenceCanvas) {
            aiInferenceCanvas = document.createElement("canvas");
        }
        if (aiInferenceCanvas.width !== safeWidth) {
            aiInferenceCanvas.width = safeWidth;
        }
        if (aiInferenceCanvas.height !== safeHeight) {
            aiInferenceCanvas.height = safeHeight;
        }
        if (!aiInferenceCtx) {
            aiInferenceCtx = aiInferenceCanvas.getContext("2d");
        }
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function analyzeLighting(video) {
        ensureAIAnalysisCanvas();
        if (!aiAnalysisCtx || !aiAnalysisCanvas) {
            return { luma: smoothedLuma, stdDev: smoothedStdDev, mode: currentConfidenceProfile };
        }

        try {
            aiAnalysisCtx.filter = "none";
            aiAnalysisCtx.drawImage(video, 0, 0, aiAnalysisCanvas.width, aiAnalysisCanvas.height);
            const pixels = aiAnalysisCtx.getImageData(0, 0, aiAnalysisCanvas.width, aiAnalysisCanvas.height).data;
            if (!pixels || pixels.length < 4) {
                return { luma: smoothedLuma, stdDev: smoothedStdDev, mode: currentConfidenceProfile };
            }

            let sum = 0;
            let sumSq = 0;
            let count = 0;
            const step = 16;
            for (let i = 0; i < pixels.length; i += step) {
                const r = pixels[i];
                const g = pixels[i + 1];
                const b = pixels[i + 2];
                const luma = (0.2126 * r) + (0.7152 * g) + (0.0722 * b);
                sum += luma;
                sumSq += (luma * luma);
                count += 1;
            }
            if (count <= 0) {
                return { luma: smoothedLuma, stdDev: smoothedStdDev, mode: currentConfidenceProfile };
            }

            const avg = sum / count;
            const variance = Math.max(0, (sumSq / count) - (avg * avg));
            const stdDev = Math.sqrt(variance);

            smoothedLuma = (smoothedLuma * (1 - LIGHTING_SMOOTH_ALPHA)) + (avg * LIGHTING_SMOOTH_ALPHA);
            smoothedStdDev = (smoothedStdDev * (1 - LIGHTING_SMOOTH_ALPHA)) + (stdDev * LIGHTING_SMOOTH_ALPHA);
        } catch (_) {
            // Keep previous smoothed values on read failures.
        }

        let mode = "default";
        if (
            smoothedLuma <= VERY_LOW_LIGHT_LUMA_THRESHOLD
            || (smoothedLuma <= LOW_LIGHT_LUMA_THRESHOLD && smoothedStdDev <= VERY_LOW_LIGHT_STDDEV_THRESHOLD)
        ) {
            mode = "very_low_light";
        } else if (smoothedLuma <= LOW_LIGHT_LUMA_THRESHOLD || smoothedStdDev <= LOW_LIGHT_STDDEV_THRESHOLD) {
            mode = "low_light";
        }

        return { luma: smoothedLuma, stdDev: smoothedStdDev, mode };
    }

    function getConfidenceProfile(mode) {
        if (mode === "very_low_light") return CONFIDENCE_PROFILE_VERY_LOW_LIGHT;
        if (mode === "low_light") return CONFIDENCE_PROFILE_LOW_LIGHT;
        return CONFIDENCE_PROFILE_DEFAULT;
    }

    function maybeApplyDynamicConfidence(mode) {
        if (!faceMesh) return;
        const now = Date.now();
        const shouldUpdate = (
            mode !== currentConfidenceProfile
            || (now - lastConfidenceUpdateAt) >= DYNAMIC_CONFIDENCE_UPDATE_INTERVAL_MS
        );
        if (!shouldUpdate) return;

        const profile = getConfidenceProfile(mode);
        try {
            faceMesh.setOptions({
                maxNumFaces: MAX_TRACKED_FACES,
                refineLandmarks: false,
                minDetectionConfidence: profile.minDetectionConfidence,
                minTrackingConfidence: profile.minTrackingConfidence
            });
            currentConfidenceProfile = mode;
            lastConfidenceUpdateAt = now;
        } catch (_) {
            // Ignore dynamic option update failures.
        }
    }

    function prepareInferenceImage(video) {
        const width = Number(video.videoWidth) || 0;
        const height = Number(video.videoHeight) || 0;
        if (!width || !height) return video;

        const lighting = analyzeLighting(video);
        maybeApplyDynamicConfidence(lighting.mode);
        if (lighting.mode === "default") {
            return video;
        }

        const scale = Math.min(1, AI_INFERENCE_MAX_WIDTH / width, AI_INFERENCE_MAX_HEIGHT / height);
        const targetWidth = Math.max(1, Math.round(width * scale));
        const targetHeight = Math.max(1, Math.round(height * scale));
        ensureAIInferenceCanvas(targetWidth, targetHeight);
        if (!aiInferenceCtx || !aiInferenceCanvas) return video;

        const brightnessBoost = lighting.mode === "very_low_light"
            ? clamp(1.85 + ((VERY_LOW_LIGHT_LUMA_THRESHOLD - lighting.luma) / 130), 1.7, 2.2)
            : clamp(1.25 + ((LOW_LIGHT_LUMA_THRESHOLD - lighting.luma) / 240), 1.2, 1.5);
        const contrastBoost = lighting.mode === "very_low_light"
            ? clamp(1.5 + ((VERY_LOW_LIGHT_STDDEV_THRESHOLD - lighting.stdDev) / 110), 1.35, 1.9)
            : clamp(1.2 + ((LOW_LIGHT_STDDEV_THRESHOLD - lighting.stdDev) / 160), 1.12, 1.45);
        const saturationBoost = lighting.mode === "very_low_light" ? 1.12 : 1.04;

        aiInferenceCtx.filter = `brightness(${brightnessBoost}) contrast(${contrastBoost}) saturate(${saturationBoost})`;
        aiInferenceCtx.drawImage(video, 0, 0, aiInferenceCanvas.width, aiInferenceCanvas.height);
        aiInferenceCtx.filter = "none";

        return aiInferenceCanvas;
    }

    function loadScriptOnce(src) {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[data-proctoring-ai-src="${src}"]`);
            if (existing) {
                if (existing.dataset.failed === "1") {
                    existing.remove();
                } else {
                    if (existing.dataset.loaded === "1") {
                        resolve();
                        return;
                    }
                    existing.addEventListener("load", () => resolve(), { once: true });
                    existing.addEventListener("error", () => reject(new Error(`Failed to load ${src}`)), { once: true });
                    return;
                }
            }

            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.defer = true;
            script.dataset.proctoringAiSrc = src;
            script.addEventListener("load", () => {
                script.dataset.loaded = "1";
                resolve();
            }, { once: true });
            script.addEventListener("error", () => {
                script.dataset.failed = "1";
                reject(new Error(`Failed to load ${src}`));
            }, { once: true });
            document.head.appendChild(script);
        });
    }

    async function loadFaceMeshScript() {
        const candidates = [
            { src: MEDIAPIPE_LOCAL_FACE_MESH_SRC, baseUrl: MEDIAPIPE_LOCAL_BASE_URL, sourceLabel: "local_static" },
            { src: MEDIAPIPE_CDN_FACE_MESH_SRC, baseUrl: MEDIAPIPE_CDN_BASE_URL, sourceLabel: "cdn" }
        ];

        let lastError = null;
        for (const candidate of candidates) {
            try {
                await loadScriptOnce(candidate.src);
                return candidate;
            } catch (error) {
                lastError = error;
            }
        }

        throw lastError || new Error("No MediaPipe script source available");
    }

    function addSuspicionScore(reasonKey, details = {}) {
        if (!isActiveExamPath()) return;
        if (!Object.prototype.hasOwnProperty.call(SUSPICION_WEIGHTS, reasonKey)) return;
        if (suspicionThresholdTriggered) return;

        const now = Date.now();
        const cooldownMs = SCORE_EVENT_COOLDOWN_MS[reasonKey] || SCORE_DEFAULT_EVENT_COOLDOWN_MS;
        const lastAt = scoreEventLastAt[reasonKey] || 0;
        if ((now - lastAt) < cooldownMs) return;
        scoreEventLastAt[reasonKey] = now;

        const weight = Number(SUSPICION_WEIGHTS[reasonKey]) || 0;
        if (weight <= 0) return;

        suspicionScore += weight;
        persistSuspicionScore();

        sendViolation("Suspicion score updated", {
            reason_key: reasonKey,
            added_score: weight,
            suspicion_score: suspicionScore,
            suspicion_threshold: SUSPICION_THRESHOLD,
            ...details
        });

        if (suspicionScore < SUSPICION_THRESHOLD) return;

        suspicionThresholdTriggered = true;
        persistThresholdLatch(true);

        sendViolation("Suspicion threshold exceeded", {
            suspicion_score: suspicionScore,
            suspicion_threshold: SUSPICION_THRESHOLD,
            reason_key: reasonKey,
            ...details
        });
        captureEvidence("suspicion_threshold_exceeded", {
            suspicion_score: suspicionScore,
            reason_key: reasonKey
        });
    }

    function normalizeViolationType(value) {
        return String(value || "").trim().toLowerCase();
    }

    function handleViolationEventScore(detail) {
        const violationType = normalizeViolationType(detail && detail.violation_type);
        if (!violationType) return;

        if (violationType === "tab switching detected") {
            addSuspicionScore("tab_switch", {
                source: detail && detail.details ? detail.details.source : ""
            });
            return;
        }

        if (
            violationType === "keyboard shortcut blocked"
            || violationType === "copy blocked"
            || violationType === "paste blocked"
        ) {
            addSuspicionScore("shortcut_block", {
                violation_type: violationType
            });
        }
    }

    function handleNoFace(nowMs) {
        if (!isActiveExamPath()) return;
        resetMultiFaceTracking();
        resetAttentionTracking();

        if (!noFaceStartedAt) {
            noFaceStartedAt = nowMs;
            return;
        }

        const missingMs = nowMs - noFaceStartedAt;
        if (missingMs < NO_FACE_GRACE_MS) return;
        if ((nowMs - lastNoFaceEventAt) < NO_FACE_EVENT_COOLDOWN_MS) return;
        lastNoFaceEventAt = nowMs;
        noFaceEventCount += 1;

        const noFaceDurationSeconds = Math.round((missingMs / 1000) * 10) / 10;
        sendViolation("No face detected", {
            no_face_duration_seconds: noFaceDurationSeconds,
            grace_threshold_seconds: NO_FACE_GRACE_MS / 1000,
            no_face_event_count: noFaceEventCount
        });
        captureEvidence("no_face", {
            no_face_duration_seconds: noFaceDurationSeconds,
            no_face_event_count: noFaceEventCount
        });
        addSuspicionScore("no_face_detected", {
            no_face_duration_seconds: noFaceDurationSeconds,
            no_face_event_count: noFaceEventCount
        });
    }

    function resetMultiFaceCounters() {
        multiFaceStartedAt = null;
        multiFaceConsecutiveFrames = 0;
        multiFaceFastConsecutiveFrames = 0;
    }

    function resetMultiFaceTracking() {
        resetMultiFaceCounters();
        multiFaceHistory.length = 0;
    }

    function recordMultiFaceSample(nowMs, isMultiFace) {
        multiFaceHistory.push({
            ts: nowMs,
            multi: !!isMultiFace
        });
        while (
            multiFaceHistory.length > 0
            && (nowMs - Number(multiFaceHistory[0].ts || 0)) > MULTI_FACE_STABILITY_WINDOW_MS
        ) {
            multiFaceHistory.shift();
        }
    }

    function hasStableMultiFacePattern(nowMs) {
        if (multiFaceHistory.length < MULTI_FACE_STABILITY_MIN_SAMPLES) return false;
        let total = 0;
        let multi = 0;
        for (const sample of multiFaceHistory) {
            if ((nowMs - Number(sample.ts || 0)) > MULTI_FACE_STABILITY_WINDOW_MS) continue;
            total += 1;
            if (sample.multi) multi += 1;
        }
        if (total < MULTI_FACE_STABILITY_MIN_SAMPLES) return false;
        return (multi / total) >= MULTI_FACE_STABILITY_REQUIRED_RATIO;
    }

    function resetAttentionTracking() {
        headDeviationStartedAt = null;
        headDeviationConsecutiveFrames = 0;
    }

    function updateAttentionBaseline(yawRatio) {
        if (!Number.isFinite(yawRatio)) return;
        if (attentionYawBaselineSamples <= 0) {
            attentionYawBaseline = yawRatio;
            attentionYawBaselineSamples = 1;
            return;
        }
        const alpha = attentionYawBaselineSamples < 30 ? 0.18 : 0.06;
        attentionYawBaseline += (yawRatio - attentionYawBaseline) * alpha;
        if (attentionYawBaselineSamples < 30) {
            attentionYawBaselineSamples += 1;
        }
    }

    function buildFaceBounds(landmarks) {
        if (!Array.isArray(landmarks) || landmarks.length === 0) return null;

        let minX = Number.POSITIVE_INFINITY;
        let minY = Number.POSITIVE_INFINITY;
        let maxX = Number.NEGATIVE_INFINITY;
        let maxY = Number.NEGATIVE_INFINITY;
        let validPoints = 0;

        for (const point of landmarks) {
            if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) continue;
            minX = Math.min(minX, point.x);
            minY = Math.min(minY, point.y);
            maxX = Math.max(maxX, point.x);
            maxY = Math.max(maxY, point.y);
            validPoints += 1;
        }

        if (validPoints < MIN_PARTIAL_FACE_LANDMARK_POINTS) return null;

        const width = Math.max(0, maxX - minX);
        const height = Math.max(0, maxY - minY);
        if (width <= 0 || height <= 0) return null;

        return {
            minX,
            minY,
            maxX,
            maxY,
            width,
            height,
            area: width * height,
            cx: (minX + maxX) / 2,
            cy: (minY + maxY) / 2,
            aspectRatio: width / height,
            points: validPoints
        };
    }

    function computeIoU(a, b) {
        const ix1 = Math.max(a.minX, b.minX);
        const iy1 = Math.max(a.minY, b.minY);
        const ix2 = Math.min(a.maxX, b.maxX);
        const iy2 = Math.min(a.maxY, b.maxY);

        const intersectionW = Math.max(0, ix2 - ix1);
        const intersectionH = Math.max(0, iy2 - iy1);
        const intersection = intersectionW * intersectionH;
        if (intersection <= 0) return 0;

        const union = a.area + b.area - intersection;
        if (union <= 0) return 0;
        return intersection / union;
    }

    function computeOverlapOverSmaller(a, b) {
        const ix1 = Math.max(a.minX, b.minX);
        const iy1 = Math.max(a.minY, b.minY);
        const ix2 = Math.min(a.maxX, b.maxX);
        const iy2 = Math.min(a.maxY, b.maxY);

        const intersectionW = Math.max(0, ix2 - ix1);
        const intersectionH = Math.max(0, iy2 - iy1);
        const intersection = intersectionW * intersectionH;
        if (intersection <= 0) return 0;

        const smallerArea = Math.min(a.area, b.area);
        if (smallerArea <= 0) return 0;
        return intersection / smallerArea;
    }

    function computeCenterDistance(a, b) {
        return Math.hypot((a.cx - b.cx), (a.cy - b.cy));
    }

    function areLikelyDuplicateFaces(primary, secondary) {
        const iou = computeIoU(primary, secondary);
        const overlapOverSmaller = computeOverlapOverSmaller(primary, secondary);
        const centerDistance = computeCenterDistance(primary, secondary);
        const areaRatio = Math.min(primary.area, secondary.area) / Math.max(primary.area, secondary.area);

        if (iou > MAX_DUPLICATE_FACE_IOU && centerDistance < MAX_DUPLICATE_FACE_CENTER_DISTANCE) {
            return true;
        }

        if (overlapOverSmaller > 0.82 && centerDistance < (MAX_DUPLICATE_FACE_CENTER_DISTANCE * 1.7)) {
            return true;
        }

        return areaRatio < MIN_SECOND_FACE_AREA_RATIO && centerDistance < (MAX_DUPLICATE_FACE_CENTER_DISTANCE * 1.2);
    }

    function getEdgeTouchCount(bounds) {
        let touches = 0;
        if (bounds.minX < MIN_FACE_EDGE_MARGIN) touches += 1;
        if (bounds.minY < MIN_FACE_EDGE_MARGIN) touches += 1;
        if (bounds.maxX > (1 - MIN_FACE_EDGE_MARGIN)) touches += 1;
        if (bounds.maxY > (1 - MIN_FACE_EDGE_MARGIN)) touches += 1;
        return touches;
    }

    function isFaceNearEdge(bounds) {
        return getEdgeTouchCount(bounds) > 0;
    }

    function isReasonableFaceAspect(bounds, relaxed = false) {
        const ratio = Number(bounds.aspectRatio || 0);
        if (!Number.isFinite(ratio) || ratio <= 0) return false;
        if (!relaxed) {
            return ratio >= MIN_FACE_ASPECT_RATIO && ratio <= MAX_FACE_ASPECT_RATIO;
        }
        return ratio >= 0.15 && ratio <= 6.0;
    }

    function isStrongFaceCandidate(bounds) {
        return (
            bounds.points >= MIN_PRIMARY_FACE_LANDMARK_POINTS
            && bounds.area >= MIN_VALID_FACE_BOUNDS_AREA
            && !isFaceNearEdge(bounds)
            && isReasonableFaceAspect(bounds, false)
        );
    }

    function isPartialFaceCandidate(bounds) {
        if (bounds.points < MIN_PARTIAL_FACE_LANDMARK_POINTS) return false;
        if (bounds.area < MIN_PARTIAL_FACE_BOUNDS_AREA) return false;
        if (!isReasonableFaceAspect(bounds, true)) return false;
        const edgeTouches = getEdgeTouchCount(bounds);
        if (edgeTouches > MAX_PARTIAL_FACE_EDGE_TOUCHES) return false;

        const nearEdge = edgeTouches > 0;
        const centerStrongEnough = (
            bounds.points >= (MIN_PARTIAL_FACE_LANDMARK_POINTS + 12)
            && bounds.area >= (MIN_PARTIAL_FACE_BOUNDS_AREA * 2.1)
        );
        return nearEdge || centerStrongEnough;
    }

    function enrichFaceCandidate(landmarks, index) {
        const bounds = buildFaceBounds(landmarks);
        if (!bounds) return null;
        const edgeTouches = getEdgeTouchCount(bounds);
        const strong = isStrongFaceCandidate(bounds);
        const partial = isPartialFaceCandidate(bounds);
        if (!strong && !partial) return null;
        return { index, landmarks, bounds, edgeTouches, strong, partial };
    }

    function pickPrimaryCandidate(unique) {
        const strongPrimary = unique.find((candidate) => candidate.strong);
        if (strongPrimary) return strongPrimary;
        return unique.find((candidate) => (
            candidate.partial && candidate.bounds.area >= (MIN_VALID_FACE_BOUNDS_AREA * 0.6)
        )) || null;
    }

    function pickSecondaryCandidates(unique, primary) {
        const rest = unique.filter((candidate) => candidate !== primary);
        if (rest.length === 0) return [];
        rest.sort((a, b) => {
            const scoreA = (a.strong ? 2 : 1) * a.bounds.area + (a.edgeTouches > 0 ? 0.0008 : 0);
            const scoreB = (b.strong ? 2 : 1) * b.bounds.area + (b.edgeTouches > 0 ? 0.0008 : 0);
            return scoreB - scoreA;
        });
        return rest;
    }

    function evaluateSecondaryCandidate(primary, secondary) {
        if (!primary || !secondary) return null;
        const secondFaceRatio = secondary.bounds.area / primary.bounds.area;
        const centerDistance = computeCenterDistance(primary.bounds, secondary.bounds);
        const overlapOverSmaller = computeOverlapOverSmaller(primary.bounds, secondary.bounds);
        const duplicateLike = (
            areLikelyDuplicateFaces(primary.bounds, secondary.bounds)
            || (overlapOverSmaller > 0.68 && centerDistance < (MIN_PARTIAL_SECOND_FACE_CENTER_DISTANCE * 2.1))
        );
        const strongSecondary = (
            secondary.strong
            && secondFaceRatio >= FAST_MULTI_FACE_MIN_AREA_RATIO
            && centerDistance >= FAST_MULTI_FACE_MIN_CENTER_DISTANCE
            && overlapOverSmaller <= 0.52
        );
        const validStrongSecondary = (
            secondary.strong
            && secondFaceRatio >= MIN_SECOND_FACE_AREA_RATIO
            && centerDistance >= (MAX_DUPLICATE_FACE_CENTER_DISTANCE * 1.05)
            && overlapOverSmaller <= 0.62
        );
        const validPartialSecondary = (
            secondary.partial
            && secondFaceRatio >= MIN_PARTIAL_SECOND_FACE_AREA_RATIO
            && centerDistance >= MIN_PARTIAL_SECOND_FACE_CENTER_DISTANCE
            && secondary.edgeTouches <= MAX_PARTIAL_FACE_EDGE_TOUCHES
            && !duplicateLike
            && (
                secondary.edgeTouches > 0
                || secondFaceRatio >= (MIN_PARTIAL_SECOND_FACE_AREA_RATIO * 1.8)
                || secondary.bounds.points >= (MIN_PARTIAL_FACE_LANDMARK_POINTS + 12)
            )
        );
        return {
            candidate: secondary,
            secondFaceRatio,
            centerDistance,
            overlapOverSmaller,
            strongSecondary,
            partialSecondary: (!strongSecondary && validPartialSecondary),
            valid: (validStrongSecondary || validPartialSecondary)
        };
    }

    function getValidatedFaceSnapshot(faces) {
        const candidates = faces
            .map((landmarks, index) => enrichFaceCandidate(landmarks, index))
            .filter((entry) => !!entry)
            .sort((a, b) => b.bounds.area - a.bounds.area);

        if (candidates.length === 0) {
            return {
                count: 0,
                primary: null,
                secondary: null,
                secondFaceRatio: 0,
                centerDistance: 0,
                strongSecondary: false,
                partialSecondary: false,
                secondaryEdgeTouches: 0
            };
        }

        const unique = [];
        for (const candidate of candidates) {
            const duplicate = unique.some((existing) => areLikelyDuplicateFaces(existing.bounds, candidate.bounds));
            if (!duplicate) unique.push(candidate);
        }

        const primary = pickPrimaryCandidate(unique);
        if (!primary) {
            return {
                count: 0,
                primary: null,
                secondary: null,
                secondFaceRatio: 0,
                centerDistance: 0,
                strongSecondary: false,
                partialSecondary: false,
                secondaryEdgeTouches: 0
            };
        }

        const secondaryCandidates = pickSecondaryCandidates(unique, primary);
        if (!secondaryCandidates || secondaryCandidates.length === 0) {
            return {
                count: 1,
                primary,
                secondary: null,
                secondFaceRatio: 0,
                centerDistance: 0,
                strongSecondary: false,
                partialSecondary: false,
                secondaryEdgeTouches: 0,
                secondaryCandidateCount: 0
            };
        }

        const validSecondaryEvaluations = secondaryCandidates
            .map((candidate) => evaluateSecondaryCandidate(primary, candidate))
            .filter((entry) => entry && entry.valid);

        if (validSecondaryEvaluations.length === 0) {
            return {
                count: 1,
                primary,
                secondary: null,
                secondFaceRatio: 0,
                centerDistance: 0,
                strongSecondary: false,
                partialSecondary: false,
                secondaryEdgeTouches: 0,
                secondaryCandidateCount: 0
            };
        }

        validSecondaryEvaluations.sort((a, b) => {
            const weightA = (a.strongSecondary ? 2 : 1) * a.secondFaceRatio;
            const weightB = (b.strongSecondary ? 2 : 1) * b.secondFaceRatio;
            return weightB - weightA;
        });
        const bestSecondary = validSecondaryEvaluations[0];
        const detectedFaceCount = Math.max(2, 1 + validSecondaryEvaluations.length);
        return {
            count: detectedFaceCount,
            primary,
            secondary: bestSecondary.candidate,
            secondFaceRatio: bestSecondary.secondFaceRatio,
            centerDistance: bestSecondary.centerDistance,
            strongSecondary: bestSecondary.strongSecondary,
            partialSecondary: bestSecondary.partialSecondary,
            secondaryEdgeTouches: bestSecondary.candidate.edgeTouches,
            secondaryCandidateCount: validSecondaryEvaluations.length
        };
    }

    function handleMultipleFaces(nowMs, snapshot) {
        if (!isActiveExamPath()) return;
        if (!snapshot || snapshot.count < 2) return;

        recordMultiFaceSample(nowMs, true);

        if (!multiFaceStartedAt) {
            multiFaceStartedAt = nowMs;
            multiFaceConsecutiveFrames = 1;
            multiFaceFastConsecutiveFrames = snapshot.strongSecondary ? 1 : 0;
            return;
        }

        multiFaceConsecutiveFrames += 1;
        if (snapshot.strongSecondary) {
            multiFaceFastConsecutiveFrames += 1;
        } else {
            multiFaceFastConsecutiveFrames = 0;
        }
        const sustainedDurationMs = nowMs - multiFaceStartedAt;
        const fastConfirmed = (
            snapshot.strongSecondary
            && sustainedDurationMs >= FAST_MULTI_FACE_GRACE_MS
            && multiFaceFastConsecutiveFrames >= FAST_MULTI_FACE_MIN_CONSECUTIVE_FRAMES
        );
        const partialConfirmed = (
            snapshot.partialSecondary
            && sustainedDurationMs >= PARTIAL_MULTI_FACE_GRACE_MS
            && multiFaceConsecutiveFrames >= PARTIAL_MULTI_FACE_MIN_CONSECUTIVE_FRAMES
            && hasStableMultiFacePattern(nowMs)
        );
        const stableConfirmed = (
            !snapshot.partialSecondary
            && sustainedDurationMs >= MULTI_FACE_GRACE_MS
            && multiFaceConsecutiveFrames >= MULTI_FACE_MIN_CONSECUTIVE_FRAMES
            && hasStableMultiFacePattern(nowMs)
        );
        if (!fastConfirmed && !partialConfirmed && !stableConfirmed) return;
        if ((nowMs - lastMultiFaceEventAt) < MULTI_FACE_EVENT_COOLDOWN_MS) return;

        lastMultiFaceEventAt = nowMs;
        multipleFaceEventCount += 1;
        const faceCount = snapshot.count;
        const detectionMode = fastConfirmed
            ? "fast_confirmed"
            : (partialConfirmed ? "partial_confirmed" : "stable_confirmed");

        sendViolation("Multiple faces detected", {
            multiple_face_event_count: multipleFaceEventCount,
            sustained_duration_ms: sustainedDurationMs,
            confirmation_frames: multiFaceConsecutiveFrames,
            detection_mode: detectionMode,
            second_face_ratio: Number(snapshot.secondFaceRatio.toFixed(3)),
            center_distance: Number(snapshot.centerDistance.toFixed(3)),
            secondary_partial_visibility: !!snapshot.partialSecondary,
            secondary_edge_touches: Number(snapshot.secondaryEdgeTouches || 0),
            secondary_candidates: Number(snapshot.secondaryCandidateCount || 1)
        });
        captureEvidence("multi_face", {
            multiple_face_event_count: multipleFaceEventCount,
            sustained_duration_ms: sustainedDurationMs,
            detection_mode: detectionMode,
            secondary_partial_visibility: !!snapshot.partialSecondary,
            secondary_candidates: Number(snapshot.secondaryCandidateCount || 1)
        });
        addSuspicionScore("multi_face_detected", {
            multiple_face_event_count: multipleFaceEventCount,
            sustained_duration_ms: sustainedDurationMs,
            detection_mode: detectionMode,
            secondary_partial_visibility: !!snapshot.partialSecondary,
            secondary_candidates: Number(snapshot.secondaryCandidateCount || 1)
        });

        multiFaceStartedAt = nowMs;
        multiFaceConsecutiveFrames = 1;
        multiFaceFastConsecutiveFrames = snapshot.strongSecondary ? 1 : 0;
        multiFaceHistory.length = 0;
    }

    function handleAttentionDeviation(nowMs, landmarks) {
        if (!isActiveExamPath()) return;
        if (!Array.isArray(landmarks) || landmarks.length < 264) return;

        const nose = landmarks[1];
        const leftEyeOuter = landmarks[33];
        const rightEyeOuter = landmarks[263];
        if (!nose || !leftEyeOuter || !rightEyeOuter) return;

        const eyeCenterX = (leftEyeOuter.x + rightEyeOuter.x) / 2;
        const eyeDistance = Math.abs(rightEyeOuter.x - leftEyeOuter.x);
        if (!eyeDistance || eyeDistance < 0.02) {
            resetAttentionTracking();
            return;
        }

        const yawRatio = (nose.x - eyeCenterX) / eyeDistance;
        const baselineAdjustedYaw = yawRatio - attentionYawBaseline;
        const deviationAbs = Math.abs(baselineAdjustedYaw);
        if (deviationAbs < HEAD_DEVIATION_RATIO_THRESHOLD) {
            updateAttentionBaseline(yawRatio);
            resetAttentionTracking();
            return;
        }

        if (!headDeviationStartedAt) {
            headDeviationStartedAt = nowMs;
            headDeviationConsecutiveFrames = 1;
            return;
        }

        headDeviationConsecutiveFrames += 1;
        const deviationDurationMs = nowMs - headDeviationStartedAt;
        if (deviationDurationMs < HEAD_DEVIATION_GRACE_MS) return;
        if (headDeviationConsecutiveFrames < HEAD_DEVIATION_MIN_CONSECUTIVE_FRAMES) return;
        if ((nowMs - lastAttentionEventAt) < ATTENTION_EVENT_COOLDOWN_MS) return;
        lastAttentionEventAt = nowMs;
        attentionDeviationCount += 1;

        sendViolation("Attention deviation detected", {
            yaw_ratio: Number(yawRatio.toFixed(3)),
            baseline_adjusted_yaw_ratio: Number(baselineAdjustedYaw.toFixed(3)),
            baseline_yaw_ratio: Number(attentionYawBaseline.toFixed(3)),
            threshold_ratio: HEAD_DEVIATION_RATIO_THRESHOLD,
            deviation_duration_ms: deviationDurationMs,
            attention_deviation_count: attentionDeviationCount
        });
        captureEvidence("attention_deviation", {
            yaw_ratio: Number(yawRatio.toFixed(3)),
            baseline_adjusted_yaw_ratio: Number(baselineAdjustedYaw.toFixed(3)),
            deviation_duration_ms: deviationDurationMs,
            attention_deviation_count: attentionDeviationCount
        });
        addSuspicionScore("attention_deviation", {
            yaw_ratio: Number(yawRatio.toFixed(3)),
            baseline_adjusted_yaw_ratio: Number(baselineAdjustedYaw.toFixed(3)),
            deviation_duration_ms: deviationDurationMs,
            attention_deviation_count: attentionDeviationCount
        });
        headDeviationStartedAt = nowMs;
        headDeviationConsecutiveFrames = 1;
    }

    function handleFaceMeshResults(results) {
        const nowMs = Date.now();
        if (isAIMonitoringSuppressed()) {
            noFaceStartedAt = null;
            resetMultiFaceTracking();
            resetAttentionTracking();
            return;
        }
        const faces = (results && Array.isArray(results.multiFaceLandmarks)) ? results.multiFaceLandmarks : [];

        if (faces.length === 0) {
            recordMultiFaceSample(nowMs, false);
            handleNoFace(nowMs);
            return;
        }

        const snapshot = getValidatedFaceSnapshot(faces);
        if (snapshot.count <= 0) {
            recordMultiFaceSample(nowMs, false);
            handleNoFace(nowMs);
            return;
        }

        noFaceStartedAt = null;
        if (snapshot.count > 1) {
            handleMultipleFaces(nowMs, snapshot);
            return;
        }
        recordMultiFaceSample(nowMs, false);
        resetMultiFaceCounters();

        handleAttentionDeviation(nowMs, snapshot.primary ? snapshot.primary.landmarks : faces[0]);
    }

    function startFaceLoop() {
        if (aiLoopRafId) return;
        aiMonitoringStarted = true;

        const tick = async (ts) => {
            aiLoopRafId = window.requestAnimationFrame(tick);
            if (!faceMeshReady || !faceMesh) return;
            if ((ts - aiLastLoopAt) < AI_LOOP_MIN_INTERVAL_MS) return;
            if (faceSendInFlight) return;
            if (isAIMonitoringSuppressed()) return;

            const video = getWebcamVideo();
            if (!hasActiveVideoStream(video)) return;
            const inferenceImage = prepareInferenceImage(video);

            aiLastLoopAt = ts;
            faceSendInFlight = true;
            try {
                await faceMesh.send({ image: inferenceImage });
            } catch (_) {
                // Ignore transient frame inference failures.
            } finally {
                faceSendInFlight = false;
            }
        };

        aiLoopRafId = window.requestAnimationFrame(tick);
    }

    async function bootstrapFaceMesh() {
        if (faceMeshReady || pendingBootstrap) return;
        pendingBootstrap = true;

        try {
            const loadedScript = await loadFaceMeshScript();
            if (typeof window.FaceMesh !== "function") {
                throw new Error("FaceMesh constructor unavailable");
            }

            faceMesh = new window.FaceMesh({
                locateFile: (file) => `${loadedScript.baseUrl}/${file}`
            });
            const initialProfile = getConfidenceProfile("default");
            faceMesh.setOptions({
                maxNumFaces: MAX_TRACKED_FACES,
                refineLandmarks: false,
                minDetectionConfidence: initialProfile.minDetectionConfidence,
                minTrackingConfidence: initialProfile.minTrackingConfidence
            });
            currentConfidenceProfile = "default";
            lastConfidenceUpdateAt = Date.now();
            faceMesh.onResults(handleFaceMeshResults);

            faceMeshReady = true;
            sendViolation("AI face monitoring enabled", {
                provider: "mediapipe_face_mesh",
                max_faces: MAX_TRACKED_FACES,
                script_source: loadedScript.sourceLabel
            });
            startFaceLoop();
        } catch (error) {
            if (!mediaPipeUnavailableLogged) {
                mediaPipeUnavailableLogged = true;
                sendViolation("AI face monitoring unavailable", {
                    reason: "mediapipe_load_failed",
                    message: String((error && error.message) || error || "")
                });
            }
        } finally {
            pendingBootstrap = false;
        }
    }

    function maybeStartAiMonitoring() {
        const video = getWebcamVideo();
        if (!hasActiveVideoStream(video)) return;
        if (faceMeshReady || aiMonitoringStarted || pendingBootstrap) return;
        bootstrapFaceMesh();
    }

    function stopAiLoop() {
        if (!aiLoopRafId) return;
        window.cancelAnimationFrame(aiLoopRafId);
        aiLoopRafId = null;
    }

    function bindGlobalHooks() {
        window.addEventListener("proctoring:violation", (event) => {
            handleViolationEventScore(event ? event.detail : null);
        });

        const triggerStart = () => {
            maybeStartAiMonitoring();
        };

        ["pointerdown", "mousedown", "touchstart", "keydown", "click", "focus"].forEach((eventName) => {
            window.addEventListener(eventName, triggerStart, { capture: true, passive: true });
        });

        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) {
                maybeStartAiMonitoring();
            }
        });

        const webcamObserver = new MutationObserver(() => {
            maybeStartAiMonitoring();
        });
        webcamObserver.observe(document.documentElement || document.body, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ["srcObject", "style", "class"]
        });

        aiBootstrapTimer = window.setInterval(() => {
            maybeStartAiMonitoring();
            if (faceMeshReady && aiBootstrapTimer) {
                window.clearInterval(aiBootstrapTimer);
                aiBootstrapTimer = null;
            }
        }, AI_BOOTSTRAP_RETRY_MS);

        window.addEventListener("beforeunload", () => {
            stopAiLoop();
            if (aiBootstrapTimer) {
                window.clearInterval(aiBootstrapTimer);
                aiBootstrapTimer = null;
            }
            sendViolation("AI monitoring session summary", {
                suspicion_score: suspicionScore,
                suspicion_threshold: SUSPICION_THRESHOLD
            }, true);
        });
    }

    bindGlobalHooks();
    maybeStartAiMonitoring();
})();
