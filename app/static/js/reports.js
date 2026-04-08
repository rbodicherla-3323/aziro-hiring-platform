(function () {
  var filterForm = document.getElementById("reportsFilterForm");
  var roleSelect = document.getElementById("reportsRoleSelect");
  var periodSelect = document.getElementById("reportsPeriodSelect");
  var dateInput = document.getElementById("reportsDateInput");
  var searchInput = document.getElementById("reportsSearchInput");
  var pageInput = document.getElementById("reportsPageInput");
  var perPageInput = document.getElementById("reportsPerPageInput");
  var perPageSelect = document.getElementById("reportsPerPageSelect");
  var offsetInput = document.getElementById("reportsOffsetInput");

  var galleryModal = document.getElementById("reportsGalleryModal");
  var galleryTitle = document.getElementById("reportsGalleryTitle");
  var galleryMeta = document.getElementById("reportsGalleryMeta");
  var galleryGrid = document.getElementById("reportsGalleryGrid");
  var consolidatedTrigger = document.getElementById("reportsConsolidatedTrigger");
  var consolidatedModal = document.getElementById("reportsConsolidatedModal");
  var consolidatedScope = document.getElementById("reportsConsolidatedScope");
  var consolidatedRoleValue = document.getElementById("consolidatedRoleValue");
  var consolidatedPeriodValue = document.getElementById("consolidatedPeriodValue");
  var consolidatedBatchValue = document.getElementById("consolidatedBatchValue");
  var consolidatedRoleSelect = document.getElementById("consolidatedRoleSelect");
  var consolidatedPeriodSelect = document.getElementById("consolidatedPeriodSelect");
  var consolidatedDateInput = document.getElementById("consolidatedDateInput");
  var consolidatedPreviewBtn = document.getElementById("reportsConsolidatedPreview");
  var consolidatedResultsMeta = document.getElementById("reportsConsolidatedResultsMeta");
  var consolidatedLoadedPreview = document.getElementById("reportsConsolidatedLoadedPreview");
  var consolidatedBatchSelect = document.getElementById("consolidatedBatchSelect");
  var consolidatedVerdictFilter = document.getElementById("consolidatedVerdictFilter");
  var consolidatedCandidateSearch = document.getElementById("consolidatedCandidateSearch");
  var consolidatedCandidateList = document.getElementById("reportsConsolidatedCandidateList");
  var consolidatedPlaceholder = document.getElementById("reportsConsolidatedPlaceholder");
  var consolidatedLoading = document.getElementById("reportsConsolidatedLoading");
  var consolidatedContent = document.getElementById("reportsConsolidatedContent");
  var consolidatedSelectionMeta = document.getElementById("reportsConsolidatedSelectionMeta");
  var consolidatedDownloadBtn = document.getElementById("reportsConsolidatedDownload");
  var consolidatedGenerateBtn = document.getElementById("reportsConsolidatedGenerate");
  var consolidatedCopyBtn = document.getElementById("reportsConsolidatedCopy");

  var searchTimer = null;
  var activeGalleryScopeKey = "";
  var consolidatedState = {
    candidates: [],
    selectedCandidateKeys: {},
    visibleCandidates: [],
    rawSummary: "",
    summaryMeta: null,
    scope: null,
    isLoadingCandidates: false,
    isGenerating: false,
    isDownloading: false,
  };

  function syncBodyModalState() {
    var hasActiveModal = Boolean(
      (galleryModal && galleryModal.classList.contains("active")) ||
      (consolidatedModal && consolidatedModal.classList.contains("active"))
    );
    document.body.style.overflow = hasActiveModal ? "hidden" : "";
  }

  function fetchJson(url, options) {
    return fetch(url, options || { credentials: "same-origin" }).then(async function (response) {
      var contentType = (response.headers.get("content-type") || "").toLowerCase();
      var isJson = contentType.indexOf("application/json") >= 0;
      if (!response.ok) {
        var message = "Request failed (" + response.status + ")";
        try {
          if (isJson) {
            var data = await response.json();
            message = data.error || data.message || message;
          } else {
            var text = await response.text();
            if (text) message = text;
          }
        } catch (_) {
          // no-op
        }
        throw new Error(message);
      }
      if (isJson) return response.json();
      return {};
    });
  }

  function buildReportLinks(payload, fallbackFilename) {
    var filename = "";
    if (payload && payload.filename) {
      filename = String(payload.filename);
    } else if (fallbackFilename) {
      filename = String(fallbackFilename);
    }

    var viewUrl = (payload && payload.view_url) || (filename ? ("/reports/view/" + encodeURIComponent(filename)) : "#");
    var downloadUrl = (payload && payload.download_url) || (filename ? ("/reports/download-file/" + encodeURIComponent(filename)) : "#");
    return {
      filename: filename,
      viewUrl: viewUrl,
      downloadUrl: downloadUrl,
    };
  }

  function candidateSelectionKey(candidate) {
    if (!candidate) return "";
    var directKey = String(candidate.candidate_key || "").trim();
    if (directKey) return directKey;

    var email = String(candidate.email || "").trim().toLowerCase();
    if (!email) return "";
    var batchId = String(candidate.batch_id || "").trim().toLowerCase();
    var roleKey = String(candidate.role_key || candidate.role || "").trim().toLowerCase();
    return [email, batchId, roleKey].join("||");
  }

  function normalizeScopeValue(value) {
    var text = String(value || "").trim();
    if (!text) return "";
    var lowered = text.toLowerCase();
    if (lowered === "none" || lowered === "null" || lowered === "undefined") {
      return "";
    }
    return text;
  }

  function getCardCandidateContext(card, actionNode) {
    var context = {
      email: "",
      name: "",
      candidateKey: "",
      roleKey: "",
      batchId: "",
      testSessionId: "",
    };

    if (card) {
      context.email = normalizeScopeValue(card.getAttribute("data-candidate-email"));
      context.name = normalizeScopeValue(card.getAttribute("data-candidate-name"));
      context.candidateKey = normalizeScopeValue(card.getAttribute("data-candidate-key"));
      context.roleKey = normalizeScopeValue(card.getAttribute("data-candidate-role-key"));
      context.batchId = normalizeScopeValue(card.getAttribute("data-candidate-batch-id"));
      context.testSessionId = normalizeScopeValue(card.getAttribute("data-candidate-test-session-id"));
    }

    if (actionNode) {
      if (!context.email) {
        context.email = normalizeScopeValue(actionNode.getAttribute("data-email"));
      }
      if (!context.name) {
        context.name = normalizeScopeValue(actionNode.getAttribute("data-name"));
      }
      if (!context.candidateKey) {
        context.candidateKey = normalizeScopeValue(actionNode.getAttribute("data-candidate-key"));
      }
      if (!context.roleKey) {
        context.roleKey = normalizeScopeValue(actionNode.getAttribute("data-role-key"));
      }
      if (!context.batchId) {
        context.batchId = normalizeScopeValue(actionNode.getAttribute("data-batch-id"));
      }
      if (!context.testSessionId) {
        context.testSessionId = normalizeScopeValue(actionNode.getAttribute("data-test-session-id"));
      }
    }

    return context;
  }

  function applyCandidateContextAttributes(node, context) {
    if (!node || !context) return;
    if (context.email) {
      node.setAttribute("data-email", context.email);
    }
    if (context.name) {
      node.setAttribute("data-name", context.name);
    }
    if (context.candidateKey) {
      node.setAttribute("data-candidate-key", context.candidateKey);
    }
    if (context.roleKey) {
      node.setAttribute("data-role-key", context.roleKey);
    }
    if (context.batchId) {
      node.setAttribute("data-batch-id", context.batchId);
    }
    if (context.testSessionId) {
      node.setAttribute("data-test-session-id", context.testSessionId);
    }
  }

  function buildScopedReportUrl(context) {
    var params = new URLSearchParams();
    if (context.testSessionId) {
      params.set("test_session_id", context.testSessionId);
    }
    if (context.candidateKey) {
      params.set("candidate_key", context.candidateKey);
    }
    if (context.roleKey) {
      params.set("role_key", context.roleKey);
    }
    if (context.batchId) {
      params.set("batch_id", context.batchId);
    }
    var query = params.toString();
    return "/reports/generate/" + encodeURIComponent(context.email) + (query ? "?" + query : "");
  }

  function buildScopedGalleryUrl(context) {
    var params = new URLSearchParams();
    if (context.email) {
      params.set("email", context.email);
    }
    if (context.testSessionId) {
      params.set("test_session_id", context.testSessionId);
    }
    params.set("limit", "300");
    return "/reports/proctoring/screenshots?" + params.toString();
  }

  function makeActionElement(config) {
    var node = config.href ? document.createElement("a") : document.createElement("button");
    var label = String(config.label || "");
    var iconOnly = Boolean(config.iconOnly);
    if (!config.href) {
      node.type = "button";
    }
    node.className = config.className || "";
    if (iconOnly) {
      node.classList.add("icon-only");
    }
    if (config.action) {
      node.setAttribute("data-action", config.action);
    }
    if (config.context) {
      applyCandidateContextAttributes(node, config.context);
    } else {
      if (config.email) {
        node.setAttribute("data-email", config.email);
      }
      if (config.name) {
        node.setAttribute("data-name", config.name);
      }
    }
    if (config.href) {
      node.href = config.href;
      if (config.target) {
        node.target = config.target;
      }
      if (config.rel) {
        node.rel = config.rel;
      }
    }
    if (config.disabled) {
      if (node.tagName === "BUTTON") {
        node.disabled = true;
      }
      node.classList.add("disabled");
      node.setAttribute("aria-disabled", "true");
    }

    if (iconOnly) {
      if (label) {
        node.title = label;
        node.setAttribute("aria-label", label);
      }
      node.innerHTML = config.icon || "";
      return node;
    }

    if (label) {
      node.setAttribute("aria-label", label);
    }
    node.innerHTML = (config.icon || "") + (label ? " " + label : "");
    return node;
  }

  function renderRowActions(card, hasReport, links) {
    var rowActions = card ? card.querySelector(".row-actions") : null;
    if (!rowActions) return;

    var context = getCardCandidateContext(card);

    rowActions.innerHTML = "";

    rowActions.appendChild(makeActionElement({
      className: "row-action-btn gallery js-open-gallery",
      action: "view-screenshots",
      context: context,
      icon: '<i class="bi bi-images"></i>',
      label: "View Screenshots",
      iconOnly: true,
    }));

    if (hasReport) {
      rowActions.appendChild(makeActionElement({
        className: "row-action-btn view",
        href: links.viewUrl,
        target: "_blank",
        rel: "noopener",
        icon: '<i class="bi bi-eye-fill"></i>',
        label: "View Report",
        iconOnly: true,
      }));
      rowActions.appendChild(makeActionElement({
        className: "row-action-btn",
        href: links.downloadUrl,
        icon: '<i class="bi bi-download"></i>',
        label: "Download PDF",
        iconOnly: true,
      }));
      rowActions.appendChild(makeActionElement({
        className: "row-action-btn generate js-generate-report",
        action: "regenerate-report",
        context: context,
        icon: '<i class="bi bi-arrow-repeat"></i>',
        label: "Regenerate Report",
        iconOnly: true,
      }));
      return;
    }

    rowActions.appendChild(makeActionElement({
      className: "row-action-btn generate js-generate-report",
      action: "generate-report",
      context: context,
      icon: '<i class="bi bi-file-earmark-pdf-fill"></i>',
      label: "Generate Report",
      iconOnly: true,
    }));
  }

  function renderActionHub(card, hasReport, links) {
    var actionGrid = card ? card.querySelector(".insight-actions") : null;
    if (!actionGrid) return;

    var context = getCardCandidateContext(card);

    actionGrid.innerHTML = "";

    if (hasReport) {
      actionGrid.appendChild(makeActionElement({
        className: "insight-action primary js-view-report",
        action: "view-report",
        href: links.viewUrl,
        target: "_blank",
        rel: "noopener",
        icon: '<i class="bi bi-eye-fill"></i>',
        label: "View Report",
      }));
      actionGrid.appendChild(makeActionElement({
        className: "insight-action report-download js-download-report",
        action: "download-report",
        href: links.downloadUrl,
        icon: '<i class="bi bi-download"></i>',
        label: "Download PDF",
      }));
    } else {
      actionGrid.appendChild(makeActionElement({
        className: "insight-action report-generate js-generate-report",
        action: "generate-report",
        context: context,
        icon: '<i class="bi bi-file-earmark-pdf-fill"></i>',
        label: "Generate Report",
      }));
      actionGrid.appendChild(makeActionElement({
        className: "insight-action report-download js-download-report disabled",
        action: "download-report",
        icon: '<i class="bi bi-download"></i>',
        label: "Download PDF",
        disabled: true,
      }));
    }

    actionGrid.appendChild(makeActionElement({
      className: "insight-action js-open-gallery",
      action: "view-screenshots",
      context: context,
      icon: '<i class="bi bi-images"></i>',
      label: "View Screenshots",
    }));

    actionGrid.appendChild(makeActionElement({
      className: "insight-action report-regenerate js-generate-report" + (hasReport ? "" : " disabled"),
      action: "regenerate-report",
      context: context,
      icon: '<i class="bi bi-arrow-repeat"></i>',
      label: "Regenerate Report",
      disabled: !hasReport,
    }));
  }

  function applyReportReadyState(card, payload) {
    if (!card) return;
    var fallbackFilename = card.getAttribute("data-report-filename") || "";
    var links = buildReportLinks(payload || {}, fallbackFilename);

    card.setAttribute("data-has-report", "1");
    if (links.filename) {
      card.setAttribute("data-report-filename", links.filename);
    }

    renderRowActions(card, true, links);
    renderActionHub(card, true, links);
  }

  function generateReport(context, button, card) {
    context = context || getCardCandidateContext(card, button);
    if (!context.email) return;

    var originalLabel = button ? button.innerHTML : "";
    var originalTitle = button ? button.getAttribute("title") : "";
    var iconOnlyButton = Boolean(button && button.classList.contains("icon-only"));
    if (button) {
      button.disabled = true;
      if (iconOnlyButton) {
        button.innerHTML = '<i class="bi bi-arrow-repeat"></i>';
        button.setAttribute("title", "Generating report...");
        button.setAttribute("aria-label", "Generating report...");
      } else {
        button.innerHTML = '<i class="bi bi-arrow-repeat"></i> Generating...';
      }
    }

    fetchJson(buildScopedReportUrl(context), { credentials: "same-origin" })
      .then(function (payload) {
        if (!payload || !payload.success) {
          throw new Error((payload && payload.error) || "Report generation failed");
        }
        applyReportReadyState(card, payload);
        if (typeof showToast === "function") {
          showToast("Report generated successfully", "success");
        }
      })
      .catch(function (error) {
        if (typeof showToast === "function") {
          showToast(error.message || "Failed to generate report", "danger");
        }
        if (button) {
          button.disabled = false;
          button.innerHTML = originalLabel;
          if (iconOnlyButton) {
            if (originalTitle) {
              button.setAttribute("title", originalTitle);
              button.setAttribute("aria-label", originalTitle);
            } else {
              button.removeAttribute("title");
              button.removeAttribute("aria-label");
            }
          }
        }
      });
  }

  function syncDateFilterVisibility() {
    if (!periodSelect || !dateInput) return;
    var isCustomDate = periodSelect.value === "date";
    dateInput.classList.toggle("is-hidden", !isCustomDate);
    if (!isCustomDate) {
      dateInput.value = "";
    }
  }

  function submitFilters(resetOffset) {
    if (!filterForm) return;
    if (pageInput) {
      pageInput.value = "1";
    }
    if (offsetInput && resetOffset !== false) {
      offsetInput.value = "0";
    }
    filterForm.submit();
  }

  var activeCard = null;
  var lockedCard = null;
  var cardSwitchToken = 0;

  function applyOverlaySpacing(card) {
    if (!card) return;
    var panel = card.querySelector(".candidate-expanded-grid");
    var panelHeight = panel ? Math.ceil(panel.getBoundingClientRect().height) : 0;
    var spacing = Math.max(220, panelHeight + 16);
    card.style.setProperty("--overlay-space", spacing + "px");
    card.classList.add("with-space");
  }

  function clearOverlaySpacing(card) {
    if (!card) return;
    card.classList.remove("with-space");
    card.style.removeProperty("--overlay-space");
  }

  function setActiveCard(card) {
    if (activeCard === card) {
      if (activeCard) {
        applyOverlaySpacing(activeCard);
      }
      return;
    }

    var oldCard = activeCard;
    activeCard = card || null;

    // Always reserve space on the next active card first so layout never shrinks first.
    if (activeCard) {
      applyOverlaySpacing(activeCard);
      activeCard.classList.add("is-active");
    }

    if (!oldCard) return;
    var token = ++cardSwitchToken;
    var releaseOldCard = function () {
      if (token !== cardSwitchToken) return;
      if (oldCard === activeCard) return;
      clearOverlaySpacing(oldCard);
      oldCard.classList.remove("is-active");
    };

    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(releaseOldCard);
      });
      return;
    }

    window.setTimeout(releaseOldCard, 40);
  }

  function initCardExpansion() {
    var cards = Array.prototype.slice.call(document.querySelectorAll("[data-candidate-card]"));
    if (!cards.length) return;

    cards.forEach(function (card) {
      card.classList.remove("is-active");
      clearOverlaySpacing(card);
    });
    setActiveCard(null);

    cards.forEach(function (card) {
      card.addEventListener("click", function (event) {
        if (event.target.closest(".row-actions, .candidate-expanded-grid, a, button, input, select, textarea, label")) {
          return;
        }
        if (lockedCard === card) {
          lockedCard = null;
          setActiveCard(null);
          return;
        }
        lockedCard = card;
        setActiveCard(card);
      });
    });
  }

  function formatExactTimestamp(isoValue) {
    if (!isoValue) {
      return {
        local: "Capture time unavailable",
        utc: "",
      };
    }

    var date = new Date(isoValue);
    if (Number.isNaN(date.getTime())) {
      return {
        local: String(isoValue),
        utc: "",
      };
    }

    var local = date.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZoneName: "short",
    });

    var utc = date.toISOString().replace("T", " ").replace("Z", " UTC");
    return { local: local, utc: utc };
  }

  function renderGallery(capturedScreenshots) {
    if (!galleryGrid) return;
    galleryGrid.innerHTML = "";

    if (!capturedScreenshots.length) {
      var emptyNode = document.createElement("div");
      emptyNode.className = "reports-gallery-empty";
      emptyNode.textContent = "No screenshots captured for this candidate yet.";
      galleryGrid.appendChild(emptyNode);
      return;
    }

    var fragment = document.createDocumentFragment();
    capturedScreenshots.forEach(function (shot) {
      var article = document.createElement("article");
      article.className = "reports-shot";

      var link = document.createElement("a");
      link.className = "reports-shot-link";
      link.href = "/reports/proctoring/screenshot/" + encodeURIComponent(String(shot.id || ""));
      link.target = "_blank";
      link.rel = "noopener";

      var img = document.createElement("img");
      img.loading = "lazy";
      img.src = link.href;
      img.alt = "Screenshot " + String(shot.id || "");
      link.appendChild(img);

      var body = document.createElement("div");
      body.className = "reports-shot-body";

      var ts = formatExactTimestamp(shot.captured_at);
      var timeLocal = document.createElement("div");
      timeLocal.className = "reports-shot-time";
      timeLocal.textContent = ts.local;
      body.appendChild(timeLocal);

      if (ts.utc) {
        var timeUtc = document.createElement("div");
        timeUtc.className = "reports-shot-time-utc";
        timeUtc.textContent = ts.utc;
        body.appendChild(timeUtc);
      }

      var meta = document.createElement("div");
      meta.className = "reports-shot-meta";
      var roundLabel = shot.round_label || shot.round_key || "Round";
      var eventType = shot.event_type || "capture";
      var source = shot.source || "system";
      meta.textContent = roundLabel + " | " + eventType + " | " + source;
      body.appendChild(meta);

      article.appendChild(link);
      article.appendChild(body);
      fragment.appendChild(article);
    });

    galleryGrid.appendChild(fragment);
  }

  function openGallery(context) {
    context = context || {};
    var scopeKey = String(context.testSessionId || context.candidateKey || context.email || "").trim();
    if (!galleryModal || !galleryMeta || !galleryGrid || !galleryTitle || !scopeKey) {
      return;
    }

    activeGalleryScopeKey = scopeKey;
    galleryTitle.textContent = "Proctoring Screenshots - " + (context.name || context.email || "Candidate");
    galleryMeta.textContent = "Loading screenshots...";
    galleryGrid.innerHTML = '<div class="reports-gallery-empty">Loading screenshots...</div>';
    galleryModal.classList.add("active");
    galleryModal.setAttribute("aria-hidden", "false");
    syncBodyModalState();

    fetchJson(buildScopedGalleryUrl(context), {
      credentials: "same-origin",
    })
      .then(function (payload) {
        if (activeGalleryScopeKey !== scopeKey) {
          return;
        }
        var screenshots = Array.isArray(payload && payload.screenshots) ? payload.screenshots : [];
        galleryMeta.textContent = screenshots.length + " screenshot(s) found";
        renderGallery(screenshots);
      })
      .catch(function (error) {
        galleryMeta.textContent = "Unable to load screenshots";
        galleryGrid.innerHTML = '<div class="reports-gallery-empty">Failed to load screenshots.</div>';
        if (typeof showToast === "function") {
          showToast(error.message || "Failed to load screenshots", "danger");
        }
      });
  }

  function closeGallery() {
    if (!galleryModal) return;
    activeGalleryScopeKey = "";
    galleryModal.classList.remove("active");
    galleryModal.setAttribute("aria-hidden", "true");
    syncBodyModalState();
  }

  function buildConsolidatedScopeParams() {
    var params = new URLSearchParams();
    if (consolidatedRoleSelect && consolidatedRoleSelect.value) {
      params.set("role", consolidatedRoleSelect.value);
    }
    if (consolidatedPeriodSelect && consolidatedPeriodSelect.value) {
      params.set("filter", consolidatedPeriodSelect.value);
    }
    if (consolidatedDateInput && consolidatedDateInput.value) {
      params.set("date", consolidatedDateInput.value);
    }
    params.set("offset", "0");
    return params;
  }

  function buildConsolidatedRequestPayload() {
    return {
      role: consolidatedRoleSelect ? consolidatedRoleSelect.value : "",
      filter: consolidatedPeriodSelect ? consolidatedPeriodSelect.value : "today",
      date: consolidatedDateInput ? consolidatedDateInput.value : "",
      offset: "0",
      q: "",
      candidate_keys: getSelectedConsolidatedCandidateKeys(),
    };
  }

  function syncConsolidatedDateFilterVisibility() {
    if (!consolidatedPeriodSelect || !consolidatedDateInput) return;
    var isSpecificDate = consolidatedPeriodSelect.value === "date";
    consolidatedDateInput.classList.toggle("is-hidden", !isSpecificDate);
    if (!isSpecificDate) {
      consolidatedDateInput.value = "";
    }
  }

  function syncConsolidatedFiltersFromPage() {
    if (consolidatedRoleSelect && roleSelect) {
      consolidatedRoleSelect.value = roleSelect.value || "All Roles";
    }
    if (consolidatedPeriodSelect && periodSelect) {
      consolidatedPeriodSelect.value = periodSelect.value || "today";
    }
    if (consolidatedDateInput && dateInput) {
      consolidatedDateInput.value = dateInput.value || "";
    }
    syncConsolidatedDateFilterVisibility();
  }

  function getSelectedConsolidatedCandidateKeys() {
    var selected = [];
    consolidatedState.candidates.forEach(function (candidate) {
      var candidateKey = candidateSelectionKey(candidate);
      if (candidateKey && consolidatedState.selectedCandidateKeys[candidateKey]) {
        selected.push(candidateKey);
      }
    });
    return selected;
  }

  function resetConsolidatedOutput(message) {
    consolidatedState.rawSummary = "";
    consolidatedState.summaryMeta = null;
    if (consolidatedContent) {
      consolidatedContent.classList.remove("is-visible");
      consolidatedContent.innerHTML = "";
    }
    if (consolidatedLoading) {
      consolidatedLoading.style.display = "none";
    }
    if (consolidatedPlaceholder) {
      consolidatedPlaceholder.textContent = message || "Select candidates and click Generate Summary.";
      consolidatedPlaceholder.style.display = "flex";
    }
    updateConsolidatedFooterState();
  }

  function setConsolidatedLoadingState(isLoading, message) {
    consolidatedState.isGenerating = Boolean(isLoading);
    if (consolidatedLoading) {
      consolidatedLoading.textContent = message || "Building a consolidated summary...";
      consolidatedLoading.style.display = isLoading ? "flex" : "none";
    }
    if (consolidatedPlaceholder) {
      consolidatedPlaceholder.style.display = isLoading ? "none" : consolidatedPlaceholder.style.display;
    }
    if (consolidatedContent && isLoading) {
      consolidatedContent.classList.remove("is-visible");
      consolidatedContent.innerHTML = "";
    }
    updateConsolidatedFooterState();
  }

  function getVerdictBadgeClass(verdict) {
    var normalized = String(verdict || "").toLowerCase();
    if (normalized === "rejected") return "verdict-rejected";
    if (normalized === "selected") return "verdict-selected";
    if (normalized === "in progress") return "verdict-progress";
    return "verdict-pending";
  }

  function stripSummaryFormatting(value) {
    return String(value || "")
      .replace(/^#{1,6}\s*/, "")
      .replace(/\*\*/g, "")
      .trim();
  }

  function ensureSummaryList(container, ordered) {
    var last = container.lastElementChild;
    if (last && last.tagName === (ordered ? "OL" : "UL")) {
      return last;
    }
    var list = document.createElement(ordered ? "ol" : "ul");
    list.className = "consolidated-summary-list";
    container.appendChild(list);
    return list;
  }

  function renderConsolidatedSummary(summaryText) {
    if (!consolidatedContent || !consolidatedPlaceholder) return;

    consolidatedState.rawSummary = String(summaryText || "").trim();
    consolidatedContent.innerHTML = "";
    consolidatedContent.classList.add("is-visible");
    consolidatedPlaceholder.style.display = "none";
    if (consolidatedLoading) {
      consolidatedLoading.style.display = "none";
    }

    var wrapper = document.createElement("div");
    wrapper.className = "consolidated-summary-block";
    var lines = consolidatedState.rawSummary.split(/\r?\n/);

    lines.forEach(function (rawLine) {
      var trimmed = String(rawLine || "").trim();
      if (!trimmed) {
        return;
      }

      var plain = stripSummaryFormatting(trimmed);
      var lowered = plain.toLowerCase();

      if (lowered === "consolidated interview feedback") {
        var title = document.createElement("h3");
        title.className = "consolidated-summary-title";
        title.textContent = plain;
        wrapper.appendChild(title);
        return;
      }

      if (
        lowered === "overall outcome" ||
        lowered === "key observations" ||
        lowered === "overall assessment & recommendations" ||
        lowered === "overall assessment and recommendations"
      ) {
        var heading = document.createElement("h4");
        heading.className = "consolidated-summary-section";
        heading.textContent = plain;
        wrapper.appendChild(heading);
        return;
      }

      if (/^\d+\.\s+/.test(trimmed)) {
        var orderedList = ensureSummaryList(wrapper, true);
        var orderedItem = document.createElement("li");
        orderedItem.textContent = stripSummaryFormatting(trimmed.replace(/^\d+\.\s+/, ""));
        orderedList.appendChild(orderedItem);
        return;
      }

      if (/^[-*\u2022]\s+/.test(trimmed)) {
        var bulletList = ensureSummaryList(wrapper, false);
        var bulletItem = document.createElement("li");
        bulletItem.textContent = stripSummaryFormatting(trimmed.replace(/^[-*\u2022]\s+/, ""));
        bulletList.appendChild(bulletItem);
        return;
      }

      var paragraph = document.createElement("p");
      paragraph.className = "consolidated-summary-paragraph";
      paragraph.textContent = plain;
      wrapper.appendChild(paragraph);
    });

    consolidatedContent.appendChild(wrapper);
    updateConsolidatedFooterState();
  }

  function populateConsolidatedBatchOptions(batchOptions) {
    if (!consolidatedBatchSelect) return;
    consolidatedBatchSelect.innerHTML = "";

    var defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = "All Batches";
    consolidatedBatchSelect.appendChild(defaultOption);

    (batchOptions || []).forEach(function (item) {
      var option = document.createElement("option");
      option.value = String(item && item.value ? item.value : "");
      var count = Number(item && item.count ? item.count : 0);
      option.textContent = String(item && item.label ? item.label : "No Batch") + (count ? " (" + count + ")" : "");
      consolidatedBatchSelect.appendChild(option);
    });

    if (batchOptions && batchOptions.length === 1) {
      consolidatedBatchSelect.value = String(batchOptions[0].value || "");
    } else {
      consolidatedBatchSelect.value = "";
    }
  }

  function getVisibleConsolidatedCandidates() {
    var batchValue = consolidatedBatchSelect ? String(consolidatedBatchSelect.value || "") : "";
    var verdictValue = consolidatedVerdictFilter ? String(consolidatedVerdictFilter.value || "").toLowerCase() : "";
    var query = consolidatedCandidateSearch ? consolidatedCandidateSearch.value.trim().toLowerCase() : "";

    return consolidatedState.candidates.filter(function (candidate) {
      var batchId = String(candidate.batch_id || "");
      var verdict = String(candidate.overall_verdict || "").toLowerCase();
      var haystack = [
        String(candidate.name || ""),
        String(candidate.email || ""),
        String(candidate.role || ""),
        batchId,
      ].join(" ").toLowerCase();

      if (batchValue !== "" && batchId !== batchValue) {
        return false;
      }
      if (verdictValue && verdict !== verdictValue) {
        return false;
      }
      if (query && haystack.indexOf(query) === -1) {
        return false;
      }
      return true;
    });
  }

  function updateConsolidatedScopeCard() {
    var scope = consolidatedState.scope || {};
    var roleLabel = scope.role || (consolidatedRoleSelect ? consolidatedRoleSelect.value : "All Roles") || "All Roles";
    var periodLabel = scope.period_label || "Current Scope";

    if (consolidatedRoleValue) {
      consolidatedRoleValue.textContent = roleLabel;
    }
    if (consolidatedPeriodValue) {
      consolidatedPeriodValue.textContent = periodLabel;
    }
    if (consolidatedBatchValue) {
      var batchOption = consolidatedBatchSelect && consolidatedBatchSelect.selectedOptions && consolidatedBatchSelect.selectedOptions[0];
      consolidatedBatchValue.textContent = batchOption ? batchOption.textContent : "All Batches";
    }
    if (consolidatedScope) {
      var candidateCount = Number(scope.filtered_total_candidates || consolidatedState.candidates.length || 0);
      var scopeBits = [roleLabel, periodLabel, candidateCount + " candidate(s)"];
      consolidatedScope.textContent = scopeBits.join(" | ");
    }
    if (consolidatedResultsMeta) {
      var selectedInfo = "Load candidates to preview the filtered result list.";
      if (consolidatedState.scope && consolidatedState.candidates.length) {
        selectedInfo = consolidatedState.candidates.length + " candidate(s) loaded for verification. Names are listed below.";
      } else if (consolidatedState.scope && !consolidatedState.isLoadingCandidates) {
        selectedInfo = "No candidates matched the selected role/date filters.";
      }
      consolidatedResultsMeta.textContent = selectedInfo;
    }
  }

  function updateConsolidatedFooterState() {
    var selectedCount = getSelectedConsolidatedCandidateKeys().length;
    var visibleCount = consolidatedState.visibleCandidates.length;

    if (consolidatedSelectionMeta) {
      consolidatedSelectionMeta.textContent = selectedCount + " selected of " + visibleCount + " visible";
    }
    if (consolidatedGenerateBtn) {
      consolidatedGenerateBtn.disabled = consolidatedState.isLoadingCandidates || consolidatedState.isGenerating || selectedCount < 1;
    }
    if (consolidatedCopyBtn) {
      consolidatedCopyBtn.disabled = !consolidatedState.rawSummary || consolidatedState.isGenerating;
    }
    if (consolidatedDownloadBtn) {
      consolidatedDownloadBtn.disabled = !consolidatedState.rawSummary || consolidatedState.isGenerating || consolidatedState.isDownloading;
    }
  }

  function renderConsolidatedLoadedPreview(candidates) {
    if (!consolidatedLoadedPreview) return;
    consolidatedLoadedPreview.innerHTML = "";

    var items = Array.isArray(candidates) ? candidates : [];
    if (!items.length) {
      consolidatedLoadedPreview.innerHTML = '<div class="consolidated-loaded-empty">No candidate names to preview for the current filters.</div>';
      return;
    }

    var fragment = document.createDocumentFragment();
    items.forEach(function (candidate) {
      var pill = document.createElement("span");
      pill.className = "consolidated-loaded-pill";
      pill.textContent = candidate.name || candidate.email || "Candidate";
      fragment.appendChild(pill);
    });
    consolidatedLoadedPreview.appendChild(fragment);
  }

  function renderConsolidatedCandidateList() {
    if (!consolidatedCandidateList) return;

    var visibleCandidates = getVisibleConsolidatedCandidates();
    consolidatedState.visibleCandidates = visibleCandidates;
    updateConsolidatedScopeCard();
    renderConsolidatedLoadedPreview(visibleCandidates);
    consolidatedCandidateList.innerHTML = "";

    if (consolidatedState.isLoadingCandidates) {
      consolidatedCandidateList.innerHTML = '<div class="consolidated-empty-state">Loading candidates...</div>';
      updateConsolidatedFooterState();
      return;
    }

    if (!visibleCandidates.length) {
      consolidatedCandidateList.innerHTML = '<div class="consolidated-empty-state">No candidates match the current batch, verdict, or search filter.</div>';
      updateConsolidatedFooterState();
      return;
    }

    var fragment = document.createDocumentFragment();
    visibleCandidates.forEach(function (candidate) {
      var email = String(candidate.email || "");
      var candidateKey = candidateSelectionKey(candidate);
      var row = document.createElement("label");
      row.className = "consolidated-candidate-row";
      row.setAttribute("data-candidate-key", candidateKey);

      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = Boolean(candidateKey && consolidatedState.selectedCandidateKeys[candidateKey]);
      checkbox.setAttribute("data-consolidated-candidate-key", candidateKey);

      var main = document.createElement("div");
      main.className = "consolidated-candidate-main";

      var name = document.createElement("div");
      name.className = "consolidated-candidate-name";
      name.textContent = candidate.name || email || "Candidate";
      main.appendChild(name);

      var emailText = document.createElement("div");
      emailText.className = "consolidated-candidate-email";
      var emailLine = candidate.email || "";
      if (candidate.batch_id) {
        emailLine += " | " + candidate.batch_id;
      }
      emailText.textContent = emailLine || "Email unavailable";
      main.appendChild(emailText);

      var meta = document.createElement("div");
      meta.className = "consolidated-candidate-meta";

      var score = document.createElement("span");
      score.className = "consolidated-badge score";
      score.textContent = Math.round(Number(candidate.overall_score || 0)) + "%";
      meta.appendChild(score);

      var verdict = document.createElement("span");
      verdict.className = "consolidated-badge " + getVerdictBadgeClass(candidate.overall_verdict);
      verdict.textContent = candidate.overall_verdict || "Pending";
      meta.appendChild(verdict);

      row.appendChild(checkbox);
      row.appendChild(main);
      row.appendChild(meta);
      fragment.appendChild(row);
    });

    consolidatedCandidateList.appendChild(fragment);
    updateConsolidatedFooterState();
  }

  function loadConsolidatedCandidates() {
    if (
      consolidatedPeriodSelect &&
      consolidatedPeriodSelect.value === "date" &&
      consolidatedDateInput &&
      !consolidatedDateInput.value
    ) {
      if (typeof showToast === "function") {
        showToast("Choose a specific date to load candidates", "warning");
      }
      if (typeof consolidatedDateInput.showPicker === "function") {
        consolidatedDateInput.showPicker();
      } else {
        consolidatedDateInput.focus();
      }
      return;
    }

    consolidatedState.isLoadingCandidates = true;
    consolidatedState.candidates = [];
    consolidatedState.selectedCandidateKeys = {};
    consolidatedState.visibleCandidates = [];
    consolidatedState.scope = null;
    resetConsolidatedOutput("Select candidates and click Generate Summary.");
    renderConsolidatedCandidateList();

    fetchJson("/reports/consolidated/candidates?" + buildConsolidatedScopeParams().toString(), {
      credentials: "same-origin",
    })
      .then(function (payload) {
        consolidatedState.scope = payload && payload.scope ? payload.scope : {};
        consolidatedState.candidates = Array.isArray(payload && payload.candidates) ? payload.candidates : [];
        consolidatedState.selectedCandidateKeys = {};
        consolidatedState.candidates.forEach(function (candidate) {
          var candidateKey = candidateSelectionKey(candidate);
          if (candidateKey) {
            consolidatedState.selectedCandidateKeys[candidateKey] = true;
          }
        });
        populateConsolidatedBatchOptions(Array.isArray(payload && payload.batch_options) ? payload.batch_options : []);
        resetConsolidatedOutput("Select candidates and click Generate Summary.");
      })
      .catch(function (error) {
        consolidatedState.scope = null;
        consolidatedState.candidates = [];
        consolidatedState.selectedCandidateKeys = {};
        if (typeof showToast === "function") {
          showToast(error.message || "Failed to load candidates", "danger");
        }
      })
      .finally(function () {
        consolidatedState.isLoadingCandidates = false;
        renderConsolidatedCandidateList();
      });
  }

  function openConsolidatedModal() {
    if (!consolidatedModal) return;

    closeGallery();
    syncConsolidatedFiltersFromPage();
    if (consolidatedVerdictFilter) {
      consolidatedVerdictFilter.value = "";
    }
    if (consolidatedCandidateSearch) {
      consolidatedCandidateSearch.value = "";
    }
    consolidatedModal.classList.add("active");
    consolidatedModal.setAttribute("aria-hidden", "false");
    syncBodyModalState();
    loadConsolidatedCandidates();
  }

  function closeConsolidatedModal() {
    if (!consolidatedModal) return;
    consolidatedModal.classList.remove("active");
    consolidatedModal.setAttribute("aria-hidden", "true");
    syncBodyModalState();
  }

  function applyConsolidatedBulkSelection(mode) {
    var visibleCandidates = getVisibleConsolidatedCandidates();
    if (mode === "none") {
      consolidatedState.selectedCandidateKeys = {};
      renderConsolidatedCandidateList();
      return;
    }

    if (mode === "all") {
      visibleCandidates.forEach(function (candidate) {
        var candidateKey = candidateSelectionKey(candidate);
        if (candidateKey) {
          consolidatedState.selectedCandidateKeys[candidateKey] = true;
        }
      });
      renderConsolidatedCandidateList();
      return;
    }

    consolidatedState.selectedCandidateKeys = {};
    visibleCandidates.forEach(function (candidate) {
      var candidateKey = candidateSelectionKey(candidate);
      if (!candidateKey) return;
      if (mode === "rejected" && String(candidate.overall_verdict || "") === "Rejected") {
        consolidatedState.selectedCandidateKeys[candidateKey] = true;
      }
      if (mode === "attempted" && Number(candidate.attempted_rounds || 0) > 0) {
        consolidatedState.selectedCandidateKeys[candidateKey] = true;
      }
    });
    renderConsolidatedCandidateList();
  }

  function generateConsolidatedSummary() {
    var selectedCandidateKeys = getSelectedConsolidatedCandidateKeys();
    if (!selectedCandidateKeys.length) {
      if (typeof showToast === "function") {
        showToast("Select at least one candidate", "warning");
      }
      return;
    }

    setConsolidatedLoadingState(true, "Building a consolidated summary...");
    fetchJson("/reports/consolidated-summary", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(buildConsolidatedRequestPayload()),
    })
      .then(function (payload) {
        if (!payload || !payload.success) {
          throw new Error((payload && payload.error) || "Failed to generate consolidated summary");
        }
        consolidatedState.summaryMeta = payload && payload.meta ? payload.meta : null;
        renderConsolidatedSummary(payload.summary || "");
        if (typeof showToast === "function") {
          showToast("Consolidated summary generated", "success");
        }
      })
      .catch(function (error) {
        resetConsolidatedOutput("Select candidates and click Generate Summary.");
        if (typeof showToast === "function") {
          showToast(error.message || "Failed to generate consolidated summary", "danger");
        }
      })
      .finally(function () {
        consolidatedState.isGenerating = false;
        if (consolidatedLoading) {
          consolidatedLoading.style.display = "none";
        }
        updateConsolidatedFooterState();
      });
  }

  function downloadConsolidatedSummaryPdf() {
    var text = String(consolidatedState.rawSummary || "").trim();
    if (!text) {
      return;
    }

    consolidatedState.isDownloading = true;
    updateConsolidatedFooterState();

    fetchJson("/reports/consolidated-summary/pdf", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        summary: text,
        meta: consolidatedState.summaryMeta || {},
      }),
    })
      .then(function (payload) {
        if (!payload || !payload.success || !payload.download_url) {
          throw new Error((payload && payload.error) || "Failed to generate summary PDF");
        }
        window.open(payload.download_url, "_blank");
        if (typeof showToast === "function") {
          showToast("Summary PDF is ready", "success");
        }
      })
      .catch(function (error) {
        if (typeof showToast === "function") {
          showToast(error.message || "Failed to generate summary PDF", "danger");
        }
      })
      .finally(function () {
        consolidatedState.isDownloading = false;
        updateConsolidatedFooterState();
      });
  }

  function copyConsolidatedSummary() {
    var text = String(consolidatedState.rawSummary || "").trim();
    if (!text) return;

    function onCopied() {
      if (typeof showToast === "function") {
        showToast("Consolidated summary copied", "success");
      }
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(onCopied).catch(function () {
        var textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "readonly");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
          document.execCommand("copy");
          onCopied();
        } finally {
          document.body.removeChild(textarea);
        }
      });
      return;
    }

    var fallbackTextarea = document.createElement("textarea");
    fallbackTextarea.value = text;
    fallbackTextarea.setAttribute("readonly", "readonly");
    fallbackTextarea.style.position = "fixed";
    fallbackTextarea.style.opacity = "0";
    document.body.appendChild(fallbackTextarea);
    fallbackTextarea.focus();
    fallbackTextarea.select();
    try {
      document.execCommand("copy");
      onCopied();
    } finally {
      document.body.removeChild(fallbackTextarea);
    }
  }

  function initializeReportActionState() {
    var cards = Array.prototype.slice.call(document.querySelectorAll("[data-candidate-card]"));
    cards.forEach(function (card) {
      var hasReport = String(card.getAttribute("data-has-report") || "0") === "1";
      var links = buildReportLinks({}, card.getAttribute("data-report-filename") || "");
      renderRowActions(card, hasReport, links);
      renderActionHub(card, hasReport, links);
    });
  }

  if (roleSelect && filterForm) {
    roleSelect.addEventListener("change", function () {
      submitFilters(true);
    });
  }

  if (periodSelect && filterForm) {
    syncDateFilterVisibility();
    periodSelect.addEventListener("change", function () {
      syncDateFilterVisibility();
      if (periodSelect.value === "date") {
        if (!dateInput) return;
        if (typeof dateInput.showPicker === "function") {
          dateInput.showPicker();
        } else {
          dateInput.focus();
          dateInput.click();
        }
        if (dateInput.value) {
          submitFilters(true);
        }
        return;
      }
      submitFilters(true);
    });
  }

  if (dateInput && filterForm) {
    dateInput.addEventListener("change", function () {
      if (periodSelect && periodSelect.value !== "date") {
        return;
      }
      submitFilters(true);
    });
  }

  if (searchInput && filterForm) {
    searchInput.addEventListener("input", function () {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(function () {
        submitFilters(true);
      }, 360);
    });

    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        window.clearTimeout(searchTimer);
        submitFilters(true);
      }
    });
  }

  if (perPageSelect && perPageInput && filterForm) {
    perPageSelect.addEventListener("change", function () {
      perPageInput.value = perPageSelect.value;
      submitFilters(false);
    });
  }

  if (consolidatedTrigger) {
    consolidatedTrigger.addEventListener("click", function () {
      openConsolidatedModal();
    });
  }

  if (consolidatedPreviewBtn) {
    consolidatedPreviewBtn.addEventListener("click", function () {
      loadConsolidatedCandidates();
    });
  }

  if (consolidatedPeriodSelect) {
    syncConsolidatedDateFilterVisibility();
    consolidatedPeriodSelect.addEventListener("change", function () {
      syncConsolidatedDateFilterVisibility();
    });
  }

  if (consolidatedDateInput) {
    consolidatedDateInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        loadConsolidatedCandidates();
      }
    });
  }

  if (consolidatedBatchSelect) {
    consolidatedBatchSelect.addEventListener("change", function () {
      renderConsolidatedCandidateList();
    });
  }

  if (consolidatedVerdictFilter) {
    consolidatedVerdictFilter.addEventListener("change", function () {
      renderConsolidatedCandidateList();
    });
  }

  if (consolidatedCandidateSearch) {
    consolidatedCandidateSearch.addEventListener("input", function () {
      renderConsolidatedCandidateList();
    });
  }

  if (consolidatedCandidateList) {
    consolidatedCandidateList.addEventListener("change", function (event) {
      var checkbox = event.target.closest("[data-consolidated-candidate-key]");
      if (!checkbox) return;
      var candidateKey = String(checkbox.getAttribute("data-consolidated-candidate-key") || "");
      if (!candidateKey) return;
      consolidatedState.selectedCandidateKeys[candidateKey] = Boolean(checkbox.checked);
      updateConsolidatedFooterState();
    });
  }

  if (consolidatedGenerateBtn) {
    consolidatedGenerateBtn.addEventListener("click", function () {
      generateConsolidatedSummary();
    });
  }

  if (consolidatedDownloadBtn) {
    consolidatedDownloadBtn.addEventListener("click", function () {
      downloadConsolidatedSummaryPdf();
    });
  }

  if (consolidatedCopyBtn) {
    consolidatedCopyBtn.addEventListener("click", function () {
      copyConsolidatedSummary();
    });
  }

  document.addEventListener("click", function (event) {
    var generateBtn = event.target.closest(".js-generate-report");
    if (generateBtn) {
      event.preventDefault();
      var ownerCard = generateBtn.closest("[data-candidate-card]");
      generateReport(getCardCandidateContext(ownerCard, generateBtn), generateBtn, ownerCard);
      return;
    }

    var galleryBtn = event.target.closest(".js-open-gallery");
    if (galleryBtn) {
      event.preventDefault();
      openGallery(getCardCandidateContext(galleryBtn.closest("[data-candidate-card]"), galleryBtn));
      return;
    }

    if (event.target.closest(".js-close-gallery")) {
      event.preventDefault();
      closeGallery();
      return;
    }

    if (event.target.closest(".js-close-consolidated")) {
      event.preventDefault();
      closeConsolidatedModal();
      return;
    }

    var selectModeButton = event.target.closest("[data-select-mode]");
    if (selectModeButton) {
      event.preventDefault();
      applyConsolidatedBulkSelection(selectModeButton.getAttribute("data-select-mode"));
    }
  });

  if (galleryModal) {
    galleryModal.addEventListener("click", function (event) {
      if (event.target === galleryModal) {
        closeGallery();
      }
    });
  }

  if (consolidatedModal) {
    consolidatedModal.addEventListener("click", function (event) {
      if (event.target === consolidatedModal) {
        closeConsolidatedModal();
      }
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeGallery();
      closeConsolidatedModal();
    }
  });

  initializeReportActionState();
  initCardExpansion();
})();
