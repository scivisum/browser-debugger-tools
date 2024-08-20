async function blockNewWindowMainFrames() {
    const currentTabs = await chrome.tabs.query({});
    console.log("Got tabs")
    _blockOtherTabs(currentTabs)
}

function unblockAllMainFrames() {
    chrome.declarativeNetRequest.updateSessionRules(
        {
            removeRuleIds: [1],
            addRules: []
        }
    )
}

function _blockOtherTabs(tabs) {
    chrome.declarativeNetRequest.updateSessionRules(
        {
            removeRuleIds: [], // Clear any existing rules to avoid conflicts'
            addRules: [
                {
                    "id": 1,
                    "priority": 1,
                    "action": {"type": "block"},
                    "condition": {
                        "resourceTypes": ["main_frame"],
                        "excludedTabIds": tabs.map(tab => tab.id)
                    }
                },
            ]
        }
    )
}


// Keep the service worker awake
setInterval(chrome.runtime.getPlatformInfo, 20e3);
