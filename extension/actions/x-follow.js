// X/Twitter Follow Action Script
// Injected into x.com/twitter.com tabs to click the Follow button.
(async function xFollowAction() {
  'use strict';

  const TIMEOUT = 12000;
  const POLL_INTERVAL = 500;

  function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
  }

  // Wait for an element matching any of the selectors to appear
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

  // Check if we're already following this account
  function isAlreadyFollowing() {
    // X shows "Following" button when already following
    const followingBtn = document.querySelector('[data-testid="placementTracking"] [role="button"][data-testid$="-unfollow"]');
    if (followingBtn) return true;

    // Check for aria-label indicating following state
    const btns = document.querySelectorAll('[role="button"]');
    for (const btn of btns) {
      const label = (btn.getAttribute('aria-label') || '').toLowerCase();
      if (label.includes('following') && !label.includes('followers')) return true;
    }

    // Check button text
    const spans = document.querySelectorAll('[data-testid="placementTracking"] span span');
    for (const span of spans) {
      const txt = (span.textContent || '').trim().toLowerCase();
      if (txt === 'following') return true;
    }

    return false;
  }

  try {
    // Wait for the page to settle
    await sleep(2000);

    // Check if already following
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'x' };
    }

    // Find the follow button
    const followSelectors = [
      '[data-testid="placementTracking"] [role="button"]',
      'button[data-testid$="-follow"]',
      '[role="button"][aria-label*="Follow @"]',
    ];

    const followBtn = await waitForElement(followSelectors, TIMEOUT);
    if (!followBtn) {
      // Maybe we're already following and didn't detect it
      if (isAlreadyFollowing()) {
        return { success: true, alreadyFollowing: true, platform: 'x' };
      }
      return { success: false, error: 'Follow button not found', platform: 'x' };
    }

    // Verify it's a Follow button (not Following/Unfollow)
    const btnText = (followBtn.textContent || '').trim().toLowerCase();
    if (btnText === 'following' || btnText === 'unfollow') {
      return { success: true, alreadyFollowing: true, platform: 'x' };
    }

    // Click the follow button
    followBtn.click();
    await sleep(1500);

    // Verify the follow was successful
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'x' };
    }

    // Even if we can't verify, the click happened
    return { success: true, alreadyFollowing: false, platform: 'x', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'x' };
  }
})();
