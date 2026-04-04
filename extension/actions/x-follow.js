// X/Twitter Follow Action Script
// Injected into x.com/twitter.com tabs to click the Follow button.
(async function xFollowAction() {
  'use strict';

  const TIMEOUT = 15000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  /**
   * Check if user is not logged in to X/Twitter.
   */
  function isNotLoggedIn() {
    // X redirects to login or shows a login sheet
    if (location.pathname === '/login' || location.pathname.startsWith('/i/flow/login')) return true;

    // Check for the bottom login bar / "Sign up" modal
    var loginSheet = document.querySelector('[data-testid="loginButton"]');
    if (loginSheet) return true;

    // Check for the "Log in" / "Sign up" bottom bar
    var bottomBar = document.querySelector('[data-testid="BottomBar"]');
    if (bottomBar) return true;

    return false;
  }

  /**
   * Find a visible button by text content.
   */
  function findButtonByText(text) {
    var lower = text.toLowerCase();
    var buttons = document.querySelectorAll('button, [role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var spans = buttons[i].querySelectorAll('span');
      for (var j = 0; j < spans.length; j++) {
        var spanText = (spans[j].textContent || '').trim().toLowerCase();
        if (spanText === lower) {
          var rect = buttons[i].getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) return buttons[i];
        }
      }
    }
    return null;
  }

  // Check if we're already following this account
  function isAlreadyFollowing() {
    // data-testid based detection (most reliable on X)
    var unfollowBtn = document.querySelector('[data-testid$="-unfollow"]');
    if (unfollowBtn) return true;

    // Check for "Following" button via data-testid in placement tracking area
    var placementBtns = document.querySelectorAll('[data-testid="placementTracking"] [role="button"]');
    for (var i = 0; i < placementBtns.length; i++) {
      var txt = (placementBtns[i].textContent || '').trim().toLowerCase();
      if (txt === 'following') return true;
    }

    // Check aria-labels
    var allBtns = document.querySelectorAll('[role="button"]');
    for (var j = 0; j < allBtns.length; j++) {
      var label = (allBtns[j].getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('following') && !label.includes('followers')) return true;
    }

    // Text-based fallback
    if (findButtonByText('following')) return true;

    return false;
  }

  try {
    // Wait for X SPA to render
    await sleep(3000);

    // Check login state
    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to X/Twitter', platform: 'x' };
    }

    // Check if already following
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'x' };
    }

    // Poll for the follow button
    var followBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      // Strategy 1: data-testid selectors (most reliable)
      followBtn = document.querySelector('[data-testid$="-follow"]');
      if (followBtn) {
        var btnText = (followBtn.textContent || '').trim().toLowerCase();
        if (btnText === 'following' || btnText === 'unfollow') {
          return { success: true, alreadyFollowing: true, platform: 'x' };
        }
        break;
      }

      // Strategy 2: Placement tracking area
      var placementBtns = document.querySelectorAll('[data-testid="placementTracking"] [role="button"]');
      for (var i = 0; i < placementBtns.length; i++) {
        var ptxt = (placementBtns[i].textContent || '').trim().toLowerCase();
        if (ptxt === 'follow') {
          followBtn = placementBtns[i];
          break;
        }
      }
      if (followBtn) break;

      // Strategy 3: aria-label based
      var ariaButtons = document.querySelectorAll('[role="button"][aria-label*="Follow @"]');
      if (ariaButtons.length > 0) {
        followBtn = ariaButtons[0];
        break;
      }

      // Strategy 4: Text-based fallback
      followBtn = findButtonByText('follow');
      if (followBtn) break;

      // Re-check following state
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'x' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!followBtn) {
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'x' };
      }
      return { success: false, error: 'Follow button not found', platform: 'x' };
    }

    // Verify it's a Follow button (not Following/Unfollow)
    var finalText = (followBtn.textContent || '').trim().toLowerCase();
    if (finalText === 'following' || finalText === 'unfollow') {
      return { success: true, alreadyFollowing: true, platform: 'x' };
    }

    // Click the follow button
    followBtn.click();
    await sleep(2000);

    // Verify the follow was successful
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'x' };
    }

    // Even if we can't verify, the click happened
    return { success: true, alreadyFollowing: false, platform: 'x', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'x' };
  }
})();
