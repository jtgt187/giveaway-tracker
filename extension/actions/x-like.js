// X/Twitter Like Action Script
// Injected into x.com/twitter.com tabs to click the Like button on a tweet.
(async function xLikeAction() {
  'use strict';

  const TIMEOUT = 12000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  function isNotLoggedIn() {
    if (location.pathname === '/login' || location.pathname.startsWith('/i/flow/login')) return true;
    if (document.querySelector('[data-testid="loginButton"]')) return true;
    if (document.querySelector('[data-testid="BottomBar"]')) return true;
    return false;
  }

  /**
   * Find the article element matching the current tweet URL (path).
   * Avoids liking a reply that happens to render before the target tweet.
   */
  function getTargetArticle() {
    var path = location.pathname; // e.g. /user/status/123
    var articles = document.querySelectorAll('article');
    for (var i = 0; i < articles.length; i++) {
      var links = articles[i].querySelectorAll('a[href*="/status/"]');
      for (var j = 0; j < links.length; j++) {
        try {
          var hrefPath = new URL(links[j].href).pathname;
          if (hrefPath === path || hrefPath.startsWith(path + '/')) {
            return articles[i];
          }
        } catch (e) {}
      }
    }
    // Fallback: first article
    return articles[0] || document.body;
  }

  function isAlreadyLiked() {
    var scope = getTargetArticle();
    // X uses data-testid="unlike" when the tweet is already liked
    var unlikeBtn = scope.querySelector('[data-testid="unlike"]');
    if (unlikeBtn) return true;

    // Check aria-label
    var buttons = scope.querySelectorAll('[role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('unlike') || (label.includes('liked') && label.includes('@'))) return true;
    }

    return false;
  }

  try {
    await sleep(3000);

    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to X/Twitter', platform: 'x', action: 'like' };
    }

    if (isAlreadyLiked()) {
      return { success: true, alreadyDone: true, platform: 'x', action: 'like' };
    }

    // Find the like button
    var likeBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      var scope = getTargetArticle();
      // Strategy 1: data-testid
      likeBtn = scope.querySelector('[data-testid="like"]');
      if (likeBtn) break;

      // Strategy 2: aria-label
      var buttons = scope.querySelectorAll('[role="button"]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('like') && !label.includes('unlike') && !label.includes('liked')) {
          likeBtn = buttons[i];
          break;
        }
      }
      if (likeBtn) break;

      if (isAlreadyLiked()) {
        return { success: true, alreadyDone: true, platform: 'x', action: 'like' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!likeBtn) {
      if (isAlreadyLiked()) {
        return { success: true, alreadyDone: true, platform: 'x', action: 'like' };
      }
      return { success: false, error: 'Like button not found', platform: 'x', action: 'like' };
    }

    likeBtn.click();
    await sleep(1500);

    if (isAlreadyLiked()) {
      return { success: true, alreadyDone: false, platform: 'x', action: 'like' };
    }

    return { success: false, attempted: true, platform: 'x', action: 'like', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'x', action: 'like' };
  }
})();
