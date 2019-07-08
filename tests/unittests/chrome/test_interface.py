import unittest
import socket

from mock import patch, MagicMock, call

from browserdebuggertools.chrome.interface import ChromeInterface, DevToolsTimeoutException

@patch("browserdebuggertools.chrome.interface.ChromeInterface.enable_domain")
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection", MagicMock())
class Test_ChromeInterface__init__(unittest.TestCase):

    def test_default_domains_are_set(self, enable_domain):

        call_list = [
            call("Page"),
            call("Network"),
            call("Runtime")
        ]

        ChromeInterface(1234)

        self.assertListEqual(call_list, enable_domain.call_args_list)

    def test_extra_domains_set(self, enable_domain):

        call_list = [
            call("IO"),
            call("Page"),
            call("Network"),
            call("Runtime"),
        ]

        ChromeInterface(1234, domains=["IO"])

        self.assertListEqual(call_list, enable_domain.call_args_list)

@patch(
    "browserdebuggertools.chrome.interface.ChromeInterface._read_socket",
    MagicMock(return_value=False)
)
@patch("browserdebuggertools.chrome.interface.ChromeInterface.enable_domain", MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection", MagicMock())
class Test_ChromeInterface_popMessages(unittest.TestCase):

    def test_cache_has_been_emptied(self):

        message = {"random": "message"}

        interface = ChromeInterface(1234)
        interface._messages = [message]

        interface.pop_messages()

        self.assertFalse(interface._messages)

    def test_messages_retrieved(self):

        message = {"random": "message"}

        interface = ChromeInterface(1234)
        interface._messages = [message, message, message]

        response = interface.pop_messages()

        self.assertListEqual([message] * 3, response)


@patch("browserdebuggertools.chrome.interface.json")
@patch("browserdebuggertools.chrome.interface.ChromeInterface._wait_for_result")
@patch("browserdebuggertools.chrome.interface.ChromeInterface.enable_domain", MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection", MagicMock())
class Test_ChromeInterface_execute(unittest.TestCase):

    def test_parameter_convertion_to_protocol(self, wait_for_result, json):

        args = {"url": "http://test.com"}

        interface = ChromeInterface(1234)

        interface.execute("Page", "navigate", args=args)

        json.dumps.assert_called_once_with(
            {'params': args, 'id': 1, 'method': 'Page.navigate'}, sort_keys=True
        )

    def test_no_args(self, wait_for_result, json):

        interface = ChromeInterface(1234)

        interface.execute("Page", "navigate")

        json.dumps.assert_called_once_with(
            {'params': {}, 'id': 1, 'method': 'Page.navigate'}, sort_keys=True
        )

    def test_message_id_increments_correctly(self, wait_for_result, json):

        call_list = [
            call({'params': {}, 'id': 1, 'method': 'Page.navigate'}, sort_keys=True),
            call({'params': {}, 'id': 2, 'method': 'Page.navigate'}, sort_keys=True),
        ]

        interface = ChromeInterface(1234)

        for i in range(2):
            interface.execute("Page", "navigate")

        self.assertListEqual(call_list, json.dumps.call_args_list)

    def test_async(self, wait_for_result, json):

        interface = ChromeInterface(1234)

        interface.async = True

        response = interface.execute("Page", "navigate")

        self.assertIsNone(response)

    def test_return_call(self, wait_for_result, json):  # This needs re-thinking.

        interface = ChromeInterface(1234)

        response = interface.execute("Page", "navigate")

        self.assertEqual(wait_for_result(), response)


@patch("browserdebuggertools.chrome.interface.time")
@patch("browserdebuggertools.chrome.interface.ChromeInterface._read_socket")
@patch("browserdebuggertools.chrome.interface.ChromeInterface.enable_domain", MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection", MagicMock())
class Test_ChromeInterface__wait_for_result(unittest.TestCase):

    def test(self, read_socket, time):

        time.time.side_effect = [1, 2, 3]

        read_socket.return_value = {"result": "text", "id": 1}

        interface = ChromeInterface(1234)

        interface._next_result_id = 1

        result = interface._wait_for_result()

        self.assertEqual({"result": "text", "id": 1}, result)

    def test_timed_out(self, read_socket, time):

        time.time.side_effect = [1, 50]

        interface = ChromeInterface(1234)

        with self.assertRaises(DevToolsTimeoutException):
            interface._wait_for_result()


@patch("browserdebuggertools.chrome.interface.json")
@patch("browserdebuggertools.chrome.interface.ChromeInterface.enable_domain", MagicMock())
@patch("browserdebuggertools.chrome.interface.ChromeInterface._get_ws_connection", MagicMock())
class Test_ChromeInterface__read_socket(unittest.TestCase):

    def test_message_retrieved(self, json):

        response = {"result": "text"}
        interface = ChromeInterface(1234)
        interface.ws.recv.return_value = response
        json.loads.return_value = response

        result = interface._read_socket()

        json.loads.assert_called_once_with(response)
        self.assertEqual(response, result)

    def test_nothing_to_retrieve(self, json):

        interface = ChromeInterface(1234)
        interface.ws.recv.side_effect = [socket.error()]

        self.assertIsNone(interface._read_socket())

    def test_message_gets_cached(self, json):

        response = {"result": "text"}
        json.loads.return_value = response

        interface = ChromeInterface(1234)

        interface._read_socket()

        self.assertEqual(response, interface._messages[0])
