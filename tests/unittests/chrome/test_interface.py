from unittest import TestCase

from unittest.mock import patch, MagicMock

from browserdebuggertools.chrome.interface import ChromeInterface
from browserdebuggertools.exceptions import TargetNotFoundError

MODULE_PATH = "browserdebuggertools.chrome.interface."


class ChromeInterfaceTest(TestCase):

    def setUp(self):
        with patch(MODULE_PATH + "TargetsManager", MagicMock()):
            self.interface = ChromeInterface(1234, "localhost", attach=False)


@patch(MODULE_PATH + "ChromeInterface.execute")
class Test_ChromeInterface_execute_javascript(ChromeInterfaceTest):

    def test(self, mockExecute):
        mock_result = MagicMock()
        mockExecute.return_value = {"id": 1, "result": {"value": mock_result}}

        result = self.interface.execute_javascript("document.readyState", foo="baa", x=2)

        mockExecute.assert_called_once_with(
            "Runtime", "evaluate", {"expression": "document.readyState", "foo": "baa", "x": 2}
        )
        self.assertEqual(mock_result, result)


class Test_ChromeInterface_switch_target(ChromeInterfaceTest):

    def test_no_target_id_but_targets_exist(self):
        self.interface._targets_manager.targets = {
            "target_0":  MagicMock(id="target_0", type="extension"),
            "target_1": MagicMock(id="target_1", type="page"),
            "target_2":  MagicMock(id="target_2", type="extension")
        }

        self.interface.switch_target()

        self.interface._targets_manager.switch_target.assert_called_once_with("target_1")

    @patch(MODULE_PATH + "ChromeInterface.create_tab")
    def test_no_target_id_and_no_targets_exist(self, create_tab):
        self.interface._targets_manager.targets = {}

        self.interface.switch_target()

        create_tab.assert_called_once_with()
        self.interface._targets_manager.switch_target.assert_called_once_with(
            create_tab.return_value.id
        )

    def test_target_id_exists(self):
        self.interface._targets_manager.targets = {
            "target_0":  MagicMock(id="target_0", type="page"),
            "target_1": MagicMock(id="target_1", type="page"),
            "target_2":  MagicMock(id="target_2", type="page")
        }

        self.interface.switch_target("target_2")

        self.interface._targets_manager.switch_target.assert_called_once_with("target_2")

    def test_target_id_does_not_exist(self):
        self.interface._targets_manager.targets = {
            "target_0":  MagicMock(id="target_0", type="page"),
            "target_1": MagicMock(id="target_1", type="page"),
            "target_2":  MagicMock(id="target_2", type="page")
        }

        with self.assertRaises(TargetNotFoundError):
            self.interface.switch_target("target_3")
