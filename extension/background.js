let links = [];
let lastExportIndex = 0;       // tracks how many links have been exported
let autoExportThreshold = 0;   // 0 = disabled
let prefetchDeadlines = true;  // auto-fetch deadlines in background tabs

// -- Auto-entry session stats ----------------------------------------
let entryStats = {
  lastUrl: '',
  lastTime: '',
  completed: 0,
  failed: 0,
  total: 0,
};

// -- Deadline prefetch queue ------------------------------------------
let deadlineQueue = [];
let deadlinePrefetchRunning = false;

// -- Platform action script mapping ----------------------------------
// Keyed by `${platform}:${actionType}`, falling back to `${platform}:follow`
const PLATFORM_SCRIPTS = {
  'twitter:follow':     'actions/x-follow.js',
  'twitter:retweet':    'actions/x-retweet.js',
  'twitter:like':       'actions/x-like.js',
  'instagram:follow':   'actions/instagram-follow.js',
  'instagram:like':     'actions/instagram-like.js',
  'twitch:follow':      'actions/twitch-follow.js',
  'youtube:follow':     'actions/youtube-subscribe.js',
  'youtube:subscribe':  'actions/youtube-subscribe.js',
  'tiktok:follow':      'actions/tiktok-follow.js',
  'tiktok:like':        'actions/tiktok-like.js',
};

// Legacy lookup (platform-only) for backward compat
const PLATFORM_SCRIPTS_LEGACY = {
  twitter:   'actions/x-follow.js',
  instagram: 'actions/instagram-follow.js',
  twitch:    'actions/twitch-follow.js',
  youtube:   'actions/youtube-subscribe.js',
  tiktok:    'actions/tiktok-follow.js',
};

// Heavy SPA platforms need extra render time after tab.status === 'complete'
const PLATFORM_RENDER_DELAY = {
  instagram: 4000,
  tiktok:    4000,
  twitter:   3000,
  youtube:   2000,
  twitch:    2000,
};
const DEFAULT_RENDER_DELAY = 2000;

// -- Persistence helpers ----------------------------------------------

function persist() {
  chrome.storage.local.set({
    gleam_links: links,
    gleam_last_export: lastExportIndex,
    gleam_auto_threshold: autoExportThreshold,
    gleam_prefetch_deadlines: prefetchDeadlines,
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
  ['gleam_links', 'gleam_last_export', 'gleam_auto_threshold', 'gleam_prefetch_deadlines', 'gleam_entry_stats'],
  (result) => {
    if (result.gleam_links) links = result.gleam_links;
    if (typeof result.gleam_last_export === 'number') lastExportIndex = result.gleam_last_export;
    if (typeof result.gleam_auto_threshold === 'number') autoExportThreshold = result.gleam_auto_threshold;
    if (typeof result.gleam_prefetch_deadlines === 'boolean') prefetchDeadlines = result.gleam_prefetch_deadlines;
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
      conflictAction: 'uniquify'
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

// -- Deadline prefetch in background tabs -----------------------------

/**
 * Queue a link for background deadline prefetch.
 * Only queues if prefetching is enabled and the link has no deadline yet.
 */
function queueDeadlinePrefetch(href) {
  if (!prefetchDeadlines) return;
  // Check if already has a deadline
  const entry = links.find(l => l.href === href);
  if (entry && entry.deadline) return;
  // Don't queue duplicates
  if (deadlineQueue.includes(href)) return;
  deadlineQueue.push(href);
  processDeadlineQueue();
}

/**
 * Process the deadline prefetch queue one at a time.
 * Opens each gleam URL in a hidden background tab so gleam-entry.js
 * can auto-extract the deadline and send it back via update-giveaway-meta.
 * Waits a random 8-15s between items to avoid rate limiting.
 */
async function processDeadlineQueue() {
  if (deadlinePrefetchRunning) return; // Already processing
  if (deadlineQueue.length === 0) return;

  deadlinePrefetchRunning = true;

  while (deadlineQueue.length > 0) {
    const href = deadlineQueue.shift();

    // Re-check: might already have a deadline by now (e.g. user visited the page)
    const entry = links.find(l => l.href === href);
    if (entry && entry.deadline) continue;

    let tabId = null;
    try {
      // Open in a background tab — gleam-entry.js content script will auto-run
      const tab = await chrome.tabs.create({ url: href, active: false });
      tabId = tab.id;

      // Wait for page load
      await waitForTabLoad(tabId, 15000);

      // Give gleam-entry.js time to parse the page and send metadata
      await sleep(5000);

    } catch (e) {
      console.warn('[GleamMonitor] Deadline prefetch error for', href, e.message);
    } finally {
      if (tabId) {
        try { await chrome.tabs.remove(tabId); } catch (e) {}
      }
    }

    // Random delay 8-15s before the next one (appear more human, avoid rate limits)
    if (deadlineQueue.length > 0) {
      const delay = 8000 + Math.floor(Math.random() * 7000);
      await sleep(delay);
    }
  }

  deadlinePrefetchRunning = false;
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
  // Look up script: first try platform:actionType, then platform:follow, then legacy
  const scriptFile = PLATFORM_SCRIPTS[platform + ':' + actionType]
    || PLATFORM_SCRIPTS[platform + ':follow']
    || PLATFORM_SCRIPTS_LEGACY[platform];

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

    // Give the page time to render dynamic content (SPA-dependent)
    const renderDelay = PLATFORM_RENDER_DELAY[platform] || DEFAULT_RENDER_DELAY;
    await sleep(renderDelay);

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
      // Only store giveaway/competition URLs, not FAQ/about/docs etc.
      const path = u.pathname.replace(/\/+$/, '');
      const isGiveaway =
        /^\/(?:giveaways|competitions)\/[A-Za-z0-9]{4,6}$/.test(path) ||
        /^\/[A-Za-z0-9]{4,6}\/[^/]+$/.test(path);
      if (!isGiveaway) {
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
        t: new Date().toISOString()
      });
      persist();
      updateBadge();
      checkAutoExport();
      // Queue for background deadline prefetch
      queueDeadlinePrefetch(msg.href);
    }
    sendResponse({ count: links.length });
    return true;
  }

  // -- Update giveaway metadata (title + deadline) from gleam-entry.js --
  if (msg.type === 'update-giveaway-meta') {
    const idx = links.findIndex(l => l.href === msg.href);
    if (idx !== -1) {
      if (msg.deadline) links[idx].deadline = msg.deadline;
      if (msg.title && msg.title.length > 3) links[idx].text = msg.title;
      persist();
    } else {
      // The link might not have been collected yet (e.g. user navigated directly).
      // Store it as a new entry with metadata.
      links.push({
        href: msg.href,
        text: msg.title || '',
        deadline: msg.deadline || '',
        t: new Date().toISOString()
      });
      persist();
      updateBadge();
      checkAutoExport();
    }
    sendResponse({ ok: true });
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
    if (!isNaN(idx) && idx > lastExportIndex) {
      lastExportIndex = Math.min(idx, links.length);
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

  // -- Get / set deadline prefetch setting --
  if (msg.type === 'get-prefetch-setting') {
    sendResponse({ prefetchDeadlines });
    return true;
  }

  if (msg.type === 'set-prefetch-setting') {
    prefetchDeadlines = !!msg.value;
    persist();
    sendResponse({ ok: true, prefetchDeadlines });
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
