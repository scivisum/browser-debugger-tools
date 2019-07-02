import time
import os
import unittest
from base64 import b64encode

from mock import MagicMock, patch

from browserdebuggertools.chrome.interface import ChromeInterface


@patch("browserdebuggertools.chrome.interface.websocket", new=MagicMock())
@patch("browserdebuggertools.chrome.interface.requests", new=MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection")
class Test_ChromeInterface__init__(unittest.TestCase):

    def test_namespace_enabled(self, _get_ws_connection):

        ws = MagicMock()
        ws.recv.side_effect = ['{"result": {}, "id": 1}', '{}', '{}',
                               '{"result": {}, "id": 2}', '{}', '{}', '{}', '{}',
                               '{"result": {}, "id": 3}', '{}']
        _get_ws_connection.return_value = ws
        interface = ChromeInterface(0, enable_name_spaces=["Network", "Page", "Runtime"])

        self.assertEqual(9, ws.recv.call_count)
        self.assertEqual(3, interface._next_result_id)


@patch("browserdebuggertools.chrome.interface.ChromeInterface.__init__", new=MagicMock(
    return_value=None
))
@patch("browserdebuggertools.chrome.interface.ChromeInterface.execute")
class Test_ChromeInterface_take_screenshot(unittest.TestCase):

    def setUp(self):

        self.file_path = "/tmp/%s" % time.time()

    def test_take_screenshot(self, execute):

        exepected_bytes = bytes("hello_world")
        execute.return_value = {"result": {"data": b64encode(exepected_bytes)}}
        interface = ChromeInterface(0)

        interface.take_screenshot(self.file_path)

        with open(self.file_path, "rb") as f:
            self.assertEqual(exepected_bytes, f.read())

    def tearDown(self):

        if os.path.exists(self.file_path):
            os.remove(self.file_path)


if __name__ == "__main__":
    unittest.main()
