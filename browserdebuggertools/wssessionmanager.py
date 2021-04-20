import contextlib
import json
import logging
import socket
import time
import collections
from threading import Thread, Event, Lock

from typing import Dict

import requests
import websocket

from browserdebuggertools.eventhandlers import (
    EventHandler, PageLoadEventHandler, JavascriptDialogEventHandler
)
from browserdebuggertools.exceptions import (
    DevToolsException, TabNotFoundError, MaxRetriesException,
    DevToolsTimeoutException, DomainNotEnabledError,
    MethodNotFoundError, UnknownError, ResourceNotFoundError, MessagingThreadIsDeadError,
    InvalidParametersError, WebSocketBlockedException
)


class NotifiableDeque(collections.deque):
    """ A Queue with the benefits of deque speed
        It also allows us to have a max size.
        It can wait until there are new messages or the timeout is met
    """
    _POLL_INTERVAL = 1
    _MAX_QUEUE_BUFFER = 1000

    def __init__(self, event=Event()):
        super(NotifiableDeque, self).__init__()
        self._poll_signal = event

    def append(self, message):
        """ Appends to the queue and allows any waiting threads to start popping from it
        """
        super(NotifiableDeque, self).append(message)
        self._poll_signal.set()

    def wait_for_messages(self):
        """ Waits until there are messages or the poll interval time
        """
        self._poll_signal.wait(self._POLL_INTERVAL)
        if self._poll_signal.is_set():
            self._poll_signal.clear()

    def is_full(self):
        return len(self) >= self._MAX_QUEUE_BUFFER


