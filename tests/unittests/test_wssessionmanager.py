import collections
import copy
from unittest import TestCase

from mock import patch, MagicMock, call
from websocket import WebSocketConnectionClosedException

from browserdebuggertools.exceptions import (
    DevToolsException, ResultNotFoundError, TabNotFoundError,
    DomainNotEnabledError, DevToolsTimeoutException, MethodNotFoundError,
    InvalidParametersError)
from browserdebuggertools.wssessionmanager import WSSessionManager, _WSMessagingThread

MODULE_PATH = "browserdebuggertools.wssessionmanager."


class MessagingThreadTest(TestCase):

    class _NoInitMessagingThread(_WSMessagingThread):

        def __init__(self):
            pass

    def setUp(self):
        self.messaging_thread = self._NoInitMessagingThread()


class SessionManagerTest(TestCase):

    class _NoWSSessionManager(WSSessionManager):

        def setup_ws_session(self):
            pass

    def setUp(self):
        self.session_manager = self._NoWSSessionManager(1234, 30)


@patch(MODULE_PATH + "requests")
@patch(MODULE_PATH + "websocket", MagicMock())
class Test__WSMessagingThread__get_websocket_url(MessagingThreadTest):

    def test(self, requests):
        mock_websocket_url = "ws://localhost:1234/devtools/page/test"
        requests.get().json.return_value = [{
            "type": "page",
            "webSocketDebuggerUrl": mock_websocket_url
        }]

        websocket_url = self.messaging_thread._get_websocket_url(1234)

        self.assertEqual(mock_websocket_url, websocket_url)

    def test_invalid_port(self, requests):
        requests.get().ok.return_value = False

        with self.assertRaises(DevToolsException):
            self.messaging_thread._get_websocket_url(1234)

    def test_no_tabs(self, requests):
        requests.get().json.return_value = [{
            "type": "iframe",
            "webSocketDebuggerUrl": "ws://localhost:1234/devtools/page/test"
        }]

        with self.assertRaises(TabNotFoundError):
            self.messaging_thread._get_websocket_url(1234)


class Test__WSMessagingThread_run(MessagingThreadTest):

    def test(self):

        self.messaging_thread._send_queue = collections.deque()
        self.messaging_thread._recv_queue = collections.deque()
        self.messaging_thread._continue = True
        self.messaging_thread._MAX_QUEUE_BUFFER = 2

        self.messaging_thread.add_to_send_queue("test1")
        self.messaging_thread.add_to_send_queue("test2")

        self.messaging_thread.ws = MagicMock()
        self.messaging_thread.ws.send = MagicMock()
        self.messaging_thread.close = MagicMock()
        self.messaging_thread.ws.recv = MagicMock(side_effect=["test3", "test4"])

        def _clear():
            self.messaging_thread._continue = False
        self.messaging_thread._poll_signal = MagicMock(clear=_clear)

        self.messaging_thread.run()

        self.messaging_thread.ws.send.assert_has_calls([call("test1"), call("test2")])
        self.assertEqual("test3", self.messaging_thread.get_from_recv_queue())
        self.assertEqual("test4", self.messaging_thread.get_from_recv_queue())
        self.messaging_thread.close.assert_called_once_with()


class Test__WSMessagingThread_blocked(MessagingThreadTest):

    def test_thread_not_started(self):

        self.messaging_thread._last_poll = None

        self.assertFalse(self.messaging_thread.blocked)

    @patch("browserdebuggertools.wssessionmanager.time")
    def test_thread_blocked(self, _time):

        now = 100
        _time.time.return_value = now

        self.messaging_thread._last_poll = now - self.messaging_thread._BLOCKED_TIMEOUT - 1

        self.assertTrue(self.messaging_thread.blocked)

    @patch("browserdebuggertools.wssessionmanager.time")
    def test_thread_not_blocked(self, _time):

        now = 100
        _time.time.return_value = now

        self.messaging_thread._last_poll = now - self.messaging_thread._BLOCKED_TIMEOUT + 1

        self.assertFalse(self.messaging_thread.blocked)


