import contextlib
import json
import logging
import socket
import time
from datetime import datetime
from typing import Dict

import requests
import websocket

from browserdebuggertools.eventhandlers import (
    EventHandler, PageLoadEventHandler, JavascriptDialogEventHandler
)
from browserdebuggertools.exceptions import (
    DevToolsException, ResultNotFoundError, TabNotFoundError, MaxRetriesException,
    DevToolsTimeoutException, DomainNotEnabledError,
    MethodNotFoundError, UnknownError, ResourceNotFoundError, TimerException
)


def open_connection_if_closed(socket_handler_method):

    def retry_if_exception(socket_handler_instance, *args, **kwargs):

        try:
            return socket_handler_method(socket_handler_instance, *args, **kwargs)

        except websocket.WebSocketConnectionClosedException:

            socket_handler_instance.increment_connection_closed_count()
            retry_if_exception(socket_handler_instance, *args, **kwargs)

    return retry_if_exception


class _Timer(object):

    def __init__(self, timeout):
        """
        :param timeout: <int> seconds elapsed until considered timed out.
        """
        self.timeout = timeout
        self._start = None

    def start(self):
        """
        Capture the start time, cannot be called again without first calling clear().
        """
        if self._start:
            raise TimerException("You cannot start a timer that's already started")
        self._start = time.time()

    def clear(self):
        """
        Make the timer object ready to be used again.
        """
        self._start = None

    @property
    def timed_out(self):
        """
        :return: <bool> True if the time from start to now is greater than the timeout threshold
        """
        if not self._start:
            raise TimerException("Timer must have started for there to have been a timeout")

        if (time.time() - self._start) > self.timeout:
            return True
        return False


