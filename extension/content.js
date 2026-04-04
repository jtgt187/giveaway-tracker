(function(){
  // Don't collect links from local development pages (e.g. Streamlit dashboard)
  if (['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)) return;

  let seenHref = new Set();
  let pageCount = 0;
  let hidden = false;

  // Only accept URLs actually hosted on gleam.io (not reddit.com/search?q=gleam.io etc.)
  function isGleamUrl(href) {
    try {
      const u = new URL(href, location.href);
      return u.hostname === 'gleam.io' || u.hostname.endsWith('.gleam.io');
    } catch (e) {
      return false;
    }
  }

  // Normalize gleam URLs: strip query params and trailing slashes for better dedup
  function normalizeGleamUrl(urlStr) {
    try {
      const u = new URL(urlStr);
      if (u.hostname.includes('gleam.io')) {
        u.search = '';
        u.hash = '';
        return u.toString().replace(/\/+$/, '');
      }
      return urlStr;
    } catch (e) {
      return urlStr;
    }
  }

  // Visual indicator — bottom-right banner for THIS page only
  const indicator = document.createElement('div');
  indicator.id = 'gleam-monitor-indicator';
  indicator.style.cssText =
    'position:fixed;bottom:10px;right:10px;background:#7c3aed;color:white;' +
    'padding:8px 14px;border-radius:6px;font-size:12px;z-index:999999;' +
    'opacity:0.9;cursor:pointer;user-select:none;transition:opacity .3s;';
  indicator.title = 'Click to dismiss';
  document.body.appendChild(indicator);

  // Click to hide/show the banner
  indicator.addEventListener('click', function() {
    if (hidden) {
      indicator.style.opacity = '0.9';
      indicator.style.width = '';
      indicator.style.overflow = '';
      indicator.textContent = pageCount > 0
        ? 'Gleam: ' + pageCount + ' on this page'
        : 'Gleam: No links';
      hidden = false;
    } else {
      indicator.style.opacity = '0.4';
      indicator.style.width = '24px';
      indicator.style.overflow = 'hidden';
      indicator.textContent = pageCount > 0 ? pageCount : '-';
      hidden = true;
    }
  });

  function updateIndicator(msg) {
    if (hidden) return;
    indicator.textContent = msg;
    indicator.style.background = pageCount > 0 ? '#10b981' : '#7c3aed';
  }

  updateIndicator('Gleam: Scanning...');

  function sendLink(href, text) {
    const normalized = normalizeGleamUrl(href);
    if (seenHref.has(normalized)) return;
    seenHref.add(normalized);
    pageCount++;

    // Update banner immediately with page-local count
    updateIndicator('Gleam: ' + pageCount + ' on this page');

    chrome.runtime.sendMessage({
      type: 'append',
      href: normalized,
      text: text || ''
    }, function(response) {
      // Badge update is handled by background.js — nothing to do here
      if (chrome.runtime.lastError) {
        console.warn('Gleam Monitor: sendMessage error', chrome.runtime.lastError.message);
      }
    });
  }

  function extractFromHTML() {
    const anchors = document.querySelectorAll('a[href*="gleam.io"]');

    if (anchors.length === 0) {
      updateIndicator('Gleam: No links');
      return;
    }

    anchors.forEach(a => {
      try {
        const url = new URL(a.href, location.href).toString();
        if (!isGleamUrl(url)) return;
        const text = (a.textContent || '').trim();
        sendLink(url, text);
      } catch (e) {}
    });
  }

  function scanMutations() {
    const anchors = document.querySelectorAll('a[href*="gleam.io"]');
    anchors.forEach(a => {
      try {
        const url = new URL(a.href, location.href).toString();
        if (!isGleamUrl(url)) return;
        const normalized = normalizeGleamUrl(url);
        if (!seenHref.has(normalized)) {
          const text = (a.textContent || '').trim();
          sendLink(url, text);
        }
      } catch (e) {}
    });
  }

  function initObserver() {
    const observer = new MutationObserver(() => {
      scanMutations();
    });

    if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      extractFromHTML();
      initObserver();
    });
  } else {
    extractFromHTML();
    initObserver();
  }

  setTimeout(scanMutations, 1000);
  setTimeout(scanMutations, 3000);
  setTimeout(scanMutations, 5000);
})();
