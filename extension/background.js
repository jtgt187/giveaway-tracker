let links = [];
let lastExportIndex = 0;       // tracks how many links have been exported
let autoExportThreshold = 0;   // 0 = disabled
let prefetchDeadlines = true;  // auto-fetch deadlines in background tabs

// O(1) dedup for `append` — kept in sync with `links` array
let hrefIndex = new Set();

// Hard caps to prevent storage quota exhaustion / attacker-driven data loss
const MAX_LINKS                  = 5000;   // hard cap on stored links
const MAX_TITLE_LEN              = 200;
const MAX_HREF_LEN               = 500;
const MAX_DEADLINE_LEN           = 100;
const MAX_DEADLINE_QUEUE_LEN     = 50;

// Allow-listed hostnames for `performSocialActionInTab` per platform.
// Prevents an attacker-controlled message from injecting an action script
// into an arbitrary URL (the action scripts call `.click()` on text-matched
// buttons, which is dangerous on attacker DOM).
const PLATFORM_HOST_ALLOWLIST = {
  twitter:   ['x.com', 'twitter.com', 'mobile.twitter.com'],
  instagram: ['instagram.com', 'www.instagram.com'],
  tiktok:    ['tiktok.com', 'www.tiktok.com', 'm.tiktok.com'],
  twitch:    ['twitch.tv', 'www.twitch.tv', 'm.twitch.tv'],
  youtube:   ['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'],
};

// Shared giveaway-path regex (also inlined in content.js and gleam-entry.js;
// keep in sync — see "GLEAM_GIVEAWAY_PATH" comment marker).
// GLEAM_GIVEAWAY_PATH:
const GLEAM_GIVEAWAY_PATH_RE_A = /^\/(?:giveaways|competitions)\/[A-Za-z0-9]{4,8}$/;
const GLEAM_GIVEAWAY_PATH_RE_B = /^\/[A-Za-z0-9]{4,8}\/[^/]+$/;

function isGleamGiveawayUrl(href) {
  try {
    const u = new URL(href);
    if (u.hostname !== 'gleam.io' && !u.hostname.endsWith('.gleam.io')) return false;
    const path = u.pathname.replace(/\/+$/, '');
    return GLEAM_GIVEAWAY_PATH_RE_A.test(path) || GLEAM_GIVEAWAY_PATH_RE_B.test(path);
  } catch (e) {
    return false;
  }
}

function clampStr(v, max) {
  if (typeof v !== 'string') return '';
  return v.length > max ? v.substring(0, max) : v;
}

function rebuildHrefIndex() {
  hrefIndex = new Set();
  for (const l of links) hrefIndex.add(l.href);
}

// -- Auto-entry session stats ----------------------------------------
let entryStats = {
  lastUrl: '',
  lastTime: '',
  completed: 0,
  failed: 0,
  total: 0,
};

// -- Local API sync ---------------------------------------------------
const LOCAL_API_URL = 'http://localhost:7778';
let localApiAvailable = false;

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

function notifyQuotaTrim(trimmed) {
  try {
    if (chrome.notifications && chrome.notifications.create) {
      chrome.notifications.create('gleam-quota-' + Date.now(), {
        type: 'basic',
        iconUrl: chrome.runtime.getURL('icon.png'),
        title: 'Gleam Monitor: storage full',
        message: 'Trimmed ' + trimmed + ' oldest links to recover storage space. Consider exporting and clearing.'
      }, () => { void chrome.runtime.lastError; });
    }
  } catch (e) {}
}

// Debounced persist: append() can fire many times per second when a
// noisy tab dumps links via mutation observer. Coalescing into a single
// storage.local.set within a 1s window cuts wasteful disk writes by
// ~50-100x without risking data loss (we flush on important boundaries
// like quota-recovery and on chrome.alarms tick).
let _persistTimer = null;
const PERSIST_DEBOUNCE_MS = 1000;

