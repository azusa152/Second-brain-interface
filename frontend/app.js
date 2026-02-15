// Second Brain Interface — Dashboard Logic
// All fetch calls use relative paths so the dashboard works on any configured port.

(function () {
  "use strict";

  const POLL_INTERVAL = 5000;

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
    searchTopK:     $("search-top-k"),
    searchTopKVal:  $("search-top-k-value"),
    searchResults:  $("search-results"),
    vaultFilter:    $("vault-filter"),
    vaultNotes:     $("vault-notes"),
    vaultLinks:     $("vault-links"),
    linksTitle:     $("links-title"),
    linksOutlinks:  $("links-outlinks"),
    linksBacklinks: $("links-backlinks"),
    rebuildBtn:     $("rebuild-btn"),
    rebuildResult:  $("rebuild-result"),
  };

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
    return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
  }

  function truncate(str, len) {
    if (!str) return "";
    return str.length > len ? str.slice(0, len) + "..." : str;
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

  dom.searchForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    const query = dom.searchInput.value.trim();
    if (!query) return;

    const topK = parseInt(dom.searchTopK.value, 10);
    dom.searchResults.innerHTML = '<li class="placeholder">Searching...</li>';

    try {
      const resp = await fetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, top_k: topK }),
      });

      if (!resp.ok) {
        dom.searchResults.innerHTML = '<li class="placeholder">Search failed (' + resp.status + ')</li>';
        return;
      }

      const data = await resp.json();

      if (data.results.length === 0) {
        dom.searchResults.innerHTML = '<li class="placeholder">No results found</li>';
        return;
      }

      dom.searchResults.innerHTML = data.results
        .map((r) => {
          const score = r.score.toFixed(4);
          const snippet = escapeHtml(truncate(r.content, 200));
          const heading = r.heading_context ? ' &mdash; ' + escapeHtml(r.heading_context) : '';
          return (
            '<li>' +
              '<span class="result-score">score ' + score + '</span>' +
              '<div class="result-title">' + escapeHtml(r.note_title) + heading + '</div>' +
              '<div class="result-path">' + escapeHtml(r.note_path) + '</div>' +
              '<div class="result-snippet">' + snippet + '</div>' +
            '</li>'
          );
        })
        .join("");
    } catch {
      dom.searchResults.innerHTML = '<li class="placeholder">Network error</li>';
    }
  });

  // ---------------------------------------------------------------------------
  // Vault Browser
  // ---------------------------------------------------------------------------
  let allNotes = [];

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
          escapeHtml(n.note_title || n.note_path) +
          '<span class="note-path">' + escapeHtml(n.note_path) + '</span>' +
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
        ? data.outlinks.map((l) => "<li>" + escapeHtml(l.note_title || l.note_path) + "</li>").join("")
        : "<li>none</li>";

      dom.linksBacklinks.innerHTML = data.backlinks.length
        ? data.backlinks.map((l) => "<li>" + escapeHtml(l.note_title || l.note_path) + "</li>").join("")
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

  // Initial load
  pollAll();
  loadNotes();

  // Start polling
  setInterval(pollAll, POLL_INTERVAL);
})();
