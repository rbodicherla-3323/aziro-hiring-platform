(function () {
  const globalSearchInput = document.getElementById("globalSearchInput");
  const globalSearchSuggestions = document.getElementById("globalSearchSuggestions");
  if (!globalSearchInput || !globalSearchSuggestions) {
    return;
  }

  function normalizeForSearch(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9+.#@_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function getQueryTokens(value) {
    return normalizeForSearch(value).split(" ").filter(Boolean);
  }

  function buildGlobalSearchPool() {
    const pool = [];
    const navLinks = Array.from(document.querySelectorAll(".sidebar-nav .nav-link[href]"));
    navLinks.forEach((link) => {
      const href = String(link.getAttribute("href") || "").trim();
      const label = String((link.textContent || "").replace(/\s+/g, " ").trim());
      if (!href || !label) return;
      pool.push({
        text: label,
        href: href,
        keywords: [label],
      });
    });

    const keywordSeeds = [
      { text: "Dashboard", href: "/dashboard", keywords: ["home", "overview", "stats"] },
      { text: "Create Test", href: "/create-test", keywords: ["new test", "generate test", "candidate test"] },
      { text: "Generated Tests", href: "/generated-tests", keywords: ["links", "test links", "sent tests"] },
      { text: "Evaluation", href: "/evaluation", keywords: ["evaluate", "score", "results"] },
      { text: "Reports", href: "/reports", keywords: ["report", "download report", "candidate report"] },
      { text: "Access Management", href: "/access-management", keywords: ["users", "roles", "permissions"] },
      { text: "AI Settings", href: "/ai-settings", keywords: ["provider", "api keys", "gpt", "gemini", "claude"] },
      { text: "Logout", href: "/logout", keywords: ["sign out", "exit"] },
    ];

    keywordSeeds.forEach((seed) => {
      pool.push({
        text: seed.text,
        href: seed.href,
        keywords: Array.isArray(seed.keywords) ? seed.keywords : [],
      });
    });

    const deduped = [];
    const seen = new Set();
    pool.forEach((item) => {
      const key = `${normalizeForSearch(item.text)}|${item.href}`;
      if (!key || seen.has(key)) return;
      seen.add(key);
      deduped.push(item);
    });
    return deduped;
  }

  const globalPool = buildGlobalSearchPool();

  function scoreItem(item, tokens) {
    const textNorm = normalizeForSearch(item.text);
    const keywordNorm = normalizeForSearch((item.keywords || []).join(" "));
    const haystack = `${textNorm} ${keywordNorm}`.trim();
    if (!tokens.length) return 1;
    if (!tokens.every((tok) => haystack.includes(tok))) return -1;

    let score = 0;
    tokens.forEach((tok) => {
      if (textNorm === tok) score += 120;
      if (textNorm.startsWith(tok)) score += 60;
      if (keywordNorm.startsWith(tok)) score += 28;
      if (haystack.includes(" " + tok)) score += 10;
      if (haystack.includes(tok)) score += 5;
    });
    score += Math.max(0, 6 - Math.min(textNorm.length, 42) / 7);
    return score;
  }

  function updateGlobalSuggestions() {
    const tokens = getQueryTokens(globalSearchInput.value);
    const ranked = globalPool
      .map((item) => ({ item, score: scoreItem(item, tokens) }))
      .filter((row) => row.score >= 0)
      .sort((a, b) => b.score - a.score || a.item.text.localeCompare(b.item.text))
      .slice(0, 8);

    globalSearchSuggestions.innerHTML = "";
    ranked.forEach((row) => {
      const opt = document.createElement("option");
      opt.value = row.item.text;
      opt.label = row.item.href;
      globalSearchSuggestions.appendChild(opt);
    });
  }

  function resolveGlobalSearchTarget(rawQuery) {
    const queryNorm = normalizeForSearch(rawQuery);
    if (!queryNorm) return null;
    const tokens = queryNorm.split(" ").filter(Boolean);
    const ranked = globalPool
      .map((item) => ({ item, score: scoreItem(item, tokens) }))
      .filter((row) => row.score >= 0)
      .sort((a, b) => b.score - a.score || a.item.text.localeCompare(b.item.text));
    return ranked.length ? ranked[0].item : null;
  }

  globalSearchInput.addEventListener("input", updateGlobalSuggestions);
  globalSearchInput.addEventListener("focus", updateGlobalSuggestions);

  globalSearchInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const target = resolveGlobalSearchTarget(globalSearchInput.value);
    if (!target) return;
    event.preventDefault();
    window.location.href = target.href;
  });

  globalSearchInput.addEventListener("change", () => {
    const target = resolveGlobalSearchTarget(globalSearchInput.value);
    if (target && normalizeForSearch(target.text) === normalizeForSearch(globalSearchInput.value)) {
      window.location.href = target.href;
    }
  });

  updateGlobalSuggestions();
})();
