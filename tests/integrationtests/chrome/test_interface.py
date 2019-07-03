import socket

import time
import os
import unittest
from base64 import b64encode

from mock import MagicMock, patch, call

from browserdebuggertools.chrome.interface import ChromeInterface, DevToolsTimeoutException


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
        interface = ChromeInterface(0)

        ws.send.assert_has_calls([
            call('{"id": 1, "method": "Page.enable", "params": {}}'),
            call('{"id": 2, "method": "Network.enable", "params": {}}'),
            call('{"id": 3, "method": "Runtime.enable", "params": {}}')
        ])

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

        exepected_bytes = bytes("hello_world".encode("utf-8"))
        execute.return_value = {"result": {"data": b64encode(exepected_bytes)}}
        interface = ChromeInterface(0)

        interface.take_screenshot(self.file_path)

        with open(self.file_path, "rb") as f:
            self.assertEqual(exepected_bytes, f.read())

    def tearDown(self):

        if os.path.exists(self.file_path):
            os.remove(self.file_path)


@patch("browserdebuggertools.chrome.interface.websocket", new=MagicMock())
@patch("browserdebuggertools.chrome.interface.requests", new=MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection")
class Test_ChromeInterface_set_timeout(unittest.TestCase):

    def test_timeout_exception_raised(self, _get_ws_connection):

        class MockWS(MagicMock):

            def __init__(self, *args, **kwargs):
                super(MockWS, self).__init__(*args, **kwargs)
                self.next_result_id = 0

            def recv(self):

                if self.next_result_id < 3:
                    self.next_result_id += 1
                return '{"result": {}, "id": %s}' % self.next_result_id

        ws = MockWS()
        _get_ws_connection.return_value = ws
        interface = ChromeInterface(0)

        start = time.time()
        with self.assertRaises(DevToolsTimeoutException):
            with interface.set_timeout(3):
                interface.execute("Something", "Else")

        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 2.9)
        self.assertLessEqual(elapsed, 3.1)

    @patch("browserdebuggertools.chrome.interface.ChromeInterface._wait_for_result")
    def test_no_timeout_exception_raise(self, _wait_for_result,  _get_ws_connection):

        ws = MagicMock()
        ws.recv.return_value = '{}'
        _get_ws_connection.return_value = ws
        interface = ChromeInterface(0)

        _wait_for_result.assert_has_calls([call()] * 3)

        with interface.set_timeout(None):
            interface.execute("Something", "Else")

        _wait_for_result.assert_has_calls([call()] * 3)


@patch("browserdebuggertools.chrome.interface.websocket", new=MagicMock())
@patch("browserdebuggertools.chrome.interface.requests", new=MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection")
class Test_ChromeInterface_pop_messages(unittest.TestCase):

    def test_pop_expected_messages(self, _get_ws_connection):

        expected_messages = [
            '{"result": {}, "id": 1}',
            '{"result": {}, "id": 2}',
            '{"result": {}, "id": 3}',
            '{"method": "Network.requestWillbeSent", "params": {"key1": "value1"}}',
            '{"result": {}, "id": 4}',
            '{"method": "Network.requestWillbeSent", "params": {"key2": "value2"}}',
            '{"result": {}, "id": 5}',
            '{"method": "Network.requestWillbeSent", "params": {"key3": "value3"}}',
            '{"result": {}, "id": 6}',
            '{"method": "Network.requestWillbeSent", "params": {"key4": "value4"}}',
            socket.error()
        ]

        ws = MagicMock()
        ws.recv.side_effect = expected_messages
        _get_ws_connection.return_value = ws
        interface = ChromeInterface(0)

        for _ in range(3):
            interface.execute("Something", "Else")

        messages = interface.pop_messages()

        self.assertEqual([
            {"result": {}, "id": 1},
            {"result": {}, "id": 2},
            {"result": {}, "id": 3},
            {"method": "Network.requestWillbeSent", "params": {"key1": "value1"}},
            {"result": {}, "id": 4},
            {"method": "Network.requestWillbeSent", "params": {"key2": "value2"}},
            {"result": {}, "id": 5},
            {"method": "Network.requestWillbeSent", "params": {"key3": "value3"}},
            {"result": {}, "id": 6},
            {"method": "Network.requestWillbeSent", "params": {"key4": "value4"}},
        ], messages)

        self.assertEqual([], interface._messages)
        self.assertEqual(6, interface._next_result_id)


if __name__ == "__main__":
    unittest.main()
