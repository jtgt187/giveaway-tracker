let fileHandle = null;
let fileWriter = null;
let writeQueue = [];
let isWriting = false;

function updateCount() {
  chrome.runtime.sendMessage({ type: 'get-count' }, function(response) {
    if (response) {
      const count = response.count;
      document.getElementById('count').textContent = count;
      document.getElementById('downloadBtn').disabled = count === 0;
      document.getElementById('clearBtn').disabled = count === 0;
      
      if (count === 0) {
        document.getElementById('status').textContent = 'Browse pages with Gleam links';
        document.getElementById('status').className = 'zero';
      } else {
        document.getElementById('status').textContent = count + ' link' + (count !== 1 ? 's' : '') + ' ready';
        document.getElementById('status').className = '';
      }
    }
  });
}

function updateFileStatus() {
  if (fileHandle) {
    document.getElementById('fileStatus').textContent = 'Auto-saving to: ' + fileHandle.name;
  } else {
    document.getElementById('fileStatus').textContent = '';
  }
}

async function selectFile() {
  if (!window.showOpenFilePicker) {
    alert('Your Edge version does not support File System Access API.');
    return;
  }
  
  try {
    const [handle] = await window.showOpenFilePicker({
      types: [{ description: 'NDJSON Files', accept: { 'application/json': ['.ndjson', '.json', '.txt'] } }],
      multiple: false
    });
    
    fileHandle = handle;
    writeQueue = [];
    isWriting = false;
    
    document.getElementById('fileStatus').textContent = 'Auto-saving to: ' + handle.name;
    document.getElementById('status').textContent = 'File selected! Links will be auto-saved.';
    
    // Write any existing links
    chrome.runtime.sendMessage({ type: 'get-links' }, function(response) {
      if (response && response.links && response.links.length > 0) {
        writeQueue = [...response.links];
        processWriteQueue();
      }
    });
  } catch (err) {
    if (err.name !== 'AbortError') {
      document.getElementById('status').textContent = 'Error: ' + err;
    }
  }
}

async function processWriteQueue() {
  if (isWriting || writeQueue.length === 0 || !fileHandle) return;
  
  isWriting = true;
  
  while (writeQueue.length > 0) {
    const entry = writeQueue.shift();
    try {
      const line = JSON.stringify(entry) + '\n';
      const writable = await fileHandle.createWritable({ keepExistingData: true });
      const file = await fileHandle.getFile();
      await writable.seek(file.size);
      await writable.write(line);
      await writable.close();
    } catch (e) {
      console.error('Write error:', e);
      writeQueue.unshift(entry);
      fileHandle = null;
      document.getElementById('fileStatus').textContent = 'File write failed! Re-select file.';
      break;
    }
  }
  
  isWriting = false;
  
  if (writeQueue.length > 0 && fileHandle) {
    processWriteQueue();
  }
}

function downloadLinks() {
  chrome.runtime.sendMessage({ type: 'download' }, function(response) {
    if (response && response.ok) {
      document.getElementById('status').textContent = 'Downloaded!';
      updateCount();
    } else if (response && response.error) {
      document.getElementById('status').textContent = 'Error: ' + response.error;
    } else {
      document.getElementById('status').textContent = 'Download failed';
    }
  });
}

function clearLinks() {
  chrome.runtime.sendMessage({ type: 'clear' }, function(response) {
    if (response && response.ok) {
      document.getElementById('status').textContent = 'Cleared!';
      updateCount();
    }
  });
}

document.addEventListener('DOMContentLoaded', function() {
  updateCount();
  updateFileStatus();
  
  setInterval(function() {
    updateCount();
    
    if (fileHandle) {
      chrome.runtime.sendMessage({ type: 'get-links' }, function(response) {
        if (response && response.links) {
          const newLinks = response.links.filter(l => {
            return !writeQueue.some(w => w.href === l.href);
          });
          if (newLinks.length > 0) {
            writeQueue.push(...newLinks);
            processWriteQueue();
          }
        }
      });
    }
  }, 3000);
  
  document.getElementById('downloadBtn').addEventListener('click', downloadLinks);
  document.getElementById('clearBtn').addEventListener('click', clearLinks);
  document.getElementById('fileBtn').addEventListener('click', selectFile);
});
