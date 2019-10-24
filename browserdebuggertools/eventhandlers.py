import logging
from abc import ABCMeta, abstractmethod

from browserdebuggertools.exceptions import DomainNotEnabledError

logging.basicConfig(format='%(levelname)s:%(message)s')


class EventHandler(object):

    __metaclass__ = ABCMeta

    @abstractmethod
    def handle(self, message):
        pass


class PageLoadEventHandler(EventHandler):

    def __init__(self, socket_handler):
        super(PageLoadEventHandler, self).__init__()
        self._socket_handler = socket_handler
        self._url = None
        self._root_node_id = None

    def handle(self, message):
        super(PageLoadEventHandler, self).handle(message)
        if message.get("method") == "Page.navigatedWithinDocument":
            logging.info("Detected URL change %s" % message["params"]["url"])
            self._url = message["params"]["url"]
        else:
            logging.info("Detected Page Load")
            self._reset()

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

    def get_root_node_id(self):
        self.check_page_load()
        return self._root_node_id
