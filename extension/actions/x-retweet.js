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

  function isAlreadyReposted() {
    // X shows a green retweet icon / "Undo repost" when already reposted
    var retweetBtn = document.querySelector('article [data-testid="unretweet"]');
    if (retweetBtn) return true;

    // Check aria-label
    var buttons = document.querySelectorAll('article [role="button"]');
    for (var i = 0; i < buttons.length; i++) {
      var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('undo repost') || label.includes('unretweet')) return true;
    }

    return false;
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
      // Strategy 1: data-testid
      retweetBtn = document.querySelector('article [data-testid="retweet"]');
      if (retweetBtn) break;

      // Strategy 2: aria-label
      var buttons = document.querySelectorAll('article [role="button"]');
      for (var i = 0; i < buttons.length; i++) {
        var label = (buttons[i].getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('repost') || label.includes('retweet')) {
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
    await sleep(1500);

    // Click "Repost" in the dropdown menu or confirmation sheet
    var menuItems = document.querySelectorAll('[role="menuitem"], [data-testid="retweetConfirm"], [data-testid="confirmationSheetConfirm"]');
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
    } else {
      // Check for confirmation sheet as a separate step (sometimes appears after a delay)
      await sleep(500);
      var confirmBtn = document.querySelector('[data-testid="confirmationSheetConfirm"]');
      if (confirmBtn) {
        var confirmRect = confirmBtn.getBoundingClientRect();
        if (confirmRect.width > 0 && confirmRect.height > 0) {
          confirmBtn.click();
          await sleep(2000);
        }
      } else {
        // Menu might not have appeared; the button click alone might have toggled repost
        await sleep(1000);
      }
    }

    if (isAlreadyReposted()) {
      return { success: true, alreadyDone: false, platform: 'x', action: 'retweet' };
    }

    return { success: true, alreadyDone: false, platform: 'x', action: 'retweet', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'x', action: 'retweet' };
  }
})();
