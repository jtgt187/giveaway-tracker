// Instagram Like Action Script
// Injected into instagram.com tabs to click the Like button on a post/reel.
(async function instagramLikeAction() {
  'use strict';

  const TIMEOUT = 12000;
  const POLL_INTERVAL = 500;

  // Localized "Like" and "Unlike" text variants
  var LIKE_TEXTS = ['like', 'gefällt mir', 'j\'aime', 'me gusta', 'mi piace', 'vind ik leuk', 'curtir', 'いいね'];
  var UNLIKE_TEXTS = ['unlike', 'gefällt mir nicht mehr', 'je n\'aime plus', 'ya no me gusta', 'non mi piace più', 'vind ik niet meer leuk', 'descurtir'];

  function isLikeText(text) {
    var lower = (text || '').trim().toLowerCase();
    return LIKE_TEXTS.indexOf(lower) !== -1;
  }

  function isUnlikeText(text) {
    var lower = (text || '').trim().toLowerCase();
    return UNLIKE_TEXTS.indexOf(lower) !== -1;
  }

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function isNotLoggedIn() {
    if (location.pathname.startsWith('/accounts/login')) return true;
    var loginModal = document.querySelector('[role="dialog"] input[name="username"]');
    if (loginModal) return true;
    // Also check for login links (like instagram-follow.js does)
    var loginBtns = document.querySelectorAll('a[href*="/accounts/login"], button');
    for (var i = 0; i < loginBtns.length; i++) {
      var txt = (loginBtns[i].textContent || '').trim().toLowerCase();
      if (txt === 'log in' || txt === 'sign up' || txt === 'anmelden' || txt === 'connexion') {
        var rect = loginBtns[i].getBoundingClientRect();
        if (rect.width > 80 && rect.height > 20) return true;
      }
    }
    return false;
  }

  function isAlreadyLiked() {
    // Instagram uses aria-label for unlike state (localized)
    var unlikeButtons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
    for (var i = 0; i < unlikeButtons.length; i++) {
      var label = (unlikeButtons[i].getAttribute('aria-label') || '').toLowerCase();
      if (isUnlikeText(label)) {
        var rect = unlikeButtons[i].getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return true;
      }
    }

    // Check for filled heart SVG (liked state) - localized aria-label
    for (var j = 0; j < UNLIKE_TEXTS.length; j++) {
      var svgs = document.querySelectorAll('article svg[aria-label="' + UNLIKE_TEXTS[j] + '"], section svg[aria-label="' + UNLIKE_TEXTS[j] + '"]');
      if (svgs.length > 0) return true;
      // Also try capitalized
      var cap = UNLIKE_TEXTS[j].charAt(0).toUpperCase() + UNLIKE_TEXTS[j].slice(1);
      svgs = document.querySelectorAll('article svg[aria-label="' + cap + '"], section svg[aria-label="' + cap + '"]');
      if (svgs.length > 0) return true;
    }

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
      // Strategy 1: aria-label with localized "Like" text on button
      var buttons = document.querySelectorAll('button[aria-label], [role="button"][aria-label]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if (isLikeText(label) && !isUnlikeText(label)) {
          var rect = buttons[i].getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            likeBtn = buttons[i];
            break;
          }
        }
      }
      if (likeBtn) break;

      // Strategy 2: SVG with localized aria-label "Like"
      for (var li = 0; li < LIKE_TEXTS.length; li++) {
        var svgLike = document.querySelector('svg[aria-label="' + LIKE_TEXTS[li] + '"]') ||
                      document.querySelector('svg[aria-label="' + LIKE_TEXTS[li].charAt(0).toUpperCase() + LIKE_TEXTS[li].slice(1) + '"]');
        if (svgLike) {
          var parent = svgLike.closest('button') || svgLike.closest('[role="button"]');
          if (parent) {
            likeBtn = parent;
            break;
          }
        }
      }
      if (likeBtn) break;

      // Strategy 3: Find the like button in the article/post section by SVG
      var articleBtns = document.querySelectorAll('article section button, article button');
      for (var j = 0; j < articleBtns.length; j++) {
        for (var lj = 0; lj < LIKE_TEXTS.length; lj++) {
          var svg = articleBtns[j].querySelector('svg[aria-label="' + LIKE_TEXTS[lj] + '"]') ||
                    articleBtns[j].querySelector('svg[aria-label="' + LIKE_TEXTS[lj].charAt(0).toUpperCase() + LIKE_TEXTS[lj].slice(1) + '"]');
          if (svg) {
            likeBtn = articleBtns[j];
            break;
          }
        }
        if (likeBtn) break;
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
