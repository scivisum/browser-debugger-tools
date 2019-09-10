import json
import logging
import socket
from datetime import datetime

import requests
import websocket

from browserdebuggertools.exceptions import ResultNotFoundError, TabNotFoundError, \
    DomainNotEnabledError

logging.basicConfig(format='%(levelname)s:%(message)s')


def open_connection_if_closed(socket_handler_method):

    def retry_if_exception(socket_handler_instance, *args, **kwargs):

        try:
            return socket_handler_method(socket_handler_instance, *args, **kwargs)

        except websocket.WebSocketConnectionClosedException:

            socket_handler_instance.increment_connection_closed_count()
            retry_if_exception(socket_handler_instance, *args, **kwargs)

    return retry_if_exception


class SocketHandler(object):

    MAX_CONNECTION_RETRIES = 3
    RETRY_COUNT_TIMEOUT = 300
    CONN_TIMEOUT = 15  # Connection timeout

    def __init__(self, port):

        self.domains = set()
        self.results = {}
        self.events = {}

        self._websocket_url = self._get_websocket_url(port)
        self.websocket = self._setup_websocket()

        self._next_result_id = 0
        self._connection_last_closed = None
        self._connection_closed_count = 0

    def _setup_websocket(self):

        self.websocket = websocket.create_connection(self._websocket_url, timeout=self.CONN_TIMEOUT)
        self.websocket.settimeout(0)  # Don"t wait for new messages

        for domain in self.domains:
            self.execute("%s.enable" % domain, {})

        return self.websocket

    def increment_connection_closed_count(self):

        now = datetime.now()

        if (
                self._connection_last_closed and
                (now - self._connection_last_closed).seconds > self.RETRY_COUNT_TIMEOUT
        ):
            self._connection_closed_count = 0

        self._connection_last_closed = now
        self._connection_closed_count += 1

        if self._connection_closed_count > self.MAX_CONNECTION_RETRIES:
            raise Exception("Websocket connection found closed too many times")

        self._setup_websocket()

    @open_connection_if_closed
    def _send(self, data):
        self.websocket.send(json.dumps(data, sort_keys=True))

    @open_connection_if_closed
    def _recv(self):
        message = self.websocket.recv()
        if message:
            message = json.loads(message)
        return message

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
            message = self._recv()
            while message:
                self._append(message)
                message = self._recv()
        except socket.error:
            return

    def find_result(self, result_id):
        if result_id not in self.results:
            self.flush_messages()

        if result_id not in self.results:
            raise ResultNotFoundError("Result not found for id: {} .".format(result_id))

        return self.results.pop(result_id)

    def execute(self, method, params):
        self._next_result_id += 1
        self._send({
            "id": self._next_result_id, "method": method, "params": params if params else {}
        })
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
