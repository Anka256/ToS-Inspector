// background.js — Service Worker for ToS Inspector

// Open the side panel when the action icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  try {
    await chrome.sidePanel.open({ tabId: tab.id });
    // Small delay to ensure the panel is rendered before messaging
    setTimeout(() => {
      chrome.runtime.sendMessage({
        type: "TAB_URL",
        url: tab.url,
        title: tab.title,
        favIconUrl: tab.favIconUrl,
      }).catch(() => {}); // ignore if panel isn't ready yet
    }, 300);
  } catch (err) {
    console.error("Failed to open side panel:", err);
  }
});

// Relay tab URL updates — only for the active tab in the currently focused window.
// tab.active is true for the active tab in ANY window, so we must also check windowId.
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) {
    chrome.windows.getCurrent((focusedWindow) => {
      if (tab.windowId === focusedWindow.id) {
        chrome.runtime.sendMessage({
          type: "TAB_UPDATED",
          url: tab.url,
          title: tab.title,
          favIconUrl: tab.favIconUrl,
        }).catch(() => {});
      }
    });
  }
});

// Also fire when the user switches between tabs (no page load needed)
chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (tab && tab.url) {
      chrome.runtime.sendMessage({
        type: "TAB_UPDATED",
        url: tab.url,
        title: tab.title,
        favIconUrl: tab.favIconUrl,
      }).catch(() => {});
    }
  });
});

// When the side panel opens and requests the current tab info
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "GET_CURRENT_TAB") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        sendResponse({
          url: tabs[0].url,
          title: tabs[0].title,
          favIconUrl: tabs[0].favIconUrl,
        });
      } else {
        sendResponse({ url: null });
      }
    });
    return true; // keep message channel open for async response
  }
});