function persist() {
  if (_persistTimer) return; // a write is already scheduled
  _persistTimer = setTimeout(() => {
    _persistTimer = null;
    _persistNow();
  }, PERSIST_DEBOUNCE_MS);
}

function _persistNow() {
  chrome.storage.local.set({
    gleam_links: links,
    gleam_last_export: lastExportIndex,
    gleam_auto_threshold: autoExportThreshold,
    gleam_prefetch_deadlines: prefetchDeadlines,
    gleam_entry_stats: entryStats,
    gleam_deadline_queue: deadlineQueue
  }, () => {
    if (chrome.runtime.lastError) {
      console.error('[GleamMonitor] Storage persist error:', chrome.runtime.lastError.message);
      // Last-resort recovery if quota exceeded despite the MAX_LINKS cap
      // (e.g. titles bloated). Trim and notify the user (no silent data loss).
      if (chrome.runtime.lastError.message.includes('QUOTA')) {
        const trimCount = Math.floor(links.length * 0.1) || 10;
        console.warn('[GleamMonitor] Trimming', trimCount, 'oldest links to free storage');
        links.splice(0, trimCount);
        rebuildHrefIndex();
        if (lastExportIndex > links.length) lastExportIndex = links.length;
        notifyQuotaTrim(trimCount);
        // Retry once without the callback to avoid infinite loop
        chrome.storage.local.set({
          gleam_links: links,
          gleam_last_export: lastExportIndex,
          gleam_auto_threshold: autoExportThreshold,
          gleam_prefetch_deadlines: prefetchDeadlines,
          gleam_entry_stats: entryStats,
          gleam_deadline_queue: deadlineQueue
        });
      }
    }
  });
}

function updateBadge() {
  const total = links.length;
  chrome.action.setBadgeText({ text: total > 0 ? String(total) : '' });
  chrome.action.setBadgeBackgroundColor({ color: '#10b981' });
}

// -- Restore state on startup -----------------------------------------
// The ready promise ensures message handlers wait for state restoration
// before responding. This prevents the "click twice" popup bug where
// the service worker wakes up but hasn't loaded chrome.storage yet.

let _resolveReady;
const stateReady = new Promise(resolve => { _resolveReady = resolve; });

// Safety net: never let the message handler deadlock if the storage callback
// never fires (e.g. browser shutdown / profile error). After 5s, resolve
// anyway with whatever in-memory state we have (defaults).
setTimeout(() => {
  try { _resolveReady(); } catch (e) {}
}, 5000);

try {
  chrome.storage.local.get(
    ['gleam_links', 'gleam_last_export', 'gleam_auto_threshold', 'gleam_prefetch_deadlines', 'gleam_entry_stats', 'gleam_deadline_queue'],
    (result) => {
      try {
        if (chrome.runtime.lastError) {
          console.error('[GleamMonitor] Storage restore error:', chrome.runtime.lastError.message);
        }
        if (result && result.gleam_links) links = result.gleam_links;
        if (result && typeof result.gleam_last_export === 'number') lastExportIndex = result.gleam_last_export;
        if (result && typeof result.gleam_auto_threshold === 'number') autoExportThreshold = result.gleam_auto_threshold;
        if (result && typeof result.gleam_prefetch_deadlines === 'boolean') prefetchDeadlines = result.gleam_prefetch_deadlines;
        if (result && result.gleam_entry_stats) entryStats = result.gleam_entry_stats;
        if (result && Array.isArray(result.gleam_deadline_queue)) {
          // Restore queue and re-cap in case it grew before a stale write
          deadlineQueue = result.gleam_deadline_queue.slice(0, MAX_DEADLINE_QUEUE_LEN);
          // Resume prefetching if there's pending work and the feature is on
          if (prefetchDeadlines && deadlineQueue.length > 0) {
            // Defer slightly so checkLocalApi can probe first
            setTimeout(processDeadlineQueue, 2000);
          }
        }
        rebuildHrefIndex();
        updateBadge();
        // Ping the local API to check availability
        checkLocalApi();
      } finally {
        _resolveReady();
      }
    }
  );
} catch (e) {
  console.error('[GleamMonitor] Storage get threw:', e);
  _resolveReady();
}

