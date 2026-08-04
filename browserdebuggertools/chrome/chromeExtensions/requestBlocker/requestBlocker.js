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

// RD-55085 Keep the service worker awake.
//
// setInterval() alone is not enough: it only keeps the worker alive while the worker is
// already running. On a loaded machine (e.g. Jenkins CI) Chrome can evict the MV3 service
// worker under memory/CPU pressure, and once it is gone the setInterval() is gone with it,
// so nothing ever brings the worker back. Talking to the dead worker over DevTools then
// fails with "Error: No SW", and retrying the same call never recovers because DevTools
// evaluate does not re-spawn an evicted worker.
//
// chrome.alarms is persisted by Chrome and re-spawns (wakes) the service worker when it
// fires, so the worker self-heals after an eviction. We re-arm the alarm every time the
// worker starts so a freshly re-spawned worker keeps itself alive again.
const KEEP_ALIVE_ALARM = "keepAlive";

function ensureKeepAliveAlarm() {
    // 0.5 minutes is the smallest period Chrome reliably honours for periodic alarms.
    chrome.alarms.create(KEEP_ALIVE_ALARM, {periodInMinutes: 0.5});
}

chrome.runtime.onStartup.addListener(ensureKeepAliveAlarm);
chrome.runtime.onInstalled.addListener(ensureKeepAliveAlarm);

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === KEEP_ALIVE_ALARM) {
        // Touching an async extension API keeps the worker warm while it is running.
        chrome.runtime.getPlatformInfo(() => {});
    }
});

// Arm the alarm immediately for the current worker lifetime, and keep the short interval
// as a best-effort warm-up for the window before the first alarm fires.
ensureKeepAliveAlarm();