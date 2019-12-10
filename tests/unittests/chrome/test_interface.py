from unittest import TestCase

from mock import patch, MagicMock, call

from browserdebuggertools.chrome.interface import ChromeInterface
from browserdebuggertools.exceptions import ResourceNotFoundError, IFrameNotFoundError

MODULE_PATH = "browserdebuggertools.chrome.interface."


class MockChromeInterface(ChromeInterface):

    def __init__(self, port, timeout=30, domains=None):
        self.timeout = timeout
        self._socket_handler = MagicMock()
        self._node_map = {}


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


class Test_ChromeInterface__get_iframe_html(ChromeInterfaceTest):

    def test_exception_then_ok(self):

        html = "<html></html>"
        self.interface._get_iframe_backend_node_id = MagicMock()
        self.interface._get_outer_html = MagicMock(
            side_effect=[ResourceNotFoundError(), html]
        )

        self.assertEqual(html,  self.interface._get_iframe_html("//iframe"))
        self.interface._get_iframe_backend_node_id._assert_has_calls([
            call("//iframe"), call("//iframe")
        ])

    def test_exception_then_exception(self):

        self.interface._get_iframe_backend_node_id = MagicMock()
        self.interface._get_outer_html = MagicMock(
            side_effect=[ResourceNotFoundError(), ResourceNotFoundError()]
        )
        with self.assertRaises(IFrameNotFoundError):
            self.interface._get_iframe_html("//iframe")


class Test_ChromeInterface__get_iframe_backend_node_id(ChromeInterfaceTest):

    def test_already_cached(self):

        self.interface._node_map = {"//iframe": 5}
        self.assertEqual(5, self.interface._get_iframe_backend_node_id("//iframe"))

    def test_not_already_cached(self):

        node_info = {
            "node": {
                "contentDocument": {
                    "backendNodeId": 10
                }
            }
        }
        self.interface._get_info_for_first_matching_node = MagicMock(return_value=node_info)
        self.interface._node_map = {}

        self.assertEqual(10, self.interface._get_iframe_backend_node_id("//iframe"))
        self.assertEqual({"//iframe": 10}, self.interface._node_map)

    def test_node_found_but_not_an_iframe(self):

        node_info = {"node": {}}
        self.interface._get_info_for_first_matching_node = MagicMock(return_value=node_info)

        with self.assertRaises(IFrameNotFoundError):
            self.interface._get_iframe_backend_node_id("//iframe")

    def test_node_not_found(self):

        self.interface._get_info_for_first_matching_node = MagicMock(
            side_effect=ResourceNotFoundError()
        )
        with self.assertRaises(IFrameNotFoundError):
            self.interface._get_iframe_backend_node_id("//iframe")


class Test_ChromeInterface__get_info_for_first_matching_node(ChromeInterfaceTest):

    def test_no_matches(self):

        self.interface._perform_search = MagicMock(return_value={"resultCount": 0})

        with self.assertRaises(ResourceNotFoundError):
            self.interface._get_info_for_first_matching_node("//iframe")

    def test_ok(self):

        node_info = MagicMock()

        self.interface._perform_search = MagicMock(return_value={
            "resultCount": 1, "searchId": 100
        })
        self.interface._get_search_results = MagicMock()
        self.interface._discard_search = MagicMock()
        self.interface._describe_node = MagicMock(return_value=node_info)

        self.assertEqual(
            node_info,
            self.interface._get_info_for_first_matching_node("//iframe")
        )
