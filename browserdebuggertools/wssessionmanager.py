import contextlib
import json
import logging
import socket
import time
import collections
from datetime import datetime
from threading import Thread, Event, Lock

from typing import Dict

import requests
import websocket

from browserdebuggertools.eventhandlers import (
    EventHandler, PageLoadEventHandler, JavascriptDialogEventHandler
)
from browserdebuggertools.exceptions import (
    DevToolsException, MessageNotFoundError, TabNotFoundError, MaxRetriesException,
    DevToolsTimeoutException, DomainNotEnabledError,
    MethodNotFoundError, UnknownError, ResourceNotFoundError, MessagingThreadIsDeadError,
    InvalidParametersError
)


class _WSMessagingThread(Thread):

    _CONN_TIMEOUT = 15
    _BLOCKED_TIMEOUT = 5
    _MAX_QUEUE_BUFFER = 1000
    _POLL_INTERVAL = 1

    def __init__(self, port, send_queue, recv_queue, poll_signal):
        super(_WSMessagingThread, self).__init__()
        self._port = port
        self._send_queue = send_queue
        self._recv_queue = recv_queue
        self._last_poll = None
        self._continue = True
        self._poll_signal = poll_signal

        self.exception = None
        self.ws = self._get_websocket()
        self.daemon = True

    def __del__(self):
        self.close()

    def _get_websocket_url(self, port):
        response = requests.get(
            "http://localhost:{}/json".format(port), timeout=self._CONN_TIMEOUT
        )
        if not response.ok:
            raise DevToolsException("{} {} for url: {}".format(
                response.status_code, response.reason, response.url)
            )

        tabs = [target for target in response.json() if target["type"] == "page"]
        if not tabs:
            raise TabNotFoundError("There is no tab to connect to.")
        return tabs[0]["webSocketDebuggerUrl"]

    def _get_websocket(self):
        websocket_url = self._get_websocket_url(self._port)
        logging.info("Connecting to websocket %s" % websocket_url)
        ws = websocket.create_connection(
            websocket_url, timeout=self._CONN_TIMEOUT
        )
        ws.settimeout(0)  # Don"t wait for new messages
        return ws

    @contextlib.contextmanager
    def _ws_io(self):

        # noinspection PyBroadException
        try:
            yield
        except Exception as e:
            self.exception = e
            logging.warning("WS messaging thread terminated with exception", exc_info=True)
        finally:
            self.close()

    def close(self):
        if hasattr(self, "ws") and self.ws:
            try:
                self.ws.close()
            except websocket.WebSocketConnectionClosedException:
                pass

    def add_to_send_queue(self, payload):
        self._send_queue.append(payload)

    def get_from_recv_queue(self):
        if self._recv_queue:
            return self._recv_queue.popleft()
        else:
            raise MessageNotFoundError()

    def stop(self):
        self._continue = False

    def run(self):

        with self._ws_io():

            self._last_poll = time.time()
            while self._continue:

                while self._send_queue:
                    message = self._send_queue[0]
                    self.ws.send(message)
                    self._send_queue.popleft()  # Don't pop first, in-case send excepts

                while len(self._recv_queue) < self._MAX_QUEUE_BUFFER:
                    try:
                        message = self.ws.recv()
                        self._recv_queue.append(message)
                    except socket.error as e:
                        # We expect [Errno 11] when there are no more messages to read
                        if "[Errno 11] Resource temporarily unavailable" not in str(e):
                            raise
                        break

                self._poll_signal.wait(self._POLL_INTERVAL)
                if self._poll_signal.isSet():
                    self._poll_signal.clear()

                self._last_poll = time.time()

    @property
    def blocked(self):
        return (
            self._last_poll and ((time.time() - self._last_poll) > self._BLOCKED_TIMEOUT)
        )


class _Timer(object):

    def __init__(self, timeout):
        """
        :param timeout: <int> seconds elapsed until considered timed out.
        """
        self.timeout = timeout
        self.start = time.time()

    @property
    def timed_out(self):
        """
        :return: <bool> True if the time from start to now is greater than the timeout threshold
        """
        return (time.time() - self.start) > self.timeout


