// TikTok Like Action Script
// Injected into tiktok.com tabs to click the Like button on a video.
(async function tiktokLikeAction() {
  'use strict';

  const TIMEOUT = 12000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function isNotLoggedIn() {
    var loginModal = document.querySelector('[data-e2e="login-modal"]');
    if (loginModal) return true;
    var loginForm = document.querySelector('form input[name="username"], [class*="login-modal"]');
    if (loginForm) return true;
    return false;
  }

  function isAlreadyLiked() {
    // Strategy 1 (most reliable): aria-pressed on the like button.
    // The like icon ([data-e2e="like-icon"]) is usually an SVG nested
    // inside a <button aria-pressed="true|false" aria-label="Like…">.
    // Walking from the icon up to the button is more reliable than the
    // earlier color heuristic, which broke whenever TikTok shipped a
    // new red shade or moved to CSS variables.
    var likeIcon = document.querySelector('[data-e2e="like-icon"]');
    if (likeIcon) {
      var btn = likeIcon.closest('button, [role="button"]');
      if (btn) {
        var pressed = btn.getAttribute('aria-pressed');
        if (pressed === 'true') return true;
        if (pressed === 'false') return false; // explicit "not yet liked"
      }
      // Class hint on the icon itself
      var classList = (likeIcon.className && likeIcon.className.baseVal !== undefined
        ? likeIcon.className.baseVal // SVG className is SVGAnimatedString
        : (likeIcon.className || '')).toLowerCase();
      if (classList.includes('active') || classList.includes('liked')) return true;

      // SVG fill as a secondary signal — TikTok flips the SVG fill
      // to its brand red when liked. We accept any reddish fill rather
      // than the exact RGB literal that previously broke on theme changes.
      var path = likeIcon.querySelector('path, svg');
      if (path) {
        var fill = (path.getAttribute('fill') || window.getComputedStyle(path).fill || '').toLowerCase();
        // Accept any explicit non-currentColor red-ish hex/rgb token
        if (/^#fe?[0-3][0-9a-f]/.test(fill) || /^rgb\(\s*2(?:5[0-5]|4\d|3\d)\s*,\s*(?:[0-5]\d|\d)\s*,/.test(fill)) {
          return true;
        }
      }

      // Color fallback (kept narrowly — only as last resort)
      var color = (window.getComputedStyle(likeIcon).color || '').toLowerCase();
      if (color.includes('rgb(254, 44, 85)') || color.includes('rgb(255, 44, 85)') || color.includes('fe2c55')) {
        return true;
      }
    }

    // Strategy 2: any aria-pressed=true with a label mentioning "like"
    var ariaButtons = document.querySelectorAll('[aria-pressed="true"]');
    for (var ab = 0; ab < ariaButtons.length; ab++) {
      var abLabel = (ariaButtons[ab].getAttribute('aria-label') || '').toLowerCase();
      if (abLabel.includes('like') && !abLabel.includes('unlike')) return true;
    }

    return false;
  }

  try {
    await sleep(3500);

    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to TikTok', platform: 'tiktok', action: 'like' };
    }

    if (isAlreadyLiked()) {
      return { success: true, alreadyDone: true, platform: 'tiktok', action: 'like' };
    }

    // Find the like button
    var likeBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      // Strategy 1: data-e2e attribute
      likeBtn = document.querySelector('[data-e2e="like-icon"]');
      if (likeBtn) {
        // Re-check liked state before proceeding (avoid accidental unlikes)
        if (isAlreadyLiked()) {
          return { success: true, alreadyDone: true, platform: 'tiktok', action: 'like' };
        }
        // Walk up to the clickable parent if needed
        var clickable = likeBtn.closest('button') || likeBtn.closest('[role="button"]') || likeBtn;
        likeBtn = clickable;
        break;
      }

      // Strategy 2: aria-label based
      var buttons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if ((label === 'like' || label.includes('like video')) && !label.includes('unlike')) {
          var rect = buttons[i].getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            likeBtn = buttons[i];
            break;
          }
        }
      }
      if (likeBtn) break;

      // Strategy 3: Find by class pattern
      var classBtn = document.querySelector('[class*="like-icon"], [class*="LikeButton"], [class*="ActionButton"]');
      if (classBtn) {
        var clickableParent = classBtn.closest('button') || classBtn.closest('[role="button"]') || classBtn;
        likeBtn = clickableParent;
        break;
      }

      if (isAlreadyLiked()) {
        return { success: true, alreadyDone: true, platform: 'tiktok', action: 'like' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!likeBtn) {
      if (isAlreadyLiked()) {
        return { success: true, alreadyDone: true, platform: 'tiktok', action: 'like' };
      }
      return { success: false, error: 'Like button not found', platform: 'tiktok', action: 'like' };
    }

    likeBtn.click();
    await sleep(2000);

    // Check if login modal appeared
    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to TikTok (login modal appeared)', platform: 'tiktok', action: 'like' };
    }

    if (isAlreadyLiked()) {
      return { success: true, alreadyDone: false, platform: 'tiktok', action: 'like' };
    }

    return { success: false, attempted: true, platform: 'tiktok', action: 'like', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'tiktok', action: 'like' };
  }
})();
