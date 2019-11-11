import logging
from typing import Dict

from browserdebuggertools.exceptions import DevToolsException


logging.basicConfig(format='%(levelname)s:%(message)s')


class DevToolsEntity(object):
    pass


class JavascriptDialog(DevToolsEntity):

    ALERT = "alert"
    CONFIRM = "confirm"
    PROMPT = "prompt"
    BEFORE_UNLOAD = "beforeunload"

    def __init__(self, socket_handler, params):
        # type: (SocketHandler, Dict) -> None
        self._socket_handler = socket_handler
        self.message = params["message"]
        self.type = params["type"]
        self.url = params["url"]
        self.has_browser_handler = params["hasBrowserHandler"]
        self.default_prompt = params.get("defaultPrompt", "")
        self.is_handled = False

    def _handle(self, accept=True, prompt_text=None):
        if not self.is_handled:
            params = {"accept": accept}
            if prompt_text is not None:
                params["promptText"] = prompt_text
            self._socket_handler.execute("Page", "handleJavaScriptDialog", params)
            self.is_handled = True
        else:
            raise DevToolsException("This javascript dialog has already been handled")

    def accept(self):
        self._handle()

    def accept_prompt(self, prompt_text):
        # type: (str) -> None
        if self.type != self.PROMPT:
            logging.warning("accept_prompt should only be used on prompts.")

        self._handle(prompt_text=prompt_text)

    def dismiss(self):
        self._handle(False)
