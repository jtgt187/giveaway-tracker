// YouTube Subscribe Action Script
// Injected into youtube.com tabs to click the Subscribe button.
(async function youtubeSubscribeAction() {
  'use strict';

  const TIMEOUT = 12000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  async function waitForElement(selectors, timeout) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) return el;
      }
      await sleep(POLL_INTERVAL);
    }
    return null;
  }

  function isAlreadySubscribed() {
    // YouTube shows "Subscribed" button when already subscribed
    const subBtn = document.querySelector('ytd-subscribe-button-renderer');
    if (subBtn) {
      const subscribed = subBtn.getAttribute('subscribed');
      if (subscribed !== null && subscribed !== 'false') return true;

      // Check button text
      const btnText = (subBtn.textContent || '').trim().toLowerCase();
      if (btnText === 'subscribed') return true;
    }

    // Alternative: check for the subscribe button's aria state
    const buttons = document.querySelectorAll('#subscribe-button button, ytd-subscribe-button-renderer button');
    for (const btn of buttons) {
      const label = (btn.getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('unsubscribe')) return true;
      const txt = (btn.textContent || '').trim().toLowerCase();
      if (txt === 'subscribed') return true;
    }

    return false;
  }

  function isNotLoggedIn() {
    // YouTube shows "Sign in" button when not logged in (only in top bar)
    var signInBtn = document.querySelector('ytd-masthead a[href*="accounts.google.com/ServiceLogin"]');
    if (signInBtn) return true;
    // Check for the "Sign in" text button in top bar
    var buttons = document.querySelectorAll('ytd-button-renderer, tp-yt-paper-button');
    for (var i = 0; i < buttons.length; i++) {
      var txt = (buttons[i].textContent || '').trim().toLowerCase();
      if (txt === 'sign in') {
        var rect = buttons[i].getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && rect.top < 80) return true;
      }
    }
    return false;
  }

  try {
    await sleep(2500);

    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to YouTube', platform: 'youtube' };
    }

    if (isAlreadySubscribed()) {
      return { success: true, alreadyFollowing: true, platform: 'youtube' };
    }

    const subscribeSelectors = [
      '#subscribe-button ytd-subscribe-button-renderer button',
      'ytd-subscribe-button-renderer button',
      '#subscribe-button button',
      'tp-yt-paper-button.ytd-subscribe-button-renderer',
      // Channel page subscribe button
      '#channel-header ytd-subscribe-button-renderer button',
    ];

    let subBtn = await waitForElement(subscribeSelectors, TIMEOUT);

    // Fallback: find button with "Subscribe" text
    if (!subBtn) {
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        const txt = (btn.textContent || '').trim().toLowerCase();
        if (txt === 'subscribe') {
          const rect = btn.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            subBtn = btn;
            break;
          }
        }
      }
    }

    if (!subBtn) {
      if (isAlreadySubscribed()) {
        return { success: true, alreadyFollowing: true, platform: 'youtube' };
      }
      return { success: false, error: 'Subscribe button not found', platform: 'youtube' };
    }

    // Verify it says "Subscribe" (not "Subscribed")
    const btnText = (subBtn.textContent || '').trim().toLowerCase();
    if (btnText === 'subscribed') {
      return { success: true, alreadyFollowing: true, platform: 'youtube' };
    }

    subBtn.click();
    await sleep(2000);

    if (isAlreadySubscribed()) {
      return { success: true, alreadyFollowing: false, platform: 'youtube' };
    }

    return { success: true, alreadyFollowing: false, platform: 'youtube', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'youtube' };
  }
})();