class Test_WSSessionManager__append(SessionManagerTest):

    def test_result(self):
        mock_result = MagicMock()
        message = {"id": 1, "result": mock_result}

        self.session_manager._append(message)

        self.assertEqual(mock_result, self.session_manager._results[1])

    def test_error(self):
        mock_result = MagicMock()
        mock_error = {"error": mock_result}
        message = {"id": 1, "error": mock_result}

        self.session_manager._append(message)

        self.assertEqual(mock_error, self.session_manager._results[1])

    def test_event(self):
        self.session_manager._events["MockDomain"] = []
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.session_manager._append(mock_event)

        self.assertIn(mock_event, self.session_manager._events["MockDomain"])

    def test_internal_event(self):
        self.session_manager._events["MockDomain"] = []
        mock_event_handler = MagicMock()
        self.session_manager.event_handlers = {
            "MockEvent": mock_event_handler
        }
        self.session_manager._internal_events = {"MockDomain": {"mockMethod": mock_event_handler}}
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.session_manager._append(mock_event)

        self.assertIn(mock_event, self.session_manager._events["MockDomain"])
        self.assertTrue(mock_event_handler.handle.called)


class Test_WSSessionManager_flush_messages(SessionManagerTest):

    def test_get_results(self):
        mock_result = {"key": "value"}
        mock_message = {"id": 1, "result": mock_result}
        self.session_manager._recv = MagicMock(side_effect=[mock_message, None])

        self.session_manager._flush_messages()

        self.assertEqual(mock_result, self.session_manager._results[1])

    def test_get_errors(self):
        mock_message = {"id": 1, "error": {"key": "value"}}
        self.session_manager._recv = MagicMock(side_effect=[mock_message, None])

        self.session_manager._flush_messages()

        self.assertEqual({"error": {"key": "value"}}, self.session_manager._results[1])

    def test_get_events(self):
        mock_message = {"method": "MockDomain.mockEvent", "params": {"key": "value"}}
        self.session_manager._events["MockDomain"] = []
        self.session_manager._recv = MagicMock(side_effect=[mock_message, None])

        self.session_manager._flush_messages()

        self.assertIn(mock_message, self.session_manager._events["MockDomain"])

    def test_get_mixed(self):
        mock_result = {"key": "value"}
        mock_error = {"error": {"key": "value"}}
        mock_event = {"method": "MockDomain.mockEvent", "params": {"key": "value"}}
        mock_result_message = {"id": 1, "result": {"key": "value"}}
        mock_error_message = {"id": 2, "error": {"key": "value"}}
        mock_event_message = {"method": "MockDomain.mockEvent", "params": {"key": "value"}}

        self.session_manager._events["MockDomain"] = []
        self.session_manager._recv = MagicMock(side_effect=[
            mock_result_message, mock_error_message, mock_event_message, None
        ])

        self.session_manager._flush_messages()

        self.assertEqual(mock_result, self.session_manager._results[1])
        self.assertEqual(mock_error, self.session_manager._results[2])
        self.assertIn(mock_event, self.session_manager._events["MockDomain"])

    def test_timed_out(self):

        self.session_manager._recv = MagicMock()

        with patch("browserdebuggertools.wssessionmanager._Timer", new=MagicMock(timed_out=True)):
            with self.assertRaises(DevToolsTimeoutException):
                self.session_manager._flush_messages()


@patch(MODULE_PATH + "WSSessionManager._flush_messages", MagicMock())
class Test_WSSessionManager_find_next_result(SessionManagerTest):

    def test_find_cached_result(self):
        mock_result = {"result": "correct result"}

        self.session_manager._next_result_id = 42
        self.session_manager._results[42] = mock_result
        result = self.session_manager._find_next_result()

        self.assertEqual(mock_result, result)

    def test_find_uncached_result(self):

        mock_result = {"result": "correct result"}
        self.session_manager._results = {}
        self.session_manager._next_result_id = 42

        def mock_flush_messages():
            self.session_manager._results[42] = mock_result

        self.session_manager._flush_messages = mock_flush_messages

        result = self.session_manager._find_next_result()
        self.assertEqual(mock_result, result)

    def test_no_result(self):

        with self.assertRaises(ResultNotFoundError):
            self.session_manager._find_next_result()


