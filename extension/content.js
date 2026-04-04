(function(){
  let seenHref = new Set();
  
  // Visual indicator
  const indicator = document.createElement('div');
  indicator.id = 'gleam-monitor-indicator';
  indicator.style.cssText = 'position:fixed;bottom:10px;right:10px;background:#7c3aed;color:white;padding:8px 12px;border-radius:6px;font-size:12px;z-index:999999;opacity:0.9;';
  document.body.appendChild(indicator);
  
  function updateIndicator(msg, count) {
    indicator.textContent = msg + (count !== undefined ? ' (' + count + ')' : '');
    indicator.style.background = count > 0 ? '#10b981' : '#7c3aed';
  }
  
  updateIndicator('Gleam: Scanning...');
  
  function sendLink(href, text) {
    if (seenHref.has(href)) return;
    seenHref.add(href);
    
    chrome.runtime.sendMessage({
      type: 'append',
      href: href,
      text: text || '',
      pageUrl: location.href
    }, function(response) {
      if (response) {
        updateIndicator('Gleam: Collected!', response.count);
      }
    });
  }
  
  function extractFromHTML() {
    const anchors = document.querySelectorAll('a[href*="gleam.io"]');
    updateIndicator('Gleam: Found ' + anchors.length + ' links');
    
    if (anchors.length === 0) {
      updateIndicator('Gleam: No Gleam links');
      return;
    }
    
    anchors.forEach(a => {
      try {
        const url = new URL(a.href, location.href).toString();
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
        if (!seenHref.has(url)) {
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
