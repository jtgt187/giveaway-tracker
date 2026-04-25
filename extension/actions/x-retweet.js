// X/Twitter Repost (Retweet) Action Script
// Injected into x.com/twitter.com tabs to click the Repost button on a tweet.
(async function xRetweetAction() {
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
    return articles[0] || document.body;
  }

  function isAlreadyReposted() {
    var scope = getTargetArticle();
    // X shows a green retweet icon / "Undo repost" when already reposted
    var retweetBtn = scope.querySelector('[data-testid="unretweet"]');
    if (retweetBtn) return true;

    // Check aria-label
    var buttons = scope.querySelectorAll('[role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('undo repost') || label.includes('unretweet')) return true;
    }

    return false;
  }

  /**
   * Wait for an element matching `selector` to appear, up to `timeout` ms.
   */
  async function waitForSelector(selector, timeout) {
    var deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      var el = document.querySelector(selector);
      if (el) {
        var rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) return el;
      }
      await sleep(150);
    }
    return null;
  }

  try {
    await sleep(3000);

    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to X/Twitter', platform: 'x', action: 'retweet' };
    }

    if (isAlreadyReposted()) {
      return { success: true, alreadyDone: true, platform: 'x', action: 'retweet' };
    }

    // Find the retweet/repost button on the tweet
    var retweetBtn = null;
    var start = Date.now();

    while (Date.now() - start < TIMEOUT) {
      var scope = getTargetArticle();
      // Strategy 1: data-testid
      retweetBtn = scope.querySelector('[data-testid="retweet"]');
      if (retweetBtn) break;

      // Strategy 2: aria-label
      var buttons = scope.querySelectorAll('[role="button"]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if ((label.includes('repost') || label.includes('retweet')) && !label.includes('undo') && !label.includes('un-')) {
          retweetBtn = buttons[i];
          break;
        }
      }
      if (retweetBtn) break;

      if (isAlreadyReposted()) {
        return { success: true, alreadyDone: true, platform: 'x', action: 'retweet' };
      }

      await sleep(POLL_INTERVAL);
    }

    if (!retweetBtn) {
      if (isAlreadyReposted()) {
        return { success: true, alreadyDone: true, platform: 'x', action: 'retweet' };
      }
      return { success: false, error: 'Repost button not found', platform: 'x', action: 'retweet' };
    }

    // Click the repost button (opens a menu)
    retweetBtn.click();

    // Prefer the dedicated confirm-action testid over text matching, which
    // would otherwise also match "Repost with comment" (Quote Tweet).
    var confirmEl = await waitForSelector('[data-testid="retweetConfirm"], [data-testid="confirmationSheetConfirm"]', 2500);
    if (confirmEl) {
      confirmEl.click();
      await sleep(2000);
    } else {
      // Strict text-match fallback (NEVER match "Repost with comment")
      var menuItems = document.querySelectorAll('[role="menuitem"]');
      var repostMenuItem = null;
      for (var j = 0; j < menuItems.length; j++) {
        var txt = (menuItems[j].textContent || '').trim().toLowerCase();
        if (txt === 'repost' || txt === 'retweet') {
          repostMenuItem = menuItems[j];
          break;
        }
      }
      if (repostMenuItem) {
        repostMenuItem.click();
        await sleep(2000);
      }
    }

    if (isAlreadyReposted()) {
      return { success: true, alreadyDone: false, platform: 'x', action: 'retweet' };
    }

    return { success: false, attempted: true, platform: 'x', action: 'retweet', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'x', action: 'retweet' };
  }
})();
