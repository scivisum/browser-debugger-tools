import os
import subprocess
import sys
import shutil
import time
import unittest
import tempfile

from requests import ConnectionError

from tests.e2etests.testsite.start import Server as TestSiteServer
from browserdebuggertools.utils.lib import get_free_port
from browserdebuggertools.chrome.interface import ChromeInterface
from browserdebuggertools.chrome.interface import DevToolsTimeoutException


BROWSER_PATH = os.environ.get("DEFAULT_CHROME_BROWSER_PATH", "/opt/google/chrome/chrome")
TEMP = tempfile.gettempdir()


class ChromeInterfaceTest(unittest.TestCase):

    testSite = None
    browser = None
    browser_cache_dir = TEMP + "/ChromeInterfaceTest_%s" % (time.time() * 1000)
    devtools_client = None

    @classmethod
    def setUpClass(cls):

        cls.testSite = TestSiteServer()
        cls.testSite.start()

        devtools_port = get_free_port()

        cls.browser = subprocess.Popen([
            BROWSER_PATH,
            "--remote-debugging-port=%s" % devtools_port,
            "--headless",
            "--user-data-dir=%s" % cls.browser_cache_dir
        ])

        start = time.time()
        while start - time.time() < 30:

            time.sleep(3)

            try:
                cls.devtools_client = ChromeInterface(devtools_port)
                break

            except ConnectionError:
                pass

        else:
            raise Exception("Devtools client could not connect to browser")

    def _assert_dom_complete(self, timeout=10):

        domComplete = False

        start = time.time()
        while (time.time() - start) < timeout:
            messages = self.devtools_client.pop_messages()
            for message in messages:
                if message.get("method") == "Page.domContentEventFired":
                    domComplete = True
                    break

        self.assertTrue(domComplete)

    @classmethod
    def tearDownClass(cls):
        cls.devtools_client.ws.close()
        cls.browser.terminate()
        shutil.rmtree(cls.browser_cache_dir)
        cls.testSite.stop()


class Test_ChromeInterface_take_screenshot(ChromeInterfaceTest):

    def setUp(self):

        self.file_path = "/tmp/screenshot%s.png" % int(time.time()*1000000)
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def test_take_screenshot_dom_complete(self):

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.devtools_client.take_screenshot(self.file_path)
        self.assertTrue(os.path.exists(self.file_path))
        self.assertEqual(5402, os.path.getsize(self.file_path))

    def test_take_screenshot_incomplete_main_exchange(self):
        with self.devtools_client.run_async():
            self.devtools_client.navigate(
                url="http://localhost:%s?main_exchange_response_time=10" % self.testSite.port
            )
        self.devtools_client.take_screenshot(self.file_path)
        self.assertTrue(os.path.exists(self.file_path))
        self.assertEqual(5402, os.path.getsize(self.file_path))

    def test_take_screenshot_incomplete_head_component(self):

        with self.devtools_client.run_async():
            self.devtools_client.navigate(
                url="http://localhost:%s?head_component_response_time=30"
                    % self.testSite.port
            )

        time.sleep(3)

        with self.devtools_client.set_timeout(10):

            self.assertRaises(
                DevToolsTimeoutException,
                lambda: self.devtools_client.take_screenshot(self.file_path)
            )

    def tearDown(self):
        if os.path.exists(self.file_path):
            os.remove(self.file_path)


class Test_ChromeInterface_get_document_readystate(ChromeInterfaceTest):

    def test_get_ready_state_dom_complete(self):

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.assertEqual("complete", self.devtools_client.get_document_readystate())

    def test_take_screenshot_incomplete_main_exchange(self):
        with self.devtools_client.run_async():
            self.devtools_client.navigate(
                url="http://localhost:%s?main_exchange_response_time=10" % self.testSite.port
            )
        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.assertEqual("complete", self.devtools_client.get_document_readystate())

    def test_take_screenshot_incomplete_head_component(self):

        with self.devtools_client.run_async():
            self.devtools_client.navigate(
                url="http://localhost:%s?head_component_response_time=30"
                    % self.testSite.port
            )

        time.sleep(3)

        with self.devtools_client.set_timeout(10):

            self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
            self._assert_dom_complete()
            self.assertEqual("complete", self.devtools_client.get_document_readystate())


if __name__ == "__main__":
    unittest.main()
