import logging
from abc import ABCMeta, abstractmethod
from typing import Optional

from browserdebuggertools.exceptions import (
    DomainNotEnabledError, JavascriptDialogNotFoundError, DevToolsException
)
from browserdebuggertools.models import JavascriptDialog


logging.basicConfig(format='%(levelname)s:%(message)s')


class EventHandler(object):

    __metaclass__ = ABCMeta

    def __init__(self, socket_handler):
        # type: (SocketHandler) -> None
        self._socket_handler = socket_handler

    def raise_unexpected_event_error(self, method):
        raise DevToolsException("{} doesn't accept this event '{}'".format(self.__class__, method))

    @abstractmethod
    def handle(self, message):
        pass


class PageLoadEventHandler(EventHandler):

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
        else:
            self.raise_unexpected_event_error(message["method"])

    def _reset(self):
        self._url = None
        self._root_node_id = None

    def check_page_load(self):
        try:
            self._socket_handler.get_events("Page")
        except DomainNotEnabledError:
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

        else:
            self.raise_unexpected_event_error(message["method"])

    def get_opened_javascript_dialog(self):
        """
        Gets the opened javascript dialog

        :return JavascriptDialog:
        :raises JavascriptDialogNotFoundError:
        """
        self._socket_handler.get_events("Page")
        # Instead of setting self._dialog to None we switch the handled property so that we
        # change the handled property for all instances of the object,
        # hence why we check both conditions.
        if not self._dialog or self._dialog.is_handled:
            raise JavascriptDialogNotFoundError()
        return self._dialog
