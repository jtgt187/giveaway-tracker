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
    // TikTok uses data-e2e="like-icon" or similar with an active/liked state
    var likeBtn = document.querySelector('[data-e2e="like-icon"]');
    if (likeBtn) {
      // Check if the like icon has an active/filled state (color change)
      var color = window.getComputedStyle(likeBtn).color;
      // TikTok uses red (rgb(254, 44, 85)) for liked state
      if (color && (color.includes('254') || color.includes('fe2c55'))) return true;
      // Also check aria-pressed or class names
      var classList = (likeBtn.className || '').toLowerCase();
      if (classList.includes('active') || classList.includes('liked')) return true;
    }

    // Check for aria-pressed on like buttons
    var ariaButtons = document.querySelectorAll('[aria-pressed="true"][aria-label*="like" i]');
    if (ariaButtons.length > 0) return true;

    // Check for "liked" class on any like-related element
    var likedElements = document.querySelectorAll('[class*="like"][class*="active"], [class*="Like"][class*="active"]');
    if (likedElements.length > 0) return true;

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
        // Walk up to the clickable parent if needed
        var clickable = likeBtn.closest('button') || likeBtn.closest('[role="button"]') || likeBtn;
        likeBtn = clickable;
        break;
      }

      // Strategy 2: aria-label based
      var buttons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if (label === 'like' || label.includes('like video')) {
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

    return { success: true, alreadyDone: false, platform: 'tiktok', action: 'like', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'tiktok', action: 'like' };
  }
})();
