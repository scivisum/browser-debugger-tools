from unittest import TestCase

from mock import MagicMock

from browserdebuggertools.exceptions import DevToolsException
from browserdebuggertools.models import JavascriptDialog


class Test_Javascript_Dialog__handle(TestCase):

    def setUp(self):
        mock_message = {
            "message": "",
            "type": "",
            "url": "",
            "hasBrowserHandler": "",
        }
        self.javascript_dialog = JavascriptDialog(MagicMock(), mock_message)

    def test_already_handled(self):
        self.javascript_dialog.is_handled = True

        with self.assertRaises(DevToolsException):
            self.javascript_dialog._handle()

    def test_not_handled(self):
        self.javascript_dialog.is_handled = False

        self.javascript_dialog._handle()

        self.assertTrue(self.javascript_dialog.is_handled)
