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
      if (/^\/(?:giveaways|competitions)\/[A-Za-z0-9]{4,8}$/.test(path)) return true;
      // /XXXXX/any-slug (the most common gleam format)
      if (/^\/[A-Za-z0-9]{4,8}\/[^/]+$/.test(path)) return true;
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

  function appendIndicator() {
    if (document.body && !indicator.parentNode) {
      document.body.appendChild(indicator);
    }
  }
  appendIndicator();

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
    // Defense-in-depth: never send truncated URLs to the background script.
    // extractFromHTML() trusts a.href which can still carry an ellipsis when
    // Google renders truncated cite text as a link.
    if (isTruncatedUrl(normalized)) return;
    seenHref.add(normalized);
    pageCount++;

    // Update banner immediately with page-local count
    updateIndicator('Gleam: ' + pageCount + ' on this page');

    try {
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
    } catch (e) {
      // Extension context invalidated (e.g. extension updated while tab is open)
      console.warn('Gleam Monitor: extension context invalidated', e.message);
    }
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

  // Detect whether a URL string has been truncated by the search engine
  // (e.g. "https://gleam.io/U90vi…" or "https://gleam.io/U90vi...")
  function isTruncatedUrl(url) {
    return url.includes('\u2026') || /\.{2,}$/.test(url);
  }

  // Given a DOM element that contains a truncated gleam.io URL, walk up the
  // tree to find a parent or nearby <a> whose href contains the same gleam.io
  // path prefix.  Returns the full href string or null.
  //
  // Typical Google DOM:
  //   <a href="https://gleam.io/U90vi/full-slug">
  //     <cite>gleam.io/U90vi…</cite>
  //   </a>
  function resolveFullUrl(el, partialUrl) {
    // Extract the short path prefix (e.g. "/U90vi") from the truncated URL
    // so we can match it against candidate <a> hrefs.
    let pathPrefix;
    try {
      const u = new URL(partialUrl);
      // Take the first path segment (the giveaway ID)
      const seg = u.pathname.split('/').filter(Boolean)[0];
      if (seg) pathPrefix = '/' + seg;
    } catch (e) {
      // partialUrl may not even parse — try a simple regex fallback
      const m = partialUrl.match(/gleam\.io\/([A-Za-z0-9]{4,6})/);
      if (m) pathPrefix = '/' + m[1];
    }
    if (!pathPrefix) return null;

    // 1) Check if this element itself is inside an <a> with the full URL
    const parentAnchor = el.closest('a[href*="gleam.io"]');
    if (parentAnchor) {
      try {
        const href = new URL(parentAnchor.href).toString();
        if (href.includes(pathPrefix) && isGleamUrl(href) && isGiveawayPath(href)) {
          return normalizeGleamUrl(href);
        }
      } catch (e) {}
    }

    // 2) Walk up to the search-result container and look for any <a> with
    //    a matching gleam.io href.  Search engines wrap each result in a
    //    container element — we check common selectors then fall back to
    //    walking up a few levels.
    const resultContainer = el.closest(
      '.g, .b_algo, .result, .dd, .Sr, [data-hveid], [data-sokoban-container]'
    );
    // Fallback: walk up a few levels, but avoid matching <body>/<html>
    // which would scan the entire page and resolve to the wrong giveaway.
    const fallback = el.parentElement?.parentElement?.parentElement;
    const container = resultContainer ||
      (fallback && fallback !== document.body && fallback !== document.documentElement ? fallback : null);

    if (container) {
      const anchors = container.querySelectorAll('a[href*="gleam.io"]');
      for (const a of anchors) {
        try {
          const href = new URL(a.href).toString();
          if (href.includes(pathPrefix) && isGleamUrl(href) && isGiveawayPath(href)) {
            return normalizeGleamUrl(href);
          }
        } catch (e) {}
      }
    }

    return null;
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

        // Handle truncated URLs (e.g. "gleam.io/U90vi…" from Google previews)
        if (isTruncatedUrl(url)) {
          const resolved = resolveFullUrl(el, url);
          if (resolved) {
            const snippet = text.substring(0, 140).trim();
            sendLink(resolved, snippet);
          }
          // Skip truncated URLs we can't resolve — they'd fail isGiveawayPath anyway
          continue;
        }

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

      // Handle truncated breadcrumbs (e.g. "gleam.io › U90vi…")
      if (isTruncatedUrl(url)) {
        const resolved = resolveFullUrl(contextEl, url);
        if (resolved) {
          sendLink(resolved, '');
        }
        continue;
      }

      if (isGiveawayPath(url)) {
        // Don't send breadcrumb text as a title — it's noise like
        // "gleam.io > giveaways > VPItO".  The real title will come from
        // the background prefetch or URL slug extraction.
        sendLink(url, '');
      }
    }
  }

  function initObserver() {
    let debounceTimer = null;
    let checkInterval = null;
    const observer = new MutationObserver(() => {
      // Debounce: wait 300ms after last mutation before scanning
      // to avoid excessive scanning during rapid DOM updates
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(scanMutations, 300);
    });

    if (document.body) {
      observer.observe(document.body, { childList: true, subtree: true });
    }

    function cleanup() {
      try { observer.disconnect(); } catch (e) {}
      if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
      if (checkInterval) { clearInterval(checkInterval); checkInterval = null; }
      // Also clear the deferred rescan timers
      deferredRescans.forEach(t => clearTimeout(t));
      deferredRescans.length = 0;
    }

    // Disconnect observer when page unloads to prevent leaks
    window.addEventListener('pagehide', cleanup, { once: true });

    // Also disconnect if extension context is invalidated (extension updated/reloaded)
    if (chrome.runtime && chrome.runtime.id) {
      checkInterval = setInterval(() => {
        try {
          // Accessing chrome.runtime.id throws if context is invalidated
          void chrome.runtime.id;
        } catch (e) {
          cleanup();
        }
      }, 10000);
    }
  }

  // Track deferred rescans so they can be cancelled on pagehide
  const deferredRescans = [];

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      appendIndicator();
      extractFromHTML();
      initObserver();
    });
  } else {
    extractFromHTML();
    initObserver();
  }

  deferredRescans.push(setTimeout(scanMutations, 1000));
  deferredRescans.push(setTimeout(scanMutations, 3000));
  deferredRescans.push(setTimeout(scanMutations, 5000));
})();
