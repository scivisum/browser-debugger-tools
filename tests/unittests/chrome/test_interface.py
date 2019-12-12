from unittest import TestCase

from mock import patch, MagicMock, call

from browserdebuggertools.chrome.interface import ChromeInterface, _DOMManager
from browserdebuggertools.exceptions import ResourceNotFoundError

MODULE_PATH = "browserdebuggertools.chrome.interface."


class MockChromeInterface(ChromeInterface):

    def __init__(self, port, timeout=30, domains=None):
        self.timeout = timeout
        self._socket_handler = MagicMock()
        self._dom_manager = _DOMManager(self._socket_handler)


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


class DOMManagerTest(TestCase):

    def setUp(self):
        self.dom_manager = _DOMManager(MagicMock())


class Test_DOMManager_get_iframe_html(DOMManagerTest):

    def test_exception_then_ok(self):

        html = "<html></html>"
        self.dom_manager._get_iframe_backend_node_id = MagicMock()
        self.dom_manager.get_outer_html = MagicMock(
            side_effect=[ResourceNotFoundError(), html]
        )

        self.assertEqual(html,  self.dom_manager.get_iframe_html("//iframe"))
        self.dom_manager._get_iframe_backend_node_id._assert_has_calls([
            call("//iframe"), call("//iframe")
        ])

    def test_exception_then_exception(self):

        self.dom_manager._get_iframe_backend_node_id = MagicMock()
        self.dom_manager.get_outer_html = MagicMock(
            side_effect=[ResourceNotFoundError(), ResourceNotFoundError()]
        )
        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager.get_iframe_html("//iframe")


class Test_DOMManager__get_iframe_backend_node_id(DOMManagerTest):

    def test_already_cached(self):

        self.dom_manager._node_map = {"//iframe": 5}
        self.assertEqual(5, self.dom_manager._get_iframe_backend_node_id("//iframe"))

    def test_not_already_cached(self):

        node_info = {
            "node": {
                "contentDocument": {
                    "backendNodeId": 10
                }
            }
        }
        self.dom_manager._get_info_for_first_matching_node = MagicMock(return_value=node_info)
        self.dom_manager._node_map = {}

        self.assertEqual(10, self.dom_manager._get_iframe_backend_node_id("//iframe"))
        self.assertEqual({"//iframe": 10}, self.dom_manager._node_map)

    def test_node_found_but_not_an_iframe(self):

        node_info = {"node": {}}
        self.dom_manager._get_info_for_first_matching_node = MagicMock(return_value=node_info)

        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager._get_iframe_backend_node_id("//iframe")

    def test_node_not_found(self):

        self.dom_manager._get_info_for_first_matching_node = MagicMock(
            side_effect=ResourceNotFoundError()
        )
        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager._get_iframe_backend_node_id("//iframe")


class Test__DOMManager__get_node_ids(DOMManagerTest):

    def test_no_matches(self):
        self.dom_manager._discard_search = MagicMock()
        self.dom_manager._perform_search = MagicMock(
            return_value={"resultCount": 0, "searchId": "SomeID"}
        )

        with self.dom_manager._get_node_ids("//iframe") as node_ids:
            self.assertEqual([], node_ids)

        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_exception_getting_search_results(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 1, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(side_effect=ResourceNotFoundError())
        self.dom_manager._discard_search = MagicMock()

        with self.assertRaises(ResourceNotFoundError):
            with self.dom_manager._get_node_ids("//iframe"):
                pass

        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_exception_performing_search(self):

        self.dom_manager._perform_search = MagicMock(side_effect=ResourceNotFoundError())

        with self.assertRaises(ResourceNotFoundError):
            with self.dom_manager._get_node_ids("//iframe"):
                pass

    def test_resultCount_is_max(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 2, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(return_value={"nodeIds": [20, 30]})
        self.dom_manager._discard_search = MagicMock()

        with self.dom_manager._get_node_ids("//iframe", max_matches=2) as node_ids:
            pass

        self.dom_manager._get_search_results.assert_called_once_with("SomeID", 0, 2)
        self.assertEqual([20, 30], node_ids)
        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_resultCount_less_than_max(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 2, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(return_value={"nodeIds": [20, 30]})
        self.dom_manager._discard_search = MagicMock()

        with self.dom_manager._get_node_ids("//iframe", max_matches=3) as node_ids:
            pass

        self.dom_manager._get_search_results.assert_called_once_with("SomeID", 0, 2)
        self.assertEqual([20, 30], node_ids)
        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_resultCount_more_than_max(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 3, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(return_value={"nodeIds": [20, 30]})
        self.dom_manager._discard_search = MagicMock()

        with self.dom_manager._get_node_ids("//iframe", max_matches=2) as node_ids:
            pass

        self.assertEqual([20, 30], node_ids)
        self.dom_manager._get_search_results.assert_called_once_with("SomeID", 0, 2)
        self.dom_manager._discard_search.assert_called_once_with("SomeID")


class Test__get_info_for_first_matching_node(DOMManagerTest):

    def test_ok(self):

        self.dom_manager._get_node_ids = MagicMock()
        self.dom_manager._get_node_ids.return_value.__enter__.return_value = [10, 4, 6]
        expected_node_info = MagicMock()
        self.dom_manager._describe_node = MagicMock(return_value=expected_node_info)

        actual_node_info = self.dom_manager._get_info_for_first_matching_node("//iframe")

        self.assertEqual(expected_node_info, actual_node_info)
        self.dom_manager._describe_node.assert_called_once_with(10)

    def test_no_matches(self):

        self.dom_manager._get_node_ids = MagicMock()
        self.dom_manager._get_node_ids.return_value.__enter__.return_value = []

        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager._get_info_for_first_matching_node("//iframe")