@patch(MODULE_PATH + "websocket.send", MagicMock())
class Test_WSSessionManager_execute(SessionManagerTest):

    def test(self):

        domain = "Page"
        method = "navigate"

        self.session_manager._wait_for_result = MagicMock()
        self.session_manager._send = MagicMock()
        self.session_manager._next_result_id = 3

        self.session_manager.execute(domain, method, None)

        self.assertEqual(4, self.session_manager._next_result_id)
        self.session_manager._wait_for_result.assert_called_once_with()
        self.session_manager._send.assert_called_once_with({
            "method": "%s.%s" % (domain, method), "params": {}
        })

    @patch(MODULE_PATH + "WSSessionManager._execute", new=MagicMock())
    def test_error(self):

        self.session_manager._wait_for_result = MagicMock(
            return_value={"error": {"code": -32602, "message": "Invalid interceptionId"}}
        )

        with self.assertRaises(InvalidParametersError):
            self.session_manager.execute(MagicMock(), MagicMock(), None)


class Test_WSSessionManager_add_domain(SessionManagerTest):

    def test_new_domain(self):
        self.session_manager._domains = {}
        self.session_manager._add_domain("MockDomain", {})

        self.assertEqual({"MockDomain": {}}, self.session_manager._domains)
        self.assertEqual({"MockDomain": []}, self.session_manager._events)

    def test_existing_domain(self):
        self.session_manager._domains = {"MockDomain": {}}
        mock_events = [MagicMock(), MagicMock()]
        self.session_manager._events["MockDomain"] = mock_events
        self.session_manager._add_domain("MockDomain", {"test": 1})

        self.assertEqual({"MockDomain": {}}, self.session_manager._domains)
        self.assertEqual({"MockDomain": mock_events}, self.session_manager._events)


class Test_WSSessionManager_remove_domain(SessionManagerTest):

    def test_existing_domain(self):

        domain = "MockDomain"

        self.session_manager._domains = {domain: {}}
        self.session_manager._events = {domain: []}

        self.session_manager._remove_domain(domain)

        self.assertEqual(self.session_manager._domains, {})
        self.assertEqual(self.session_manager._events, {})

    def test_invalid(self):

        domain = "MockDomain"

        self.session_manager._domains = {domain: {}}
        self.session_manager._events = {domain: []}

        self.session_manager._remove_domain("InvalidMockDomain")

        self.assertEqual(self.session_manager._domains, {domain: {}})
        self.assertEqual(self.session_manager._events, {domain: []})


class Test_WSSessionManager_get_events(SessionManagerTest):

    def setUp(self):
        super(Test_WSSessionManager_get_events, self).setUp()
        self.domain = "MockDomain"
        self.session_manager._domains = {self.domain: {}}

    @patch(MODULE_PATH + "WSSessionManager._flush_messages")
    def test_no_clear(self, _flush_messages):

        self.mock_events = {self.domain: [MagicMock()]}
        self.session_manager._events = self.mock_events

        events = self.session_manager.get_events(self.domain)

        _flush_messages.assert_called_once_with()
        self.assertEqual(self.mock_events[self.domain], events)
        self.assertEqual(self.mock_events, self.session_manager._events)

    def test_domain_not_enabled(self):
        self.session_manager._domains = {}
        with self.assertRaises(DomainNotEnabledError):
            self.session_manager.get_events("MockDomain")

    @patch(MODULE_PATH + "WSSessionManager._flush_messages")
    def test_clear(self, _flush_messages):

        self.mock_events = {self.domain: [MagicMock()]}
        self.session_manager._events = copy.deepcopy(self.mock_events)

        events = self.session_manager.get_events(self.domain, clear=True)

        _flush_messages.assert_called_once_with()
        self.assertEqual(self.mock_events[self.domain], events)
        self.assertEqual([], self.session_manager._events[self.domain])


class Test_wssessionmanager_clear_all_events(SessionManagerTest):

    def test(self):
        self.session_manager.domains = ["Page", "Network"]
        self.session_manager._events = {
            "Page": [MagicMock(), MagicMock()],
            "Network": [MagicMock(), MagicMock()]
        }

        self.session_manager.reset()

        for key, value in self.session_manager._events.items():
            self.assertEqual([], value)


