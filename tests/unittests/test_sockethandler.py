import copy
import socket
from unittest import TestCase

from mock import patch, MagicMock

from browserdebuggertools.exceptions import (
    DevToolsException, ResultNotFoundError, TabNotFoundError,
    DomainNotEnabledError, DevToolsTimeoutException, MethodNotFoundError
)
from browserdebuggertools.sockethandler import SocketHandler

MODULE_PATH = "browserdebuggertools.sockethandler."


class BaseMockSocketHandler(SocketHandler):

    def __init__(self):
        self._websocket = MagicMock()

        self._next_result_id = 0
        self.timeout = 30
        self._domains = []
        self._results = {}
        self._events = {}


class MockSocketHandler(SocketHandler):

    def __init__(self):
        super(MockSocketHandler, self).__init__(1234, 30)

    def _get_websocket_url(self, port):
        return "ws://localhost:1234/devtools/page/test"

    def _setup_websocket(self):
        return MagicMock()


class SocketHandlerTest(TestCase):

    def setUp(self):
        self.socket_handler = MockSocketHandler()


@patch(MODULE_PATH + "requests")
@patch(MODULE_PATH + "websocket", MagicMock())
class Test_Sockethandler__get_websocket_url(TestCase):

    def setUp(self):
        self.socket_handler = BaseMockSocketHandler()

    def test(self, requests):
        mock_websocket_url = "ws://localhost:1234/devtools/page/test"
        requests.get().json.return_value = [{
            "type": "page",
            "webSocketDebuggerUrl": mock_websocket_url
        }]

        websocket_url = self.socket_handler._get_websocket_url(1234)

        self.assertEqual(mock_websocket_url, websocket_url)

    def test_invalid_port(self, requests):
        requests.get().ok.return_value = False

        with self.assertRaises(DevToolsException):
            self.socket_handler._get_websocket_url(1234)

    def test_no_tabs(self, requests):
        requests.get().json.return_value = [{
            "type": "iframe",
            "webSocketDebuggerUrl": "ws://localhost:1234/devtools/page/test"
        }]

        with self.assertRaises(TabNotFoundError):
            self.socket_handler._get_websocket_url(1234)


class Test_SocketHandler__append(SocketHandlerTest):

    def test_result(self):
        mock_result = MagicMock()
        message = {"id": 1, "result": mock_result}

        self.socket_handler._append(message)

        self.assertEqual(mock_result, self.socket_handler._results[1])

    def test_error(self):
        mock_result = MagicMock()
        mock_error = {"error": mock_result}
        message = {"id": 1, "error": mock_result}

        self.socket_handler._append(message)

        self.assertEqual(mock_error, self.socket_handler._results[1])

    def test_event(self):
        self.socket_handler._events["MockDomain"] = []
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.socket_handler._append(mock_event)

        self.assertIn(mock_event, self.socket_handler._events["MockDomain"])

    def test_internal_event(self):
        self.socket_handler._events["MockDomain"] = []
        mock_event_handler = MagicMock()
        self.socket_handler.event_handlers = {
            "MockEvent": mock_event_handler
        }
        self.socket_handler._internal_events = {"MockDomain": {"mockMethod": mock_event_handler}}
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.socket_handler._append(mock_event)

        self.assertIn(mock_event, self.socket_handler._events["MockDomain"])
        self.assertTrue(mock_event_handler.handle.called)


