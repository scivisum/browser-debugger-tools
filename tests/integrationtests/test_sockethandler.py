import socket
from unittest import TestCase

from mock import MagicMock

from browserdebuggertools.sockethandler import SocketHandler

MODULE_PATH = "browserdebuggertools.sockethandler."


class MockSocketHandler(SocketHandler):

    def __init__(self):
        self._websocket = MagicMock()

        self._next_result_id = 0
        self._domains = []
        self._results = {}
        self._events = {}


class SocketHandlerTest(TestCase):

    def setUp(self):
        self.socket_handler = MockSocketHandler()


class Test_SocketHandler_can_get_messages(SocketHandlerTest):

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
