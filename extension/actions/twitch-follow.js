// Twitch Follow Action Script
// Injected into twitch.tv tabs to click the Follow button.
(async function twitchFollowAction() {
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

  function isAlreadyFollowing() {
    // Twitch shows "Unfollow" or heart icon when following
    const unfollowBtn = document.querySelector('[data-a-target="unfollow-button"]');
    if (unfollowBtn) return true;

    // Check for "Following" text in follow area
    const followArea = document.querySelector('[data-a-target="follow-button"]');
    if (!followArea) {
      // If no follow button exists, check for unfollow button presence
      const btns = document.querySelectorAll('button');
      for (const btn of btns) {
        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('unfollow')) return true;
      }
    }

    return false;
  }

  function isNotLoggedIn() {
    // Twitch shows a login modal or redirects to login
    if (location.pathname.startsWith('/login')) return true;
    var loginModal = document.querySelector('[data-a-target="login-modal"]');
    if (loginModal) return true;
    // Check for prominent "Log In" button in the top nav
    var loginBtn = document.querySelector('[data-a-target="login-button"]');
    if (loginBtn) {
      var rect = loginBtn.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) return true;
    }
    return false;
  }

  try {
    await sleep(2500);

    if (isNotLoggedIn()) {
      return { success: false, error: 'Not logged in to Twitch', platform: 'twitch' };
    }

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'twitch' };
    }

    const followSelectors = [
      '[data-a-target="follow-button"]',
      'button[aria-label="Follow"]',
      // Fallback: look for button with Follow text
    ];

    let followBtn = await waitForElement(followSelectors, TIMEOUT);

    // Fallback: search by text
    if (!followBtn) {
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        const txt = (btn.textContent || '').trim().toLowerCase();
        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
        if (txt === 'follow' || label === 'follow') {
          const rect = btn.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            followBtn = btn;
            break;
          }
        }
      }
    }

    if (!followBtn) {
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'twitch' };
      }
      return { success: false, error: 'Follow button not found', platform: 'twitch' };
    }

    followBtn.click();
    await sleep(1500);

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'twitch' };
    }

    return { success: true, alreadyFollowing: false, platform: 'twitch', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'twitch' };
  }
})();