class Test_SocketHandler_flush_messages(SocketHandlerTest):

    class MockSocketHandler(SocketHandler):

        def __init__(self):
            self._websocket = MagicMock()

            self._next_result_id = 0
            self._domains = []
            self._results = {}
            self._events = {}
            self._internal_events = {}
            self.timer = MagicMock(timed_out=False)

    def setUp(self):
        self.socket_handler = self.MockSocketHandler()

    def test_get_results(self):
        mock_result = {"key": "value"}
        mock_message = '{"id": 1, "result": {"key": "value"}}'
        self.socket_handler._websocket.recv.side_effect = [mock_message, None]

        self.socket_handler._flush_messages()

        self.assertEqual(mock_result, self.socket_handler._results[1])

    def test_get_errors(self):
        mock_error = {"error": {"key": "value"}}
        mock_message = '{"id": 1, "error": {"key": "value"}}'
        self.socket_handler._websocket.recv.side_effect = [mock_message, None]

        self.socket_handler._flush_messages()

        self.assertEqual(mock_error, self.socket_handler._results[1])

    def test_get_events(self):
        mock_event = {"method": "MockDomain.mockEvent", "params": {"key": "value"}}
        mock_message = '{"method": "MockDomain.mockEvent", "params": {"key": "value"}}'
        self.socket_handler._events["MockDomain"] = []
        self.socket_handler._websocket.recv.side_effect = [mock_message, None]

        self.socket_handler._flush_messages()

        self.assertIn(mock_event, self.socket_handler._events["MockDomain"])

    def test_get_mixed(self):
        mock_result = {"key": "value"}
        mock_error = {"error": {"key": "value"}}
        mock_event = {"method": "MockDomain.mockEvent", "params": {"key": "value"}}
        mock_result_message = '{"id": 1, "result": {"key": "value"}}'
        mock_error_message = '{"id": 2, "error": {"key": "value"}}'
        mock_event_message = '{"method": "MockDomain.mockEvent", "params": {"key": "value"}}'

        self.socket_handler._events["MockDomain"] = []
        self.socket_handler._websocket.recv.side_effect = [
            mock_result_message, mock_error_message, mock_event_message, None
        ]

        self.socket_handler._flush_messages()

        self.assertEqual(mock_result, self.socket_handler._results[1])
        self.assertEqual(mock_error, self.socket_handler._results[2])
        self.assertIn(mock_event, self.socket_handler._events["MockDomain"])

    def test_get_messages_then_except(self):
        mock_result = {"key": "value"}
        mock_message = '{"id": 1, "result": {"key": "value"}}'
        self.socket_handler._websocket.recv.side_effect = [mock_message, socket.error]

        self.socket_handler._flush_messages()

        self.assertEqual(mock_result, self.socket_handler._results[1])



@patch(MODULE_PATH + "SocketHandler._flush_messages", MagicMock())
class Test_SocketHandler_find_next_result(SocketHandlerTest):

    def test_find_cached_result(self):
        mock_result = {"result": "correct result"}

        self.socket_handler._next_result_id = 42
        self.socket_handler._results[42] = mock_result
        result = self.socket_handler._find_next_result()

        self.assertEqual(mock_result, result)

    def test_find_uncached_result(self):

        mock_result = {"result": "correct result"}
        self.socket_handler._results = {}
        self.socket_handler._next_result_id = 42

        def mock_flush_messages():
            self.socket_handler._results[42] = mock_result

        self.socket_handler._flush_messages = mock_flush_messages

        result = self.socket_handler._find_next_result()
        self.assertEqual(mock_result, result)

    def test_no_result(self):

        with self.assertRaises(ResultNotFoundError):
            self.socket_handler._find_next_result()


@patch(MODULE_PATH + "websocket.send", MagicMock())
class Test_SocketHandler_execute(SocketHandlerTest):

    def test(self):

        domain = "Page"
        method = "navigate"

        self.socket_handler._wait_for_result = MagicMock()
        self.socket_handler._send = MagicMock()
        self.socket_handler._next_result_id = 3

        self.socket_handler.execute(domain, method, None)

        self.assertEqual(4, self.socket_handler._next_result_id)
        self.socket_handler._wait_for_result.assert_called_once_with()
        self.socket_handler._send.assert_called_once_with({
            "method": "%s.%s" % (domain, method), "params": {}
        })


class Test_SocketHandler_add_domain(SocketHandlerTest):

    def test_new_domain(self):
        self.socket_handler._domains = {}
        self.socket_handler._add_domain("MockDomain", {})

        self.assertEqual({"MockDomain": {}}, self.socket_handler._domains)
        self.assertEqual({"MockDomain": []}, self.socket_handler._events)

    def test_existing_domain(self):
        self.socket_handler._domains = {"MockDomain": {}}
        mock_events = [MagicMock(), MagicMock()]
        self.socket_handler._events["MockDomain"] = mock_events
        self.socket_handler._add_domain("MockDomain", {"test": 1})

        self.assertEqual({"MockDomain": {}}, self.socket_handler._domains)
        self.assertEqual({"MockDomain": mock_events}, self.socket_handler._events)


