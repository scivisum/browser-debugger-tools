from unittest import TestCase

from mock import MagicMock, patch

from browserdebuggertools.eventhandlers import PageLoadEventHandler, JavascriptDialogEventHandler
from browserdebuggertools.exceptions import DomainNotEnabledError, JavascriptDialogNotFoundError

MODULE_PATH = "browserdebuggertools.eventhandlers."


class PageLoadEventHandlerTest(TestCase):

    def setUp(self):
        self.event_handler = PageLoadEventHandler(socket_handler=MagicMock())


class Test_PageLoadEventHandler_handle(PageLoadEventHandlerTest):

    def test_url_change(self):
        mock_url = "url.com"
        mock_message = {"method": "Page.navigatedWithinDocument", "params": {"url": mock_url}}

        self.event_handler.handle(mock_message)

        self.assertEqual(mock_url, self.event_handler._url)

    def test_page_change(self):
        mock_message = {"method": "Page.domContentEventFired", "params": {}}

        self.event_handler.handle(mock_message)

        self.assertIsNone(self.event_handler._url)
        self.assertIsNone(self.event_handler._root_node_id)


class Test_PageLoadEventHandler_check_page_load(PageLoadEventHandlerTest):

    def test_Page_domain_not_enabled(self):
        mock_doc_url, mock_root_node_id = "doc.url", 999
        mock_response = {"root": {"documentURL": mock_doc_url, "backendNodeId": mock_root_node_id}}
        self.event_handler._socket_handler.get_events.side_effect = DomainNotEnabledError
        self.event_handler._socket_handler.execute.return_value = mock_response

        self.event_handler.check_page_load()

        self.assertEqual(mock_doc_url, self.event_handler._url)
        self.assertEqual(mock_root_node_id, self.event_handler._root_node_id)


class JavascriptDialogEventHandlerTest(TestCase):

    def setUp(self):
        self.event_handler = JavascriptDialogEventHandler(socket_handler=MagicMock())


@patch(MODULE_PATH + "JavascriptDialog", MagicMock())
class Test_JavascriptDialogEventHandler_handle(JavascriptDialogEventHandlerTest):

    def test_dialog_opened(self):
        mock_message = {"method": "Page.javascriptDialogOpening", "params": {}}

        self.event_handler.handle(mock_message)

        self.assertIsNotNone(self.event_handler._dialog)

    def test_dialog_closed(self):
        mock_message = {"method": "Page.javascriptDialogClosed", "params": {}}
        self.event_handler._dialog = MagicMock(is_handled=False)

        self.event_handler.handle(mock_message)

        self.assertTrue(self.event_handler._dialog.is_handled)


class Test_JavascriptDialogEventHandler_get_opened_javascript_dialog(
    JavascriptDialogEventHandlerTest
):

    def test_unhandled_dialog(self):
        self.event_handler._dialog = mock_dialog = MagicMock(is_handled=False)

        self.assertEqual(mock_dialog, self.event_handler.get_opened_javascript_dialog())

    def test_no_dialog(self):
        self.event_handler._dialog = None

        with self.assertRaises(JavascriptDialogNotFoundError):
            self.event_handler.get_opened_javascript_dialog()

    def test_handled_dialog(self):
        self.event_handler._dialog = MagicMock(is_handled=True)

        with self.assertRaises(JavascriptDialogNotFoundError):
            self.event_handler.get_opened_javascript_dialog()
