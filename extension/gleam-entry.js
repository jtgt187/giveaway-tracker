// Gleam.io Auto-Entry Content Script
// Runs on gleam.io pages to parse entry methods and provide auto-entry UI.
(function () {
  'use strict';

  // -- Guard: only run on competition/giveaway pages --------------------
  const path = location.pathname;
  // Gleam competition URLs look like: /competitions/xxxxx/yyyy or /xxxxx/yyyy
  // Skip non-competition pages like /giveaways, /login, /account, etc.
  const skipPaths = ['/giveaways', '/login', '/signup', '/account', '/settings', '/privacy', '/terms'];
  if (skipPaths.some(p => path.startsWith(p))) return;
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

  // Action types we can automate
  const AUTOMATABLE_ACTIONS = ['follow', 'subscribe', 'visit', 'view', 'click', 'watch'];

  // -- State ------------------------------------------------------------
  let entryMethods = [];
  let isRunning = false;
  let overlay = null;

  // -- Utility ----------------------------------------------------------

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function log(msg, level) {
    const logEl = document.querySelector('.gae-log');
    if (!logEl) return;
    logEl.classList.add('active');
    const entry = document.createElement('div');
    entry.className = 'gae-log-entry ' + (level || '');
    entry.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
    logEl.appendChild(entry);
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
          resolve(widget);
          return;
        }

        if (Date.now() - start > WIDGET_POLL_TIMEOUT) {
          clearInterval(timer);
          resolve(null);
        }
      }, WIDGET_POLL_INTERVAL);
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
    if (lower.indexOf('like') !== -1) return 'like';
    if (lower.indexOf('tweet') !== -1) return 'tweet';
    if (lower.indexOf('share') !== -1) return 'share';
    if (lower.indexOf('comment') !== -1) return 'comment';
    if (lower.indexOf('click') !== -1 || lower.indexOf('enter') !== -1) return 'click';
    return 'unknown';
  }

  function extractTargetUrl(element) {
    // Look for links to social platforms inside the entry method
    var links = element.querySelectorAll('a[href]');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].href;
      // Skip gleam.io internal links
      if (href.indexOf('gleam.io') !== -1) continue;
      // Skip javascript: links
      if (href.indexOf('javascript:') === 0) continue;
      // Check if it's a social platform URL
      for (var key in PLATFORM_PATTERNS) {
        var patterns = PLATFORM_PATTERNS[key].urlPatterns;
        for (var j = 0; j < patterns.length; j++) {
          if (href.indexOf(patterns[j]) !== -1) return href;
        }
      }
    }

    // Try ng-click or data attributes for the URL
    var ngClick = element.querySelector('[ng-click]');
    if (ngClick) {
      var clickAttr = ngClick.getAttribute('ng-click') || '';
      // Try to extract URL from ng-click attribute
      var urlMatch = clickAttr.match(/https?:\/\/[^\s'"]+/);
      if (urlMatch) return urlMatch[0];
    }

    // Try data attributes
    var dataUrl = element.getAttribute('data-url') || element.getAttribute('data-href');
    if (dataUrl) return dataUrl;

    return null;
  }

  function isEntryCompleted(element) {
    var classes = (element.className || '').toLowerCase();
    if (classes.indexOf('completed') !== -1) return true;
    if (classes.indexOf('entered') !== -1) return true;
    if (classes.indexOf('done') !== -1) return true;

    // Check for Angular ng-class indicating completion
    var ngClass = element.getAttribute('ng-class') || '';
    if (ngClass.indexOf('completed') !== -1 || ngClass.indexOf('entered') !== -1) {
      // Check if the element actually has a completion class applied
      if (element.classList.contains('completed') || element.classList.contains('entered')) {
        return true;
      }
    }

    // Check for checkmark icon indicating completion
    var checkIcons = element.querySelectorAll('.fa-check, .fa-check-circle, .icon-check, [class*="check"]');
    if (checkIcons.length > 0) {
      // Verify the check is visible
      for (var i = 0; i < checkIcons.length; i++) {
        var style = window.getComputedStyle(checkIcons[i]);
        if (style.display !== 'none' && style.visibility !== 'hidden') return true;
      }
    }

    // Check for green/success coloring on the entry
    var style = window.getComputedStyle(element);
    if (style.opacity === '0.5' || style.opacity === '0.4') return true;

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

    var elements = [];
    for (var s = 0; s < selectors.length; s++) {
      var found = document.querySelectorAll(selectors[s]);
      if (found.length > 0) {
        elements = found;
        break;
      }
    }

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
        if (text.length > 3) return text;
      }
    }

    return document.title || 'Gleam Giveaway';
  }

  // -- Overlay UI ------------------------------------------------------

  function createOverlay() {
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'gleam-auto-entry-overlay';

    var totalEntries = entryMethods.length;
    var completedEntries = entryMethods.filter(function (m) { return m.completed; }).length;
    var pendingEntries = totalEntries - completedEntries;

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
    entryMethods[index].status = status;

    var item = document.querySelector('.gae-entry-item[data-index="' + index + '"]');
    if (!item) return;

    var statusEl = item.querySelector('.gae-entry-status');
    if (statusEl) {
      statusEl.className = 'gae-entry-status ' + status;
      if (status === 'done') statusEl.innerHTML = '&#10003;';
      else if (status === 'failed') statusEl.innerHTML = '&#10007;';
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
    if (fillEl) fillEl.style.width = Math.round((current / total) * 100) + '%';
    if (textEl) textEl.textContent = text || (current + ' / ' + total);
  }

  function bindOverlayEvents() {
    var closeBtn = document.getElementById('gae-close');
    var enterAllBtn = document.getElementById('gae-enter-all');
    var rescanBtn = document.getElementById('gae-rescan');

    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
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
  }

  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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
    } else if (method.actionType === 'visit' || method.actionType === 'view' || method.actionType === 'watch') {
      // For visit/view entries, click the action button (it opens a URL)
      var visitBtn = findActionButton(method);
      if (visitBtn) {
        log('Opening visit URL...', 'info');
        // Let the background handle opening the tab
        var visitUrl = visitBtn.href || method.targetUrl;
        if (visitUrl) {
          var visitResult = await new Promise(function (resolve) {
            chrome.runtime.sendMessage({
              type: 'perform-visit-action',
              targetUrl: visitUrl,
            }, function (response) {
              if (chrome.runtime.lastError) {
                resolve({ success: false });
                return;
              }
              resolve(response || { success: true });
            });
          });
          await sleep(2000);
        } else {
          // Click the button directly
          visitBtn.click();
          await sleep(3000);
        }
      }
    } else {
      // Simple click/enter entry - just click the action button if present
      var simpleBtn = findActionButton(method);
      if (simpleBtn) {
        simpleBtn.click();
        await sleep(1000);
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

    // Even if we can't confirm completion, mark as done if we clicked everything
    updateEntryStatus(index, 'done');
    log('Entry attempted: ' + method.displayText, 'info');
    return true;
  }

  async function startAutoEntry() {
    if (isRunning) return;
    isRunning = true;

    var enterBtn = document.getElementById('gae-enter-all');
    var rescanBtn = document.getElementById('gae-rescan');
    if (enterBtn) enterBtn.disabled = true;
    if (rescanBtn) rescanBtn.disabled = true;

    var pending = entryMethods.filter(function (m) { return m.status === 'pending'; });
    var total = pending.length;

    log('Starting auto-entry for ' + total + ' entries...', 'info');
    updateProgress(0, total, 'Starting...');

    var completed = 0;
    var failed = 0;

    for (var i = 0; i < entryMethods.length; i++) {
      if (entryMethods[i].status !== 'pending') continue;

      try {
        updateProgress(completed, total, 'Processing ' + (completed + 1) + '/' + total + '...');
        await executeEntry(entryMethods[i], i);
        completed++;
      } catch (e) {
        log('Error on entry ' + (i + 1) + ': ' + e.message, 'error');
        updateEntryStatus(i, 'failed');
        failed++;
      }

      // Delay between entries
      if (i < entryMethods.length - 1) {
        await sleep(ENTRY_DELAY_MS);
      }
    }

    updateProgress(total, total, 'Done! ' + completed + ' completed, ' + failed + ' failed');
    log('Auto-entry finished. Completed: ' + completed + ', Failed: ' + failed, completed > 0 ? 'success' : 'error');

    isRunning = false;
    if (enterBtn) {
      enterBtn.textContent = 'Done';
      enterBtn.disabled = true;
    }
    if (rescanBtn) rescanBtn.disabled = false;

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

  init();
})();
