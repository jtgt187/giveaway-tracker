let links = [];

// Restore links on startup
chrome.storage.local.get(['gleam_links'], (result) => {
  if (result.gleam_links) {
    links = result.gleam_links;
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'append') {
    const exists = links.some(l => l.href === msg.href);
    if (!exists) {
      const entry = {
        href: msg.href,
        text: msg.text || '',
        pageUrl: msg.pageUrl || '',
        t: new Date().toISOString()
      };
      links.push(entry);
      chrome.storage.local.set({ gleam_links: links });
      sendResponse({ count: links.length });
    } else {
      sendResponse({ count: links.length });
    }
    return true;
  }
  
  if (msg.type === 'get-count') {
    sendResponse({ count: links.length });
    return true;
  }
  
  if (msg.type === 'get-links') {
    sendResponse({ links: links });
    return true;
  }
  
  if (msg.type === 'download') {
    if (links.length === 0) {
      sendResponse({ ok: false, error: 'No links' });
      return true;
    }
    
    downloadAll().then(() => {
      sendResponse({ ok: true });
    }).catch(e => {
      sendResponse({ ok: false, error: String(e) });
    });
    return true;
  }
  
  if (msg.type === 'clear') {
    links = [];
    chrome.storage.local.set({ gleam_links: [] });
    sendResponse({ ok: true });
    return true;
  }
  
  return false;
});

async function downloadAll() {
  if (links.length === 0) throw new Error('No links');
  
  const content = links.map(l => JSON.stringify(l)).join('\n') + '\n';
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const filename = 'gleam-links-' + timestamp + '.ndjson';
  
  await new Promise((resolve, reject) => {
    chrome.downloads.download({
      url: url,
      filename: filename,
      saveAs: true
    }, (downloadId) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(downloadId);
      }
    });
  });
  
  links = [];
  chrome.storage.local.set({ gleam_links: [] });
}
