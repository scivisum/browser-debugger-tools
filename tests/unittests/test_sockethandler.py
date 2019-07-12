import socket
from unittest import TestCase

from mock import patch, MagicMock

from browserdebuggertools.exceptions import ResultNotFoundError, TabNotFoundError, \
    DomainNotEnabledError
from browserdebuggertools.sockethandler import SocketHandler

MODULE_PATH = "browserdebuggertools.sockethandler."


class MockSocketHandler(SocketHandler):

    def __init__(self):
        self.websocket = MagicMock()

        self._next_result_id = 0
        self.domains = []
        self.results = {}
        self.events = {}


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

        self.assertEqual(mock_result, self.socket_handler.results[1])

    def test_error(self):
        mock_result = MagicMock()
        mock_error = {"error": mock_result}
        message = {"id": 1, "error": mock_result}

        self.socket_handler._append(message)

        self.assertEqual(mock_error, self.socket_handler.results[1])

    def test_event(self):
        self.socket_handler.events["MockDomain"] = []
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.socket_handler._append(mock_event)

        self.assertIn(mock_event, self.socket_handler.events["MockDomain"])


@patch(MODULE_PATH + "SocketHandler._append", MagicMock())
class Test_SocketHandler_flush_messages(SocketHandlerTest):

    def test_socket_error(self):
        self.socket_handler.websocket.recv.side_effect = [socket.error]

        self.socket_handler.flush_messages()


@patch(MODULE_PATH + "SocketHandler.flush_messages", MagicMock())
class Test_SocketHandler_find_result(SocketHandlerTest):

    def test_find_cached_result(self):
        mock_result = {"result": "correct result"}
        self.socket_handler.results[42] = mock_result

        result = self.socket_handler.find_result(42)

        self.assertEqual(mock_result, result)

    def test_find_uncached_result(self):
        mock_result = {"result": "correct result"}

        def mock_flush_messages():
            self.socket_handler.results[42] = mock_result

        self.socket_handler.flush_messages = mock_flush_messages

        result = self.socket_handler.find_result(42)

        self.assertEqual(mock_result, result)

    def test_no_result(self):

        with self.assertRaises(ResultNotFoundError):
            self.socket_handler.find_result(42)


@patch(MODULE_PATH + "websocket.send", MagicMock())
class Test_SocketHandler_execute(SocketHandlerTest):

    def test(self):
        self.socket_handler._next_result_id = 3

        self.socket_handler.execute("Page.navigate", None)

        self.assertEqual(4, self.socket_handler._next_result_id)


class Test_SocketHandler_add_domain(SocketHandlerTest):

    def test_new_domain(self):
        self.socket_handler.domains = set()

        self.socket_handler.add_domain("MockDomain")

        self.assertIn("MockDomain", self.socket_handler.domains)
        self.assertIn("MockDomain", self.socket_handler.events)

    def test_existing_domain(self):
        self.socket_handler.domains = {"MockDomain"}
        mock_events = [MagicMock(), MagicMock()]
        self.socket_handler.events["MockDomain"] = mock_events

        self.socket_handler.add_domain("MockDomain")

        self.assertIn("MockDomain", self.socket_handler.domains)
        self.assertIn("MockDomain", self.socket_handler.events)
        self.assertEqual(mock_events, self.socket_handler.events["MockDomain"])


class Test_SocketHandler_remove_domain(SocketHandlerTest):

    def test_existing_domain(self):
        self.socket_handler.domains = {"MockDomain"}

        self.socket_handler.remove_domain("MockDomain")

        self.assertNotIn("MockDomain", self.socket_handler.domains)

    def test_invalid(self):
        self.socket_handler.domains = {"MockDomain"}

        self.socket_handler.remove_domain("InvalidMockDomain")

        self.assertIn("MockDomain", self.socket_handler.domains)
        self.assertNotIn("InvalidMockDomain", self.socket_handler.events)


@patch(MODULE_PATH + "SocketHandler.flush_messages", MagicMock())
class Test_SocketHandler_get_events(SocketHandlerTest):

    def test(self):
        mock_events = [MagicMock()]
        self.socket_handler.events["MockDomain"] = mock_events
        self.socket_handler.domains = {"MockDomain"}

        events = self.socket_handler.get_events("MockDomain")

        self.assertEqual(mock_events, events)

    def test_domain_not_enabled(self):
        self.socket_handler.domains = set()

        with self.assertRaises(DomainNotEnabledError):
            self.socket_handler.get_events("MockDomain")

    def test_clear(self):
        mock_events = [MagicMock()]
        self.socket_handler.events["MockDomain"] = mock_events
        self.socket_handler.domains = {"MockDomain"}

        events = self.socket_handler.get_events("MockDomain", clear=True)

        self.assertEqual(mock_events, events)
        self.assertEqual(0, len(self.socket_handler.events["MockDomain"]))
