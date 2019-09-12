import os
import subprocess
import shutil
import time
import tempfile
from unittest import TestCase

from requests import ConnectionError

from browserdebuggertools.exceptions import DevToolsTimeoutException
from tests.e2etests.testsite.start import Server as TestSiteServer
from browserdebuggertools.utils import get_free_port
from browserdebuggertools.chrome.interface import ChromeInterface


BROWSER_PATH = os.environ.get("DEFAULT_CHROME_BROWSER_PATH", "/opt/google/chrome/chrome")
TEMP = tempfile.gettempdir()


class ChromeInterfaceTest(object):

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
            "--no-default-browser-check",
            "--headless" if cls.headless else "",
            "--user-data-dir=%s" % cls.browser_cache_dir,
            "--no-first-run",
        ])

        start = time.time()
        while start - time.time() < 30:

            time.sleep(3)

            try:
                cls.devtools_client = ChromeInterface(devtools_port)
                cls.devtools_client.enable_domain("Page")
                break

            except ConnectionError:
                pass

        else:
            raise Exception("Devtools client could not connect to browser")

    def _assert_dom_complete(self, timeout=10):

        domComplete = False
        start = time.time()
        while (time.time() - start) < timeout:
            page_events = self.devtools_client.get_events("Page")
            for event in page_events:
                if event.get("method") == "Page.domContentEventFired":
                    domComplete = True
                    break

        self.assertTrue(domComplete)

    def _get_responses_received(self):

        responses_received = []
        for event in self.devtools_client.get_events("Network"):
            if event.get("method") == "Network.responseReceived":
                responses_received.append(event["params"]["response"]["status"])
        return responses_received

    @classmethod
    def tearDownClass(cls):
        cls.devtools_client.quit()
        cls.browser.kill()
        time.sleep(3)
        shutil.rmtree(cls.browser_cache_dir)
        cls.testSite.stop()


class HeadedChromeInterfaceTest(ChromeInterfaceTest):

    headless = False


class HeadlessChromeInterfaceTest(ChromeInterfaceTest):

    headless = True


class ChromeInterface_take_screenshot(object):

    def setUp(self):

        self.file_path = "/tmp/screenshot%s.png" % int(time.time()*1000000)
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def test_take_screenshot_dom_complete(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.devtools_client.take_screenshot(self.file_path)
        self.assertTrue(os.path.exists(self.file_path))
        self.assertTrue(os.path.getsize(self.file_path) >= 5000)

    def test_take_screenshot_incomplete_main_exchange(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.navigate(
            url="http://localhost:%s?main_exchange_response_time=10" % self.testSite.port
        )
        self.devtools_client.take_screenshot(self.file_path)
        self.assertTrue(os.path.exists(self.file_path))
        self.assertTrue(os.path.getsize(self.file_path) >= 5000)

    def test_take_screenshot_incomplete_head_component(self):

        assert isinstance(self, ChromeInterfaceTest)

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


class Test_ChromeInterface_take_screenshot_headed(
    HeadedChromeInterfaceTest, ChromeInterface_take_screenshot, TestCase
):
    pass


class Test_ChromeInterface_take_screenshot_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_take_screenshot, TestCase
):
    pass


class ChromeInterface_get_document_readystate(object):

    def test_get_ready_state_dom_complete(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.assertEqual("complete", self.devtools_client.get_document_readystate())

    def test_take_screenshot_incomplete_main_exchange(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.navigate(
            url="http://localhost:%s?main_exchange_response_time=10" % self.testSite.port
        )
        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.assertEqual("complete", self.devtools_client.get_document_readystate())

    def test_take_screenshot_incomplete_head_component(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.navigate(
            url="http://localhost:%s?head_component_response_time=30"
                % self.testSite.port
        )

        time.sleep(3)

        with self.devtools_client.set_timeout(10):

            self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
            self._assert_dom_complete()
            self.assertEqual("complete", self.devtools_client.get_document_readystate())


class Test_ChromeInterface_get_document_readystate_headed(
    HeadedChromeInterfaceTest, ChromeInterface_get_document_readystate, TestCase
):
    pass


class Test_ChromeInterface_get_document_readystate_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_get_document_readystate, TestCase
):
    pass


class ChromeInterface_emulate_network_conditions(object):

    def waitForEventWithMethod(self, method, timeout=30):

        assert isinstance(self, ChromeInterfaceTest)

        start = time.time()
        while (time.time() - start) < timeout:
            for event in self.devtools_client.get_events(method.split(".")[0]):
                if event.get("method") == method:
                    return True
        return False

    def test_took_expected_time(self):

        upload = 1000000000000  # 1 terabytes / second (no limit)
        download = 100000  # 100 kilobytes / second

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.enable_domain("Network")
        self.devtools_client.emulate_network_conditions(1, download, upload)

        # Page has a default of 1 megabyte response body
        self.devtools_client.navigate(url="http://localhost:%s/big_body"
                                      % self.testSite.port)
        self.assertTrue(self.waitForEventWithMethod("Network.responseReceived"))
        # We have received the response header, now measure how long it takes to download the
        # response body. It should take approximately 10 seconds.
        start = time.time()
        self.assertTrue(self.waitForEventWithMethod("Network.loadingFinished"))
        time_taken = time.time() - start
        self.assertIn(int(round(time_taken)), [10, 11])  # Headed browser is a bit slower


class Test_ChromeInterface_emulate_network_conditions_headed(
    HeadedChromeInterfaceTest, ChromeInterface_emulate_network_conditions, TestCase
):
    pass


class Test_ChromeInterface_emulate_network_conditions_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_emulate_network_conditions, TestCase
):
    pass


class ChromeInterface_set_basic_auth(object):

    def test_standard_auth_page(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.enable_domain("Network")
        url = "http://username:password@localhost:%s/auth_challenge" % self.testSite.port
        self.devtools_client.navigate(url=url)
        self._assert_dom_complete()

        responses_received = self._get_responses_received()

        self.assertTrue(len(responses_received) >= 2)  # Headed browser creates extra requests
        self.assertIn(200, responses_received)
        self.assertNotIn(401, responses_received)  # Devtools genuinely doesn't report these


class Test_ChromeInterface_set_baic_auth_headed(
    HeadedChromeInterfaceTest, ChromeInterface_set_basic_auth, TestCase
):
    pass


class Test_ChromeInterface_set_baic_auth_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_set_basic_auth, TestCase
):
    pass


class ChromeInterface_connection_unexpectadely_closed(object):

    def test(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.enable_domain("Network")
        self.devtools_client.quit()

        url = "http://localhost:%s" % self.testSite.port
        self.devtools_client.navigate(url=url)

        self._assert_dom_complete()

        responses_received = self._get_responses_received()
        self.assertIn(200, responses_received)


class Test_ChromeInterface_connection_unexpectadely_closed_headed(
    HeadedChromeInterfaceTest, ChromeInterface_connection_unexpectadely_closed, TestCase
):
    pass


class Test_ChromeInterface_connection_unexpectadely_closed_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_connection_unexpectadely_closed, TestCase
):
    pass
