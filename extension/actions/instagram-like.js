// Instagram Like Action Script
// Injected into instagram.com tabs to click the Like button on a post/reel.
(async function instagramLikeAction() {
  'use strict';

  const TIMEOUT = 12000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function isNotLoggedIn() {
    if (location.pathname.startsWith('/accounts/login')) return true;
    var loginModal = document.querySelector('[role="dialog"] input[name="username"]');
    if (loginModal) return true;
    return false;
  }

  function isAlreadyLiked() {
    // Instagram uses aria-label "Unlike" when already liked
    var unlikeButtons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
    for (var i = 0; i < unlikeButtons.length; i++) {
      var label = (unlikeButtons[i].getAttribute('aria-label') || '').toLowerCase();
      if (label === 'unlike') {
        var rect = unlikeButtons[i].getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return true;
      }
    }

    // Check for filled heart SVG (liked state)
    var svgs = document.querySelectorAll('article svg[aria-label="Unlike"], section svg[aria-label="Unlike"]');
    if (svgs.length > 0) return true;

    return false;
  }

  try {
    await sleep(3000);

    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to Instagram', platform: 'instagram', action: 'like' };
    }

    if (isAlreadyLiked()) {
      return { success: true, alreadyDone: true, platform: 'instagram', action: 'like' };
    }

    // Find the like button
    var likeBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      // Strategy 1: aria-label "Like" on button
      var buttons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if (label === 'like') {
          var rect = buttons[i].getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            likeBtn = buttons[i];
            break;
          }
        }
      }
      if (likeBtn) break;

      // Strategy 2: SVG with aria-label "Like"
      var svgLike = document.querySelector('svg[aria-label="Like"]');
      if (svgLike) {
        // Walk up to find the clickable parent button
        var parent = svgLike.closest('button') || svgLike.closest('[role="button"]');
        if (parent) {
          likeBtn = parent;
          break;
        }
      }

      // Strategy 3: Find the like button in the article/post section
      var articleBtns = document.querySelectorAll('article section button, article button');
      for (var j = 0; j < articleBtns.length; j++) {
        var svg = articleBtns[j].querySelector('svg[aria-label="Like"]');
        if (svg) {
          likeBtn = articleBtns[j];
          break;
        }
      }
      if (likeBtn) break;

      if (isAlreadyLiked()) {
        return { success: true, alreadyDone: true, platform: 'instagram', action: 'like' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!likeBtn) {
      if (isAlreadyLiked()) {
        return { success: true, alreadyDone: true, platform: 'instagram', action: 'like' };
      }
      return { success: false, error: 'Like button not found', platform: 'instagram', action: 'like' };
    }

    likeBtn.click();
    await sleep(2000);

    if (isAlreadyLiked()) {
      return { success: true, alreadyDone: false, platform: 'instagram', action: 'like' };
    }

    return { success: true, alreadyDone: false, platform: 'instagram', action: 'like', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'instagram', action: 'like' };
  }
})();
