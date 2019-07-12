import json
import logging
import socket

import requests
import websocket

from browserdebuggertools.exceptions import ResultNotFoundError, TabNotFoundError, \
    DomainNotEnabledError

logging.basicConfig(format='%(levelname)s:%(message)s')


class SocketHandler(object):

    CONN_TIMEOUT = 15  # Connection timeout

    def __init__(self, port):
        websocket_url = self._get_websocket_url(port)
        self.websocket = websocket.create_connection(websocket_url, timeout=self.CONN_TIMEOUT)
        self.websocket.settimeout(0)  # Don"t wait for new messages

        self._next_result_id = 0
        self.domains = set()
        self.results = {}
        self.events = {}

    def _get_websocket_url(self, port):
        targets = requests.get(
            "http://localhost:{}/json".format(port), timeout=self.CONN_TIMEOUT
        ).json()
        logging.debug(targets)
        tabs = [target for target in targets if target["type"] == "page"]
        if not tabs:
            raise TabNotFoundError("There is no tab to connect to.")
        return tabs[0]["webSocketDebuggerUrl"]

    def close(self):
        self.websocket.close()

    def _append(self, message):
        if "result" in message:
            self.results[message["id"]] = message.get("result")
        elif "error" in message:
            result_id = message.pop("id")
            self.results[result_id] = message
        elif "method" in message:
            domain, event = message["method"].split(".")
            self.events[domain].append(message)
        else:
            logging.warning("Unrecognised message: {}".format(message))

    def flush_messages(self):
        """ Will only return once all the messages have been retrieved.
            and will hold the thread until so.
        """
        try:
            message = self.websocket.recv()
            while message:
                message = json.loads(message)
                self._append(message)
                message = self.websocket.recv()
        except socket.error:
            return

    def find_result(self, result_id):
        if result_id not in self.results:
            self.flush_messages()

        if result_id not in self.results:
            raise ResultNotFoundError("Result not found for id: {} .".format(result_id))

        return self.results[result_id]

    def execute(self, method, params):
        self._next_result_id += 1
        self.websocket.send(json.dumps({
            "id": self._next_result_id, "method": method, "params": params if params else {}
        }, sort_keys=True))
        return self._next_result_id

    def add_domain(self, domain):
        if domain not in self.domains:
            self.domains.add(domain)
            self.events[domain] = []

    def remove_domain(self, domain):
        if domain in self.domains:
            self.domains.remove(domain)

    def get_events(self, domain, clear=False):
        if domain not in self.domains:
            raise DomainNotEnabledError(
                'The domain "%s" is not enabled, try enabling it via the interface.' % domain
            )

        self.flush_messages()
        events = self.events[domain][:]
        if clear:
            self.events[domain] = []

        return events
