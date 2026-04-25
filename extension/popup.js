// -- State -------------------------------------------------------------

let knownCount = 0;

// -- UI helpers --------------------------------------------------------

function setStatus(msg, duration) {
  const el = document.getElementById('status');
  el.textContent = msg;
  if (duration) {
    setTimeout(function() { if (el.textContent === msg) el.textContent = ''; }, duration);
  }
}

// -- Local download helper ---------------------------------------------
// Runs in the popup context which has full DOM access (Blob, URL, <a>).
// This avoids MV3 service-worker limitations entirely.

function downloadNdjsonFile(entries) {
  var content = entries.map(function(l) { return JSON.stringify(l); }).join('\n') + '\n';
  var blob = new Blob([content], { type: 'application/x-ndjson' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'gleam-links.ndjson';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a short delay to ensure the download starts
  setTimeout(function() { URL.revokeObjectURL(url); }, 1000);
}

// -- Update counter & unexported badge ---------------------------------
//
// Renderers are split into two layers:
//   * `render*` functions accept already-fetched state and only touch the
//     DOM. Cheap, synchronous, no IPC.
//   * `update*` wrappers exist for callers that genuinely need a fresh
//     read of just-one slice (e.g. after a write). They go through
//     `refreshState()` so the wire format stays identical.
//
// The 3s poll uses `refreshState()` exactly once per tick — previously
// the popup fired 4 separate `sendMessage` calls per tick, each waking
// the service worker. The new flow cuts that to a single round-trip.

function renderCount(state) {
  var count = state.count;
  var unexported = state.unexported;
  knownCount = count;

  document.getElementById('count').textContent = count;
  document.getElementById('downloadBtn').disabled = count === 0;
  document.getElementById('clearBtn').disabled = count === 0;
  document.getElementById('exportNewBtn').disabled = unexported === 0;

  if (unexported > 0) {
    document.getElementById('unexported').textContent = unexported + ' new since last export';
  } else if (count > 0) {
    document.getElementById('unexported').textContent = 'all exported';
  } else {
    document.getElementById('unexported').textContent = '';
  }

  // Update live DB sync indicator
  var syncEl = document.getElementById('syncStatus');
  if (state.apiConnected) {
    syncEl.innerHTML = '<span class="sync-dot connected"></span><span style="color:#10b981">Live sync to DB</span>';
  } else {
    syncEl.innerHTML = '<span class="sync-dot disconnected"></span><span style="color:#666">DB offline</span>';
  }
}

function renderRecentLinks(links) {
  if (!links) return;
  var list = document.getElementById('recentList');
  var recent = links.slice(-5).reverse(); // last 5, newest first

  if (recent.length === 0) {
    list.innerHTML = '<div class="recent-empty">No links yet</div>';
    return;
  }

  list.innerHTML = recent.map(function(l) {
    var displayUrl = l.href.replace('https://', '').replace('http://', '');
    var label = l.text || displayUrl;
    // Sanitize URL: only allow http/https to prevent javascript: XSS
    var safeHref = '';
    try {
      var urlObj = new URL(l.href);
      if (urlObj.protocol === 'http:' || urlObj.protocol === 'https:') {
        safeHref = l.href;
      }
    } catch (e) {}
    if (!safeHref) return ''; // Skip invalid URLs
    return '<div class="recent-item">' +
      '<a href="' + escapeHtml(safeHref) + '" target="_blank" rel="noopener" title="' + escapeHtml(l.href) + '">' +
        escapeHtml(label.substring(0, 60)) +
      '</a>' +
    '</div>';
  }).join('');
}

function renderEntryStats(stats) {
  if (!stats) return;
  document.getElementById('statTotal').textContent = stats.total || 0;
  document.getElementById('statCompleted').textContent = stats.completed || 0;
  document.getElementById('statFailed').textContent = stats.failed || 0;

  var lastEntryEl = document.getElementById('lastEntry');
  if (stats.lastUrl && stats.lastTime) {
    var safeUrl = '';
    try {
      var urlObj = new URL(stats.lastUrl);
      if (urlObj.protocol === 'http:' || urlObj.protocol === 'https:') {
        safeUrl = stats.lastUrl;
      }
    } catch (e) {}

    var timeAgo = getTimeAgo(stats.lastTime);
    var shortUrl = stats.lastUrl.replace('https://', '').replace('http://', '');
    if (shortUrl.length > 40) shortUrl = shortUrl.substring(0, 40) + '...';
    if (safeUrl) {
      lastEntryEl.innerHTML = 'Last: <a href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener">' +
        escapeHtml(shortUrl) + '</a> (' + timeAgo + ')';
    } else {
      lastEntryEl.textContent = 'Last: ' + shortUrl + ' (' + timeAgo + ')';
    }
  } else {
    lastEntryEl.textContent = 'No entries yet';
  }
}

function renderSettings(state) {
  var ti = document.getElementById('thresholdInput');
  if (ti && typeof state.autoExportThreshold === 'number') ti.value = state.autoExportThreshold || 0;
  var pt = document.getElementById('prefetchToggle');
  if (pt && typeof state.prefetchDeadlines === 'boolean') pt.checked = state.prefetchDeadlines !== false;
}

function refreshState(cb) {
  chrome.runtime.sendMessage({ type: 'get-popup-state' }, function(response) {
    if (chrome.runtime.lastError || !response) { if (cb) cb(null); return; }
    renderCount(response);
    renderRecentLinks(response.links);
    renderEntryStats(response.entryStats);
    if (cb) cb(response);
  });
}

// Back-compat one-slice shims (used by callers after a write)
function updateCount() { refreshState(); }
function updateRecentLinks() { /* covered by refreshState */ }
function updateEntryStats() { refreshState(); }

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// -- Export new links only ---------------------------------------------
// Fetches export data from background, downloads locally in popup,
// then tells background to update the export index.

function exportNew() {
  setStatus('Exporting new links...');
  chrome.runtime.sendMessage({ type: 'get-export-data' }, function(response) {
    if (chrome.runtime.lastError) {
      setStatus('Export failed: ' + chrome.runtime.lastError.message, 4000);
      return;
    }
    if (!response || !response.links) {
      setStatus('Export failed: no data', 4000);
      return;
    }

    var newEntries = response.links.slice(response.lastExportIndex);
    if (newEntries.length === 0) {
      setStatus('No new links since last export', 3000);
      return;
    }

    try {
      downloadNdjsonFile(newEntries);
    } catch (e) {
      setStatus('Export failed: ' + e.message, 4000);
      return;
    }

    // Tell background to advance the export index
    chrome.runtime.sendMessage({
      type: 'mark-exported',
      upToIndex: response.links.length
    }, function() {
      if (chrome.runtime.lastError) return;
      setStatus('Exported ' + newEntries.length + ' new links', 3000);
      updateCount();
    });
  });
}

// -- Download all links ------------------------------------------------

function downloadAll() {
  setStatus('Preparing download...');
  chrome.runtime.sendMessage({ type: 'get-export-data' }, function(response) {
    if (chrome.runtime.lastError) {
      setStatus('Download failed: ' + chrome.runtime.lastError.message, 4000);
      return;
    }
    if (!response || !response.links || response.links.length === 0) {
      setStatus('No links collected', 3000);
      return;
    }

    try {
      downloadNdjsonFile(response.links);
    } catch (e) {
      setStatus('Download failed: ' + e.message, 4000);
      return;
    }

    // Mark all as exported
    chrome.runtime.sendMessage({
      type: 'mark-exported',
      upToIndex: response.links.length
    }, function() {
      if (chrome.runtime.lastError) return;
      setStatus('Downloaded ' + response.links.length + ' links', 3000);
      updateCount();
    });
  });
}

// -- Clear all links ---------------------------------------------------

function clearLinks() {
  chrome.runtime.sendMessage({ type: 'clear' }, function(response) {
    if (chrome.runtime.lastError) return;
    if (response && response.ok) {
      setStatus('Cleared!', 2000);
      updateCount();
      updateRecentLinks();
    }
  });
}

// -- Auto-entry stats -------------------------------------------------
// (renderer above; kept here only for the legacy reset hook below)

function getTimeAgo(isoString) {
  var diff = Date.now() - new Date(isoString).getTime();
  if (isNaN(diff) || diff < 0) return 'unknown';
  var mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + 'm ago';
  var hours = Math.floor(mins / 60);
  if (hours < 24) return hours + 'h ago';
  var days = Math.floor(hours / 24);
  return days + 'd ago';
}

function resetEntryStats() {
  chrome.runtime.sendMessage({ type: 'reset-entry-stats' }, function(response) {
    if (chrome.runtime.lastError) return;
    if (response && response.ok) {
      setStatus('Stats reset', 2000);
      refreshState();
    }
  });
}

// -- Auto-export threshold setting -------------------------------------
// loadSettings is now folded into refreshState() — kept as a no-op
// alias for any legacy caller / future hook.
function loadSettings() { /* handled by refreshState */ }

function onThresholdChange() {
  var val = parseInt(document.getElementById('thresholdInput').value, 10) || 0;
  chrome.runtime.sendMessage({ type: 'set-auto-threshold', value: val }, function(response) {
    if (chrome.runtime.lastError) return;
    if (response && response.ok) {
      setStatus(val > 0 ? 'Auto-export every ' + val + ' links' : 'Auto-export disabled', 2000);
    }
  });
}

function onPrefetchToggle() {
  var enabled = document.getElementById('prefetchToggle').checked;
  chrome.runtime.sendMessage({ type: 'set-prefetch-setting', value: enabled }, function(response) {
    if (chrome.runtime.lastError) return;
    if (response && response.ok) {
      setStatus(enabled ? 'Deadline prefetch enabled' : 'Deadline prefetch disabled', 2000);
    }
  });
}

// -- Update DB total from local API -----------------------------------

function updateDbTotal() {
  // Abort if request takes longer than 2s — popup polls every 3s and a
  // hung localhost call must not pile up.
  var ctl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  var timer = ctl ? setTimeout(function() { try { ctl.abort(); } catch (e) {} }, 2000) : null;
  fetch('http://127.0.0.1:7778/api/stats', ctl ? { signal: ctl.signal } : {})
    .then(function(r) { return r.json(); })
    .then(function(stats) {
      var el = document.getElementById('dbTotal');
      el.innerHTML = '<span class="db-num">' + (stats.total || 0) + '</span> giveaways in DB';
    })
    .catch(function() {
      document.getElementById('dbTotal').textContent = '';
    })
    .finally(function() { if (timer) clearTimeout(timer); });
}

// -- Init --------------------------------------------------------------

let _pollInterval = null;

document.addEventListener('DOMContentLoaded', function() {
  // First paint: one IPC for everything, then settings inputs.
  refreshState(function(state) {
    if (state) renderSettings(state);
  });
  updateDbTotal();

  // Poll for updates every 3 seconds while popup is open.
  // refreshState is a single sendMessage, vs. previously 4 per tick.
  _pollInterval = setInterval(function() {
    refreshState();
    updateDbTotal();
  }, 3000);

  document.getElementById('exportNewBtn').addEventListener('click', exportNew);
  document.getElementById('downloadBtn').addEventListener('click', downloadAll);
  document.getElementById('clearBtn').addEventListener('click', clearLinks);
  document.getElementById('thresholdInput').addEventListener('change', onThresholdChange);
  document.getElementById('prefetchToggle').addEventListener('change', onPrefetchToggle);
  document.getElementById('resetStats').addEventListener('click', resetEntryStats);
});

// Clean up the polling interval when the popup closes — otherwise the
// browser may keep waking the service worker every 3s for a moment.
window.addEventListener('pagehide', function() {
  if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
});
