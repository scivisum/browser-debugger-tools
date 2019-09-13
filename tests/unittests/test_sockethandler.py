import copy
import socket
from unittest import TestCase

from mock import patch, MagicMock

from browserdebuggertools.exceptions import ResultNotFoundError, TabNotFoundError, \
    DomainNotEnabledError, DomainNotFoundError, DevToolsTimeoutException
from browserdebuggertools.sockethandler import SocketHandler

MODULE_PATH = "browserdebuggertools.sockethandler."


class MockSocketHandler(SocketHandler):

    def __init__(self):
        self._websocket = MagicMock()

        self._next_result_id = 0
        self.timeout = 30
        self._domains = []
        self._results = {}
        self._events = {}


class SocketHandlerTest(TestCase):

    def setUp(self):
        self.socket_handler = MockSocketHandler()


@patch(MODULE_PATH + "requests")
@patch(MODULE_PATH + "websocket", MagicMock())
class Test_Sockethandler__get_websocket_url(SocketHandlerTest):

    def test(self, requests):
        mock_websocket_url = "ws://localhost:1234/devtools/page/test"
        requests.get().json.return_value = [{
            "type": "page",
            "webSocketDebuggerUrl": mock_websocket_url
        }]

        websocket_url = self.socket_handler._get_websocket_url(1234)

        self.assertEqual(mock_websocket_url, websocket_url)

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


@patch(MODULE_PATH + "SocketHandler._append", MagicMock())
class Test_SocketHandler_flush_messages(SocketHandlerTest):

    def test_socket_error(self):
        self.socket_handler._websocket.recv.side_effect = [socket.error]

        self.socket_handler._flush_messages()


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
        execute.return_value = {"error": "some error"}

        with self.assertRaises(DomainNotFoundError):
            self.socket_handler.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_called_once_with(domain_name, {})


@patch(MODULE_PATH + "time")
class Test_ChromeInterface_wait_for_result(SocketHandlerTest):

    def test(self, time):
        mock_result = MagicMock()
        self.socket_handler._find_next_result = MagicMock()
        self.socket_handler._find_next_result.side_effect = [mock_result]
        time.time.side_effect = [1, 2, 3]

        result = self.socket_handler._wait_for_result()

        self.assertEqual(mock_result, result)

    def test_wait(self, time):
        mock_result = MagicMock()
        self.socket_handler._find_next_result = MagicMock()
        self.socket_handler._find_next_result.side_effect = [ResultNotFoundError, mock_result]
        time.time.side_effect = [1, 2, 3]

        result = self.socket_handler._wait_for_result()

        self.assertEqual(mock_result, result)

    def test_timed_out(self, time):
        self.socket_handler.timeout = 2
        self.socket_handler._find_next_result = MagicMock()
        self.socket_handler._find_next_result.side_effect = [
            ResultNotFoundError, ResultNotFoundError
        ]
        time.time.side_effect = [1, 2, 3]

        with self.assertRaises(DevToolsTimeoutException):
            self.socket_handler._wait_for_result()
