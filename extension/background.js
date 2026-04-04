let links = [];
let lastExportIndex = 0;       // tracks how many links have been exported
let autoExportThreshold = 0;   // 0 = disabled

// ── Persistence helpers ──────────────────────────────────────────────

function persist() {
  chrome.storage.local.set({
    gleam_links: links,
    gleam_last_export: lastExportIndex,
    gleam_auto_threshold: autoExportThreshold
  });
}

function updateBadge() {
  const total = links.length;
  chrome.action.setBadgeText({ text: total > 0 ? String(total) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#10b981' });
}

// ── Restore state on startup ─────────────────────────────────────────

chrome.storage.local.get(
  ['gleam_links', 'gleam_last_export', 'gleam_auto_threshold'],
  (result) => {
    if (result.gleam_links) links = result.gleam_links;
    if (typeof result.gleam_last_export === 'number') lastExportIndex = result.gleam_last_export;
    if (typeof result.gleam_auto_threshold === 'number') autoExportThreshold = result.gleam_auto_threshold;
    updateBadge();
  }
);

// ── Auto-export download (background-only, fire-and-forget) ─────────
// Service workers lack Blob/URL.createObjectURL, so use a data URI.
// This is only used for auto-export where no popup is waiting for a
// response, avoiding the "message port closed" problem entirely.

function backgroundDownloadNdjson(entries) {
  if (entries.length === 0) return;

  try {
    const content = entries.map(l => JSON.stringify(l)).join('\n') + '\n';
    const dataUrl = 'data:application/x-ndjson;base64,' + btoa(unescape(encodeURIComponent(content)));

    chrome.downloads.download({
      url: dataUrl,
      filename: 'gleam-links.ndjson',
      saveAs: false,
      conflictAction: 'overwrite'
    }, () => {
      if (chrome.runtime.lastError) {
        console.warn('Gleam Monitor: auto-export download error', chrome.runtime.lastError.message);
      }
    });
  } catch (e) {
    console.warn('Gleam Monitor: auto-export encoding error', e);
  }
}

// ── Auto-export check ────────────────────────────────────────────────

function checkAutoExport() {
  if (autoExportThreshold <= 0) return;
  const unexported = links.length - lastExportIndex;
  if (unexported >= autoExportThreshold) {
    const newEntries = links.slice(lastExportIndex);
    backgroundDownloadNdjson(newEntries);
    lastExportIndex = links.length;
    persist();
  }
}

// ── Message handler ──────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // ── Append a newly found link ──
  if (msg.type === 'append') {
    const exists = links.some(l => l.href === msg.href);
    if (!exists) {
      links.push({
        href: msg.href,
        text: msg.text || '',
        pageUrl: msg.pageUrl || '',
        t: new Date().toISOString()
      });
      persist();
      updateBadge();
      checkAutoExport();
    }
    sendResponse({ count: links.length });
    return true;
  }

  // ── Get counts ──
  if (msg.type === 'get-count') {
    sendResponse({
      count: links.length,
      unexported: links.length - lastExportIndex
    });
    return true;
  }

  // ── Get full link list ──
  if (msg.type === 'get-links') {
    sendResponse({ links });
    return true;
  }

  // ── Get export data (links + index so popup can build the file) ──
  if (msg.type === 'get-export-data') {
    sendResponse({ links, lastExportIndex });
    return true;
  }

  // ── Mark links as exported (called by popup after successful download) ──
  if (msg.type === 'mark-exported') {
    const idx = parseInt(msg.upToIndex, 10);
    if (idx > lastExportIndex) {
      lastExportIndex = idx;
      persist();
    }
    sendResponse({ ok: true, lastExportIndex });
    return true;
  }

  // ── Clear everything ──
  if (msg.type === 'clear') {
    links = [];
    lastExportIndex = 0;
    persist();
    updateBadge();
    sendResponse({ ok: true });
    return true;
  }

  // ── Get / set auto-export threshold ──
  if (msg.type === 'get-settings') {
    sendResponse({ autoExportThreshold });
    return true;
  }

  if (msg.type === 'set-auto-threshold') {
    autoExportThreshold = parseInt(msg.value, 10) || 0;
    persist();
    sendResponse({ ok: true, autoExportThreshold });
    return true;
  }

  return false;
});