class _WSMessageProducer(Thread):
    """ Interfaces with the websocket to send messages from the send queue
        or put messages from the websocket into recv queue
    """
    _CONN_TIMEOUT = 15
    _BLOCKED_TIMEOUT = 5

    def __init__(self, port, send_queue, recv_queue):
        super(_WSMessageProducer, self).__init__()
        self._port = port
        self._send_queue = send_queue
        self._recv_queue = recv_queue
        self._last_poll = None
        self._continue = True

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

    def _empty_send_queue(self):
        while self._send_queue:
            message = self._send_queue.popleft()
            try:
                self.ws.send(message)
            except Exception:
                # Add the message to the beginning of the queue again
                self._send_queue.appendleft(message)
                raise

    def _empty_websocket(self):
        while not self._recv_queue.is_full():
            try:
                message = self.ws.recv()
                self._recv_queue.append(message)
            except socket.error as e:
                # We expect [Errno 11] when there are no more messages to read
                if "[Errno 11] Resource temporarily unavailable" not in str(e):
                    raise
                break

    def stop(self):
        self._continue = False

    def run(self):

        with self._ws_io():

            self._last_poll = time.time()
            while self._continue:

                self._empty_send_queue()
                self._empty_websocket()

                self._send_queue.wait_for_messages()
                self._last_poll = time.time()

    @property
    def blocked(self):
        """ Returns True if:
                the websocket hangs https://github.com/websocket-client/websocket-client/issues/437
                or we've been consuming messages from the websocket for too long **

            Although taking too long to receive messages from the websocket doesn't technically mean
            we're blocked it means we can't send any messages to that websocket either,
            some messages could allow us to reduce the load on the websocket
            so raising an exception in this case allows us to empty the send queue and try again.

            **  This could be solved by having a separate thread to handle sending messages,
                assuming ws.send() doesn't hang and is also thread safe.
                Then we could update self._last_poll after every successful ws.send()/ws.recv()
        """
        return (
            self._last_poll and ((time.time() - self._last_poll) > self._BLOCKED_TIMEOUT)
        )

    def health_check(self):
        """ Checks if the message_producer hasn't crashed
            and that we still have a connection to the websocket.
        """
        if self.is_alive():
            if self.blocked:
                logging.warning("WS messaging thread appears to be blocked")
                self.close()
                raise WebSocketBlockedException()
        else:
            if self.exception:
                raise self.exception
            else:
                raise MessagingThreadIsDeadError("WS messaging thread died for an unknown reason")


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

        self._internal_events = {}  # type: Dict[str, EventHandler]
        for handler in self.event_handlers.values():
            for event in handler.supported_events:
                self._internal_events[event] = handler

        self._next_result_id = 0
        self._result_id_lock = Lock()

        self._last_not_ok = None
        self._message_producer_not_ok_count = 0

        self.port = port
        # Use the same event since the _WSMessageProducer thread accesses both queues
        # Normally you'd have a thread processing each queue but the benefits of that aren't high
        # since the send queue is not likely to block the recv queue (but the opposite is possible)
        poll_signal = Event()
        self._send_queue = NotifiableDeque(poll_signal)
        self._recv_queue = NotifiableDeque(poll_signal)

        self._message_producer = None

        self._message_consumer = Thread(target=self._flush_messages, daemon=True)
        self._events_access_lock = Lock()
        self._should_flush_messages = True
        self._exception = None

        self._setup_ws_session()

    def __del__(self):
        self.close()

    def _check_message_producer(self):
        """ Checks if the websocket is healthy and recreates the connection if not
            Any other failure gets raised since we cant recover from it
        """
        try:
            self._message_producer.health_check()
            self._recv_queue.wait_for_messages()
        except (websocket.WebSocketConnectionClosedException, WebSocketBlockedException):
            self._increment_message_producer_not_ok()
            self._setup_ws_session()

    def _increment_message_producer_not_ok(self):
        now = time.time()

        if self._last_not_ok and (now - self._last_not_ok) > self.RETRY_COUNT_TIMEOUT:
            self._message_producer_not_ok_count = 0

        self._last_not_ok = now
        self._message_producer_not_ok_count += 1

        if self._message_producer_not_ok_count > self.MAX_RETRY_THREADS:
            raise MaxRetriesException(
                "WS messaging thread not ok %s times within %s seconds" % (
                    self.MAX_RETRY_THREADS, self.RETRY_COUNT_TIMEOUT
                )
            )

    def _setup_ws_session(self):

        self._message_producer = _WSMessageProducer(self.port, self._send_queue, self._recv_queue)
        self._message_producer.start()

        if not (self._message_consumer.is_alive() or self._exception):
            # The message consumer needs to be started or we cannot enable the domains
            self._message_consumer.start()

        for domain, params in self._domains.items():
            self.enable_domain(domain, params)

    def _send(self, data):
        self._send_queue.append(json.dumps(data, sort_keys=True))
        self._check_message_producer()

    def close(self):
        self._should_flush_messages = False

        if hasattr(self, "_message_producer") and self._message_producer:

            self._message_producer.stop()
            timer = _Timer(5)
            while not timer.timed_out:
                if not self._message_producer.is_alive():
                    return
                time.sleep(0.1)

            self._message_producer.close()

    def _append(self, message):

        if "result" in message:
            self._results[message["id"]] = message.get("result")
        elif "error" in message:
            result_id = message.pop("id")
            self._results[result_id] = message
        elif "method" in message:
            method = message["method"]
            if method in self._internal_events:
                self._internal_events[method].handle(message)
            domain, event = method.split(".")
            if domain in self._events:
                with self._events_access_lock:
                    self._events[domain].append(message)
        else:
            logging.warning("Unrecognised message: {}".format(message))

    def _flush_messages(self):
        """ Consumes messages from the message queue
        """
        try:
            while self._should_flush_messages:
                while self._recv_queue:
                    message = self._recv_queue.popleft()
                    message = json.loads(message)
                    self._append(message)

                self._check_message_producer()
        except Exception as e:
            self._exception = e

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

        with self._events_access_lock:
            events = self._events[domain]
            if clear:
                self._events[domain] = []
            else:
                # This is to make the events immutable unless using clear
                events = events[:]

        return events

    def reset(self):
        with self._events_access_lock:
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
            if self._exception:
                raise self._exception

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
