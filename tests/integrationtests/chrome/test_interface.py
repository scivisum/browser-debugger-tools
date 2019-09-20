import time
import os
from unittest import TestCase
from base64 import b64encode

from mock import MagicMock, patch

from browserdebuggertools.chrome.interface import ChromeInterface
from browserdebuggertools.exceptions import DevToolsTimeoutException

MODULE_PATH = "browserdebuggertools.chrome.interface."


class MockChromeInterface(ChromeInterface):

    def __init__(self, port, timeout=30, domains=None):
        self.timeout = timeout
        self._socket_handler = MagicMock()


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


@patch(MODULE_PATH + "SocketHandler._setup_websocket", MagicMock())
@patch(MODULE_PATH + "SocketHandler._get_websocket_url", MagicMock())
class Test_ChromeInterface_set_timeout(TestCase):

    def test_timeout_exception_raised(self):

        interface = ChromeInterface(0)
        interface._socket_handler._websocket.send = MagicMock()
        interface._socket_handler._websocket.recv = MagicMock(return_value=None)

        start = time.time()
        with self.assertRaises(DevToolsTimeoutException):
            with interface.set_timeout(3):
                interface.execute("Something", "Else")

        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 2.5)
        self.assertLessEqual(elapsed, 3.4)
