import json
import time
import os
from unittest import TestCase
from base64 import b64encode

from mock import MagicMock, patch

from browserdebuggertools.chrome.interface import ChromeInterface
from browserdebuggertools.exceptions import DevToolsTimeoutException
from browserdebuggertools.wssessionmanager import _WSMessageProducer
from tests.integrationtests.test_wssessionmanager import _DummyWebsocket

MODULE_PATH = "browserdebuggertools.chrome.interface."


class _SlowWebsocket(_DummyWebsocket):

    def recv(self):
        time.sleep(4)
        return super(_SlowWebsocket, self).recv()


class ChromeInterfaceTest(TestCase):

    WEBSOCKET_CLS = _DummyWebsocket

    def setUp(self):
        with patch.object(
            _WSMessageProducer, "_get_websocket", new=MagicMock(return_value=self.WEBSOCKET_CLS())
        ):
            self.interface = ChromeInterface(1234)


@patch(MODULE_PATH + "ChromeInterface.execute")
class Test_ChromeInterface_take_screenshot(ChromeInterfaceTest):

    def setUp(self):
        super(Test_ChromeInterface_take_screenshot, self).setUp()
        self.file_path = "/tmp/%s" % time.time()

    def test_take_screenshot(self, execute):
        exepected_bytes = bytes("hello_world".encode("utf-8"))
        execute.return_value = {"data": b64encode(exepected_bytes)}

        self.interface.take_screenshot(self.file_path)

        with open(self.file_path, "rb") as f:
            self.assertEqual(exepected_bytes, f.read())

    def tearDown(self):

        if os.path.exists(self.file_path):
            os.remove(self.file_path)


class Test_ChromeInterface_set_timeout(ChromeInterfaceTest):

    WEBSOCKET_CLS = _SlowWebsocket

    def test_timeout_exception_raised(self):
        start = time.time()
        with self.assertRaises(DevToolsTimeoutException):
            with self.interface.set_timeout(3):
                self.interface.execute("Something", "Else")

        elapsed = time.time() - start
        self.assertGreaterEqual(elapsed, 2.5)
        self.assertLessEqual(elapsed, 3.4)


class Test_ChromeInterface_get_url(ChromeInterfaceTest):

    def load_pages(self, count):
        mock_message = json.dumps({"method": "Page.domContentEventFired"})
        for _ in range(count):
            self.interface._session_manager._message_producer.ws.queue.append(mock_message)

    def load_js_pages(self, count):
        mock_message = json.dumps({"method": "Page.navigatedWithinDocument", "params": {"url": ""}})

        for _ in range(count):
            self.interface._session_manager._message_producer.ws.queue.append(mock_message)

    def test_page_enabled_cache(self):
        self.interface._session_manager._domains["Page"] = {}
        self.interface._session_manager._events["Page"] = []
        self.interface._session_manager._recv = MagicMock(return_value=None)
        self.interface._session_manager.execute = MagicMock()

        self.interface.get_url()
        self.interface.get_page_source()
        self.assertEqual(2, self.interface._session_manager.execute.call_count)
        self.interface.get_url()
        self.interface.get_page_source()
        self.assertEqual(3, self.interface._session_manager.execute.call_count)

        self.load_pages(2)
        self.assertEqual(3, self.interface._session_manager.execute.call_count)

        self.interface.get_url()
        self.interface.get_page_source()
        self.assertEqual(4, self.interface._session_manager.execute.call_count)

        self.load_js_pages(1)
        self.interface.get_url()
        self.assertEqual(4, self.interface._session_manager.execute.call_count)
        self.interface.get_page_source()
        self.assertEqual(5, self.interface._session_manager.execute.call_count)
