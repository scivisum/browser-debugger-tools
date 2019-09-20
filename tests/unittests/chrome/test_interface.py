from unittest import TestCase

from mock import patch, MagicMock

from browserdebuggertools.chrome.interface import ChromeInterface

MODULE_PATH = "browserdebuggertools.chrome.interface."


class MockChromeInterface(ChromeInterface):

    def __init__(self, port, timeout=30, domains=None):
        self.timeout = timeout
        self._socket_handler = MagicMock()


class ChromeInterfaceTest(TestCase):

    def setUp(self):
        self.interface = MockChromeInterface(1234)


@patch(MODULE_PATH + "ChromeInterface.execute", MagicMock())
class Test_ChromeInterface_execute_javascript(ChromeInterfaceTest):

    def test(self):
        mock_result = MagicMock()
        self.interface.execute.return_value = {"id": 1, "result": {"value": mock_result}}

        result = self.interface.execute_javascript("document.readyState")

        self.assertEqual(mock_result, result)
