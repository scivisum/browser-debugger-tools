import contextlib
import json
import logging
import socket
import time
import collections
from threading import Thread, Lock, Event, RLock

from typing import Dict, Callable, Optional, List, NamedTuple

import requests
import websocket

from browserdebuggertools.event_handlers import (
    EventHandler, PageLoadEventHandler, JavascriptDialogEventHandler
)
from browserdebuggertools.exceptions import (
    DevToolsException, MaxRetriesException,
    DevToolsTimeoutException, DomainNotEnabledError,
    MethodNotFoundError, UnknownError, ResourceNotFoundError, MessagingThreadIsDeadError,
    InvalidParametersError, WebSocketBlockedException,
    TargetNotAttachedError, TargetNotFoundError
)


def _unwrap_json_response(request: Callable) -> Callable:
    def _make_request_and_check_response(*args, **kwargs) -> dict:
        response = request(*args, **kwargs)
        if not response.ok:
            raise DevToolsException("{} {} for url: {}".format(
                response.status_code, response.reason, response.url)
            )
        return response.json()

    return _make_request_and_check_response


class _WSMessageProducer(Thread):
    """ Interfaces with the websocket to send messages from the send queue
        or put messages from the websocket into recv queue
    """
    _CONN_TIMEOUT = 15
    _BLOCKED_TIMEOUT = 5
    _POLL_INTERVAL = 1  # How long to wait for new ws messages

    def __init__(self, ws_url, send_queue, on_message):
        super(_WSMessageProducer, self).__init__()
        self._ws_url = ws_url
        self._send_queue = send_queue
        self._on_message = on_message
        self._last_ws_attempt = None
        self._continue = True

        self.exception = None
        self.ws = self._get_websocket()
        self.daemon = True
        self.poll_signal = Event()

    def __del__(self):
        self.close()

    def _get_websocket(self):
        logging.info(f"Connecting to websocket {self._ws_url}")
        ws = websocket.create_connection(
            self._ws_url, timeout=self._CONN_TIMEOUT
        )
        ws.settimeout(0)  # Don"t wait for new messages
        return ws

    @contextlib.contextmanager
    def _ws_io(self):

        # noinspection PyBroadException
        try:
            yield
        except websocket.WebSocketConnectionClosedException as e:
            self.exception = e
            logging.warning("WS messaging thread terminated due to closed connection")
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
        while True:
            try:
                message = self.ws.recv()
                self._on_message(json.loads(message))
            except socket.error as e:
                # We expect [Errno 11] when there are no more messages to read
                if "[Errno 11] Resource temporarily unavailable" not in str(e):
                    raise
                break

    def stop(self):
        self._continue = False

    def run(self):

        with self._ws_io():

            while self._continue:
                self._last_ws_attempt = time.time()
                self._empty_send_queue()
                self._empty_websocket()
                self.poll_signal.wait(self._POLL_INTERVAL)
                if self.poll_signal.is_set():
                    self.poll_signal.clear()

    @property
    def blocked(self):
        """ Returns True if:
                the websocket hangs https://github.com/websocket-client/websocket-client/issues/437,
                or we've been consuming messages from the websocket for too long **

            Although taking too long to receive messages from the websocket doesn't technically mean
            we're blocked it means we can't send any messages to that websocket either,
            some messages could allow us to reduce the load on the websocket
            so raising an exception in this case allows us to empty the send queue and try again.

            **  This could be solved by not handling sending messages in the thread,
                assuming ws.send() doesn't hang and is atomic.
                Then we could update self._last_ws_attempt after every successful ws send()/recv()
        """
        return (
            self._last_ws_attempt
            and ((time.time() - self._last_ws_attempt) > self._BLOCKED_TIMEOUT)
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


class _Timer:

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


class _Target:
    """
    A target is a tab or window that is open in the browser. It has a unique ID and a URL.
    :param info: <dict> The target info returned by the Chrome DevTools API
    """

    def __init__(self, info: dict, timeout, domains=None):
        self.info = info
        self._timeout = timeout
        self._domains = domains or {}
        self.wsm: Optional[_WSSessionManager] = None
        self.dom_manager: Optional[_DOMManager] = None

    def __repr__(self):
        return json.dumps(self.info)

    @property
    def id(self):
        return self.info["id"]

    @property
    def type(self):
        return self.info["type"]

    def reset(self):
        if not self.wsm:
            raise TargetNotAttachedError()
        self.wsm.reset()
        self.dom_manager.reset()

    def attach(self):
        self.wsm = _WSSessionManager(
            self.info["webSocketDebuggerUrl"], self._timeout, domains=self._domains)
        self.dom_manager = _DOMManager(self.wsm)

    def detach(self):
        self.wsm.close()


class ServiceWorkerTarget(_Target):

    def __init__(self, info: dict, timeout):
        super().__init__(info, timeout)


class EventHandlers(NamedTuple):
    pageLoad: PageLoadEventHandler
    javascriptDialog: JavascriptDialogEventHandler


class _WSSessionManager:
    MAX_RETRY_THREADS = 3
    RETRY_COUNT_TIMEOUT = 300  # Seconds

    def __init__(self, ws_url, timeout, domains=None):

        self.timeout = timeout
        self._domains = domains or {}
        self._events = dict([(k, []) for k in self._domains])
        self._results = {}

        self.event_handlers: EventHandlers = EventHandlers(
            PageLoadEventHandler(self),
            JavascriptDialogEventHandler(self)
        )

        self._internal_events: Dict[str, EventHandler] = {}
        for event in self.event_handlers.pageLoad.supported_events:
            self._internal_events[event] = self.event_handlers.pageLoad
        for event in self.event_handlers.javascriptDialog.supported_events:
            self._internal_events[event] = self.event_handlers.javascriptDialog

        # Used to manage concurrency within the session manager
        self._next_result_id = 0
        self._result_id_lock = Lock()
        self._events_access_lock = Lock()

        # Used to manage the health of the message producer
        self._message_producer_lock = RLock()  # Lock making sure we don't create 2 ws connections
        self._last_not_ok = None
        self._message_producer_not_ok_count = 0
        self._send_queue = collections.deque()

        self.ws_url = ws_url
        self._message_producer = None

        self._setup_ws_session()

    def __del__(self):
        self.close()

    def _check_message_producer(self):
        """ Checks if the websocket is healthy and recreates the connection if not
            Any other failure gets raised since we cant recover from it
        """
        with self._message_producer_lock:
            try:
                self._message_producer.health_check()
            except (websocket.WebSocketConnectionClosedException, WebSocketBlockedException):
                # If the current ws connection is only blocked, we better make sure we close it
                # before opening a new one.
                self._message_producer.close()
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

        self._message_producer = _WSMessageProducer(
            self.ws_url, self._send_queue, self._process_message
        )
        self._message_producer.start()

        for domain, params in self._domains.items():
            self.enable_domain(domain, params)

    def _send(self, data):
        self._send_queue.append(json.dumps(data, sort_keys=True))
        self._check_message_producer()

    def close(self):
        if hasattr(self, "_message_producer") and self._message_producer:
            self._message_producer.stop()
            timer = _Timer(5)
            while not timer.timed_out:
                if not self._message_producer.is_alive():
                    return
                time.sleep(0.1)
            self._message_producer.close()

    def _process_message(self, message):

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

        self._check_message_producer()

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

    def _wait_for_result(self, result_id):
        """ Waits for a result to complete within the timeout duration then returns it.
            Raises a DevToolsTimeoutException if it cannot find the result.

        :return: The result.
        """
        timer = _Timer(self.timeout)
        while not timer.timed_out:
            if result_id in self._results:
                return self._results.pop(result_id)

            self._check_message_producer()
            self._message_producer.poll_signal.set()
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
            logging.warning("Domain \"{}\" doesn't exist".format(domain_name))
        else:
            logging.info("Domain {} has been disabled".format(domain_name))


class _DOMManager:

    def __init__(self, socket_handler):
        self._socket_handler = socket_handler
        self._node_map = {}

    def get_outer_html(self, backend_node_id: int) -> str:
        return self._socket_handler.execute(
            "DOM", "getOuterHTML", {"backendNodeId": backend_node_id}
        )["outerHTML"]

    def get_iframe_html(self, xpath: str) -> str:
        backend_node_id = self._get_iframe_backend_node_id(xpath)
        try:
            return self.get_outer_html(backend_node_id)
        except ResourceNotFoundError:
            # The cached node doesn't exist anymore, so we need to find a new one that matches
            # the xpath. Backend node IDs are unique, so there is not a risk of getting the
            # outer html of the wrong node.
            if xpath in self._node_map:
                del self._node_map[xpath]
            backend_node_id = self._get_iframe_backend_node_id(xpath)
            return self.get_outer_html(backend_node_id)

    def _get_iframe_backend_node_id(self, xpath: str) -> int:
        if xpath in self._node_map:
            return self._node_map[xpath]

        node_info = self._get_info_for_first_matching_node(xpath)
        try:

            backend_node_id = node_info["node"]["contentDocument"]["backendNodeId"]
        except KeyError:
            raise ResourceNotFoundError("The node found by xpath '%s' is not an iframe" % xpath)

        self._node_map[xpath] = backend_node_id
        return backend_node_id

    def _get_info_for_first_matching_node(self, xpath: str) -> dict:
        with self._get_node_ids(xpath) as node_ids:
            if node_ids:
                return self._describe_node(node_ids[0])
        raise ResourceNotFoundError("No matching nodes for xpath: %s" % xpath)

    @contextlib.contextmanager
    def _get_node_ids(self, xpath: str, max_matches: int = 1) -> List:
        assert max_matches > 0
        search_info = self._perform_search(xpath)
        try:
            results = []
            if search_info["resultCount"] > 0:
                results = self._get_search_results(
                    search_info["searchId"], 0,
                    min([max_matches, search_info["resultCount"]])
                )["nodeIds"]
            yield results

        finally:
            self._discard_search(search_info["searchId"])

    def _perform_search(self, xpath: str) -> dict:
        # DOM.getDocument must have been called on the current page first otherwise performSearch
        # returns an array of 0s.
        self._socket_handler.event_handlers.pageLoad.check_page_load()
        return self._socket_handler.execute("DOM", "performSearch", {"query": xpath})

    def _get_search_results(self, search_id: str, from_index: int, to_index: int) -> dict:
        return self._socket_handler.execute("DOM", "getSearchResults", {
            "searchId": search_id, "fromIndex": from_index, "toIndex": to_index
        })

    def _discard_search(self, search_id: str) -> None:
        """
        Discards search results for the session with the given id. get_search_results should no
        longer be called for that search.
        """
        self._socket_handler.execute("DOM", "discardSearchResults", {"searchId": search_id})

    def _describe_node(self, node_id: str) -> dict:
        return self._socket_handler.execute("DOM", "describeNode", {"nodeId": node_id})

    def reset(self):
        self._node_map = {}


class TargetsManager:
    """
    Manages "targets" - end points which can be communicated with via the DevTools protocol
    e.g. tabs, iframes, chrome extensions
    """

    def __init__(
        self,
        connection_timeout: int,
        port: int,
        host: str = "localhost",
        domains: Optional[dict] = None
    ):
        """
        :param domains: The default domains to enable for any attached target
        """
        self._targets: dict[str, _Target] = {}
        self._domains = domains or {}
        self._host = host
        self._port = port
        self._connection_timeout = connection_timeout
        self.current_target_id = None

    def get_opened_javascript_dialog(self):
        return (
            self.current_target.wsm.event_handlers.javascriptDialog.get_opened_javascript_dialog()
        )

    def get_page_source(self):
        root_node_id = self.current_target.wsm.event_handlers.pageLoad.get_root_backend_node_id()
        return self.current_target.dom_manager.get_outer_html(root_node_id)

    def get_iframe_source_content(self, xpath):
        return self.current_target.dom_manager.get_iframe_html(xpath)

    def get_url(self):
        return self.current_target.wsm.event_handlers.pageLoad.get_current_url()

    @contextlib.contextmanager
    def set_timeout(self, value: int):
        """ Switches the timeout to the given value.
        """
        _timeout = self.current_target.wsm.timeout
        self.current_target.wsm.timeout = value
        try:
            yield
        finally:
            self.current_target.wsm.timeout = _timeout

    def get_all_events(self, *args, **kwargs):
        events = []
        for target in self._targets.values():
            try:
                events.extend(target.wsm.get_events(*args, **kwargs))
            except DomainNotEnabledError:
                pass
        return events

    def get_events(self, *args, **kwargs):
        return self.current_target.wsm.get_events(*args, **kwargs)

    def execute(self, *args, **kwargs):
        return self.current_target.wsm.execute(*args, **kwargs)

    def enable_domain(self, domain: str, parameters=None):
        self._domains[domain] = parameters or {}
        self.current_target.wsm.enable_domain(domain, parameters=parameters)

    def disable_domain(self, domain: str):
        if domain not in self._domains:
            raise DomainNotEnabledError(domain)
        del self._domains[domain]
        return self.current_target.wsm.disable_domain(domain)

    def switch_target(self, target_id: str):
        self.current_target_id = target_id

    @property
    def current_target(self) -> _Target:
        return self._targets[self.current_target_id]

    def detach_all(self):
        if self._targets:
            for target in self._targets.values():
                target.detach()

    def reset(self):
        for target in self._targets.values():
            target.reset()

    def refresh_targets(self):
        expected = self._get_targets()
        expected_ids = []
        # For each target we just fetched
        for targetInfo in expected:
            expected_ids.append(targetInfo["id"])

            # Ignore targets that are not pages. Some targets, do not support the same protocol,
            # i.e. a service_worker target doesn't support the "Page" domain, and if we try to
            # enable it, we get an exception.
            if targetInfo["type"] == "page":
                if targetInfo["id"] not in self._targets:
                    target = _Target(targetInfo, self._connection_timeout, domains=self._domains)
                    target.attach()
                    self._targets[targetInfo["id"]] = target
                else:
                    self._targets[targetInfo["id"]].info = targetInfo

        # detach and remove any target that does not exist anymore.
        for target_id, target in list(self._targets.items()):
            if target_id not in expected_ids:
                target.detach()
                del self._targets[target_id]
        return self._targets

    @property
    def targets(self):
        return self._targets

    @_unwrap_json_response
    def _get_targets(self):
        # noinspection HttpUrlsUsage
        return requests.get(
            f"http://{self._host}:{self._port}/json", timeout=self._connection_timeout
        )

    def create_tab(self):
        target_id = self._create_tab()["id"]
        self.refresh_targets()
        return self._targets[target_id]

    @_unwrap_json_response
    def _create_tab(self):
        # noinspection HttpUrlsUsage
        return requests.put(
            f"http://{self._host}:{self._port}/json/new", timeout=self._connection_timeout
        )

    def get_service_worker(self, service_script_name):

        def find_target_info():
            for target in self._get_targets():
                if (
                    target["type"] == "service_worker"
                    and target["url"].endswith(service_script_name)
                ):
                    return target

        targetInfo = find_target_info()
        if targetInfo:
            return ServiceWorkerTarget(targetInfo, self._connection_timeout)
        else:
            raise TargetNotFoundError(service_script_name)