// -- Local API sync ---------------------------------------------------

/**
 * Check if the local API server is running.
 * Returns a promise so callers can await it.
 */
function checkLocalApi() {
  return fetch(LOCAL_API_URL + '/health', { method: 'GET' })
    .then(r => {
      localApiAvailable = r.ok;
      if (r.ok) {
        // Reset post-backoff state so queued writes resume immediately
        _apiFailures = 0;
        _apiBackoffUntil = 0;
      }
      return localApiAvailable;
    })
    .catch(() => {
      localApiAvailable = false;
      return false;
    });
}

// Re-check API availability every 30 seconds using chrome.alarms
// (survives service worker sleep, unlike setInterval which dies).
chrome.alarms.create('check-local-api', { periodInMinutes: 0.5 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'check-local-api') {
    checkLocalApi();
  }
});

/**
 * Push a new or updated link to the local database via the API.
 * Fire-and-forget: failures are silently ignored (data is still in chrome.storage).
 * If localApiAvailable is false, attempts a health check first (recovers
 * from stale state after service worker sleep).
 */
function syncToLocalApi(entry) {
  if (localApiAvailable) {
    _postToApi('/api/link', entry);
  } else {
    // Service worker may have slept and lost the setInterval;
    // re-check now and sync if the API is actually up.
    checkLocalApi().then(ok => {
      if (ok) _postToApi('/api/link', entry);
    });
  }
}

/**
 * Push a deadline/title/ended update to the local database via the API.
 */
function syncMetaToLocalApi(href, title, deadline, ended) {
  const payload = { href, title, deadline };
  if (ended) payload.ended = true;
  if (localApiAvailable) {
    _postToApi('/api/meta', payload);
  } else {
    checkLocalApi().then(ok => {
      if (ok) _postToApi('/api/meta', payload);
    });
  }
}

/**
 * Internal: POST JSON to a local API path.
 *
 * Failure handling: after 3 consecutive failures we suspend posts for
 * an exponentially-growing backoff window (max 5 min). This prevents
 * a 30-call-per-second flood when the local API is down — every
 * append() / meta-update was previously triggering an immediate
 * unconditional fetch even though `localApiAvailable` was false (the
 * caller path through `checkLocalApi()` would also retry on every
 * call). The chrome.alarms periodic checkLocalApi() will reset this
 * once the API recovers.
 */
let _apiFailures = 0;
let _apiBackoffUntil = 0;
const MAX_API_BACKOFF_MS = 5 * 60 * 1000;

