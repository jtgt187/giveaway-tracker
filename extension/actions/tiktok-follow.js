// TikTok Follow Action Script
// Injected into tiktok.com tabs to click the Follow button.
(async function tiktokFollowAction() {
  'use strict';

  const TIMEOUT = 15000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  /**
   * Check if user is not logged in to TikTok.
   */
  function isNotLoggedIn() {
    // TikTok shows a login modal
    var loginModal = document.querySelector('[data-e2e="login-modal"]');
    if (loginModal) return true;

    // Check for login dialog with username/password fields
    var loginForm = document.querySelector('form input[name="username"], [class*="login-modal"]');
    if (loginForm) return true;

    // Check for "Log in" prominent button/link at the top
    var loginLinks = document.querySelectorAll('a[href*="/login"], button[data-e2e="top-login-button"]');
    for (var i = 0; i < loginLinks.length; i++) {
      var txt = (loginLinks[i].textContent || '').trim().toLowerCase();
      if (txt === 'log in' || txt === 'login') {
        var rect = loginLinks[i].getBoundingClientRect();
        if (rect.width > 50 && rect.height > 20 && rect.top < 100) return true;
      }
    }

    return false;
  }

  /**
   * Find a visible button by text content in the profile/header area (top 500px).
   */
  function findFollowButtonByText(text) {
    var lower = text.toLowerCase();
    var buttons = document.querySelectorAll('button, [role="button"]');

    for (var i = 0; i < buttons.length; i++) {
      var btn = buttons[i];
      var btnText = (btn.textContent || '').trim().toLowerCase();

      if (btnText === lower) {
        var rect = btn.getBoundingClientRect();
        // Must be visible and in the upper portion (profile area)
        if (rect.width > 0 && rect.height > 0 && rect.top < 500) return btn;
      }
    }
    return null;
  }

  function isAlreadyFollowing() {
    // data-e2e based detection
    var unfollowBtn = document.querySelector('[data-e2e="unfollow-button"]');
    if (unfollowBtn) return true;

    // Check for "Following" or "Friends" text on buttons in profile area
    if (findFollowButtonByText('following')) return true;
    if (findFollowButtonByText('friends')) return true;

    // Check data-e2e follow button that says "Following"
    var followE2E = document.querySelector('[data-e2e="follow-button"]');
    if (followE2E) {
      var txt = (followE2E.textContent || '').trim().toLowerCase();
      if (txt === 'following' || txt === 'friends') return true;
    }

    return false;
  }

  try {
    // Wait for TikTok SPA to render (React hydration is slow)
    await sleep(3500);

    // Check login state
    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to TikTok', platform: 'tiktok' };
    }

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'tiktok' };
    }

    // Poll for the follow button
    var followBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      // Strategy 1: data-e2e attribute (most reliable when present)
      followBtn = document.querySelector('[data-e2e="follow-button"]');
      if (followBtn) {
        var txt = (followBtn.textContent || '').trim().toLowerCase();
        if (txt === 'following' || txt === 'friends') {
          return { success: true, alreadyFollowing: true, platform: 'tiktok' };
        }
        if (txt === 'follow') break;
        // Reset if button text doesn't match
        followBtn = null;
      }

      // Strategy 2: class-based selectors
      var classBtn = document.querySelector('button[class*="follow-button"], [class*="FollowButton"]');
      if (classBtn) {
        var ctxt = (classBtn.textContent || '').trim().toLowerCase();
        if (ctxt === 'follow') {
          followBtn = classBtn;
          break;
        }
      }

      // Strategy 3: Text-based fallback in profile area
      followBtn = findFollowButtonByText('follow');
      if (followBtn) break;

      // Re-check if now following
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'tiktok' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!followBtn) {
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'tiktok' };
      }
      return { success: false, error: 'Follow button not found', platform: 'tiktok' };
    }

    followBtn.click();
    await sleep(2500);

    // Check if login modal appeared after click (not logged in)
    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to TikTok (login modal appeared)', platform: 'tiktok' };
    }

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'tiktok' };
    }

    return { success: true, alreadyFollowing: false, platform: 'tiktok', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'tiktok' };
  }
})();
