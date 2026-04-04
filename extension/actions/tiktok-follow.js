// TikTok Follow Action Script
// Injected into tiktok.com tabs to click the Follow button.
(async function tiktokFollowAction() {
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
    // TikTok shows "Following" or "Friends" when already following
    const followingBtns = document.querySelectorAll('[data-e2e="follow-button"], [data-e2e="unfollow-button"]');
    for (const btn of followingBtns) {
      const txt = (btn.textContent || '').trim().toLowerCase();
      if (txt === 'following' || txt === 'friends') return true;
      if (btn.getAttribute('data-e2e') === 'unfollow-button') return true;
    }

    // Check all buttons in the profile header area
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
      const txt = (btn.textContent || '').trim().toLowerCase();
      if (txt === 'following' || txt === 'friends') {
        const rect = btn.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && rect.top < 500) return true;
      }
    }

    return false;
  }

  try {
    await sleep(2500);

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'tiktok' };
    }

    const followSelectors = [
      '[data-e2e="follow-button"]',
      'button[class*="follow-button"]',
      // Profile page follow button
      '[class*="ShareFollowButton"]',
    ];

    let followBtn = await waitForElement(followSelectors, TIMEOUT);

    // Verify it actually says "Follow"
    if (followBtn) {
      const txt = (followBtn.textContent || '').trim().toLowerCase();
      if (txt === 'following' || txt === 'friends') {
        return { success: true, alreadyFollowing: true, platform: 'tiktok' };
      }
    }

    // Fallback: search all buttons for "Follow"
    if (!followBtn) {
      const buttons = document.querySelectorAll('button');
      for (const btn of buttons) {
        const txt = (btn.textContent || '').trim().toLowerCase();
        if (txt === 'follow') {
          const rect = btn.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0 && rect.top < 500) {
            followBtn = btn;
            break;
          }
        }
      }
    }

    if (!followBtn) {
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'tiktok' };
      }
      return { success: false, error: 'Follow button not found', platform: 'tiktok' };
    }

    followBtn.click();
    await sleep(2000);

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'tiktok' };
    }

    return { success: true, alreadyFollowing: false, platform: 'tiktok', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'tiktok' };
  }
})();
