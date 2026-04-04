// Instagram Follow Action Script
// Injected into instagram.com tabs to click the Follow button.
(async function instagramFollowAction() {
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
    // Instagram shows "Following" or "Requested" button when already following
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
      const txt = (btn.textContent || '').trim().toLowerCase();
      if (txt === 'following' || txt === 'requested') return true;
      // Instagram also uses aria-label
      const label = (btn.getAttribute('aria-label') || '').toLowerCase();
      if (label === 'following' || label === 'requested') return true;
    }

    // Check for the "Following" button with a specific structure (IG uses divs inside buttons)
    const headerSection = document.querySelector('header section');
    if (headerSection) {
      const btns = headerSection.querySelectorAll('button');
      for (const btn of btns) {
        // Following button often contains a dropdown arrow/icon
        const innerText = (btn.innerText || '').trim().toLowerCase();
        if (innerText === 'following' || innerText === 'requested') return true;
      }
    }

    return false;
  }

  try {
    await sleep(2500);

    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: true, platform: 'instagram' };
    }

    // Instagram follow button selectors (these change frequently)
    const followSelectors = [
      // Header follow button on profile page
      'header section button:not([type="button"])',
      'header button',
      // Various IG class patterns
      'button._acan',
      'button._acap',
      // Fallback: find button with "Follow" text in the header area
    ];

    let followBtn = await waitForElement(followSelectors, TIMEOUT);

    // If generic selectors matched, verify it's actually a Follow button
    if (followBtn) {
      const txt = (followBtn.textContent || '').trim().toLowerCase();
      if (txt !== 'follow') {
        // Try to find the actual Follow button by text content
        followBtn = null;
      }
    }

    // Fallback: search all buttons for one that says "Follow"
    if (!followBtn) {
      const allButtons = document.querySelectorAll('button');
      for (const btn of allButtons) {
        const txt = (btn.textContent || '').trim().toLowerCase();
        if (txt === 'follow') {
          // Make sure it's visible and in the profile area
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
        return { success: true, alreadyFollowing: true, platform: 'instagram' };
      }
      return { success: false, error: 'Follow button not found', platform: 'instagram' };
    }

    followBtn.click();
    await sleep(2000);

    // Check for success
    if (isAlreadyFollowing()) {
      return { success: true, alreadyFollowing: false, platform: 'instagram' };
    }

    return { success: true, alreadyFollowing: false, platform: 'instagram', note: 'clicked but could not verify' };

  } catch (e) {
    return { success: false, error: e.message, platform: 'instagram' };
  }
})();
