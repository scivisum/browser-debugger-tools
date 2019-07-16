from unittest import TestCase

from mock import patch, MagicMock

from browserdebuggertools.chrome.interface import ChromeInterface, DevToolsTimeoutException
from browserdebuggertools.exceptions import ResultNotFoundError, DomainNotFoundError

MODULE_PATH = "browserdebuggertools.chrome.interface."


class MockChromeInterface(ChromeInterface):

    def __init__(self, port, timeout=30, domains=None):
        self.timeout = timeout
        self._socket_handler = MagicMock()


class ChromeInterfaceTest(TestCase):

    def setUp(self):
        self.interface = MockChromeInterface(1234)


@patch(MODULE_PATH + "time")
class Test_ChromeInterface_wait_for_result(ChromeInterfaceTest):

    def test(self, time):
        mock_result = MagicMock()
        self.interface._socket_handler.find_result.side_effect = [mock_result]
        time.time.side_effect = [1, 2, 3]

        result = self.interface.wait_for_result(1)

        self.assertEqual(mock_result, result)

    def test_wait(self, time):
        mock_result = MagicMock()
        self.interface._socket_handler.find_result.side_effect = [ResultNotFoundError, mock_result]
        time.time.side_effect = [1, 2, 3]

        result = self.interface.wait_for_result(1)

        self.assertEqual(mock_result, result)

    def test_timed_out(self, time):
        self.interface.timeout = 2
        self.interface._socket_handler.find_result.side_effect = [
            ResultNotFoundError, ResultNotFoundError
        ]
        time.time.side_effect = [1, 2, 3]

        with self.assertRaises(DevToolsTimeoutException):
            self.interface.wait_for_result(1)


@patch(MODULE_PATH + "ChromeInterface.execute", MagicMock())
class Test_ChromeInterface_enable_domain(ChromeInterfaceTest):

    def test_invalid_domain(self):
        self.interface.execute.return_value = {"id": 1, "error": MagicMock()}

        with self.assertRaises(DomainNotFoundError):
            self.interface.enable_domain("InvalidDomain")


@patch(MODULE_PATH + "ChromeInterface.execute", MagicMock())
class Test_ChromeInterface_execute_javascript(ChromeInterfaceTest):

    def test(self):
        mock_result = MagicMock()
        self.interface.execute.return_value = {"id": 1, "result": {"value": mock_result}}

        result = self.interface.execute_javascript("document.readyState")

        self.assertEqual(mock_result, result)