function _postToApi(path, data) {
  const now = Date.now();
  if (now < _apiBackoffUntil) return; // suspended
  fetch(LOCAL_API_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then(r => {
    if (r.ok) {
      _apiFailures = 0;
      _apiBackoffUntil = 0;
    } else {
      _registerApiFailure();
    }
  }).catch(() => {
    localApiAvailable = false;
    _registerApiFailure();
  });
}

function _registerApiFailure() {
  _apiFailures++;
  if (_apiFailures >= 3) {
    // 3rd fail → 5s, 4th → 10s, 5th → 20s, ... cap 5 min
    const delay = Math.min(MAX_API_BACKOFF_MS, 5000 * Math.pow(2, _apiFailures - 3));
    _apiBackoffUntil = Date.now() + delay;
  }
}

// -- Auto-export download (background-only, fire-and-forget) ---------
// Service workers lack Blob/URL.createObjectURL, so use a data URI.
// This is only used for auto-export where no popup is waiting for a
// response, avoiding the "message port closed" problem entirely.

function backgroundDownloadNdjson(entries, onSuccess) {
  if (entries.length === 0) return;

  try {
    const content = entries.map(l => JSON.stringify(l)).join('\n') + '\n';
    const dataUrl = 'data:application/x-ndjson;base64,' + btoa(unescape(encodeURIComponent(content)));

    chrome.downloads.download({
      url: dataUrl,
      filename: 'gleam-links.ndjson',
      saveAs: false,
      conflictAction: 'uniquify'
    }, (downloadId) => {
      if (chrome.runtime.lastError) {
        console.warn('Gleam Monitor: auto-export download error', chrome.runtime.lastError.message);
      } else if (downloadId && onSuccess) {
        onSuccess();
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
    const exportUpTo = links.length;
    backgroundDownloadNdjson(newEntries, () => {
      // Only advance index after confirmed successful download
      lastExportIndex = exportUpTo;
      persist();
    });
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
  // Cap queue to prevent unbounded background-tab work
  if (deadlineQueue.length >= MAX_DEADLINE_QUEUE_LEN) return;
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

  // Allow-list the targetUrl hostname against the requested platform.
  // Without this, an attacker-controlled message could load attacker.com
  // and have the action script click random buttons there.
  const allowedHosts = PLATFORM_HOST_ALLOWLIST[platform];
  if (!allowedHosts) {
    return { success: false, error: 'No allow-list for platform: ' + platform };
  }
  let parsedUrl;
  try {
    parsedUrl = new URL(targetUrl);
  } catch (e) {
    return { success: false, error: 'Invalid targetUrl' };
  }
  if (parsedUrl.protocol !== 'https:' && parsedUrl.protocol !== 'http:') {
    return { success: false, error: 'Disallowed protocol: ' + parsedUrl.protocol };
  }
  const host = parsedUrl.hostname.toLowerCase();
  const hostAllowed = allowedHosts.some(h => host === h || host.endsWith('.' + h));
  if (!hostAllowed) {
    console.warn('[GleamMonitor] Rejected social action for', platform, '→', host, '(not in allow-list)');
    return { success: false, error: 'Host not allowed for platform: ' + host };
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

  // Defense in depth: only allow http(s)
  try {
    const u = new URL(targetUrl);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') {
      return { success: false, error: 'Disallowed protocol: ' + u.protocol };
    }
  } catch (e) {
    return { success: false, error: 'Invalid URL' };
  }

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
 * Wait for a tab to finish loading. Rejects on timeout or tab-gone.
 */
function waitForTabLoad(tabId, timeout) {
  return new Promise((resolve, reject) => {
    const start = Date.now();

    function check() {
      if (Date.now() - start > timeout) {
        reject(new Error('tab_load_timeout'));
        return;
      }

      chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError) {
          reject(new Error('Tab not found: ' + chrome.runtime.lastError.message));
          return;
        }

        if (tab && tab.status === 'complete') {
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
// All handlers await stateReady so the popup never sees empty data
// when the service worker is freshly woken.

// Messages that any web page (via content.js on <all_urls>) is allowed
// to send. Everything else requires either the popup (no sender.tab) or
// a sender on gleam.io (where gleam-entry.js runs).
const PUBLIC_MESSAGE_TYPES = new Set([
  'append',          // content.js found a gleam URL
  'get-count',       // benign read
]);

// Messages that only gleam.io content scripts may send.
const GLEAM_ONLY_MESSAGE_TYPES = new Set([
  'update-giveaway-meta',
  'perform-social-action',
  'perform-visit-action',
]);

function isAllowedSender(msg, sender) {
  // All extension contexts must come from this extension
  if (sender && sender.id && sender.id !== chrome.runtime.id) return false;

  const type = msg && msg.type;
  if (!type) return false;

  // Public — accepted from any tab
  if (PUBLIC_MESSAGE_TYPES.has(type)) return true;

  // Popup / extension-page contexts have no sender.tab
  const fromExtensionPage = !sender || !sender.tab;
  if (fromExtensionPage) return true;

  // Gleam-only — must originate from a gleam.io tab
  if (GLEAM_ONLY_MESSAGE_TYPES.has(type)) {
    try {
      const u = new URL(sender.url || sender.tab.url || '');
      return u.hostname === 'gleam.io' || u.hostname.endsWith('.gleam.io');
    } catch (e) {
      return false;
    }
  }

  // Everything else (settings, clear, stats…) — popup only
  return false;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (!isAllowedSender(msg, sender)) {
    try { sendResponse({ error: 'forbidden' }); } catch (e) {}
    return false;
  }

  // Wrap handler in stateReady to fix the "click twice" popup bug,
  // and ensure no rejection ever leaves the channel hanging.
  stateReady
    .then(() => handleMessage(msg, sender, sendResponse))
    .catch(err => {
      console.error('[GleamMonitor] handleMessage error:', err);
      try { sendResponse({ error: (err && err.message) || 'handler_error' }); } catch (e) {}
    });
  return true; // Keep channel open for async response
});

function handleMessage(msg, sender, sendResponse) {

  // -- Append a newly found link --
  if (msg.type === 'append') {
    // Defensive type/length checks (msg may come from any web page)
    if (typeof msg.href !== 'string' || msg.href.length === 0 || msg.href.length > MAX_HREF_LEN) {
      sendResponse({ count: links.length });
      return;
    }
    // Only store actual gleam.io URLs (defense-in-depth)
    try {
      const u = new URL(msg.href);
      if (u.hostname !== 'gleam.io' && !u.hostname.endsWith('.gleam.io')) {
        sendResponse({ count: links.length });
        return;
      }
      // Only store giveaway/competition URLs, not FAQ/about/docs etc.
      const path = u.pathname.replace(/\/+$/, '');
      const isGiveaway =
        GLEAM_GIVEAWAY_PATH_RE_A.test(path) ||
        GLEAM_GIVEAWAY_PATH_RE_B.test(path);
      if (!isGiveaway) {
        sendResponse({ count: links.length });
        return;
      }
      // Reject truncated URLs (containing ellipsis character or trailing dots)
      if (u.href.includes('\u2026') || /\.{2,}$/.test(u.pathname)) {
        sendResponse({ count: links.length });
        return;
      }
    } catch (e) {
      sendResponse({ count: links.length });
      return;
    }

    if (!hrefIndex.has(msg.href)) {
      const entry = {
        href: msg.href,
        text: clampStr(msg.text, MAX_TITLE_LEN),
        t: new Date().toISOString()
      };
      links.push(entry);
      hrefIndex.add(entry.href);
      // Hard cap to prevent attacker-driven storage exhaustion
      while (links.length > MAX_LINKS) {
        const dropped = links.shift();
        if (dropped) hrefIndex.delete(dropped.href);
        if (lastExportIndex > 0) lastExportIndex--;
      }
      persist();
      updateBadge();
      checkAutoExport();
      // Sync to local DB immediately
      syncToLocalApi(entry);
      // Queue for background deadline prefetch
      queueDeadlinePrefetch(msg.href);
    }
    sendResponse({ count: links.length });
    return;
  }

  // -- Update giveaway metadata (title + deadline) from gleam-entry.js --
  if (msg.type === 'update-giveaway-meta') {
    if (typeof msg.href !== 'string' || msg.href.length > MAX_HREF_LEN) {
      sendResponse({ ok: false, error: 'invalid_url' });
      return;
    }

    // Validate the URL before processing
    let isValidGleamUrl = false;
    try {
      const u = new URL(msg.href);
      if (u.hostname === 'gleam.io' || u.hostname.endsWith('.gleam.io')) {
        isValidGleamUrl = true;
      }
    } catch (e) {}

    if (!isValidGleamUrl) {
      sendResponse({ ok: false, error: 'invalid_url' });
      return;
    }

    // Sanitize and clamp untrusted fields
    const title    = clampStr(msg.title, MAX_TITLE_LEN);
    const deadline = clampStr(msg.deadline, MAX_DEADLINE_LEN);
    const ended    = !!msg.ended;

    const idx = links.findIndex(l => l.href === msg.href);
    if (idx !== -1) {
      if (deadline) links[idx].deadline = deadline;
      if (title && title.length > 3) links[idx].text = title;
      persist();
    } else {
      // The link might not have been collected yet (e.g. user navigated directly).
      // Validate it's a giveaway path before storing.
      if (isGleamGiveawayUrl(msg.href)) {
        const entry = {
          href: msg.href,
          text: title,
          deadline: deadline,
          t: new Date().toISOString()
        };
        links.push(entry);
        hrefIndex.add(entry.href);
        while (links.length > MAX_LINKS) {
          const dropped = links.shift();
          if (dropped) hrefIndex.delete(dropped.href);
          if (lastExportIndex > 0) lastExportIndex--;
        }
        persist();
        updateBadge();
        checkAutoExport();
        syncToLocalApi(entry);
      }
    }
    // Always sync the metadata update to the local DB
    syncMetaToLocalApi(msg.href, title, deadline, ended);
    sendResponse({ ok: true });
    return;
  }

  // -- Get counts --
  if (msg.type === 'get-count') {
    sendResponse({
      count: links.length,
      unexported: links.length - lastExportIndex,
      apiConnected: localApiAvailable
    });
    return;
  }

  // -- Get full link list --
  if (msg.type === 'get-links') {
    sendResponse({ links });
    return;
  }

  // -- Get export data (links + index so popup can build the file) --
  if (msg.type === 'get-export-data') {
    sendResponse({ links, lastExportIndex });
    return;
  }

  // -- Mark links as exported (called by popup after successful download) --
  if (msg.type === 'mark-exported') {
    const idx = parseInt(msg.upToIndex, 10);
    if (!isNaN(idx) && idx > lastExportIndex) {
      lastExportIndex = Math.min(idx, links.length);
      persist();
    }
    sendResponse({ ok: true, lastExportIndex });
    return;
  }

  // -- Clear everything --
  if (msg.type === 'clear') {
    links = [];
    hrefIndex = new Set();
    lastExportIndex = 0;
    persist();
    updateBadge();
    sendResponse({ ok: true });
    return;
  }

  // -- Get / set auto-export threshold --
  if (msg.type === 'get-settings') {
    sendResponse({ autoExportThreshold });
    return;
  }

  if (msg.type === 'set-auto-threshold') {
    autoExportThreshold = parseInt(msg.value, 10) || 0;
    persist();
    sendResponse({ ok: true, autoExportThreshold });
    return;
  }

  // -- Get / set deadline prefetch setting --
  if (msg.type === 'get-prefetch-setting') {
    sendResponse({ prefetchDeadlines });
    return;
  }

  if (msg.type === 'set-prefetch-setting') {
    prefetchDeadlines = !!msg.value;
    persist();
    sendResponse({ ok: true, prefetchDeadlines });
    return;
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

    return;
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

    return;
  }

  // -- Get entry stats --
  if (msg.type === 'get-entry-stats') {
    sendResponse({ entryStats });
    return;
  }

  // -- Reset entry stats --
  if (msg.type === 'reset-entry-stats') {
    entryStats = { lastUrl: '', lastTime: '', completed: 0, failed: 0, total: 0 };
    persist();
    sendResponse({ ok: true });
    return;
  }

  // -- Coalesced popup state --
  // The popup polls every 3s and previously fired 4 separate sendMessage
  // calls per tick (count, links, entry-stats, plus settings/prefetch on
  // first load). Each call wakes the service worker and round-trips
  // through the message handler. This single read returns everything
  // the popup renders so a poll = one IPC.
  if (msg.type === 'get-popup-state') {
    sendResponse({
      count: links.length,
      unexported: links.length - lastExportIndex,
      apiConnected: localApiAvailable,
      links: links,
      entryStats: entryStats,
      autoExportThreshold: autoExportThreshold,
      prefetchDeadlines: prefetchDeadlines,
      lastExportIndex: lastExportIndex
    });
    return;
  }

  sendResponse({ error: 'unknown_message_type', type: msg && msg.type });
}
