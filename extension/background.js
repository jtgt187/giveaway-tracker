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

// ── Download helper ──────────────────────────────────────────────────

function downloadNdjson(entries) {
  return new Promise((resolve, reject) => {
    if (entries.length === 0) { reject(new Error('No links to export')); return; }

    const content = entries.map(l => JSON.stringify(l)).join('\n') + '\n';
    // Service Workers (MV3) don't support URL.createObjectURL — use a data URI instead
    const dataUrl = 'data:application/x-ndjson;base64,' + btoa(unescape(encodeURIComponent(content)));
    const filename = 'gleam-links.ndjson';

    chrome.downloads.download({
      url: dataUrl,
      filename,
      saveAs: false,
      conflictAction: 'overwrite'
    }, (downloadId) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(downloadId);
      }
    });
  });
}

// ── Auto-export check ────────────────────────────────────────────────

function checkAutoExport() {
  if (autoExportThreshold <= 0) return;
  const unexported = links.length - lastExportIndex;
  if (unexported >= autoExportThreshold) {
    const newEntries = links.slice(lastExportIndex);
    downloadNdjson(newEntries).then(() => {
      lastExportIndex = links.length;
      persist();
    }).catch(e => {
      console.warn('Gleam Monitor: auto-export failed', e);
    });
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

  // ── Download ALL links ──
  if (msg.type === 'download') {
    if (links.length === 0) {
      sendResponse({ ok: false, error: 'No links collected' });
      return true;
    }
    downloadNdjson(links).then(() => {
      lastExportIndex = links.length;
      persist();
      sendResponse({ ok: true });
    }).catch(e => {
      sendResponse({ ok: false, error: String(e.message || e) });
    });
    return true;
  }

  // ── Download only NEW (unexported) links ──
  if (msg.type === 'export-new') {
    const newEntries = links.slice(lastExportIndex);
    if (newEntries.length === 0) {
      sendResponse({ ok: false, error: 'No new links since last export' });
      return true;
    }
    downloadNdjson(newEntries).then(() => {
      lastExportIndex = links.length;
      persist();
      sendResponse({ ok: true, exported: newEntries.length });
    }).catch(e => {
      sendResponse({ ok: false, error: String(e.message || e) });
    });
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
