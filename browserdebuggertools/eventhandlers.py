import logging
from abc import ABCMeta, abstractmethod
from typing import Optional

from browserdebuggertools.exceptions import (
    JavascriptDialogNotFoundError
)
from browserdebuggertools.models import JavascriptDialog


logging.basicConfig(format='%(levelname)s:%(message)s')


class EventHandler(object):

    __metaclass__ = ABCMeta
    supported_events = []

    def __init__(self, socket_handler):
        # type: (SocketHandler) -> None
        self._socket_handler = socket_handler

    @abstractmethod
    def handle(self, message):
        """ Implement the method to handle the events relating to the event EventHandler
            If the handle method needs to execute a method via the socket handler then it should
            be done asynchronously since this method blocks the _WSMessagingThread.

            We have no use for executing a devtools command in the handle method
            but when we do the TODO in execute_async needs to be resolved
        """
        pass


class PageLoadEventHandler(EventHandler):

    supported_events = [
        "Page.domContentEventFired",
        "Page.navigatedWithinDocument",
        "Page.frameNavigated",
    ]

    def __init__(self, socket_handler):
        super(PageLoadEventHandler, self).__init__(socket_handler)
        self._url = None
        self._root_node_id = None

    def handle(self, message):
        if message.get("method") == "Page.navigatedWithinDocument":
            logging.info("Detected URL change %s" % message["params"]["url"])
            self._url = message["params"]["url"]
        elif message.get("method") == "Page.domContentEventFired":
            logging.info("Detected Page Load")
            self._reset()
        elif message.get("method") == "Page.frameNavigated":
            logging.info("Detected Frame Navigation")
            self._reset()

    def _reset(self):
        self._url = None
        self._root_node_id = None

    def check_page_load(self):
        if not self._socket_handler.is_domain_enabled("Page"):
            self._reset()

        if self._root_node_id is None:
            logging.info("Retrieving new page data")
            root = self._socket_handler.execute("DOM", "getDocument", {"depth": 0})["root"]
            self._url = root["documentURL"]
            self._root_node_id = root["backendNodeId"]

    def get_current_url(self):
        self.check_page_load()
        return self._url

    def get_root_backend_node_id(self):
        self.check_page_load()
        return self._root_node_id


class JavascriptDialogEventHandler(EventHandler):

    supported_events = [
        "Page.javascriptDialogOpening",
        "Page.javascriptDialogClosed",
    ]

    def __init__(self, socket_handler):
        super(JavascriptDialogEventHandler, self).__init__(socket_handler)
        self._dialog = None  # type: Optional[JavascriptDialog]

    def handle(self, message):
        if message["method"] == "Page.javascriptDialogOpening":
            logging.info("Detected dialog opened")
            self._dialog = JavascriptDialog(self._socket_handler, message["params"])

        elif message["method"] == "Page.javascriptDialogClosed":
            logging.info("Detected javascript dialog closed")
            self._dialog.is_handled = True

    def get_opened_javascript_dialog(self):
        """
        Gets the opened javascript dialog

        :return JavascriptDialog:
        :raises JavascriptDialogNotFoundError:
        """
        # Instead of setting self._dialog to None we switch the handled property so that we
        # change the handled property for all instances of the object,
        # hence why we check both conditions.
        if not self._dialog or self._dialog.is_handled:
            raise JavascriptDialogNotFoundError()
        return self._dialog
