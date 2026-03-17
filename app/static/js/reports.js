(function () {
  const searchInput = document.getElementById("searchInput");
  const searchResults = document.getElementById("searchResults");
  const searchResultsList = document.getElementById("searchResultsList");
  const proctoringModal = document.getElementById("proctoringModal");
  const proctoringGallery = document.getElementById("proctoringGallery");
  const proctoringGalleryMeta = document.getElementById("proctoringGalleryMeta");
  const proctoringModalTitle = document.getElementById("proctoringModalTitle");
  const proctoringViewer = document.getElementById("proctoringViewer");
  const proctoringViewerImage = document.getElementById("proctoringViewerImage");
  const proctoringViewerMeta = document.getElementById("proctoringViewerMeta");
  const proctoringPrevBtn = document.getElementById("proctoringPrevBtn");
  const proctoringNextBtn = document.getElementById("proctoringNextBtn");

  let proctoringShots = [];
  let proctoringShotIndex = -1;
  let searchTimer = null;

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatGalleryTimestamp(ts) {
    if (!ts) return "";
    try {
      const date = new Date(ts);
      if (Number.isNaN(date.getTime())) return ts;
      return date.toLocaleString();
    } catch (_) {
      return ts;
    }
  }

  function fetchJson(url, options) {
    const opts = Object.assign({ credentials: "same-origin" }, options || {});
    return fetch(url, opts).then(async (response) => {
      const contentType = (response.headers.get("content-type") || "").toLowerCase();
      const isJson = contentType.includes("application/json");
      if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try {
          if (isJson) {
            const data = await response.json();
            message = data.error || data.message || message;
          } else {
            const text = await response.text();
            if (text) message = text;
          }
        } catch (_) {
          // ignore parse errors
        }
        throw new Error(message);
      }
      if (isJson) {
        return response.json();
      }
      const text = await response.text();
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (_) {
        throw new Error("Unexpected response.");
      }
    });
  }

  function searchCandidates(forcedQuery, showWarning) {
    if (!searchInput || !searchResults || !searchResultsList) return;
    const q = (forcedQuery !== undefined ? forcedQuery : searchInput.value).trim();
    if (q.length < 2) {
      if (showWarning && typeof showToast === "function") {
        showToast("Enter at least 2 characters", "warning");
      }
      searchResults.classList.remove("active");
      searchResultsList.innerHTML = "";
      return;
    }
    searchResultsList.innerHTML =
      '<div class="text-center py-3"><div class="spinner-border spinner-border-sm" style="color:var(--az-primary);"></div><span class="ms-2 text-muted">Searching...</span></div>';
    searchResults.classList.add("active");
    fetchJson("/reports/search?q=" + encodeURIComponent(q))
      .then((data) => {
        const items = (data && data.candidates) ? data.candidates : [];
        if (!items.length) {
          searchResultsList.innerHTML =
            '<div class="text-center py-3 text-muted"><i class="fas fa-search me-1"></i>No candidates found</div>';
          return;
        }
        let html = "";
        items.forEach((c, i) => {
          const aid = "sr-" + i;
          const safeName = escapeHtml(c.name || "");
          const safeEmail = escapeHtml(c.email || "");
          const safeRole = escapeHtml(c.role || "N/A");
          const hasReport = !!(c.has_report && c.report_filename);
          let actions = "";
          if (hasReport) {
            const viewUrl = "/reports/view/" + encodeURIComponent(c.report_filename);
            const downloadUrl = "/reports/download-file/" + encodeURIComponent(c.report_filename);
            actions += '<a href="' + viewUrl + '" target="_blank" class="icon-btn btn-view" title="View"><i class="fas fa-eye"></i></a>';
            actions += '<a href="' + downloadUrl + '" class="icon-btn btn-dl" title="Download"><i class="fas fa-download"></i></a>';
            actions += '<button class="icon-btn btn-regen js-generate-report" data-email="' + safeEmail + '" data-container="' + aid + '" title="Regenerate"><i class="fas fa-redo"></i></button>';
          } else {
            actions += '<button class="icon-btn btn-gen js-generate-report" data-email="' + safeEmail + '" data-container="' + aid + '" title="Generate Report"><i class="fas fa-file-pdf"></i></button>';
          }
          actions += '<button class="icon-btn btn-gallery js-open-proctoring" data-email="' + safeEmail + '" title="View Proctoring Screenshots"><i class="fas fa-images"></i></button>';
          html += '<div class="d-flex align-items-center justify-content-between p-2 border-bottom">';
          html += '<div><span style="font-weight:500; color:var(--az-slate-900);">' + safeName + '</span>';
          html += ' <span class="badge-role ms-1">' + safeRole + "</span>";
          html += '<div style="font-size:0.78rem;color:var(--az-slate-500);">' + safeEmail + "</div></div>";
          html += '<div class="report-actions" id="' + aid + '" data-email="' + safeEmail + '">';
          html += actions;
          html += "</div></div>";
        });
        searchResultsList.innerHTML = html;
      })
      .catch(() => {
        searchResultsList.innerHTML =
          '<div class="text-center py-3 text-danger"><i class="fas fa-exclamation-circle me-1"></i>Search failed</div>';
      });
  }

  function renderReportActions(email, containerId, payload) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const safeEmail = escapeHtml(email);
    if (payload && payload.success) {
      const viewUrl = payload.view_url || "#";
      const downloadUrl = payload.download_url || "#";
      container.innerHTML =
        '<a href="' + viewUrl + '" target="_blank" class="icon-btn btn-view" title="View"><i class="fas fa-eye"></i></a>' +
        '<a href="' + downloadUrl + '" class="icon-btn btn-dl" title="Download"><i class="fas fa-download"></i></a>' +
        '<button class="icon-btn btn-regen js-generate-report" data-email="' + safeEmail + '" data-container="' + containerId + '" title="Regenerate"><i class="fas fa-redo"></i></button>' +
        '<button class="icon-btn btn-gallery js-open-proctoring" data-email="' + safeEmail + '" title="View Proctoring Screenshots"><i class="fas fa-images"></i></button>';
      return;
    }
    const errorText = escapeHtml((payload && payload.error) ? payload.error : "Failed");
    container.innerHTML =
      '<span class="text-danger" style="font-size:0.75rem;"><i class="fas fa-exclamation-circle"></i> ' + errorText + "</span>" +
      ' <button class="icon-btn btn-regen js-generate-report" data-email="' + safeEmail + '" data-container="' + containerId + '"><i class="fas fa-redo"></i></button>' +
      ' <button class="icon-btn btn-gallery js-open-proctoring" data-email="' + safeEmail + '" title="View Proctoring Screenshots"><i class="fas fa-images"></i></button>';
  }

  function generateReport(email, containerId) {
    if (!email || !containerId) return;
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '<span class="icon-btn btn-loading"><i class="fas fa-spinner fa-spin"></i></span>';
    fetchJson("/reports/generate/" + encodeURIComponent(email))
      .then((data) => renderReportActions(email, containerId, data))
      .catch((err) => renderReportActions(email, containerId, { success: false, error: err.message || "Error" }));
  }

  function openProctoringGallery(email) {
    if (!email) return;
    if (proctoringModal) {
      proctoringModal.classList.add("active");
      proctoringModal.setAttribute("aria-hidden", "false");
    }
    if (proctoringModalTitle) {
      proctoringModalTitle.textContent = "Proctoring Screenshots - " + email;
    }
    if (proctoringGalleryMeta) {
      proctoringGalleryMeta.textContent = "Loading screenshots...";
    }
    if (proctoringGallery) {
      proctoringGallery.innerHTML = "";
    }
    proctoringShots = [];
    proctoringShotIndex = -1;

    fetchJson("/reports/proctoring/screenshots?email=" + encodeURIComponent(email))
      .then((data) => {
        const items = (data && data.screenshots) ? data.screenshots : [];
        if (!items.length) {
          if (proctoringGalleryMeta) proctoringGalleryMeta.textContent = "No proctoring screenshots found.";
          return;
        }
        proctoringShots = items.map((item, idx) => Object.assign({ __index: idx }, item));
        proctoringShotIndex = -1;
        if (proctoringGalleryMeta) {
          proctoringGalleryMeta.textContent = items.length + " screenshot(s) captured";
        }
        let html = "";
        proctoringShots.forEach((item) => {
          const meta = [];
          if (item.round_label) meta.push(escapeHtml(item.round_label));
          if (item.source) meta.push(escapeHtml(String(item.source).toUpperCase()));
          if (item.captured_at) meta.push(escapeHtml(formatGalleryTimestamp(item.captured_at)));
          html += '<div class="proctoring-shot">';
          html += '<img src="/reports/proctoring/screenshot/' + item.id + '" loading="lazy" alt="Proctoring screenshot" data-proctoring-index="' + item.__index + '">';
          html += '<div class="proctoring-shot-meta">' + meta.join(" | ") + "</div>";
          html += "</div>";
        });
        if (proctoringGallery) {
          proctoringGallery.innerHTML = html;
        }
      })
      .catch(() => {
        if (proctoringGalleryMeta) {
          proctoringGalleryMeta.textContent = "Failed to load screenshots. Please try again.";
        }
      });
  }

  function renderProctoringViewer() {
    if (proctoringShotIndex < 0 || proctoringShotIndex >= proctoringShots.length) return;
    const shot = proctoringShots[proctoringShotIndex];
    if (proctoringViewerImage) {
      proctoringViewerImage.src = "/reports/proctoring/screenshot/" + shot.id;
    }
    if (proctoringViewerMeta) {
      const parts = [];
      if (shot.round_label) parts.push(shot.round_label);
      if (shot.source) parts.push(String(shot.source).toUpperCase());
      if (shot.captured_at) parts.push(formatGalleryTimestamp(shot.captured_at));
      parts.push((proctoringShotIndex + 1) + " / " + proctoringShots.length);
      proctoringViewerMeta.textContent = parts.join(" | ");
    }
    if (proctoringPrevBtn) proctoringPrevBtn.disabled = proctoringShotIndex === 0;
    if (proctoringNextBtn) proctoringNextBtn.disabled = proctoringShotIndex === (proctoringShots.length - 1);
  }

  function openProctoringViewerByIndex(index) {
    if (!Array.isArray(proctoringShots) || proctoringShots.length === 0) return;
    const idx = Number(index);
    if (Number.isNaN(idx) || idx < 0 || idx >= proctoringShots.length) return;
    proctoringShotIndex = idx;
    renderProctoringViewer();
    if (proctoringViewer) {
      proctoringViewer.classList.add("active");
      proctoringViewer.setAttribute("aria-hidden", "false");
    }
  }

  function stepProctoringViewer(delta) {
    if (!proctoringShots.length) return;
    const next = proctoringShotIndex + delta;
    if (next < 0 || next >= proctoringShots.length) return;
    proctoringShotIndex = next;
    renderProctoringViewer();
  }

  function closeProctoringViewer() {
    if (!proctoringViewer) return;
    proctoringViewer.classList.remove("active");
    proctoringViewer.setAttribute("aria-hidden", "true");
  }

  function closeProctoringGallery() {
    if (!proctoringModal) return;
    proctoringModal.classList.remove("active");
    proctoringModal.setAttribute("aria-hidden", "true");
  }

  const searchBtn = document.getElementById("searchBtn");
  if (searchBtn && searchInput) {
    searchBtn.addEventListener("click", function () { searchCandidates(undefined, true); });
    searchInput.addEventListener("keyup", function (e) {
      if (e.key === "Enter") searchCandidates(undefined, true);
    });
    searchInput.addEventListener("input", function () {
      const q = searchInput.value.trim();
      window.clearTimeout(searchTimer);
      if (q.length < 2) {
        if (searchResults) searchResults.classList.remove("active");
        if (searchResultsList) searchResultsList.innerHTML = "";
        return;
      }
      searchTimer = window.setTimeout(function () {
        searchCandidates(q, false);
      }, 250);
    });
  }

  const clearBtn = document.getElementById("clearSearchBtn");
  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      if (searchInput) searchInput.value = "";
      if (searchResults) searchResults.classList.remove("active");
      if (searchResultsList) searchResultsList.innerHTML = "";
    });
  }

  document.addEventListener("click", function (event) {
    const generateBtn = event.target.closest(".js-generate-report");
    if (generateBtn) {
      event.preventDefault();
      generateReport(generateBtn.dataset.email, generateBtn.dataset.container);
      return;
    }

    const openBtn = event.target.closest(".js-open-proctoring");
    if (openBtn) {
      event.preventDefault();
      openProctoringGallery(openBtn.dataset.email);
      return;
    }

    const closeGalleryBtn = event.target.closest(".js-close-gallery");
    if (closeGalleryBtn) {
      event.preventDefault();
      closeProctoringGallery();
      return;
    }

    const closeViewerBtn = event.target.closest(".js-close-viewer");
    if (closeViewerBtn) {
      event.preventDefault();
      closeProctoringViewer();
      return;
    }

    const stepBtn = event.target.closest(".js-step-viewer");
    if (stepBtn) {
      event.preventDefault();
      const delta = Number(stepBtn.dataset.step || 0);
      if (delta) stepProctoringViewer(delta);
      return;
    }

    const shotImg = event.target.closest("[data-proctoring-index]");
    if (shotImg) {
      event.preventDefault();
      openProctoringViewerByIndex(shotImg.dataset.proctoringIndex);
    }
  });

  if (proctoringModal) {
    proctoringModal.addEventListener("click", function (e) {
      if (e.target === proctoringModal) {
        closeProctoringGallery();
      }
    });
  }

  if (proctoringViewer) {
    proctoringViewer.addEventListener("click", function (e) {
      if (e.target === proctoringViewer) {
        closeProctoringViewer();
      }
    });
  }

  document.addEventListener("keydown", function (e) {
    if (proctoringViewer && proctoringViewer.classList.contains("active")) {
      if (e.key === "ArrowRight") stepProctoringViewer(1);
      if (e.key === "ArrowLeft") stepProctoringViewer(-1);
      if (e.key === "Escape") {
        closeProctoringViewer();
        return;
      }
    }
    if (proctoringModal && proctoringModal.classList.contains("active") && e.key === "Escape") {
      closeProctoringGallery();
    }
  });

  window.AziroReports = {
    generateReport: generateReport,
    openProctoringGallery: openProctoringGallery,
  };
})();
