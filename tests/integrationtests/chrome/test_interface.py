import time
import os
from unittest import TestCase
from base64 import b64encode

from mock import MagicMock, patch

from browserdebuggertools.chrome.interface import ChromeInterface, _DOMManager
from browserdebuggertools.exceptions import DevToolsTimeoutException
from browserdebuggertools.sockethandler import SocketHandler

MODULE_PATH = "browserdebuggertools.chrome.interface."


class MockChromeInterface(ChromeInterface):

    def __init__(self, port, timeout=30, domains=None):
        self._socket_handler = MockSocketHandler(port, timeout, domains=domains)
        self._dom_manager = _DOMManager(self._socket_handler)


class MockSocketHandler(SocketHandler):

    def _setup_websocket(self):
        return MagicMock()

    def _get_websocket_url(self, port):
        return MagicMock()


@patch(MODULE_PATH + "ChromeInterface.execute")
class Test_ChromeInterface_take_screenshot(TestCase):

    def setUp(self):
        super(Test_ChromeInterface_take_screenshot, self).setUp()
        self.interface = MockChromeInterface(1234)
        self.file_path = "/tmp/%s" % time.time()

    def test_take_screenshot(self, execute):
        exepected_bytes = bytes("hello_world".encode("utf-8"))
        execute.return_value = {"data": b64encode(exepected_bytes)}

        self.interface.take_screenshot(self.file_path)

        with open(self.file_path, "rb") as f:
            self.assertEqual(exepected_bytes, f.read())

    def tearDown(self):

        if os.path.exists(self.file_path):
            os.remove(self.file_path)


class ChromeInterfaceTest(TestCase):

    def setUp(self):
        self.interface = MockChromeInterface(0)
        self.interface._socket_handler._websocket.send = MagicMock()



class Test_ChromeInterface_set_timeout(ChromeInterfaceTest):

    def test_timeout_exception_raised(self):
        self.interface._socket_handler._websocket.send = MagicMock()
        self.interface._socket_handler._websocket.recv = MagicMock(return_value=None)

        start = time.time()
        with self.assertRaises(DevToolsTimeoutException):
            with self.interface.set_timeout(3):
                self.interface.execute("Something", "Else")

        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 2.5)
        self.assertLessEqual(elapsed, 3.4)


class Test_ChromeInterface_get_url(ChromeInterfaceTest):

    def load_pages(self, count):
        mock_message = '{"method": "Page.domContentEventFired"}'
        messages = [None]
        for _ in range(count):
            messages.insert(0, mock_message)
        self.interface._socket_handler._websocket.recv.side_effect = messages

    def load_js_pages(self, count):
        mock_message = '{"method": "Page.navigatedWithinDocument", "params":{"url": ""}}'
        messages = [None]
        for _ in range(count):
            messages.insert(0, mock_message)
        self.interface._socket_handler._websocket.recv.side_effect = messages

    def test_page_enabled_cache(self):
        self.interface._socket_handler._domains["Page"] = {}
        self.interface._socket_handler._events["Page"] = []
        self.interface._socket_handler._websocket.recv = MagicMock(return_value=None)
        self.interface._socket_handler.execute = MagicMock()

        self.interface.get_url()
        self.interface.get_page_source()
        self.assertEqual(2, self.interface._socket_handler.execute.call_count)
        self.interface.get_url()
        self.interface.get_page_source()
        self.assertEqual(3, self.interface._socket_handler.execute.call_count)

        self.load_pages(2)
        self.assertEqual(3, self.interface._socket_handler.execute.call_count)

        self.interface.get_url()
        self.interface._socket_handler._websocket.recv = MagicMock(return_value=None)
        self.interface.get_page_source()
        self.interface._socket_handler._websocket.recv = MagicMock(return_value=None)
        self.assertEqual(5, self.interface._socket_handler.execute.call_count)

        self.load_js_pages(1)
        self.interface.get_url()
        self.assertEqual(5, self.interface._socket_handler.execute.call_count)
        self.interface._socket_handler._websocket.recv = MagicMock(return_value=None)
        self.interface.get_page_source()
        self.assertEqual(6, self.interface._socket_handler.execute.call_count)
