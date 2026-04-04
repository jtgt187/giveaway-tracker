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

function updateCount() {
  chrome.runtime.sendMessage({ type: 'get-count' }, function(response) {
    if (chrome.runtime.lastError || !response) return;

    var count = response.count;
    var unexported = response.unexported;
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
  });
}

// -- Render recent links -----------------------------------------------

function updateRecentLinks() {
  chrome.runtime.sendMessage({ type: 'get-links' }, function(response) {
    if (chrome.runtime.lastError || !response || !response.links) return;

    var list = document.getElementById('recentList');
    var recent = response.links.slice(-5).reverse(); // last 5, newest first

    if (recent.length === 0) {
      list.innerHTML = '<div class="recent-empty">No links yet</div>';
      return;
    }

    list.innerHTML = recent.map(function(l) {
      var displayUrl = l.href.replace('https://', '').replace('http://', '');
      var label = l.text || displayUrl;
      return '<div class="recent-item">' +
        '<a href="' + escapeHtml(l.href) + '" target="_blank" title="' + escapeHtml(l.href) + '">' +
          escapeHtml(label.substring(0, 60)) +
        '</a>' +
      '</div>';
    }).join('');
  });
}

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

function updateEntryStats() {
  chrome.runtime.sendMessage({ type: 'get-entry-stats' }, function(response) {
    if (chrome.runtime.lastError || !response || !response.entryStats) return;

    var stats = response.entryStats;
    document.getElementById('statTotal').textContent = stats.total || 0;
    document.getElementById('statCompleted').textContent = stats.completed || 0;
    document.getElementById('statFailed').textContent = stats.failed || 0;

    var lastEntryEl = document.getElementById('lastEntry');
    if (stats.lastUrl && stats.lastTime) {
      var timeAgo = getTimeAgo(stats.lastTime);
      var shortUrl = stats.lastUrl.replace('https://', '').replace('http://', '');
      if (shortUrl.length > 40) shortUrl = shortUrl.substring(0, 40) + '...';
      lastEntryEl.innerHTML = 'Last: <a href="' + escapeHtml(stats.lastUrl) + '" target="_blank">' +
        escapeHtml(shortUrl) + '</a> (' + timeAgo + ')';
    } else {
      lastEntryEl.textContent = 'No entries yet';
    }
  });
}

function getTimeAgo(isoString) {
  var diff = Date.now() - new Date(isoString).getTime();
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
      updateEntryStats();
    }
  });
}

// -- Auto-export threshold setting -------------------------------------

function loadSettings() {
  chrome.runtime.sendMessage({ type: 'get-settings' }, function(response) {
    if (chrome.runtime.lastError || !response) return;
    document.getElementById('thresholdInput').value = response.autoExportThreshold || 0;
  });
}

function onThresholdChange() {
  var val = parseInt(document.getElementById('thresholdInput').value, 10) || 0;
  chrome.runtime.sendMessage({ type: 'set-auto-threshold', value: val }, function(response) {
    if (chrome.runtime.lastError) return;
    if (response && response.ok) {
      setStatus(val > 0 ? 'Auto-export every ' + val + ' links' : 'Auto-export disabled', 2000);
    }
  });
}

// -- Init --------------------------------------------------------------

document.addEventListener('DOMContentLoaded', function() {
  updateCount();
  updateRecentLinks();
  updateEntryStats();
  loadSettings();

  // Poll for updates every 3 seconds while popup is open
  setInterval(function() {
    updateCount();
    updateRecentLinks();
    updateEntryStats();
  }, 3000);

  document.getElementById('exportNewBtn').addEventListener('click', exportNew);
  document.getElementById('downloadBtn').addEventListener('click', downloadAll);
  document.getElementById('clearBtn').addEventListener('click', clearLinks);
  document.getElementById('thresholdInput').addEventListener('change', onThresholdChange);
  document.getElementById('resetStats').addEventListener('click', resetEntryStats);
});
