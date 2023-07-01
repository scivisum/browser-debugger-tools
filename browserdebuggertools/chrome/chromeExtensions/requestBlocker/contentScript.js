
(async () => {
  const response = await chrome.runtime.sendMessage({method: "getExtensionID"});
  localStorage.setItem("requestBlockerExtensionID", response.result);
})();