@patch(MODULE_PATH + "WSSessionManager.execute")
@patch(MODULE_PATH + "WSSessionManager._add_domain")
class Test_WSSessionManager_enable_domain(SessionManagerTest):

    def test_no_parameters(self, _add_domain, execute):

        domain_name = "Network"

        self.session_manager.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_called_once_with(domain_name, {})

    def test_with_parameters(self, _add_domain, execute):

        domain_name = "Network"
        parameters = {"some": "param"}

        self.session_manager.enable_domain(domain_name, parameters=parameters)

        execute.assert_called_once_with(domain_name, "enable", parameters)
        _add_domain.assert_called_once_with(domain_name, parameters)

    def test_invalid_domain(self, _add_domain, execute):

        domain_name = "Network"
        execute.side_effect = [MethodNotFoundError("Domain not found")]

        with self.assertRaises(MethodNotFoundError):
            self.session_manager.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_not_called()


class Test_WSSessionManager_wait_for_result(SessionManagerTest):

    @patch("browserdebuggertools.wssessionmanager._Timer",
           new=MagicMock(return_value=MagicMock(timed_out=False)))
    def test_succeed_immediately(self):
        mock_result = MagicMock()
        self.session_manager._find_next_result = MagicMock()
        self.session_manager._find_next_result.side_effect = [mock_result]

        result = self.session_manager._wait_for_result()
        self.assertEqual(mock_result, result)

    @patch("browserdebuggertools.wssessionmanager._Timer",
           new=MagicMock(return_value=MagicMock(timed_out=False)))
    def test_wait_and_then_succeeed(self):

        mock_result = MagicMock()
        self.session_manager._find_next_result = MagicMock()
        self.session_manager._find_next_result.side_effect = [ResultNotFoundError, mock_result]
        self.session_manager.timer = MagicMock(timed_out=False)

        result = self.session_manager._wait_for_result()

        self.assertEqual(mock_result, result)

    @patch("browserdebuggertools.wssessionmanager._Timer",
           new=MagicMock(return_value=MagicMock(timed_out=True)))
    def test_timed_out(self):

        self.session_manager._recv = MagicMock()
        self.session_manager.timer = MagicMock(timed_out=True)
        with self.assertRaises(DevToolsTimeoutException):
            self.session_manager._wait_for_result()


class Test_WSSessionManager__check_messaging_thread(SessionManagerTest):

    def test_ok(self):

        self.session_manager.messaging_thread = MagicMock(
            is_alive=MagicMock(return_value=True), blocked=False
        )
        self.session_manager.setup_ws_session = MagicMock()
        self.session_manager.increment_messaging_thread_not_ok = MagicMock()

        self.session_manager._check_messaging_thread()

        self.session_manager.setup_ws_session.assert_not_called()
        self.session_manager.increment_messaging_thread_not_ok.assert_not_called()

    def test_blocked(self):
        self.session_manager.messaging_thread = MagicMock(
            is_alive=MagicMock(return_value=True), blocked=True
        )
        self.session_manager.setup_ws_session = MagicMock()
        self.session_manager.increment_messaging_thread_not_ok = MagicMock()
        self.session_manager.close = MagicMock()

        self.session_manager._check_messaging_thread()

        self.session_manager.setup_ws_session.assert_called_once_with()
        self.session_manager.increment_messaging_thread_not_ok.assert_called_once_with()
        self.session_manager.close.assert_called_once_with()

    def test_dead_because_connection_closed(self):
        self.session_manager.messaging_thread = MagicMock(
            is_alive=MagicMock(return_value=False), blocked=False
        )
        self.session_manager.setup_ws_session = MagicMock()
        self.session_manager.increment_messaging_thread_not_ok = MagicMock()
        self.session_manager.close = MagicMock()
        self.session_manager.messaging_thread.exception = WebSocketConnectionClosedException()

        self.session_manager._check_messaging_thread()

        self.session_manager.setup_ws_session.assert_called_once_with()
        self.session_manager.increment_messaging_thread_not_ok.assert_called_once_with()

    def test_dead_because_other(self):
        self.session_manager.messaging_thread = MagicMock(
            is_alive=MagicMock(return_value=False), blocked=False
        )
        self.session_manager.setup_ws_session = MagicMock()
        self.session_manager.increment_messaging_thread_not_ok = MagicMock()
        self.session_manager.close = MagicMock()

        class TestException(Exception):
            pass

        self.session_manager.messaging_thread.exception = TestException()

        with self.assertRaises(TestException):
            self.session_manager._check_messaging_thread()

        self.session_manager.setup_ws_session.assert_not_called()
        self.session_manager.increment_messaging_thread_not_ok.assert_not_called()
