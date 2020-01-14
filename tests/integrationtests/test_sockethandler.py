import json
import socket
from unittest import TestCase

from mock import MagicMock

from browserdebuggertools.exceptions import DevToolsTimeoutException
from browserdebuggertools.sockethandler import SocketHandler

MODULE_PATH = "browserdebuggertools.sockethandler."


class Test_SocketHandler_get_events(TestCase):

    class _DummyWebsocket(object):

        def __init__(self):
            self._result_id = -1

        def recv(self):
            self._result_id += 1
            return json.dumps({"method": "Network.Something", "params": {}})

    class MockSocketHandler(SocketHandler):

        def __init__(self):
            SocketHandler.__init__(self, 1234, 30)

        def _get_websocket_url(self, port):
            return "ws://localhost:1234/devtools/page/test"

        def _setup_websocket(self):
            return MagicMock()

    def setUp(self):
        self.socket_handler = self.MockSocketHandler()

    def test_timeout_when_getting_events(self):

        self.socket_handler._websocket = self._DummyWebsocket()
        self.socket_handler.timer.timeout = 1
        self.socket_handler._domains = {"Network": []}

        with self.assertRaises(DevToolsTimeoutException):
            self.socket_handler.get_events("Network")


class Test_SocketHandler_wait_for_result(TestCase):

    class _DummyWebsocket(object):

        def __init__(self):
            self._result_id = -1

        def recv(self):
            self._result_id += 1
            return json.dumps({"method": "Network.Something", "params": {}})

    class MockSocketHandler(SocketHandler):

        def __init__(self):
            SocketHandler.__init__(self, 1234, 30)

        def _get_websocket_url(self, port):
            return "ws://localhost:1234/devtools/page/test"

        def _setup_websocket(self):
            return MagicMock()

    def setUp(self):
        self.socket_handler = self.MockSocketHandler()

    def test_no_messages_with_result_timeout(self):

        self.socket_handler._websocket = MagicMock(recv=MagicMock(side_effect=socket.error()))
        self.socket_handler.timer.timeout = 1
        self.socket_handler._next_result_id = 2

        with self.assertRaises(DevToolsTimeoutException):
            self.socket_handler._wait_for_result()

    def test_message_spamming_with_result_timeout(self):

        self.socket_handler._websocket = self._DummyWebsocket()
        self.socket_handler.timer.timeout = 1
        self.socket_handler._next_result_id = -1

        with self.assertRaises(DevToolsTimeoutException):
            self.socket_handler._wait_for_result()

    def test_message_spamming_with_result_found(self):

        self.socket_handler._websocket = self._DummyWebsocket()
        self.socket_handler.timer.timeout = 1
        self.socket_handler._next_result_id = 2

        with self.assertRaises(DevToolsTimeoutException):
            self.socket_handler._wait_for_result()
