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

  var searchTimer = null;
  var activeGalleryEmail = "";

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
    if (config.email) {
      node.setAttribute("data-email", config.email);
    }
    if (config.name) {
      node.setAttribute("data-name", config.name);
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

    var email = String(card.getAttribute("data-candidate-email") || "");
    var name = String(card.getAttribute("data-candidate-name") || "");

    rowActions.innerHTML = "";

    rowActions.appendChild(makeActionElement({
      className: "row-action-btn gallery js-open-gallery",
      action: "view-screenshots",
      email: email,
      name: name,
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
        email: email,
        icon: '<i class="bi bi-arrow-repeat"></i>',
        label: "Regenerate Report",
        iconOnly: true,
      }));
      return;
    }

    rowActions.appendChild(makeActionElement({
      className: "row-action-btn generate js-generate-report",
      action: "generate-report",
      email: email,
      icon: '<i class="bi bi-file-earmark-pdf-fill"></i>',
      label: "Generate Report",
      iconOnly: true,
    }));
  }

  function renderActionHub(card, hasReport, links) {
    var actionGrid = card ? card.querySelector(".insight-actions") : null;
    if (!actionGrid) return;

    var email = String(card.getAttribute("data-candidate-email") || "");
    var name = String(card.getAttribute("data-candidate-name") || "");

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
        email: email,
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
      email: email,
      name: name,
      icon: '<i class="bi bi-images"></i>',
      label: "View Screenshots",
    }));

    actionGrid.appendChild(makeActionElement({
      className: "insight-action report-regenerate js-generate-report" + (hasReport ? "" : " disabled"),
      action: "regenerate-report",
      email: email,
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

  function generateReport(email, button, card) {
    if (!email) return;

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

    fetchJson("/reports/generate/" + encodeURIComponent(email), { credentials: "same-origin" })
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

  var HOVER_DELAY_MS = 40;
  var LIST_EXIT_DELAY_MS = 180;
  var activeCard = null;
  var lockedCard = null;
  var enterTimer = null;
  var leaveTimer = null;
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
    var reportsList = document.querySelector(".reports-list");

    cards.forEach(function (card) {
      card.classList.remove("is-active");
      clearOverlaySpacing(card);
    });
    setActiveCard(null);

    if (reportsList) {
      reportsList.addEventListener("mouseenter", function () {
        window.clearTimeout(leaveTimer);
      });

      reportsList.addEventListener("mouseleave", function () {
        if (lockedCard) {
          return;
        }
        window.clearTimeout(enterTimer);
        window.clearTimeout(leaveTimer);
        leaveTimer = window.setTimeout(function () {
          if (lockedCard) {
            return;
          }
          setActiveCard(null);
        }, LIST_EXIT_DELAY_MS);
      });
    }

    function isOverRowActions(card, event) {
      if (!card || !event) return false;
      var hitNode = event.target;
      if ((!hitNode || hitNode === card) && typeof document.elementFromPoint === "function") {
        hitNode = document.elementFromPoint(event.clientX, event.clientY);
      }
      return Boolean(hitNode && hitNode.closest && hitNode.closest(".row-actions"));
    }

    cards.forEach(function (card) {
      card.addEventListener("mouseenter", function (event) {
        if (lockedCard && lockedCard !== card) {
          return;
        }
        if (isOverRowActions(card, event)) {
          window.clearTimeout(enterTimer);
          return;
        }
        window.clearTimeout(leaveTimer);
        window.clearTimeout(enterTimer);
        enterTimer = window.setTimeout(function () {
          setActiveCard(card);
        }, HOVER_DELAY_MS);
      });

      card.addEventListener("mouseleave", function () {
        window.clearTimeout(enterTimer);
        if (lockedCard) {
          return;
        }
        if (!reportsList) {
          window.clearTimeout(leaveTimer);
          leaveTimer = window.setTimeout(function () {
            if (lockedCard) {
              return;
            }
            if (activeCard === card) {
              setActiveCard(null);
            }
          }, HOVER_DELAY_MS);
        }
      });

      card.addEventListener("focusin", function () {
        if (lockedCard && lockedCard !== card) {
          return;
        }
        window.clearTimeout(leaveTimer);
        window.clearTimeout(enterTimer);
        setActiveCard(card);
      });

      card.addEventListener("focusout", function (event) {
        var next = event.relatedTarget;
        if (next && card.contains(next)) {
          return;
        }
        if (lockedCard) {
          return;
        }
        if (activeCard === card) {
          setActiveCard(null);
        }
      });

      card.addEventListener("click", function (event) {
        if (event.target.closest(".row-actions, a, button, input, select, textarea, label")) {
          return;
        }
        window.clearTimeout(leaveTimer);
        window.clearTimeout(enterTimer);

        // Click toggles lock on this card.
        if (lockedCard === card) {
          lockedCard = null;
          setActiveCard(null);
          return;
        }
        lockedCard = card;
        setActiveCard(card);
      });

      var rowActions = card.querySelector(".row-actions");
      if (rowActions) {
        rowActions.addEventListener("mouseenter", function () {
          window.clearTimeout(enterTimer);
        });
      }
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

  function openGallery(email, candidateName) {
    if (!galleryModal || !galleryMeta || !galleryGrid || !galleryTitle || !email) {
      return;
    }

    activeGalleryEmail = String(email);
    galleryTitle.textContent = "Proctoring Screenshots - " + (candidateName || email);
    galleryMeta.textContent = "Loading screenshots...";
    galleryGrid.innerHTML = '<div class="reports-gallery-empty">Loading screenshots...</div>';
    galleryModal.classList.add("active");
    galleryModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";

    fetchJson("/reports/proctoring/screenshots?email=" + encodeURIComponent(email) + "&limit=300", {
      credentials: "same-origin",
    })
      .then(function (payload) {
        if (activeGalleryEmail !== String(email)) {
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
    activeGalleryEmail = "";
    galleryModal.classList.remove("active");
    galleryModal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
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

  document.addEventListener("click", function (event) {
    var generateBtn = event.target.closest(".js-generate-report");
    if (generateBtn) {
      event.preventDefault();
      var ownerCard = generateBtn.closest("[data-candidate-card]");
      generateReport(generateBtn.getAttribute("data-email"), generateBtn, ownerCard);
      return;
    }

    var galleryBtn = event.target.closest(".js-open-gallery");
    if (galleryBtn) {
      event.preventDefault();
      openGallery(
        galleryBtn.getAttribute("data-email"),
        galleryBtn.getAttribute("data-name")
      );
      return;
    }

    if (event.target.closest(".js-close-gallery")) {
      event.preventDefault();
      closeGallery();
    }
  });

  if (galleryModal) {
    galleryModal.addEventListener("click", function (event) {
      if (event.target === galleryModal) {
        closeGallery();
      }
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeGallery();
    }
  });

  initializeReportActionState();
  initCardExpansion();
})();