class Test_SocketHandler_remove_domain(SocketHandlerTest):

    def test_existing_domain(self):

        domain = "MockDomain"

        self.socket_handler._domains = {domain: {}}
        self.socket_handler._events = {domain: []}

        self.socket_handler._remove_domain(domain)

        self.assertEqual(self.socket_handler._domains, {})
        self.assertEqual(self.socket_handler._events, {})

    def test_invalid(self):

        domain = "MockDomain"

        self.socket_handler._domains = {domain: {}}
        self.socket_handler._events = {domain: []}

        self.socket_handler._remove_domain("InvalidMockDomain")

        self.assertEqual(self.socket_handler._domains, {domain: {}})
        self.assertEqual(self.socket_handler._events, {domain: []})


class Test_SocketHandler_get_events(SocketHandlerTest):

    def setUp(self):
        super(Test_SocketHandler_get_events, self).setUp()
        self.domain = "MockDomain"
        self.socket_handler._domains = {self.domain: {}}

    @patch(MODULE_PATH + "SocketHandler._flush_messages")
    def test_no_clear(self, _flush_messages):

        self.mock_events = {self.domain: [MagicMock()]}
        self.socket_handler._events = self.mock_events

        events = self.socket_handler.get_events(self.domain)

        _flush_messages.assert_called_once_with()
        self.assertEqual(self.mock_events[self.domain], events)
        self.assertEqual(self.mock_events, self.socket_handler._events)

    def test_domain_not_enabled(self):
        self.socket_handler._domains = {}
        with self.assertRaises(DomainNotEnabledError):
            self.socket_handler.get_events("MockDomain")

    @patch(MODULE_PATH + "SocketHandler._flush_messages")
    def test_clear(self, _flush_messages):

        self.mock_events = {self.domain: [MagicMock()]}
        self.socket_handler._events = copy.deepcopy(self.mock_events)

        events = self.socket_handler.get_events(self.domain, clear=True)

        _flush_messages.assert_called_once_with()
        self.assertEqual(self.mock_events[self.domain], events)
        self.assertEqual([], self.socket_handler._events[self.domain])


class Test_Sockethandler_clear_all_events(SocketHandlerTest):

    def test(self):
        self.socket_handler.domains = ["Page", "Network"]
        self.socket_handler._events = {
            "Page": [MagicMock(), MagicMock()],
            "Network": [MagicMock(), MagicMock()]
        }

        self.socket_handler.reset()

        for key, value in self.socket_handler._events.items():
            self.assertEqual([], value)


@patch(MODULE_PATH + "SocketHandler.execute")
@patch(MODULE_PATH + "SocketHandler._add_domain")
class Test_SocketHandler_enable_domain(SocketHandlerTest):

    def test_no_parameters(self, _add_domain, execute):

        domain_name = "Network"

        self.socket_handler.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_called_once_with(domain_name, {})

    def test_with_parameters(self, _add_domain, execute):

        domain_name = "Network"
        parameters = {"some": "param"}

        self.socket_handler.enable_domain(domain_name, parameters=parameters)

        execute.assert_called_once_with(domain_name, "enable", parameters)
        _add_domain.assert_called_once_with(domain_name, parameters)

    def test_invalid_domain(self, _add_domain, execute):

        domain_name = "Network"
        execute.side_effect = [MethodNotFoundError("Domain not found")]

        with self.assertRaises(MethodNotFoundError):
            self.socket_handler.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_not_called()


class Test_ChromeInterface_wait_for_result(SocketHandlerTest):

    def test_succeed_immediately(self):
        mock_result = MagicMock()
        self.socket_handler._find_next_result = MagicMock()
        self.socket_handler._find_next_result.side_effect = [mock_result]
        self.socket_handler.timer = MagicMock(timed_out=False)

        result = self.socket_handler._wait_for_result()

        self.assertEqual(mock_result, result)

    def test_wait_and_then_succeeed(self):

        mock_result = MagicMock()
        self.socket_handler._find_next_result = MagicMock()
        self.socket_handler._find_next_result.side_effect = [ResultNotFoundError, mock_result]
        self.socket_handler.timer = MagicMock(timed_out=False)

        result = self.socket_handler._wait_for_result()

        self.assertEqual(mock_result, result)

    def test_timed_out(self):

        self.socket_handler.timer = MagicMock(timed_out=True)
        with self.assertRaises(DevToolsTimeoutException):
            self.socket_handler._wait_for_result()