class SocketHandler(object):

    MAX_CONNECTION_RETRIES = 3
    RETRY_COUNT_TIMEOUT = 300  # Seconds
    CONN_TIMEOUT = 15  # Connection timeout seconds

    def __init__(self, port, timeout, domains=None):

        self.timeout = timeout
        self.timer = _Timer(self.timeout)

        if not domains:
            domains = {}

        self._domains = domains
        self._events = dict([(k, []) for k in self._domains])
        self._results = {}

        self.event_handlers = {
            "PageLoad": PageLoadEventHandler(self),
            "JavascriptDialog": JavascriptDialogEventHandler(self),
        }  # type: Dict[str, EventHandler]

        self._internal_events = {
            "Page": {
                "domContentEventFired": self.event_handlers["PageLoad"],
                "navigatedWithinDocument": self.event_handlers["PageLoad"],
                "javascriptDialogOpening": self.event_handlers["JavascriptDialog"],
                "javascriptDialogClosed": self.event_handlers["JavascriptDialog"],
            }
        }  # type: Dict[str, Dict[str, EventHandler]]
        self._next_result_id = 0
        self._connection_last_closed = None
        self._connection_closed_count = 0

        self._websocket_url = self._get_websocket_url(port)
        self._websocket = self._setup_websocket()

    def __del__(self):
        try:
            self.close()
        except:
            pass

    def _setup_websocket(self):
        logging.info("Connecting to websocket %s" % self._websocket_url)
        self._websocket = websocket.create_connection(
            self._websocket_url, timeout=self.CONN_TIMEOUT
        )
        self._websocket.settimeout(0)  # Don"t wait for new messages

        for domain, params in self._domains.items():
            self.enable_domain(domain, params)

        return self._websocket

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
            raise MaxRetriesException(
                "Websocket connection found closed %s times within %s seconds" % (
                    self.MAX_CONNECTION_RETRIES, self.RETRY_COUNT_TIMEOUT
                )
            )

        self._setup_websocket()

    @open_connection_if_closed
    def _send(self, data):
        data['id'] = self._next_result_id
        self._websocket.send(json.dumps(data, sort_keys=True))

    @open_connection_if_closed
    def _recv(self):
        message = self._websocket.recv()
        if message:
            message = json.loads(message)
        return message

    def _get_websocket_url(self, port):
        response = requests.get(
            "http://localhost:{}/json".format(port), timeout=self.CONN_TIMEOUT
        )
        if not response.ok:
            raise DevToolsException("{} {} for url: {}".format(
                response.status_code, response.reason, response.url)
            )

        tabs = [target for target in response.json() if target["type"] == "page"]
        if not tabs:
            raise TabNotFoundError("There is no tab to connect to.")
        return tabs[0]["webSocketDebuggerUrl"]

    def close(self):
        if hasattr(self, "_websocket"):
            self._websocket.close()

    def _append(self, message):

        if "result" in message:
            self._results[message["id"]] = message.get("result")
        elif "error" in message:
            result_id = message.pop("id")
            self._results[result_id] = message
        elif "method" in message:
            domain, event = message["method"].split(".")
            if domain in self._internal_events:
                if event in self._internal_events[domain]:
                    self._internal_events[domain][event].handle(message)
            if domain in self._events:
                self._events[domain].append(message)
        else:
            logging.warning("Unrecognised message: {}".format(message))

    def _flush_messages(self):
        """ Will only return once all the messages have been retrieved.
            and will hold the thread until so.
        """
        try:
            message = self._recv()
            while not self.timer.timed_out and message:
                self._append(message)
                message = self._recv()
            if self.timer.timed_out:
                raise DevToolsTimeoutException("Timed out flushing messages")
        except socket.error:
            return

    def _find_next_result(self):
        if self._next_result_id not in self._results:
            self._flush_messages()

        if self._next_result_id not in self._results:
            raise ResultNotFoundError("Result not found for id: {} .".format(self._next_result_id))

        return self._results.pop(self._next_result_id)

    def _execute(self, domain_name, method_name, params=None):

        if params is None:
            params = {}

        self._next_result_id += 1
        method = "{}.{}".format(domain_name, method_name)
        self._send({
            "method": method, "params": params
        })

    def execute(self, domain_name, method_name, params=None):
        self._execute(domain_name, method_name, params)
        result = self._wait_for_result()
        if "error" in result:
            code = result["error"]["code"]
            message = result["error"]["message"]
            if code == -32000:
                raise ResourceNotFoundError(message)
            if code == -32601:
                raise MethodNotFoundError(message)
            raise UnknownError("DevTools Protocol error code %s: %s" % (code, message))
        return result

    def execute_async(self, domain_name, method_name, params=None):
        self._execute(domain_name, method_name, params)
        # TODO: complete this method
        # This isn't fully implemented as we don't have a method to retrieve results
        # Also we'll need a smarter way to manage memory as there is the danger of regressing to
        # this: https://github.com/scivisum/browser-debugger-tools/pull/20/
        return self._next_result_id

    def _add_domain(self, domain, params):
        if domain not in self._domains:
            self._domains[domain] = params
            self._events[domain] = []

    def _remove_domain(self, domain):
        if domain in self._domains:
            del self._domains[domain]
            del self._events[domain]

    def get_events(self, domain, clear=False):
        if domain not in self._domains:
            raise DomainNotEnabledError(
                'The domain "%s" is not enabled, try enabling it via the interface.' % domain
            )

        with self.timed_method():
            self._flush_messages()

        events = self._events[domain]
        if clear:
            self._events[domain] = []
        else:
            # This is to make the events immutable unless using clear
            events = events[:]

        return events

    def reset(self):
        for domain in self._events:
            self._events[domain] = []

        self._results = {}
        self._next_result_id = 0

    @contextlib.contextmanager
    def timed_method(self):

        self.timer.start()
        try:
            yield

        finally:
            self.timer.clear()

    def _wait_for_result(self):
        """ Waits for a result to complete within the timeout duration then returns it.
            Raises a DevToolsTimeoutException if it cannot find the result.

        :return: The result.
          """
        with self.timed_method():
            while not self.timer.timed_out:
                try:
                    return self._find_next_result()
                except ResultNotFoundError:
                    time.sleep(0.01)
        raise DevToolsTimeoutException(
            "Reached timeout limit of {}, waiting for a response message".format(self.timeout)
        )

    def enable_domain(self, domain_name, parameters=None):

        if not parameters:
            parameters = {}

        self.execute(domain_name, "enable", parameters)
        self._add_domain(domain_name, parameters)

        logging.info("\"{}\" domain has been enabled".format(domain_name))

    def disable_domain(self, domain_name):
        """ Disables further notifications from the given domain.
        """
        self._remove_domain(domain_name)
        result = self.execute(domain_name, "disable", {})
        if "error" in result:
            logging.warn("Domain \"{}\" doesn't exist".format(domain_name))
        else:
            logging.info("Domain {} has been disabled".format(domain_name))
