function blockMainFrames() {
    chrome.declarativeNetRequest.updateEnabledRulesets(
        {
      disableRulesetIds: [],
      enableRulesetIds:["blockMainFrames"]
        },
        () => {console.log("Blocked main frames")}
    );
}


function unblockMainFrames() {
    chrome.declarativeNetRequest.updateEnabledRulesets(
        {
      disableRulesetIds: ["blockMainFrames"],
      enableRulesetIds:[]
        },
        () => {console.log("unblocked main frames")}
    );
}


chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.method === "getExtensionID") {
        sendResponse({result: chrome.runtime.id});
    }
    else {
        sendResponse({result: "error", message: "Unexpected method: " + request.method});
    }
});


chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
   if (request.method === "blockMainFrames") {
        blockMainFrames();
        sendResponse({result: "success"});
    }
    else if (request.method === "unblockMainFrames") {
        unblockMainFrames();
        sendResponse({result: "success"});
    } else {
        sendResponse({result: "error", message: "Unexpected method: " + request.method});
   }
});
