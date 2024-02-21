import re
from unittest import TestCase
from unittest.mock import patch, MagicMock

from browserdebuggertools.chrome.interface import ChromeInterface
from browserdebuggertools.exceptions import TargetNotFoundError, JavascriptError

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
            "Runtime", "evaluate",
            {
                "expression": "document.readyState",
                "foo": "baa", "x": 2, "returnByValue": True
            }
        )
        self.assertEqual(mock_result, result)

    def test_value_error(self, mockExecute):
        mock_result = MagicMock()
        mockExecute.return_value = {"id": 1, "result": {"value": mock_result}}

        with self.assertRaisesRegex(
                ValueError,
                re.escape(
                    "If want returnByValue as False, "
                    "use .execute('runtime', 'evaluate', "
                    "{'expression': 'document.readyState', returnByValue: False}) directly"
                )
        ):
            self.interface.execute_javascript(
                "document.readyState", returnByValue=False
            )

        self.assertFalse(mockExecute.called)

    def test_javascript_error(self, mockExecute):
        mockExecute.return_value = {
            "result": {
                "type": "object",
                "subtype": "error",
                "className": "SyntaxError",
                "description": "SyntaxError: Unexpected identifier 'and'",
                "objectId": "1297274167796877720.2.1"
            }
        }

        with self.assertRaises(JavascriptError):
            self.interface.execute_javascript("garbage and stuff", foo="baa", x=2)

        mockExecute.assert_called_once_with(
            "Runtime", "evaluate",
            {
                "expression": "garbage and stuff",
                "foo": "baa", "x": 2, "returnByValue": True
            }
        )


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


class Test_ChromeInterface_service_worker(ChromeInterfaceTest):

    def test(self):
        service_worker = MagicMock()
        self.interface._targets_manager.get_service_worker.return_value = service_worker

        with self.interface.service_worker("myExtension.json") as service_worker:
            service_worker.attach.assert_called_once_with()
            self.assertFalse(service_worker.detach.called)

        service_worker.detach.assert_called_once_with()