class WSSessionManager(object):

    MAX_RETRY_THREADS = 3
    RETRY_COUNT_TIMEOUT = 300  # Seconds

    def __init__(self, port, timeout, domains=None):

        self.timeout = timeout

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
                "frameNavigated": self.event_handlers["PageLoad"],
                "javascriptDialogOpening": self.event_handlers["JavascriptDialog"],
                "javascriptDialogClosed": self.event_handlers["JavascriptDialog"],
            }
        }  # type: Dict[str, Dict[str, EventHandler]]
        self._next_result_id = 0
        self._result_id_lock = Lock()

        self._last_not_ok = None
        self._messaging_thread_not_ok_count = 0

        self.port = port
        self._send_queue = collections.deque()
        self._recv_queue = collections.deque()

        self._poll_signal = Event()
        self.messaging_thread = None
        self._message_access_lock = Lock()

        self.setup_ws_session()

    def __del__(self):
        self.close()

    def _check_messaging_thread(self):

        if self.messaging_thread.is_alive():
            if self.messaging_thread.blocked:
                logging.warning("WS messaging thread appears to be blocked")
                self.close()
                restart = True
            else:
                restart = False
        else:
            if isinstance(self.messaging_thread.exception,
                          websocket.WebSocketConnectionClosedException):
                restart = True
            elif self.messaging_thread.exception:
                raise self.messaging_thread.exception
            else:
                raise MessagingThreadIsDeadError("WS messaging thread died for an unknown reason")

        if restart:
            self.increment_messaging_thread_not_ok()
            self.setup_ws_session()

    def increment_messaging_thread_not_ok(self):

        now = datetime.now()

        if (
            self._last_not_ok and
            (now - self._last_not_ok).seconds > self.RETRY_COUNT_TIMEOUT
        ):
            self._messaging_thread_not_ok_count = 0

        self._last_not_ok = now
        self._messaging_thread_not_ok_count += 1

        if self._messaging_thread_not_ok_count > self.MAX_RETRY_THREADS:
            raise MaxRetriesException(
                "WS messaging thread not ok %s times within %s seconds" % (
                    self.MAX_RETRY_THREADS, self.RETRY_COUNT_TIMEOUT
                )
            )

    def setup_ws_session(self):

        self.messaging_thread = _WSMessagingThread(
            self.port, self._send_queue, self._recv_queue, self._poll_signal
        )
        self.messaging_thread.start()
        message_consumer = Thread(target=self._flush_messages)
        message_consumer.start()

        for domain, params in self._domains.items():
            self.enable_domain(domain, params)

    def _send(self, data):
        self._check_messaging_thread()
        self.messaging_thread.add_to_send_queue(json.dumps(data, sort_keys=True))
        self._poll_signal.set()

    def close(self):
        if hasattr(self, "messaging_thread") and self.messaging_thread:
            self.messaging_thread.stop()
            timer = _Timer(5)
            while not timer.timed_out:
                if not self.messaging_thread.is_alive():
                    return
                time.sleep(0.1)

            self.messaging_thread.close()

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
        """ Processes messages forever only stopping to allow the events to be collected
        """
        while True:
            self._check_messaging_thread()
            self._poll_signal.set()
            try:
                with self._message_access_lock:
                    message = self.messaging_thread.get_from_recv_queue()
                    message = json.loads(message)
                    self._append(message)
            except MessageNotFoundError:
                time.sleep(0.1)

    def _execute(self, domain_name, method_name, params=None):

        if params is None:
            params = {}

        with self._result_id_lock:
            self._next_result_id += 1
            result_id = self._next_result_id

        method = "{}.{}".format(domain_name, method_name)
        self._send({
            "id": result_id, "method": method, "params": params
        })
        return result_id

    def execute(self, domain_name, method_name, params=None):
        result_id = self._execute(domain_name, method_name, params)
        result = self._wait_for_result(result_id)
        if "error" in result:
            code = result["error"]["code"]
            message = result["error"]["message"]
            if code == -32000:
                raise ResourceNotFoundError(message)
            if code == -32601:
                raise MethodNotFoundError(message)
            if code == -32602:
                raise InvalidParametersError(message)
            raise UnknownError("DevTools Protocol error code %s: %s" % (code, message))
        return result

    def execute_async(self, domain_name, method_name, params=None):
        result_id = self._execute(domain_name, method_name, params)
        # TODO: complete this method
        # This isn't fully implemented as we don't have a method to retrieve results
        # Also we'll need a smarter way to manage memory as there is the danger of regressing to
        # this: https://github.com/scivisum/browser-debugger-tools/pull/20/
        return result_id

    def is_domain_enabled(self, domain):
        return domain in self._domains

    def _add_domain(self, domain, params):
        if not self.is_domain_enabled(domain):
            self._domains[domain] = params
            self._events[domain] = []

    def _remove_domain(self, domain):
        if self.is_domain_enabled(domain):
            del self._domains[domain]
            del self._events[domain]

    def get_events(self, domain, clear=False):
        if not self.is_domain_enabled(domain):
            raise DomainNotEnabledError(
                'The domain "%s" is not enabled, try enabling it via the interface.' % domain
            )

        with self._message_access_lock:
            events = self._events[domain]
            if clear:
                self._events[domain] = []
            else:
                # This is to make the events immutable unless using clear
                events = events[:]

        return events

    def reset(self):
        with self._message_access_lock:
            for domain in self._events:
                self._events[domain] = []

            self._results = {}
            self._next_result_id = 0

            self._send_queue.clear()
            self._recv_queue.clear()

    def _wait_for_result(self, result_id):
        """ Waits for a result to complete within the timeout duration then returns it.
            Raises a DevToolsTimeoutException if it cannot find the result.

        :return: The result.
        """
        timer = _Timer(self.timeout)
        while not timer.timed_out:
            if result_id in self._results:
                return self._results.pop(result_id)

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
