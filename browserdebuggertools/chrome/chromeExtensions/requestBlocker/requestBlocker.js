let windowIDs = [];

function recordNewWindowIDs(window) {
    windowIDs.append(window.id);
}

function blockNewWindowMainFrames() {
    windowIDs = [];
    chrome.windows.onCreated.addListener(recordNewWindowIDs);
}

function unblockAllMainFrames() {
    windowIDs = [];
    chrome.windows.onCreated.removeListener(recordNewWindowIDs);
}

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    // Get the window ID for the current request
    chrome.tabs.get(details.tabId, (tab) => {
      if (windowIDs.includes(tab.windowId)) {
        return { cancel: true };
      }
    });
  },
  { urls: ["<all_urls>"], types: ["main_frame"] },
  ["blocking"]
);
