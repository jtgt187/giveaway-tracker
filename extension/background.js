let links = [];
let lastExportIndex = 0;       // tracks how many links have been exported
let autoExportThreshold = 0;   // 0 = disabled

// -- Auto-entry session stats ----------------------------------------
let entryStats = {
  lastUrl: '',
  lastTime: '',
  completed: 0,
  failed: 0,
  total: 0,
};

// -- Platform action script mapping ----------------------------------
const PLATFORM_SCRIPTS = {
  twitter:   'actions/x-follow.js',
  instagram: 'actions/instagram-follow.js',
  twitch:    'actions/twitch-follow.js',
  youtube:   'actions/youtube-subscribe.js',
  tiktok:    'actions/tiktok-follow.js',
};

// -- Persistence helpers ----------------------------------------------

function persist() {
  chrome.storage.local.set({
    gleam_links: links,
    gleam_last_export: lastExportIndex,
    gleam_auto_threshold: autoExportThreshold,
    gleam_entry_stats: entryStats
  });
}

function updateBadge() {
  const total = links.length;
  chrome.action.setBadgeText({ text: total > 0 ? String(total) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#10b981' });
}

// -- Restore state on startup -----------------------------------------

chrome.storage.local.get(
  ['gleam_links', 'gleam_last_export', 'gleam_auto_threshold', 'gleam_entry_stats'],
  (result) => {
    if (result.gleam_links) links = result.gleam_links;
    if (typeof result.gleam_last_export === 'number') lastExportIndex = result.gleam_last_export;
    if (typeof result.gleam_auto_threshold === 'number') autoExportThreshold = result.gleam_auto_threshold;
    if (result.gleam_entry_stats) entryStats = result.gleam_entry_stats;
    updateBadge();
  }
);

// -- Auto-export download (background-only, fire-and-forget) ---------
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

// -- Auto-export check ------------------------------------------------

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

// -- Social action tab orchestration ----------------------------------

/**
 * Open a URL in a background tab, inject a platform-specific action script,
 * wait for the result, and close the tab.
 *
 * @param {string} platform - Platform key (twitter, instagram, twitch, youtube, tiktok)
 * @param {string} targetUrl - URL to open (e.g. https://x.com/username)
 * @param {string} actionType - Action type (follow, subscribe, visit)
 * @returns {Promise<object>} - Result from the action script
 */
async function performSocialActionInTab(platform, targetUrl, actionType) {
  const scriptFile = PLATFORM_SCRIPTS[platform];
  if (!scriptFile) {
    return { success: false, error: 'Unknown platform: ' + platform };
  }

  let tabId = null;

  try {
    // Create a background tab
    const tab = await chrome.tabs.create({
      url: targetUrl,
      active: false,
    });
    tabId = tab.id;

    // Wait for the tab to finish loading
    await waitForTabLoad(tabId, 20000);

    // Give the page a moment to render dynamic content
    await sleep(2000);

    // Inject the action script
    const results = await chrome.scripting.executeScript({
      target: { tabId: tabId },
      files: [scriptFile],
    });

    // The script returns its result as the last expression value
    let result = { success: false, error: 'no_result' };
    if (results && results.length > 0 && results[0].result) {
      result = results[0].result;
    }

    // Update stats
    if (result.success) {
      entryStats.completed++;
    } else {
      entryStats.failed++;
    }
    entryStats.total++;
    persist();

    return result;

  } catch (e) {
    console.error('[GleamMonitor] Social action error:', e);
    entryStats.failed++;
    entryStats.total++;
    persist();
    return { success: false, error: e.message };
  } finally {
    // Always close the tab
    if (tabId) {
      try {
        await chrome.tabs.remove(tabId);
      } catch (e) {
        // Tab might already be closed
      }
    }
  }
}

/**
 * Open a URL in a background tab briefly for "visit" type entries.
 */
async function performVisitAction(targetUrl) {
  let tabId = null;

  try {
    const tab = await chrome.tabs.create({
      url: targetUrl,
      active: false,
    });
    tabId = tab.id;

    // Wait for load, then close after a few seconds
    await waitForTabLoad(tabId, 15000);
    await sleep(3000);

    return { success: true };

  } catch (e) {
    return { success: false, error: e.message };
  } finally {
    if (tabId) {
      try {
        await chrome.tabs.remove(tabId);
      } catch (e) {}
    }
  }
}

/**
 * Wait for a tab to finish loading.
 */
function waitForTabLoad(tabId, timeout) {
  return new Promise((resolve, reject) => {
    const start = Date.now();

    function check() {
      if (Date.now() - start > timeout) {
        resolve(); // Resolve anyway on timeout, let the script try
        return;
      }

      chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError) {
          reject(new Error('Tab not found'));
          return;
        }

        if (tab.status === 'complete') {
          resolve();
        } else {
          setTimeout(check, 500);
        }
      });
    }

    check();
  });
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// -- Message handler --------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // -- Append a newly found link --
  if (msg.type === 'append') {
    // Only store actual gleam.io URLs (defense-in-depth)
    try {
      const u = new URL(msg.href);
      if (u.hostname !== 'gleam.io' && !u.hostname.endsWith('.gleam.io')) {
        sendResponse({ count: links.length });
        return true;
      }
    } catch (e) {
      sendResponse({ count: links.length });
      return true;
    }

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

  // -- Get counts --
  if (msg.type === 'get-count') {
    sendResponse({
      count: links.length,
      unexported: links.length - lastExportIndex
    });
    return true;
  }

  // -- Get full link list --
  if (msg.type === 'get-links') {
    sendResponse({ links });
    return true;
  }

  // -- Get export data (links + index so popup can build the file) --
  if (msg.type === 'get-export-data') {
    sendResponse({ links, lastExportIndex });
    return true;
  }

  // -- Mark links as exported (called by popup after successful download) --
  if (msg.type === 'mark-exported') {
    const idx = parseInt(msg.upToIndex, 10);
    if (idx > lastExportIndex) {
      lastExportIndex = idx;
      persist();
    }
    sendResponse({ ok: true, lastExportIndex });
    return true;
  }

  // -- Clear everything --
  if (msg.type === 'clear') {
    links = [];
    lastExportIndex = 0;
    persist();
    updateBadge();
    sendResponse({ ok: true });
    return true;
  }

  // -- Get / set auto-export threshold --
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

  // -- Perform social action (follow/subscribe) in a background tab --
  if (msg.type === 'perform-social-action') {
    const { platform, targetUrl, actionType } = msg;

    entryStats.lastUrl = targetUrl;
    entryStats.lastTime = new Date().toISOString();

    performSocialActionInTab(platform, targetUrl, actionType)
      .then(result => {
        sendResponse(result);
      })
      .catch(err => {
        sendResponse({ success: false, error: err.message });
      });

    return true; // Keep message channel open for async response
  }

  // -- Perform visit action (open URL briefly) --
  if (msg.type === 'perform-visit-action') {
    performVisitAction(msg.targetUrl)
      .then(result => {
        sendResponse(result);
      })
      .catch(err => {
        sendResponse({ success: false, error: err.message });
      });

    return true;
  }

  // -- Get entry stats --
  if (msg.type === 'get-entry-stats') {
    sendResponse({ entryStats });
    return true;
  }

  // -- Reset entry stats --
  if (msg.type === 'reset-entry-stats') {
    entryStats = { lastUrl: '', lastTime: '', completed: 0, failed: 0, total: 0 };
    persist();
    sendResponse({ ok: true });
    return true;
  }

  return false;
});
