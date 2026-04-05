// Instagram Follow Action Script
// Injected into instagram.com tabs to click the Follow button.
(async function instagramFollowAction() {
  'use strict';

  const TIMEOUT = 15000;
  const POLL_INTERVAL = 500;

  // Localized "Follow" and "Following" text variants
  var FOLLOW_TEXTS = ['follow', 'folgen', 'suivre', 'seguir', 'segui', 'volgen', 'seguire'];
  var FOLLOWING_TEXTS = ['following', 'gefolgt', 'abonné', 'siguiendo', 'seguendo', 'volgend', 'requested', 'angefragt', 'demandé', 'solicitado'];

  function isFollowText(text) {
    var lower = (text || '').trim().toLowerCase();
    return FOLLOW_TEXTS.indexOf(lower) !== -1;
  }

  function isFollowingText(text) {
    var lower = (text || '').trim().toLowerCase();
    return FOLLOWING_TEXTS.indexOf(lower) !== -1;
  }

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  /**
   * Check if user is not logged in. Instagram redirects to login or shows
   * a login modal when not authenticated.
   */
  function isNotLoggedIn() {
    // Check if redirected to login page
    if (location.pathname.startsWith('/accounts/login')) return true;

    // Check for login modal overlay
    var loginModal = document.querySelector('[role="dialog"] input[name="username"]');
    if (loginModal) return true;

    // Check for "Log in" prominent button suggesting not logged in (localized)
    var loginBtns = document.querySelectorAll('a[href="/accounts/login/"], button');
    for (var i = 0; i < loginBtns.length; i++) {
      var txt = (loginBtns[i].textContent || '').trim().toLowerCase();
      if (txt === 'log in' || txt === 'sign up' || txt === 'anmelden' || txt === 'registrieren' || txt === 'connexion' || txt === 'iniciar sesión') {
        // Only count as "not logged in" if it's a prominent/visible login prompt
        var rect = loginBtns[i].getBoundingClientRect();
        if (rect.width > 80 && rect.height > 20) return true;
      }
    }

    return false;
  }

  /**
   * Find a visible button by its text content (case-insensitive exact match).
   * Accepts a single string or array of localized variants.
   * Searches within an optional container, or the whole document.
   */
  function findButtonByText(text, container) {
    var root = container || document;
    var buttons = root.querySelectorAll('button, [role="button"]');
    var textList = Array.isArray(text) ? text : [text.toLowerCase()];

    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      // Get the direct text content (avoid matching nested buttons)
      var btnText = (btn.textContent || '').trim().toLowerCase();

      if (textList.indexOf(btnText) !== -1) {
        var rect = btn.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return btn;
      }
    }
    return null;
  }

  function isAlreadyFollowing() {
    // Look for "Following" or "Requested" button anywhere on profile page (localized)
    if (findButtonByText(FOLLOWING_TEXTS)) return true;

    // Also check aria-labels (Instagram uses these)
    var buttons = document.querySelectorAll('button, [role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
      if (isFollowingText(label)) return true;
    }

    return false;
  }

  try {
    // Wait for Instagram SPA to render (React hydration takes time)
    await sleep(3000);

    // Check login state first
    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to Instagram', platform: 'instagram' };
    }

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'instagram' };
    }

    // Poll for the Follow button to appear (SPA rendering can be slow)
    var followBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      // Strategy 1: Find button with follow text in the header/profile area (localized)
      var header = document.querySelector('header') || document.querySelector('main');
      if (header) {
        followBtn = findButtonByText(FOLLOW_TEXTS, header);
        if (followBtn) break;
      }

      // Strategy 2: Search entire page for follow button (localized)
      followBtn = findButtonByText(FOLLOW_TEXTS);
      if (followBtn) break;

      // Strategy 3: Try aria-label based search (localized)
      var ariaButtons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
      for (var i = 0; i < ariaButtons.length; i++) {
        var ariaLabel = (ariaButtons[i].getAttribute('aria-label') || '').toLowerCase();
        // Check if aria-label starts with any localized follow text
        var isFollow = false;
        for (var fi = 0; fi < FOLLOW_TEXTS.length; fi++) {
          if (ariaLabel.startsWith(FOLLOW_TEXTS[fi]) && !isFollowingText(ariaLabel)) {
            isFollow = true;
            break;
          }
        }
        if (isFollow) {
          // Exclude if it also looks like "following" or "followers"
          if (!ariaLabel.includes('followers')) {
            var rect = ariaButtons[i].getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
              followBtn = ariaButtons[i];
              break;
            }
          }
        }
      }
      if (followBtn) break;

      // Re-check if we are now following (page may have updated)
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'instagram' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!followBtn) {
      // Final check - maybe we're already following
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'instagram' };
      }
      return { success: false, error: 'Follow button not found', platform: 'instagram' };
    }

    followBtn.click();
    await sleep(2500);

    // Verify success
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'instagram' };
    }

    return { success: true, alreadyFollowing: false, platform: 'instagram', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'instagram' };
  }
})();
