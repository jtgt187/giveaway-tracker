// Gleam.io Auto-Entry Content Script
// Runs on gleam.io pages to parse entry methods and provide auto-entry UI.
(function () {
  'use strict';

  // -- Guard: only run on competition/giveaway pages --------------------
  const path = location.pathname;
  // Gleam competition URLs look like: /competitions/xxxxx/yyyy or /xxxxx/yyyy
  // Skip non-competition pages like /login, /account, etc.
  // Note: /giveaways/XXXXX is a valid giveaway URL, so only skip /giveaways exactly
  const skipPathsExact = ['/giveaways', '/login', '/signup', '/account', '/settings', '/privacy', '/terms'];
  if (skipPathsExact.some(p => path === p || path === p + '/')) return;
  // Must have at least one path segment after domain
  if (path === '/' || path === '') return;

  // -- Constants --------------------------------------------------------
  const WIDGET_POLL_INTERVAL = 500;
  const WIDGET_POLL_TIMEOUT = 15000;
  const ENTRY_DELAY_MS = 2500;
  const SOCIAL_ACTION_DELAY_MS = 3000;

  // Platform detection patterns from entry method DOM
  const PLATFORM_PATTERNS = {
    twitter: {
      icons: ['fa-twitter', 'fa-x-twitter', 'icon-twitter'],
      textMatches: ['twitter', 'tweet', 'retweet', 'x.com', '@'],
      urlPatterns: ['twitter.com', 'x.com'],
      actionScript: 'actions/x-follow.js',
      label: 'X/Twitter',
      cssClass: 'twitter',
    },
    instagram: {
      icons: ['fa-instagram', 'icon-instagram'],
      textMatches: ['instagram', 'insta'],
      urlPatterns: ['instagram.com'],
      actionScript: 'actions/instagram-follow.js',
      label: 'Instagram',
      cssClass: 'instagram',
    },
    twitch: {
      icons: ['fa-twitch', 'icon-twitch'],
      textMatches: ['twitch'],
      urlPatterns: ['twitch.tv'],
      actionScript: 'actions/twitch-follow.js',
      label: 'Twitch',
      cssClass: 'twitch',
    },
    youtube: {
      icons: ['fa-youtube', 'fa-youtube-play', 'icon-youtube'],
      textMatches: ['youtube', 'subscribe', 'channel'],
      urlPatterns: ['youtube.com', 'youtu.be'],
      actionScript: 'actions/youtube-subscribe.js',
      label: 'YouTube',
      cssClass: 'youtube',
    },
    tiktok: {
      icons: ['fa-tiktok', 'icon-tiktok'],
      textMatches: ['tiktok', 'tik tok'],
      urlPatterns: ['tiktok.com'],
      actionScript: 'actions/tiktok-follow.js',
      label: 'TikTok',
      cssClass: 'tiktok',
    },
  };

  // Action types we can automate (kept for reference / future feature
  // gating). Not currently consumed at runtime — detectActionType()
  // returns the matched string directly and the dispatcher trusts it.
  // Leaving as a code-level allow-list documents what we expect to see.
  // const AUTOMATABLE_ACTIONS = ['follow', 'subscribe', 'visit', 'view', 'click', 'watch', 'retweet', 'like', 'share'];

  // -- State ------------------------------------------------------------
  let entryMethods = [];
  let isRunning = false;
  let abortRequested = false;
  let overlay = null;

  // -- Utility ----------------------------------------------------------

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  // Cap on log entries kept in DOM to prevent unbounded growth on long sessions
  const MAX_LOG_ENTRIES = 100;

  // Track active timers/intervals so they can be cleaned up on pagehide
  const _activeIntervals = new Set();
  const _activeTimeouts = new Set();
  function _trackInterval(id) { _activeIntervals.add(id); return id; }
  function _trackTimeout(id) { _activeTimeouts.add(id); return id; }
  function _clearAllTimers() {
    _activeIntervals.forEach(id => { try { clearInterval(id); } catch (e) {} });
    _activeTimeouts.forEach(id => { try { clearTimeout(id); } catch (e) {} });
    _activeIntervals.clear();
    _activeTimeouts.clear();
  }
  window.addEventListener('pagehide', _clearAllTimers, { once: true });

  function log(msg, level) {
    const logEl = document.querySelector('.gae-log');
    if (!logEl) {
      console.log('[GleamAutoEntry]', msg);
      return;
    }
    logEl.classList.add('active');
    const entry = document.createElement('div');
    entry.className = 'gae-log-entry ' + (level || '');
    entry.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    logEl.appendChild(entry);
    // Trim oldest log entries to prevent unbounded DOM growth
    while (logEl.childNodes.length > MAX_LOG_ENTRIES) {
      logEl.removeChild(logEl.firstChild);
    }
    logEl.scrollTop = logEl.scrollHeight;
    console.log('[GleamAutoEntry]', msg);
  }

  // -- Widget Detection ------------------------------------------------

  function waitForWidget() {
    return new Promise(function (resolve) {
      const start = Date.now();
      var timer = setInterval(function () {
        // Look for Gleam's AngularJS widget container
        var widget = document.querySelector('.ng-scope')
          || document.querySelector('.incentive-description')
          || document.querySelector('[ng-app]')
          || document.querySelector('.entry-method')
          || document.querySelector('.gleam-comp');

        if (widget) {
          clearInterval(timer);
          _activeIntervals.delete(timer);
          resolve(widget);
          return;
        }

        if (Date.now() - start > WIDGET_POLL_TIMEOUT) {
          clearInterval(timer);
          _activeIntervals.delete(timer);
          resolve(null);
        }
      }, WIDGET_POLL_INTERVAL);
      _trackInterval(timer);
    });
  }

  // -- Entry Method Parsing --------------------------------------------

  function detectPlatform(element) {
    var html = element.innerHTML.toLowerCase();
    var text = (element.textContent || '').toLowerCase();
    var classes = (element.className || '').toLowerCase();

    // Check each platform
    for (var key in PLATFORM_PATTERNS) {
      var platform = PLATFORM_PATTERNS[key];

      // Check icons (font-awesome classes)
      for (var i = 0; i < platform.icons.length; i++) {
        if (html.indexOf(platform.icons[i]) !== -1 || classes.indexOf(platform.icons[i]) !== -1) {
          return key;
        }
      }

      // Check text content
      for (var j = 0; j < platform.textMatches.length; j++) {
        if (text.indexOf(platform.textMatches[j]) !== -1) {
          return key;
        }
      }

      // Check URLs within the element
      var links = element.querySelectorAll('a[href]');
      for (var k = 0; k < links.length; k++) {
        var href = links[k].href.toLowerCase();
        for (var m = 0; m < platform.urlPatterns.length; m++) {
          if (href.indexOf(platform.urlPatterns[m]) !== -1) {
            return key;
          }
        }
      }
    }

    return 'generic';
  }

  function detectActionType(text) {
    var lower = text.toLowerCase();
    if (lower.indexOf('follow') !== -1) return 'follow';
    if (lower.indexOf('subscribe') !== -1) return 'subscribe';
    if (lower.indexOf('visit') !== -1) return 'visit';
    if (lower.indexOf('view') !== -1) return 'view';
    if (lower.indexOf('watch') !== -1) return 'watch';
    if (lower.indexOf('retweet') !== -1) return 'retweet';
    // Check 'click' before 'like' to avoid false-matches in phrases like
    // "click the link below" where "like" is a substring of "link".
    if (lower.indexOf('click') !== -1 || lower.indexOf('enter') !== -1) return 'click';
    if (/\blike\b/.test(lower)) return 'like';
    if (lower.indexOf('tweet') !== -1) return 'tweet';
    if (lower.indexOf('share') !== -1) return 'share';
    if (lower.indexOf('comment') !== -1) return 'comment';
    return 'unknown';
  }

  function extractTargetUrl(element) {
    // Score each candidate href and return the best match. We previously
    // returned the first href that matched any platform, which on entries
    // like "Visit X and tweet about Y" would happily return a CDN avatar
    // URL or a tracking redirect. Scoring prefers:
    //   +3 if href matches a known platform domain
    //   +2 if href appears in an <a> with non-trivial text (likely the CTA)
    //   +1 if href is on an https:// URL (cosmetic / spam-bait filter)
    //   -2 if href looks like an asset (svg/png/jpg/css/js) or analytics
    var links = element.querySelectorAll('a[href]');
    var best = null;
    var bestScore = -Infinity;
    for (var i = 0; i < links.length; i++) {
      var a = links[i];
      var href = a.href;
      if (!href || href.indexOf('gleam.io') !== -1) continue;
      if (href.indexOf('javascript:') === 0) continue;
      if (href.indexOf('mailto:') === 0) continue;

      var score = 0;
      var lowerHref = href.toLowerCase();
      var matchedPlatform = false;
      for (var key in PLATFORM_PATTERNS) {
        var patterns = PLATFORM_PATTERNS[key].urlPatterns;
        for (var j = 0; j < patterns.length; j++) {
          if (lowerHref.indexOf(patterns[j]) !== -1) { matchedPlatform = true; break; }
        }
        if (matchedPlatform) break;
      }
      if (matchedPlatform) score += 3;

      var aText = (a.textContent || '').trim();
      if (aText.length > 2) score += 2;

      if (lowerHref.indexOf('https://') === 0) score += 1;

      if (/\.(?:svg|png|jpg|jpeg|gif|webp|css|js|ico)(?:[?#]|$)/.test(lowerHref)) score -= 2;
      if (/(?:google-analytics|doubleclick|googletagmanager|adservice)/.test(lowerHref)) score -= 2;

      if (score > bestScore) { bestScore = score; best = href; }
    }
    if (best && bestScore > 0) return best;

    // Try ng-click or data attributes for the URL
    var ngClick = element.querySelector('[ng-click]');
    if (ngClick) {
      var clickAttr = ngClick.getAttribute('ng-click') || '';
      var urlMatch = clickAttr.match(/https?:\/\/[^\s'"]+/);
      if (urlMatch) return urlMatch[0];
    }

    var dataUrl = element.getAttribute('data-url') || element.getAttribute('data-href');
    if (dataUrl) return dataUrl;

    // Fall back to the first non-gleam link even if it scored 0
    return best;
  }

  function isEntryCompleted(element) {
    // Strongest signal: Angular ng-class actually applied a completion class
    if (element.classList.contains('completed')
        || element.classList.contains('entered')
        || element.classList.contains('done')
        || element.classList.contains('em-action-success')) {
      return true;
    }

    // Visible green checkmark (Gleam swaps to fa-check on success).
    // Don't trust the icon being present in the DOM — Gleam pre-renders
    // hidden icons for animation. Require it to be visible.
    var checkIcons = element.querySelectorAll('.fa-check, .fa-check-circle, .icon-check');
    for (var i = 0; i < checkIcons.length; i++) {
      var icon = checkIcons[i];
      var style = window.getComputedStyle(icon);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      // Must also have non-zero size — getComputedStyle returns "block"
      // for elements with display set but offsetParent === null.
      if (icon.offsetWidth === 0 && icon.offsetHeight === 0) continue;
      return true;
    }

    return false;
  }

  function extractPoints(element) {
    // Look for points/bonus indicators
    var pointsEl = element.querySelector('.points, .bonus, .entry-count, [class*="point"]');
    if (pointsEl) {
      var match = (pointsEl.textContent || '').match(/\+?\s*(\d+)/);
      if (match) return parseInt(match[1], 10);
    }

    // Check text content for "+N" pattern
    var text = element.textContent || '';
    var pointMatch = text.match(/\+\s*(\d+)\s*(?:entr|point|bonus)/i);
    if (pointMatch) return parseInt(pointMatch[1], 10);

    return 1;
  }

  function parseEntryMethods() {
    var methods = [];

    // Primary selectors for Gleam entry methods
    var selectors = [
      '.entry-method',
      '[ng-repeat*="entry_method"]',
      '[ng-repeat*="entryMethod"]',
      '.incentive-row',
      '.contest-entry',
    ];

    // Collect from all selectors and dedupe — Gleam often double-tags rows
    // with both .entry-method and ng-repeat, so iterating selectors with
    // "first match wins" silently drops valid rows on some templates.
    var elementsSet = new Set();
    for (var s = 0; s < selectors.length; s++) {
      var found = document.querySelectorAll(selectors[s]);
      for (var k = 0; k < found.length; k++) elementsSet.add(found[k]);
    }
    var elements = Array.from(elementsSet);

    // Fallback: look for clickable entry items in the widget
    if (elements.length === 0) {
      // Try to find the main entry container
      var container = document.querySelector('.incentive-description, .gleam-comp, .entry-methods, [class*="entry"]');
      if (container) {
        // Look for repeated child elements that look like entry rows
        var children = container.children;
        var candidates = [];
        for (var c = 0; c < children.length; c++) {
          if (children[c].querySelector('a, button, [ng-click]')) {
            candidates.push(children[c]);
          }
        }
        if (candidates.length >= 2) {
          elements = candidates;
        }
      }
    }

    // Filter out nested matches (one entry-method containing another)
    // by skipping any element that is a descendant of another in the set.
    var topLevel = [];
    for (var a = 0; a < elements.length; a++) {
      var isNested = false;
      for (var b = 0; b < elements.length; b++) {
        if (a !== b && elements[b].contains(elements[a])) { isNested = true; break; }
      }
      if (!isNested) topLevel.push(elements[a]);
    }
    elements = topLevel;

    for (var i = 0; i < elements.length; i++) {
      var el = elements[i];
      var text = (el.textContent || '').trim();
      var platform = detectPlatform(el);
      var actionType = detectActionType(text);
      var targetUrl = extractTargetUrl(el);
      var completed = isEntryCompleted(el);
      var points = extractPoints(el);

      // Clean up the display text
      var displayText = text.replace(/\s+/g, ' ').substring(0, 80);

      methods.push({
        index: i,
        element: el,
        platform: platform,
        actionType: actionType,
        targetUrl: targetUrl,
        completed: completed,
        points: points,
        displayText: displayText,
        status: completed ? 'done' : 'pending',
      });
    }

    return methods;
  }

  // -- Giveaway Info Extraction ----------------------------------------

  // Status messages that Gleam shows instead of a real title when the
  // competition is paused, ended, or unavailable.  Matched case-insensitively.
  var BAD_TITLES = [
    'competition paused',
    'competition ended',
    'competition has ended',
    'this competition has ended',
    'this giveaway has ended',
    'this promotion has ended',
    'giveaway ended',
    'giveaway has ended',
    'entries are now closed',
    'gleam giveaway',
  ];

  function isBadTitle(text) {
    var lower = text.toLowerCase();
    // Substring match (was exact equality, which missed titles like
    // "🎉 This giveaway has ended!" or "Sorry — competition ended.")
    for (var i = 0; i < BAD_TITLES.length; i++) {
      if (lower.indexOf(BAD_TITLES[i]) !== -1) return true;
    }
    return false;
  }

  function extractGiveawayTitle() {
    var selectors = [
      '.competition-title',
      '.incentive-title',
      'h1.ng-binding',
      '.campaign-title',
      'h1',
      'h2.ng-binding',
    ];

    for (var i = 0; i < selectors.length; i++) {
      var el = document.querySelector(selectors[i]);
      if (el) {
        var text = (el.textContent || '').trim();
        if (text.length > 3 && !isBadTitle(text)) return text;
      }
    }

    // Fallback: document.title (also filtered)
    var docTitle = (document.title || '').trim();
    if (docTitle.length > 3 && !isBadTitle(docTitle)) return docTitle;

    return '';
  }

  // Extract the giveaway deadline/end date from the Gleam widget.
  // Gleam typically shows a countdown timer or an end-date element.
  function extractDeadline() {
    // Priority 1: Gleam's gl-countdown element carries a data-ends Unix timestamp.
    // This is the most reliable source and works on both standalone and embedded pages.
    var countdownEl = document.querySelector('[gl-countdown][data-ends]')
      || document.querySelector('.square-describe[data-ends]');
    if (countdownEl) {
      var endTs = parseInt(countdownEl.getAttribute('data-ends'), 10);
      if (endTs > 0) {
        // Convert Unix timestamp to ISO-like date string the backend can parse
        var d = new Date(endTs * 1000);
        // Format: "DD Month YYYY at HH:MM:SS" (matches backend parse_deadline patterns)
        var months = ['January','February','March','April','May','June',
                      'July','August','September','October','November','December'];
        return d.getDate() + ' ' + months[d.getMonth()] + ' ' + d.getFullYear()
          + ' at ' + String(d.getHours()).padStart(2,'0')
          + ':' + String(d.getMinutes()).padStart(2,'0')
          + ':' + String(d.getSeconds()).padStart(2,'0');
      }
    }

    // Priority 2: Try common selectors for Gleam countdown/timer/end-date elements
    var timerSelectors = [
      '.countdown',
      '.competition-countdown',
      '.incentive-timer',
      '.timer',
      '.ends-at',
      '.end-date',
      '.competition-ends',
      '[ng-bind*="countdown"]',
      '[ng-bind*="end"]',
      '[ng-bind*="timer"]',
      '[class*="countdown"]',
      '[class*="timer"]',
      '[class*="deadline"]',
    ];

    for (var i = 0; i < timerSelectors.length; i++) {
      var el = document.querySelector(timerSelectors[i]);
      if (el) {
        var text = (el.textContent || '').trim();
        // Must contain something that looks like a date or time span
        if (text.length > 3 && /\d/.test(text)) return text;
      }
    }

    // Fallback: scan the page text for date patterns near "end" / "closes" / "deadline"
    var body = document.body ? document.body.textContent || '' : '';

    // Pattern: "Ends Friday 03 April 2026 at 22:59:59" or similar
    var endDateMatch = body.match(
      /(?:ends?|closing|closes?|deadline|expires?)[:\s]+(\w+\s+\d{1,2}\s+\w+\s+\d{4}(?:\s+at\s+\d{2}:\d{2}(?::\d{2})?)?)/i
    );
    if (endDateMatch) return endDateMatch[1].trim();

    // Pattern: "03 April 2026" near end-related keywords (within 50 chars)
    var dateNearEnd = body.match(
      /(?:ends?|closing|closes?|deadline|expires?).{0,50}?(\d{1,2}\s+\w+\s+\d{4}(?:\s+at\s+\d{2}:\d{2}(?::\d{2})?)?)/i
    );
    if (dateNearEnd) return dateNearEnd[1].trim();

    return '';
  }

  // Detect if the giveaway has ended using Gleam's DOM elements.
  // Checks the gl-countdown element for past data-ends timestamps and "Ended" status text.
  function detectEnded() {
    // Check gl-countdown data-ends attribute — if end timestamp is in the past, it's ended
    var countdownEl = document.querySelector('[gl-countdown][data-ends]')
      || document.querySelector('.square-describe[data-ends]');
    if (countdownEl) {
      var endTs = parseInt(countdownEl.getAttribute('data-ends'), 10);
      if (endTs > 0 && endTs * 1000 < Date.now()) return true;
      // Also check for the one-line class (Gleam adds this when ended)
      if (countdownEl.classList.contains('one-line')) return true;
    }

    // Check for "Ended" text in the status span within the countdown element
    var statusEls = document.querySelectorAll('.square-describe .status');
    for (var i = 0; i < statusEls.length; i++) {
      var text = (statusEls[i].textContent || '').trim().toLowerCase();
      if (text === 'ended') return true;
    }

    // Fall back to existing keyword-based detection on page text
    var bodyText = (document.body ? document.body.textContent || '' : '').toLowerCase();
    for (var j = 0; j < BAD_TITLES.length; j++) {
      if (bodyText.indexOf(BAD_TITLES[j]) !== -1) return true;
    }

    return false;
  }

  // Normalize a gleam URL (same logic as content.js)
  function normalizeGleamUrl(urlStr) {
    try {
      var u = new URL(urlStr);
      if (u.hostname.indexOf('gleam.io') !== -1) {
        u.search = '';
        u.hash = '';
        return u.toString().replace(/\/+$/, '');
      }
      return urlStr;
    } catch (e) {
      return urlStr;
    }
  }

  // Send giveaway metadata (title + deadline + ended status) to the background script
  // so it can be stored alongside the link entry and exported in NDJSON.
  function sendGiveawayMeta() {
    var title = extractGiveawayTitle();
    var deadline = extractDeadline();
    var ended = detectEnded();
    var href = normalizeGleamUrl(location.href);

    chrome.runtime.sendMessage({
      type: 'update-giveaway-meta',
      href: href,
      title: title,
      deadline: deadline,
      ended: ended,
    }, function(response) {
      if (chrome.runtime.lastError) {
        console.warn('[GleamAutoEntry] sendGiveawayMeta error:', chrome.runtime.lastError.message);
      } else {
        console.log('[GleamAutoEntry] Metadata sent — title:', title, 'deadline:', deadline, 'ended:', ended);
      }
    });
  }

  // -- Overlay UI ------------------------------------------------------

  function createOverlay() {
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'gleam-auto-entry-overlay';

    var totalEntries = entryMethods.length;
    var completedEntries = entryMethods.filter(function (m) { return m.status === 'done' || m.status === 'attempted'; }).length;
    var pendingEntries = entryMethods.filter(function (m) { return m.status === 'pending'; }).length;

    overlay.innerHTML =
      '<div class="gae-header">' +
      '  <span class="gae-header-title">Auto Entry</span>' +
      '  <button class="gae-header-close" id="gae-close" title="Close">&times;</button>' +
      '</div>' +
      '<div class="gae-info">' +
      '  <div class="gae-giveaway-title">' + escapeHtml(extractGiveawayTitle()) + '</div>' +
      '  <div class="gae-stats">' +
      '    <span>Total: <span class="gae-stat-value">' + totalEntries + '</span></span>' +
      '    <span>Done: <span class="gae-stat-value">' + completedEntries + '</span></span>' +
      '    <span>Pending: <span class="gae-stat-value" id="gae-pending-count">' + pendingEntries + '</span></span>' +
      '  </div>' +
      '</div>' +
      '<div class="gae-entries" id="gae-entry-list"></div>' +
      '<div class="gae-progress" id="gae-progress">' +
      '  <div class="gae-progress-bar"><div class="gae-progress-fill" id="gae-progress-fill"></div></div>' +
      '  <div class="gae-progress-text" id="gae-progress-text"></div>' +
      '</div>' +
      '<div class="gae-log" id="gae-log"></div>' +
      '<div class="gae-footer">' +
      '  <button class="gae-btn gae-btn-secondary" id="gae-rescan">Rescan</button>' +
      '  <button class="gae-btn gae-btn-danger" id="gae-abort" style="display:none;">Stop</button>' +
      '  <button class="gae-btn gae-btn-primary" id="gae-enter-all"' +
      (pendingEntries === 0 ? ' disabled' : '') + '>Enter All (' + pendingEntries + ')</button>' +
      '</div>';

    document.body.appendChild(overlay);
    renderEntryList();
    bindOverlayEvents();
  }

  function renderEntryList() {
    var listEl = document.getElementById('gae-entry-list');
    if (!listEl) return;

    var html = '';
    for (var i = 0; i < entryMethods.length; i++) {
      var m = entryMethods[i];
      var platformInfo = PLATFORM_PATTERNS[m.platform] || { label: 'Other', cssClass: 'generic' };
      var iconClass = platformInfo.cssClass || 'generic';
      var iconLetter = (platformInfo.label || 'O').charAt(0);

      var statusClass = m.status;
      var statusIcon = '';
      if (m.status === 'done') statusIcon = '&#10003;';
      else if (m.status === 'failed') statusIcon = '&#10007;';
      else if (m.status === 'attempted') statusIcon = '&#63;';
      else if (m.status === 'skipped') statusIcon = '&#8211;';
      else if (m.status === 'running') statusIcon = '';
      else statusIcon = '&#8226;';

      html +=
        '<div class="gae-entry-item" data-index="' + i + '">' +
        '  <div class="gae-entry-icon ' + iconClass + '">' + iconLetter + '</div>' +
        '  <div class="gae-entry-text" title="' + escapeHtml(m.displayText) + '">' +
        escapeHtml(m.displayText) +
        '  </div>' +
        '  <div class="gae-entry-points">+' + m.points + '</div>' +
        '  <div class="gae-entry-status ' + statusClass + '">' + statusIcon + '</div>' +
        '</div>';
    }

    listEl.innerHTML = html || '<div style="padding:16px;text-align:center;color:#666;">No entry methods found</div>';
  }

  function updateEntryStatus(index, status) {
    if (index < 0 || index >= entryMethods.length) return;
    entryMethods[index].status = status;

    var item = document.querySelector('.gae-entry-item[data-index="' + index + '"]');
    if (!item) return;

    var statusEl = item.querySelector('.gae-entry-status');
    if (statusEl) {
      statusEl.className = 'gae-entry-status ' + status;
      if (status === 'done') statusEl.innerHTML = '&#10003;';
      else if (status === 'failed') statusEl.innerHTML = '&#10007;';
      else if (status === 'attempted') statusEl.innerHTML = '&#63;';
      else if (status === 'skipped') statusEl.innerHTML = '&#8211;';
      else if (status === 'running') statusEl.innerHTML = '';
      else statusEl.innerHTML = '&#8226;';
    }
  }

  function updateProgress(current, total, text) {
    var progressEl = document.getElementById('gae-progress');
    var fillEl = document.getElementById('gae-progress-fill');
    var textEl = document.getElementById('gae-progress-text');

    if (progressEl) progressEl.classList.add('active');
    if (fillEl) fillEl.style.width = (total > 0 ? Math.round((current / total) * 100) : 0) + '%';
    if (textEl) textEl.textContent = text || (current + ' / ' + total);
  }

  function bindOverlayEvents() {
    var closeBtn = document.getElementById('gae-close');
    var enterAllBtn = document.getElementById('gae-enter-all');
    var rescanBtn = document.getElementById('gae-rescan');
    var abortBtn = document.getElementById('gae-abort');

    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        // Closing while running implicitly aborts the loop so we don't
        // leave a detached process driving DOM that no longer exists.
        abortRequested = true;
        if (overlay) overlay.remove();
        overlay = null;
      });
    }

    if (enterAllBtn) {
      enterAllBtn.addEventListener('click', function () {
        if (!isRunning) startAutoEntry();
      });
    }

    if (rescanBtn) {
      rescanBtn.addEventListener('click', function () {
        if (!isRunning) {
          entryMethods = parseEntryMethods();
          createOverlay();
          log('Rescanned: found ' + entryMethods.length + ' entry methods', 'info');
        }
      });
    }

    if (abortBtn) {
      abortBtn.addEventListener('click', function () {
        if (isRunning) {
          abortRequested = true;
          abortBtn.disabled = true;
          abortBtn.textContent = 'Stopping…';
          log('Stop requested — finishing current entry, then halting.', 'warn');
        }
      });
    }
  }

  function escapeHtml(str) {
    // Defensive: stringify everything so a non-string title (e.g. number,
    // null, undefined) doesn't throw on .replace.
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      // Apostrophe was previously left raw — when an attacker-controlled
      // string lands inside a single-quoted attribute (or in a title=
      // built via single-quote concat) it could break out. We have no
      // such call site today, but escaping here closes the foot-gun for
      // future edits to the inline-HTML render path.
      .replace(/'/g, '&#39;')
      .replace(/`/g, '&#96;');
  }

  // -- Entry Execution -------------------------------------------------

  function clickEntryMethod(method) {
    var el = method.element;
    if (!el) return false;

    // Try clicking the heading/title area to expand the entry
    var clickTargets = [
      el.querySelector('.entry-method-heading, .entry-heading, [ng-click*="toggle"], [ng-click*="expand"]'),
      el.querySelector('a[ng-click], [ng-click]'),
      el.querySelector('.entry-method-name, .method-name'),
      el,
    ];

    for (var i = 0; i < clickTargets.length; i++) {
      if (clickTargets[i]) {
        try {
          clickTargets[i].click();
          return true;
        } catch (e) {
          continue;
        }
      }
    }

    return false;
  }

  function findClaimButton(method) {
    var el = method.element;
    if (!el) return null;

    // Look for claim/continue/done buttons within the expanded entry
    var buttonSelectors = [
      'a[ng-click*="continue"]',
      'a[ng-click*="claim"]',
      'a[ng-click*="enterMethod"]',
      'a[ng-click*="completeEntry"]',
      'button[ng-click*="continue"]',
      'button[ng-click*="claim"]',
      'a.btn:not([ng-click*="toggle"])',
      'button.btn:not([ng-click*="toggle"])',
    ];

    for (var i = 0; i < buttonSelectors.length; i++) {
      var btn = el.querySelector(buttonSelectors[i]);
      if (btn) {
        var rect = btn.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return btn;
      }
    }

    // Fallback: look for any visible button/link with action text
    var allBtns = el.querySelectorAll('a, button');
    for (var j = 0; j < allBtns.length; j++) {
      var text = (allBtns[j].textContent || '').trim().toLowerCase();
      if (text === 'continue' || text === 'claim' || text === 'done' || text === 'enter' || text === 'verify') {
        var rect = allBtns[j].getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return allBtns[j];
      }
    }

    return null;
  }

  function findActionButton(method) {
    // Find the main action button (e.g., "Follow @username", "Visit Page")
    // This is different from the claim button - it's the button that initiates the action
    var el = method.element;
    if (!el) return null;

    var actionSelectors = [
      'a[ng-click*="visitUrl"]',
      'a[ng-click*="openUrl"]',
      'a[ng-click*="follow"]',
      'a[ng-click*="subscribe"]',
      'a[target="_blank"]',
      'a[href]:not([href*="gleam.io"]):not([href^="#"])',
    ];

    for (var i = 0; i < actionSelectors.length; i++) {
      var btn = el.querySelector(actionSelectors[i]);
      if (btn) {
        var rect = btn.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return btn;
      }
    }

    return null;
  }

  async function performSocialAction(method) {
    // Send message to background to handle the social action in a background tab
    var platform = method.platform;
    var targetUrl = method.targetUrl;

    if (!targetUrl) {
      // Try to find the URL from the action button
      var actionBtn = findActionButton(method);
      if (actionBtn && actionBtn.href) {
        targetUrl = actionBtn.href;
      }
    }

    if (!targetUrl) {
      log('No target URL found for ' + method.displayText, 'error');
      return { success: false, error: 'no_target_url' };
    }

    log('Opening ' + targetUrl + ' in background tab...', 'info');

    return new Promise(function (resolve) {
      chrome.runtime.sendMessage({
        type: 'perform-social-action',
        platform: platform,
        targetUrl: targetUrl,
        actionType: method.actionType,
      }, function (response) {
        if (chrome.runtime.lastError) {
          log('Background error: ' + chrome.runtime.lastError.message, 'error');
          resolve({ success: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { success: false, error: 'no_response' });
      });
    });
  }

  /**
   * Open a URL in a managed background tab (opened + closed by the background script).
   * Use this instead of raw element.click() to prevent orphan tabs.
   */
  function performVisitViaBackground(url) {
    return new Promise(function (resolve) {
      chrome.runtime.sendMessage({
        type: 'perform-visit-action',
        targetUrl: url,
      }, function (response) {
        if (chrome.runtime.lastError) {
          log('Visit background error: ' + chrome.runtime.lastError.message, 'error');
          resolve({ success: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { success: true });
      });
    });
  }

  async function executeEntry(method, index) {
    updateEntryStatus(index, 'running');

    // Step 1: Click the entry method to expand it
    log('Expanding entry: ' + method.displayText, 'info');
    clickEntryMethod(method);
    await sleep(1500);

    var needsSocialAction = method.platform !== 'generic' &&
      PLATFORM_PATTERNS[method.platform] &&
      (method.actionType === 'follow' || method.actionType === 'subscribe');

    // Step 2: If it needs a social action, perform it
    if (needsSocialAction) {
      log('Performing ' + method.actionType + ' on ' + (PLATFORM_PATTERNS[method.platform] || {}).label + '...', 'info');

      // First, try clicking the action button in gleam (this may open a popup)
      var actionBtn = findActionButton(method);
      if (actionBtn) {
        // Don't click the link directly - let our background handle it
        // But extract the URL if we haven't already
        if (!method.targetUrl && actionBtn.href) {
          method.targetUrl = actionBtn.href;
        }
      }

      var result = await performSocialAction(method);
      await sleep(SOCIAL_ACTION_DELAY_MS);

      if (result.success) {
        if (result.alreadyFollowing) {
          log('Already following - skipping action', 'info');
        } else {
          log(method.actionType + ' completed on ' + (PLATFORM_PATTERNS[method.platform] || {}).label, 'success');
        }
      } else {
        log('Social action failed: ' + (result.error || 'unknown'), 'error');
        // Continue anyway - try to claim the entry
      }
    } else if (method.actionType === 'retweet' || method.actionType === 'like' || method.actionType === 'share') {
      // For retweet/like/share entries on known platforms, use dedicated action scripts
      var socialBtn = findActionButton(method);
      if (socialBtn && !method.targetUrl) {
        method.targetUrl = socialBtn.href || null;
      }

      if (method.platform !== 'generic' && PLATFORM_PATTERNS[method.platform] && method.targetUrl) {
        log('Performing ' + method.actionType + ' on ' + (PLATFORM_PATTERNS[method.platform] || {}).label + '...', 'info');
        var socialResult = await performSocialAction(method);
        await sleep(SOCIAL_ACTION_DELAY_MS);

        if (socialResult.success) {
          log(method.actionType + ' completed on ' + (PLATFORM_PATTERNS[method.platform] || {}).label, 'success');
        } else {
          log('Social action failed: ' + (socialResult.error || 'unknown'), 'error');
        }
      } else if (method.targetUrl) {
        // Known URL but unknown platform - open via managed tab
        log('Opening ' + method.actionType + ' URL in managed tab...', 'info');
        await performVisitViaBackground(method.targetUrl);
        await sleep(2000);
      } else if (socialBtn) {
        // Last resort: click but extract href first, prevent orphan tabs
        var fallbackUrl = socialBtn.href || socialBtn.getAttribute('data-href');
        if (fallbackUrl && fallbackUrl.indexOf('javascript:') !== 0 && fallbackUrl.indexOf('gleam.io') === -1) {
          await performVisitViaBackground(fallbackUrl);
          await sleep(2000);
        } else {
          socialBtn.click();
          await sleep(2000);
        }
      }
    } else if (method.actionType === 'visit' || method.actionType === 'view' || method.actionType === 'watch') {
      // For visit/view/watch entries, always route through background tab management
      var visitBtn = findActionButton(method);
      var visitUrl = method.targetUrl || (visitBtn ? (visitBtn.href || null) : null);

      if (visitUrl && visitUrl.indexOf('javascript:') !== 0 && visitUrl.indexOf('gleam.io') === -1) {
        log('Opening visit URL in managed tab...', 'info');
        await performVisitViaBackground(visitUrl);
        await sleep(2000);
      } else if (visitBtn) {
        // Extract any possible URL from the button before clicking
        var btnUrl = visitBtn.href || visitBtn.getAttribute('data-href') || visitBtn.getAttribute('data-url');
        if (btnUrl && btnUrl.indexOf('javascript:') !== 0 && btnUrl.indexOf('gleam.io') === -1) {
          await performVisitViaBackground(btnUrl);
          await sleep(2000);
        } else {
          // Absolute last resort: click directly (no URL could be extracted)
          visitBtn.click();
          await sleep(3000);
        }
      }
    } else {
      // Simple click/enter entry - extract URL and use managed tab if possible
      var simpleBtn = findActionButton(method);
      if (simpleBtn) {
        var simpleBtnUrl = simpleBtn.href || simpleBtn.getAttribute('data-href') || simpleBtn.getAttribute('data-url');
        if (simpleBtnUrl && simpleBtnUrl.indexOf('javascript:') !== 0 && simpleBtnUrl.indexOf('gleam.io') === -1
            && (simpleBtn.target === '_blank' || simpleBtnUrl.indexOf('http') === 0)) {
          // Route through managed tab to prevent orphan tabs
          log('Opening entry URL in managed tab...', 'info');
          await performVisitViaBackground(simpleBtnUrl);
          await sleep(2000);
        } else {
          simpleBtn.click();
          await sleep(1000);
        }
      }
    }

    // Step 3: Try to click the claim/continue button
    await sleep(1000);
    var claimBtn = findClaimButton(method);
    if (claimBtn) {
      log('Clicking claim/continue button...', 'info');
      claimBtn.click();
      await sleep(2000);
    } else {
      // Try re-expanding and looking for the claim button
      clickEntryMethod(method);
      await sleep(1000);
      claimBtn = findClaimButton(method);
      if (claimBtn) {
        claimBtn.click();
        await sleep(2000);
      }
    }

    // Step 4: Check if entry was successful
    // Re-check the element for completion state
    if (isEntryCompleted(method.element)) {
      updateEntryStatus(index, 'done');
      log('Entry completed: ' + method.displayText, 'success');
      return true;
    }

    // Could not confirm completion - mark as attempted (not confirmed)
    updateEntryStatus(index, 'attempted');
    log('Entry attempted but not confirmed: ' + method.displayText, 'warn');
    return false;
  }

  async function startAutoEntry() {
    if (isRunning) return;
    isRunning = true;
    abortRequested = false;

    var enterBtn = document.getElementById('gae-enter-all');
    var rescanBtn = document.getElementById('gae-rescan');
    var abortBtn = document.getElementById('gae-abort');
    if (enterBtn) enterBtn.disabled = true;
    if (rescanBtn) rescanBtn.disabled = true;
    if (abortBtn) {
      abortBtn.style.display = '';
      abortBtn.disabled = false;
      abortBtn.textContent = 'Stop';
    }

    var pending = entryMethods.filter(function (m) { return m.status === 'pending'; });
    var total = pending.length;

    log('Starting auto-entry for ' + total + ' entries...', 'info');
    updateProgress(0, total, 'Starting...');

    var completed = 0;
    var failed = 0;
    var attempted = 0;
    var aborted = false;

    for (var i = 0; i < entryMethods.length; i++) {
      if (abortRequested) { aborted = true; break; }
      if (entryMethods[i].status !== 'pending') continue;

      try {
        updateProgress(completed + attempted, total, 'Processing ' + (completed + attempted + 1) + '/' + total + '...');
        var success = await executeEntry(entryMethods[i], i);
        if (success) {
          completed++;
        } else {
          attempted++;
        }
      } catch (e) {
        log('Error on entry ' + (i + 1) + ': ' + e.message, 'error');
        updateEntryStatus(i, 'failed');
        failed++;
      }

      // Delay between entries — but break out promptly on abort
      if (i < entryMethods.length - 1 && !abortRequested) {
        await sleep(ENTRY_DELAY_MS);
      }
    }

    var summary = completed + ' completed';
    if (attempted > 0) summary += ', ' + attempted + ' unconfirmed';
    if (failed > 0) summary += ', ' + failed + ' failed';
    if (aborted) summary += ' (stopped by user)';
    updateProgress(total, total, (aborted ? 'Stopped. ' : 'Done! ') + summary);
    log('Auto-entry ' + (aborted ? 'aborted' : 'finished') + '. ' + summary,
        completed > 0 ? 'success' : (aborted ? 'warn' : 'error'));

    isRunning = false;
    abortRequested = false;
    if (enterBtn) {
      enterBtn.textContent = aborted ? 'Resume' : 'Done';
      // Re-enable if there are still pending entries (e.g. after abort)
      var stillPending = entryMethods.some(function (m) { return m.status === 'pending'; });
      enterBtn.disabled = !stillPending;
    }
    if (rescanBtn) rescanBtn.disabled = false;
    if (abortBtn) abortBtn.style.display = 'none';

    // Update pending count
    var pendingEl = document.getElementById('gae-pending-count');
    var newPending = entryMethods.filter(function (m) { return m.status === 'pending'; }).length;
    if (pendingEl) pendingEl.textContent = newPending;
  }

  // -- Initialization --------------------------------------------------

  async function init() {
    console.log('[GleamAutoEntry] Waiting for Gleam widget...');

    var widget = await waitForWidget();
    if (!widget) {
      console.log('[GleamAutoEntry] No Gleam widget found on this page.');
      return;
    }

    console.log('[GleamAutoEntry] Widget found, parsing entry methods...');

    // Give the widget a moment to fully render
    await sleep(2000);

    // Send giveaway metadata (title + deadline) to background for storage/export
    sendGiveawayMeta();

    entryMethods = parseEntryMethods();
    console.log('[GleamAutoEntry] Found ' + entryMethods.length + ' entry methods.');

    if (entryMethods.length === 0) {
      // Retry after a longer wait (widget might still be loading entries)
      await sleep(3000);
      entryMethods = parseEntryMethods();
      console.log('[GleamAutoEntry] Retry: found ' + entryMethods.length + ' entry methods.');
    }

    createOverlay();

    if (entryMethods.length > 0) {
      log('Found ' + entryMethods.length + ' entry methods', 'info');
      var platforms = {};
      entryMethods.forEach(function (m) {
        var p = (PLATFORM_PATTERNS[m.platform] || {}).label || 'Other';
        platforms[p] = (platforms[p] || 0) + 1;
      });
      var summary = Object.keys(platforms).map(function (k) { return k + ': ' + platforms[k]; }).join(', ');
      log('Platforms: ' + summary, 'info');
    } else {
      log('No entry methods detected. Try clicking "Rescan" after the page loads fully.', 'error');
    }
  }

  // Wrap init in a guard so an unexpected throw doesn't leave the user
  // on a gleam page with no overlay and no diagnostic.
  Promise.resolve()
    .then(init)
    .catch(function (err) {
      console.error('[GleamAutoEntry] init failed:', err);
      try { log('Init error: ' + (err && err.message), 'error'); } catch (e) {}
    });
})();
