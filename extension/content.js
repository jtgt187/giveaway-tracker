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

  // Only accept actual giveaway/competition URLs, not FAQ/about/docs/login etc.
  // Valid patterns:
  //   /XXXXX/title-slug   (4-6 alphanum ID + slug)
  //   /giveaways/XXXXX    (giveaways path + 4-6 char ID)
  //   /competitions/XXXXX (competitions path + 4-6 char ID)
  function isGiveawayPath(urlStr) {
    try {
      const u = new URL(urlStr);
      const path = u.pathname.replace(/\/+$/, '');
      // /giveaways/XXXXX or /competitions/XXXXX
      if (/^\/(?:giveaways|competitions)\/[A-Za-z0-9]{4,6}$/.test(path)) return true;
      // /XXXXX/any-slug (the most common gleam format)
      if (/^\/[A-Za-z0-9]{4,6}\/[^/]+$/.test(path)) return true;
      return false;
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

    anchors.forEach(a => {
      try {
        const url = new URL(a.href, location.href).toString();
        if (!isGleamUrl(url) || !isGiveawayPath(url)) return;
        const text = (a.textContent || '').trim();
        sendLink(url, text);
      } catch (e) {}
    });

    // Also scan plain text for gleam.io URLs (search result snippets, etc.)
    scanTextForGleamUrls();

    if (pageCount === 0) {
      updateIndicator('Gleam: No links');
    }
  }

  function scanMutations() {
    const anchors = document.querySelectorAll('a[href*="gleam.io"]');
    anchors.forEach(a => {
      try {
        const url = new URL(a.href, location.href).toString();
        if (!isGleamUrl(url) || !isGiveawayPath(url)) return;
        const normalized = normalizeGleamUrl(url);
        if (!seenHref.has(normalized)) {
          const text = (a.textContent || '').trim();
          sendLink(url, text);
        }
      } catch (e) {}
    });

    // Also scan text content for URLs not wrapped in <a> tags
    scanTextForGleamUrls();
  }

  // Scan plain text content for gleam.io URLs (search snippets, cite elements, etc.)
  // This catches URLs displayed as text in Google/Bing/DuckDuckGo search results
  // where the URL appears in the preview snippet but is not a clickable link.
  function scanTextForGleamUrls() {
    // Regex to match full gleam.io URLs in plain text
    const GLEAM_TEXT_RE = /https?:\/\/(?:[\w-]+\.)*gleam\.io\/[^\s<>"')}\]]+/gi;

    // Targeted containers: search engine snippets, cite elements, and common content areas.
    // Scoped to avoid scanning the entire DOM for performance.
    const containers = document.querySelectorAll(
      // Google
      '.VwiC3b, cite, .IsZvec, .st,' +
      // Bing
      '.b_caption, .b_snippet,' +
      // DuckDuckGo
      '.result__snippet, .result__url,' +
      // Yahoo
      '.compText,' +
      // Generic content
      'article, .post-body, .post-content, .entry-content,' +
      'p, li, td, dd, blockquote'
    );

    containers.forEach(el => {
      const text = el.textContent || '';
      // Quick bail-out: skip elements that don't mention gleam.io at all
      if (text.indexOf('gleam.io') === -1) return;

      let match;
      GLEAM_TEXT_RE.lastIndex = 0;
      while ((match = GLEAM_TEXT_RE.exec(text)) !== null) {
        // Strip trailing punctuation that may have been captured
        let url = match[0].replace(/[.,;:!?)]+$/, '');
        if (isGleamUrl(url) && isGiveawayPath(url)) {
          const snippet = text.substring(0, 140).trim();
          sendLink(url, snippet);
        }
      }

      // Also check for breadcrumb-style URLs (gleam.io › giveaways › xxxxx)
      scanBreadcrumbUrls(text, el);
    });
  }

  // Convert breadcrumb-style URLs displayed by search engines:
  //   "gleam.io › CkSGl › glampings-in-bloom" -> "https://gleam.io/CkSGl/glampings-in-bloom"
  //   "gleam.io › giveaways › wyzeg"           -> "https://gleam.io/giveaways/wyzeg"
  function scanBreadcrumbUrls(text, contextEl) {
    // Match gleam.io followed by one or more › separated path segments
    const BREADCRUMB_RE = /gleam\.io\s*›\s*(\S+(?:\s*›\s*\S+)*)/gi;
    let match;
    while ((match = BREADCRUMB_RE.exec(text)) !== null) {
      const pathPart = match[1].replace(/\s*›\s*/g, '/').replace(/[.,;:!?)]+$/, '');
      const url = 'https://gleam.io/' + pathPart;
      if (isGiveawayPath(url)) {
        const snippet = (contextEl ? contextEl.textContent || '' : text).substring(0, 140).trim();
        sendLink(url, snippet);
      }
    }
  }

  function initObserver() {
    let debounceTimer = null;
    const observer = new MutationObserver(() => {
      // Debounce: wait 300ms after last mutation before scanning
      // to avoid excessive scanning during rapid DOM updates
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(scanMutations, 300);
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
