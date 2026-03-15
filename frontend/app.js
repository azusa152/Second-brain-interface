// Second Brain Interface — Dashboard Logic
// All fetch calls use relative paths so the dashboard works on any configured port.

(function () {
  "use strict";

  const POLL_INTERVAL = 5000;
  const SEARCH_DEBOUNCE_MS = 300;

  // ---------------------------------------------------------------------------
  // DOM references
  // ---------------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);

  const dom = {
    headerStatus:   $("header-status"),
    healthBackend:  $("health-backend"),
    healthQdrant:   $("health-qdrant"),
    healthWatcher:  $("health-watcher"),
    statNotes:      $("stat-notes"),
    statChunks:     $("stat-chunks"),
    statLastIndexed:$("stat-last-indexed"),
    eventsList:     $("events-list"),
    searchForm:     $("search-form"),
    searchInput:    $("search-input"),
    searchClear:    $("search-clear"),
    searchTopK:     $("search-top-k"),
    searchTopKVal:  $("search-top-k-value"),
    searchMeta:     $("search-meta"),
    searchDeepLinkStatus: $("search-deeplink-status"),
    searchResults:  $("search-results"),
    vaultFilter:    $("vault-filter"),
    vaultDeepLinkStatus: $("vault-deeplink-status"),
    vaultNotes:     $("vault-notes"),
    vaultLinks:     $("vault-links"),
    linksTitle:     $("links-title"),
    linksOutlinks:  $("links-outlinks"),
    linksBacklinks: $("links-backlinks"),
    rebuildBtn:     $("rebuild-btn"),
    rebuildResult:  $("rebuild-result"),
  };
  let vaultName = "";
  let deepLinksConfigured = false;
  let deepLinkMessage = "";
  let allNotes = [];
  let latestSearchToken = 0;
  let searchDebounceTimer = null;

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function setBadge(el, ok, label) {
    el.textContent = label || (ok ? "ok" : "down");
    el.className = "badge " + (ok ? "badge-ok" : "badge-error");
  }

  function timeAgo(isoStr) {
    const diff = Date.now() - new Date(isoStr).getTime();
    const secs = Math.floor(diff / 1000);
    if (secs < 60) return secs + "s ago";
    const mins = Math.floor(secs / 60);
    if (mins < 60) return mins + "m ago";
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + "h ago";
    return Math.floor(hrs / 24) + "d ago";
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return String(str).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  }

  function truncate(str, len) {
    if (!str) return "";
    return str.length > len ? str.slice(0, len) + "..." : str;
  }

  function pluralize(count, singular, plural) {
    return count === 1 ? singular : plural;
  }

  function normalizeNotePathForObsidian(notePath) {
    if (!notePath) return "";
    return notePath.toLowerCase().endsWith(".md") ? notePath.slice(0, -3) : notePath;
  }

  function buildObsidianUri(notePath) {
    if (!vaultName) return "";
    const filePath = normalizeNotePathForObsidian(notePath);
    if (!filePath) return "";
    return (
      "obsidian://open?vault=" +
      encodeURIComponent(vaultName) +
      "&file=" +
      encodeURIComponent(filePath)
    );
  }

  function openInObsidianLink(notePath, className) {
    const uri = buildObsidianUri(notePath);
    if (!uri) {
      return '<span class="' + className + ' obsidian-open-disabled" title="Vault name unavailable">Unavailable</span>';
    }
    return (
      '<a class="' +
      className +
      '" href="' +
      escapeAttr(uri) +
      '" title="Open in Obsidian" aria-label="Open in Obsidian">Open</a>'
    );
  }

  function noteLinkHtml(notePath, noteTitle, className) {
    const uri = buildObsidianUri(notePath);
    const safeTitle = escapeHtml(noteTitle || notePath || "Untitled note");
    if (!uri) {
      return '<span class="' + className + ' obsidian-open-disabled">' + safeTitle + "</span>";
    }
    return (
      '<a class="' +
      className +
      '" href="' +
      escapeAttr(uri) +
      '" title="Open in Obsidian" aria-label="Open in Obsidian">' +
      safeTitle +
      "</a>"
    );
  }

  function renderDeepLinkStatus() {
    if (deepLinksConfigured) {
      dom.searchDeepLinkStatus.hidden = true;
      dom.searchDeepLinkStatus.textContent = "";
      dom.vaultDeepLinkStatus.hidden = true;
      dom.vaultDeepLinkStatus.textContent = "";
      return;
    }
    const message =
      deepLinkMessage ||
      "Obsidian deep links are unavailable. Set OBSIDIAN_VAULT_NAME or verify OBSIDIAN_VAULT_PATH.";
    dom.searchDeepLinkStatus.hidden = false;
    dom.searchDeepLinkStatus.textContent = message;
    dom.vaultDeepLinkStatus.hidden = false;
    dom.vaultDeepLinkStatus.textContent = message;
  }

  function setSearchMeta(message) {
    dom.searchMeta.textContent = message;
  }

  function renderSearchIdleState() {
    dom.searchResults.innerHTML = '<li class="placeholder">Enter a keyword or phrase to search your vault</li>';
    setSearchMeta("Ready for keyword search");
  }

  function toggleSearchClearButton() {
    dom.searchClear.hidden = dom.searchInput.value.length === 0;
  }

  async function loadVaultConfig() {
    try {
      const resp = await fetch("/config/vault");
      if (!resp.ok) {
        deepLinksConfigured = false;
        deepLinkMessage = "Obsidian deep links are unavailable because vault configuration could not be loaded.";
        renderDeepLinkStatus();
        return;
      }
      const data = await resp.json();
      vaultName = (data.vault_name || "").trim();
      deepLinksConfigured = Boolean(data.is_configured && vaultName);
      deepLinkMessage = data.message || "";
    } catch {
      vaultName = "";
      deepLinksConfigured = false;
      deepLinkMessage = "Obsidian deep links are unavailable because dashboard could not reach /config/vault.";
    }
    renderDeepLinkStatus();
  }

  // ---------------------------------------------------------------------------
  // Health Panel
  // ---------------------------------------------------------------------------
  async function pollHealth() {
    try {
      const resp = await fetch("/health");
      if (resp.ok) {
        setBadge(dom.healthBackend, true);
        setBadge(dom.headerStatus, true, "online");
      } else {
        setBadge(dom.healthBackend, false);
        setBadge(dom.headerStatus, false, "error");
      }
    } catch {
      setBadge(dom.healthBackend, false);
      setBadge(dom.headerStatus, false, "offline");
    }
  }

  // ---------------------------------------------------------------------------
  // Index Status Panel (also feeds Health badges for Qdrant + Watcher)
  // ---------------------------------------------------------------------------
  async function pollIndexStatus() {
    try {
      const resp = await fetch("/index/status");
      if (!resp.ok) return;
      const data = await resp.json();

      dom.statNotes.textContent = data.indexed_notes;
      dom.statChunks.textContent = data.indexed_chunks;
      dom.statLastIndexed.textContent = data.last_indexed
        ? timeAgo(data.last_indexed)
        : "never";

      setBadge(dom.healthQdrant, data.qdrant_healthy);
      setBadge(dom.healthWatcher, data.watcher_running, data.watcher_running ? "ok" : "stopped");
    } catch {
      // Silently skip — health poll will catch backend down
    }
  }

  // ---------------------------------------------------------------------------
  // Recent Events Panel
  // ---------------------------------------------------------------------------
  async function pollEvents() {
    try {
      const resp = await fetch("/index/events?limit=20");
      if (!resp.ok) return;
      const data = await resp.json();

      if (data.events.length === 0) {
        dom.eventsList.innerHTML = '<li class="placeholder">No events yet</li>';
        return;
      }

      dom.eventsList.innerHTML = data.events
        .map((e) => {
          const typeClass = "event-type event-type-" + e.event_type;
          const path = escapeHtml(e.file_path);
          const dest = e.dest_path ? " &rarr; " + escapeHtml(e.dest_path) : "";
          const time = timeAgo(e.timestamp);
          return (
            '<li>' +
              '<span class="' + typeClass + '">' + e.event_type + '</span>' +
              '<span class="event-path">' + path + dest + '</span>' +
              '<span class="event-time">' + time + '</span>' +
            '</li>'
          );
        })
        .join("");
    } catch {
      // Silently skip
    }
  }

  // ---------------------------------------------------------------------------
  // Search Playground
  // ---------------------------------------------------------------------------
  dom.searchTopK.addEventListener("input", function () {
    dom.searchTopKVal.textContent = this.value;
  });

  async function performSearch(rawQuery) {
    const query = rawQuery.trim();
    const searchToken = ++latestSearchToken;
    if (!query) {
      renderSearchIdleState();
      return;
    }

    const topK = parseInt(dom.searchTopK.value, 10);
    dom.searchResults.innerHTML = '<li class="placeholder"><span class="loading-spinner"></span> Searching...</li>';
    setSearchMeta("Searching...");

    try {
      const resp = await fetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, top_k: topK }),
      });

      if (searchToken !== latestSearchToken) return;

      if (!resp.ok) {
        dom.searchResults.innerHTML = '<li class="placeholder">Search failed (' + resp.status + ')</li>';
        setSearchMeta("Search request failed");
        return;
      }

      const data = await resp.json();

      if (searchToken !== latestSearchToken) return;

      const resultCount = data.results.length;
      const roundedTime = Math.round(data.search_time_ms);
      setSearchMeta(
        resultCount +
          " " +
          pluralize(resultCount, "result", "results") +
          " in " +
          roundedTime +
          "ms"
      );

      if (resultCount === 0) {
        dom.searchResults.innerHTML =
          '<li class="placeholder">No matches found. Try broader keywords or check spelling.</li>';
        return;
      }

      dom.searchResults.innerHTML = data.results
        .map((r) => {
          const score = r.score.toFixed(4);
          const snippet = escapeHtml(truncate(r.content, 200));
          const heading = r.heading_context ? '<span class="result-heading"> - ' + escapeHtml(r.heading_context) + '</span>' : "";
          return (
            '<li class="result-item">' +
              '<span class="result-score">score ' + score + '</span>' +
              '<div class="result-title-row">' +
                '<div class="result-title">' +
                  noteLinkHtml(r.note_path, r.note_title, "obsidian-note-link") +
                  heading +
                '</div>' +
                openInObsidianLink(r.note_path, "obsidian-open-link") +
              '</div>' +
              '<div class="result-path">' + escapeHtml(r.note_path) + '</div>' +
              '<div class="result-snippet">' + snippet + '</div>' +
            '</li>'
          );
        })
        .join("");
    } catch {
      if (searchToken !== latestSearchToken) return;
      dom.searchResults.innerHTML = '<li class="placeholder">Network error</li>';
      setSearchMeta("Could not reach search service");
    }
  }

  function scheduleSearch() {
    clearTimeout(searchDebounceTimer);
    const query = dom.searchInput.value.trim();
    if (!query) {
      latestSearchToken++;
      renderSearchIdleState();
      return;
    }
    searchDebounceTimer = setTimeout(function () {
      performSearch(query);
    }, SEARCH_DEBOUNCE_MS);
  }

  dom.searchInput.addEventListener("input", function () {
    toggleSearchClearButton();
    scheduleSearch();
  });

  dom.searchClear.addEventListener("click", function () {
    dom.searchInput.value = "";
    latestSearchToken++;
    clearTimeout(searchDebounceTimer);
    toggleSearchClearButton();
    renderSearchIdleState();
    dom.searchInput.focus();
  });

  dom.searchForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    clearTimeout(searchDebounceTimer);
    await performSearch(dom.searchInput.value);
  });

  dom.searchTopK.addEventListener("change", function () {
    if (dom.searchInput.value.trim()) {
      performSearch(dom.searchInput.value);
    }
  });

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      dom.searchInput.focus();
      dom.searchInput.select();
    }
  });

  // ---------------------------------------------------------------------------
  // Vault Browser
  // ---------------------------------------------------------------------------
  async function loadNotes() {
    try {
      const resp = await fetch("/index/notes");
      if (!resp.ok) return;
      const data = await resp.json();
      allNotes = data.notes;
      renderNotes(allNotes);
    } catch {
      dom.vaultNotes.innerHTML = '<li class="placeholder">Failed to load notes</li>';
    }
  }

  function renderNotes(notes) {
    if (notes.length === 0) {
      dom.vaultNotes.innerHTML = '<li class="placeholder">No notes found</li>';
      return;
    }

    dom.vaultNotes.innerHTML = notes
      .map((n) =>
        '<li data-path="' + escapeAttr(n.note_path) + '">' +
          '<div class="note-row-main">' +
            '<span class="note-title">' + escapeHtml(n.note_title || n.note_path) + '</span>' +
            '<span class="note-path">' + escapeHtml(n.note_path) + '</span>' +
          "</div>" +
          '<button type="button" class="note-inspect-btn" data-action="show-links" aria-label="Show links for ' + escapeAttr(n.note_title || n.note_path) + '">Show links</button>' +
          openInObsidianLink(n.note_path, "obsidian-open-link") +
        '</li>'
      )
      .join("");
  }

  dom.vaultFilter.addEventListener("input", function () {
    const q = this.value.toLowerCase();
    if (!q) {
      renderNotes(allNotes);
      return;
    }
    const filtered = allNotes.filter(
      (n) =>
        n.note_path.toLowerCase().includes(q) ||
        (n.note_title && n.note_title.toLowerCase().includes(q))
    );
    renderNotes(filtered);
  });

  dom.vaultNotes.addEventListener("click", async function (e) {
    if (e.target.closest("a")) return;
    const showLinksBtn = e.target.closest('button[data-action="show-links"]');
    if (!showLinksBtn) return;
    const li = e.target.closest("li[data-path]");
    if (!li) return;
    const path = li.dataset.path;
    await showLinks(path);
  });

  async function showLinks(notePath) {
    dom.linksTitle.textContent = notePath;
    dom.linksOutlinks.innerHTML = "";
    dom.linksBacklinks.innerHTML = "";
    dom.vaultLinks.hidden = false;

    try {
      const encodedPath = notePath.split("/").map(encodeURIComponent).join("/");
      const resp = await fetch("/note/" + encodedPath + "/links");
      if (!resp.ok) {
        dom.linksOutlinks.innerHTML = "<li>--</li>";
        dom.linksBacklinks.innerHTML = "<li>--</li>";
        return;
      }
      const data = await resp.json();

      dom.linksOutlinks.innerHTML = data.outlinks.length
        ? data.outlinks
            .map(
              (l) =>
                "<li>" +
                noteLinkHtml(l.note_path, l.note_title || l.note_path, "obsidian-note-link") +
                "</li>"
            )
            .join("")
        : "<li>none</li>";

      dom.linksBacklinks.innerHTML = data.backlinks.length
        ? data.backlinks
            .map(
              (l) =>
                "<li>" +
                noteLinkHtml(l.note_path, l.note_title || l.note_path, "obsidian-note-link") +
                "</li>"
            )
            .join("")
        : "<li>none</li>";
    } catch {
      dom.linksOutlinks.innerHTML = "<li>error</li>";
      dom.linksBacklinks.innerHTML = "<li>error</li>";
    }
  }

  // ---------------------------------------------------------------------------
  // Rebuild Action
  // ---------------------------------------------------------------------------
  dom.rebuildBtn.addEventListener("click", async function () {
    dom.rebuildBtn.disabled = true;
    dom.rebuildBtn.textContent = "Rebuilding...";
    dom.rebuildResult.hidden = true;

    try {
      const resp = await fetch("/index/rebuild", { method: "POST" });
      const data = await resp.json();

      if (resp.ok) {
        dom.rebuildResult.textContent =
          "Rebuilt " + data.notes_indexed + " notes, " +
          data.chunks_created + " chunks in " +
          data.time_taken_seconds + "s";
      } else if (resp.status === 409) {
        dom.rebuildResult.textContent = "Rebuild already in progress";
      } else {
        dom.rebuildResult.textContent = "Rebuild failed (" + resp.status + ")";
      }
    } catch {
      dom.rebuildResult.textContent = "Network error";
    }

    dom.rebuildResult.hidden = false;
    dom.rebuildBtn.disabled = false;
    dom.rebuildBtn.textContent = "Rebuild Index";

    // Refresh status after rebuild
    await pollIndexStatus();
    await loadNotes();
  });

  // ---------------------------------------------------------------------------
  // Polling loop
  // ---------------------------------------------------------------------------
  async function pollAll() {
    await Promise.all([pollHealth(), pollIndexStatus(), pollEvents()]);
  }

  async function init() {
    await loadVaultConfig();
    renderDeepLinkStatus();
    toggleSearchClearButton();
    renderSearchIdleState();
    await pollAll();
    await loadNotes();
  }

  // Initial load
  init();

  // Start polling
  setInterval(pollAll, POLL_INTERVAL);
})();
