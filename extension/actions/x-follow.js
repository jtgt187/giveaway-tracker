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
   * Get the primary content area (excludes "Who to follow" sidebar etc).
   */
  function getPrimaryRoot() {
    return document.querySelector('[data-testid="primaryColumn"]')
        || document.querySelector('main')
        || document.body;
  }

  /**
   * Find a visible button by text content, scoped to a root element.
   */
  function findButtonByText(text, root) {
    var lower = text.toLowerCase();
    var scope = root || getPrimaryRoot();
    var buttons = scope.querySelectorAll('button, [role="button"]');
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
    var scope = getPrimaryRoot();
    // data-testid based detection (most reliable on X) — scoped
    var unfollowBtn = scope.querySelector('[data-testid$="-unfollow"]');
    if (unfollowBtn) return true;

    // Check for "Following" button via data-testid in placement tracking area
    var placementBtns = scope.querySelectorAll('[data-testid="placementTracking"] [role="button"]');
    for (var i = 0; i < placementBtns.length; i++) {
      var txt = (placementBtns[i].textContent || '').trim().toLowerCase();
      if (txt === 'following') return true;
    }

    // Check aria-labels — scoped
    var allBtns = scope.querySelectorAll('[role="button"]');
    for (var j = 0; j < allBtns.length; j++) {
      var label = (allBtns[j].getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('following') && !label.includes('followers') && !label.includes('not following')) return true;
    }

    // Text-based fallback
    if (findButtonByText('following', scope)) return true;

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
      var scope = getPrimaryRoot();

      // Strategy 1: data-testid selectors (most reliable) — scoped to primary column
      // Use :not to exclude unfollow buttons (since $="-follow" also matches $="-unfollow")
      followBtn = scope.querySelector('[data-testid$="-follow"]:not([data-testid$="-unfollow"])');
      if (followBtn) {
        var btnText = (followBtn.textContent || '').trim().toLowerCase();
        if (btnText === 'following' || btnText === 'unfollow') {
          return { success: true, alreadyFollowing: true, platform: 'x' };
        }
        break;
      }

      // Strategy 2: Placement tracking area
      var placementBtns = scope.querySelectorAll('[data-testid="placementTracking"] [role="button"]');
      for (var i = 0; i < placementBtns.length; i++) {
        var ptxt = (placementBtns[i].textContent || '').trim().toLowerCase();
        if (ptxt === 'follow') {
          followBtn = placementBtns[i];
          break;
        }
      }
      if (followBtn) break;

      // Strategy 3: aria-label based (use starts-with ^= to avoid matching "Following @")
      var ariaButtons = scope.querySelectorAll('[role="button"][aria-label^="Follow @"]');
      for (var ai = 0; ai < ariaButtons.length; ai++) {
        var ariaLabel = (ariaButtons[ai].getAttribute('aria-label') || '');
        // Exclude "Following @" which also starts with "Follow"
        if (!ariaLabel.startsWith('Following')) {
          followBtn = ariaButtons[ai];
          break;
        }
      }
      if (followBtn) break;

      // Strategy 4: Text-based fallback (scoped to primary column)
      followBtn = findButtonByText('follow', scope);
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

    // Handle confirmation sheet dialog (X sometimes shows "Follow @user" confirmation)
    var confirmBtn = document.querySelector('[data-testid="confirmationSheetConfirm"]');
    if (confirmBtn) {
      var confirmRect = confirmBtn.getBoundingClientRect();
      if (confirmRect.width > 0 && confirmRect.height > 0) {
        confirmBtn.click();
        await sleep(2000);
      }
    }

    // Verify the follow was successful
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'x' };
    }

    // Click happened but follow state could not be confirmed
    return { success: false, attempted: true, platform: 'x', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'x' };
  }
})();
