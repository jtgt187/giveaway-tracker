// ── State ─────────────────────────────────────────────────────────────

let knownCount = 0;

// ── UI helpers ────────────────────────────────────────────────────────

function setStatus(msg, duration) {
  const el = document.getElementById('status');
  el.textContent = msg;
  if (duration) {
    setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, duration);
  }
}

// ── Update counter & unexported badge ─────────────────────────────────

function updateCount() {
  chrome.runtime.sendMessage({ type: 'get-count' }, function(response) {
    if (chrome.runtime.lastError || !response) return;

    const count = response.count;
    const unexported = response.unexported;
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

// ── Render recent links ───────────────────────────────────────────────

function updateRecentLinks() {
  chrome.runtime.sendMessage({ type: 'get-links' }, function(response) {
    if (chrome.runtime.lastError || !response || !response.links) return;

    const list = document.getElementById('recentList');
    const recent = response.links.slice(-5).reverse(); // last 5, newest first

    if (recent.length === 0) {
      list.innerHTML = '<div class="recent-empty">No links yet</div>';
      return;
    }

    list.innerHTML = recent.map(l => {
      const displayUrl = l.href.replace('https://', '').replace('http://', '');
      const label = l.text || displayUrl;
      const page = l.pageUrl ? new URL(l.pageUrl).hostname : '';
      return '<div class="recent-item">' +
        '<a href="' + escapeHtml(l.href) + '" target="_blank" title="' + escapeHtml(l.href) + '">' +
          escapeHtml(label.substring(0, 60)) +
        '</a>' +
        (page ? ' <span class="page">from ' + escapeHtml(page) + '</span>' : '') +
      '</div>';
    }).join('');
  });
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Export new links only ─────────────────────────────────────────────

function exportNew() {
  setStatus('Exporting new links...');
  chrome.runtime.sendMessage({ type: 'export-new' }, function(response) {
    if (chrome.runtime.lastError) {
      setStatus('Export failed: ' + chrome.runtime.lastError.message, 4000);
      return;
    }
    if (response && response.ok) {
      setStatus('Exported ' + response.exported + ' new links', 3000);
      updateCount();
    } else {
      setStatus(response ? response.error : 'Export failed', 3000);
    }
  });
}

// ── Download all links ────────────────────────────────────────────────

function downloadAll() {
  setStatus('Preparing download...');
  chrome.runtime.sendMessage({ type: 'download' }, function(response) {
    if (chrome.runtime.lastError) {
      setStatus('Download failed: ' + chrome.runtime.lastError.message, 4000);
      return;
    }
    if (response && response.ok) {
      setStatus('Downloaded! Links remain in collection.', 3000);
      updateCount();
    } else {
      setStatus(response ? response.error : 'Download failed', 3000);
    }
  });
}

// ── Clear all links ───────────────────────────────────────────────────

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

// ── Auto-export threshold setting ─────────────────────────────────────

function loadSettings() {
  chrome.runtime.sendMessage({ type: 'get-settings' }, function(response) {
    if (chrome.runtime.lastError || !response) return;
    document.getElementById('thresholdInput').value = response.autoExportThreshold || 0;
  });
}

function onThresholdChange() {
  const val = parseInt(document.getElementById('thresholdInput').value, 10) || 0;
  chrome.runtime.sendMessage({ type: 'set-auto-threshold', value: val }, function(response) {
    if (chrome.runtime.lastError) return;
    if (response && response.ok) {
      setStatus(val > 0 ? 'Auto-export every ' + val + ' links' : 'Auto-export disabled', 2000);
    }
  });
}

// ── Init ──────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  updateCount();
  updateRecentLinks();
  loadSettings();

  // Poll for updates every 3 seconds while popup is open
  setInterval(function() {
    updateCount();
    updateRecentLinks();
  }, 3000);

  document.getElementById('exportNewBtn').addEventListener('click', exportNew);
  document.getElementById('downloadBtn').addEventListener('click', downloadAll);
  document.getElementById('clearBtn').addEventListener('click', clearLinks);
  document.getElementById('thresholdInput').addEventListener('change', onThresholdChange);
});
