import os
import subprocess
import shutil
import time
import tempfile
from unittest import TestCase

from requests import ConnectionError

from browserdebuggertools.exceptions import (
    DevToolsException, DevToolsTimeoutException, JavascriptDialogNotFoundError,
    InvalidXPathError, ResourceNotFoundError
)
from browserdebuggertools.models import JavascriptDialog
from tests.e2etests.testsite.start import Server as TestSiteServer, env
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
        self.devtools_client.enable_domain("Page")
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

        with self.devtools_client.set_timeout(30):

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
        self.devtools_client.disable_domain("Page")


class Test_ChromeInterface_take_screenshot_headed(
    HeadedChromeInterfaceTest, ChromeInterface_take_screenshot, TestCase
):
    pass


class Test_ChromeInterface_take_screenshot_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_take_screenshot, TestCase
):
    pass


class ChromeInterface_get_document_readystate(object):

    def setUp(self):
        self.devtools_client.enable_domain("Page")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test_get_ready_state_dom_complete(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.assertEqual("complete", self.devtools_client.get_document_readystate())

    def test_take_screenshot_incomplete_main_exchange(self):

        assert isinstance(self, ChromeInterfaceTest)

        with self.devtools_client.set_timeout(30):
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

    def setUp(self):
        self.devtools_client.enable_domain("Network")

    def tearDown(self):
        self.devtools_client.disable_domain("Network")

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

    def setUp(self):
        self.devtools_client.enable_domain("Page")
        self.devtools_client.enable_domain("Network")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")
        self.devtools_client.disable_domain("Network")


    def test_standard_auth_page(self):

        assert isinstance(self, ChromeInterfaceTest)

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


class ChromeInterface_connection_unexpectedely_closed(object):

    def setUp(self):
        self.devtools_client.enable_domain("Page")
        self.devtools_client.enable_domain("Network")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")
        self.devtools_client.disable_domain("Network")

    def test(self):

        assert isinstance(self, ChromeInterfaceTest)

        self.devtools_client.quit()

        url = "http://localhost:%s" % self.testSite.port
        self.devtools_client.navigate(url=url)

        self._assert_dom_complete()

        responses_received = self._get_responses_received()
        self.assertIn(200, responses_received)


class Test_ChromeInterface_connection_unexpectadely_closed_headed(
    HeadedChromeInterfaceTest, ChromeInterface_connection_unexpectedely_closed, TestCase
):
    pass


class Test_ChromeInterface_connection_unexpectadely_closed_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_connection_unexpectedely_closed, TestCase
):
    pass


class ChromeInterface_cache_page(object):

    def setUp(self):
        self.devtools_client.enable_domain("Page")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")


    def test_with_page(self):

        assert isinstance(self, ChromeInterfaceTest)

        base_url = "http://localhost:%s/" % self.testSite.port

        simple_page = "<html><head></head><body><h1>Simple Page</h1></body></html>"

        fake_page_load = "<script>" \
                         "function fake_page_load(){" \
                         "document.getElementById('title-text').innerHTML= 'Fake Title';" \
                         "window.history.pushState('fake_page', 'Fake Title', '/fake_page');" \
                         "}" \
                         "</script>"

        simple_page_3 = '<html><head></head><body><h1 id="title-text">Simple Page 3</h1>%' \
                        's</body></html>' % fake_page_load
        fake_page = '<html><head></head><body><h1 id="title-text">Fake Title</h1>' \
                    '%s</body></html>' % fake_page_load

        # Test caching without page loads (low 3 calls)
        self.devtools_client.navigate(base_url + "simple_page")
        self.assertEqual(base_url + "simple_page", self.devtools_client.get_url())
        self.assertEqual(simple_page, _cleanupHTML(self.devtools_client.get_page_source()))
        self.assertEqual(base_url + "simple_page", self.devtools_client.get_url())
        self.assertEqual(simple_page, _cleanupHTML(self.devtools_client.get_page_source()))

        # Test caching with page loads (low 2 calls)
        self.devtools_client.navigate(base_url + "simple_page_2")
        self.devtools_client.navigate(base_url + "fake_load_page")
        self.assertEqual(base_url + "fake_load_page", self.devtools_client.get_url())
        self.assertEqual(simple_page_3, _cleanupHTML(self.devtools_client.get_page_source()))

        # Test caching with javascript page loads (low 1 call)
        self.devtools_client.execute_javascript("fake_page_load()")

        self.assertEqual(base_url + "fake_page", self.devtools_client.get_url())
        self.assertEqual(fake_page, _cleanupHTML(self.devtools_client.get_page_source()))


class Test_ChromeInterface_cache_page_headed(
    HeadedChromeInterfaceTest, ChromeInterface_cache_page, TestCase
):
    pass


class Test_ChromeInterface_cache_page_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_cache_page, TestCase
):
    pass


class ChromeInterface_test_javascript_dialogs(object):

    def setUp(self):
        self.load_javascript_dialog_page()
        self.devtools_client.enable_domain("Page")

    def get_dialog_if_present(self):
        try:
            self.devtools_client.get_opened_javascript_dialog()
            return True
        except JavascriptDialogNotFoundError:
            return False

    def tearDown(self):
        # beforeunload behaves differently in headless
        while self.get_dialog_if_present():
            self.devtools_client.get_opened_javascript_dialog().accept()

        self.devtools_client._socket_handler.execute_async("Runtime", "evaluate", {
            "expression": "reset()",
        })
        # Allow time for this message
        time.sleep(2)
        self.devtools_client.disable_domain("Page")

    def load_javascript_dialog_page(self):
        base_url = "http://localhost:%s/" % self.testSite.port
        self.url = base_url + "javascript_dialog_page"
        self.devtools_client.navigate(self.url)

    def open_dialog(self, dialog):
        self.devtools_client._socket_handler.execute_async("Runtime", "evaluate", {
            "expression": "open_%s()" % dialog, "userGesture": True,
        })
        # wait for the dialog to appear
        time.sleep(2)

    def test_no_dialog(self):
        with self.assertRaises(JavascriptDialogNotFoundError):
            self.devtools_client.get_opened_javascript_dialog()

    def check_dialog(self, type, message=None):
        self.open_dialog(type)

        dialog = self.devtools_client.get_opened_javascript_dialog()

        # Check the dialog
        self.assertTrue(dialog)
        self.assertEqual(dialog, self.devtools_client.get_opened_javascript_dialog())
        self.assertEqual(type, dialog.type)
        self.assertEqual(message, dialog.message)
        self.assertFalse(dialog.is_handled)
        if type != JavascriptDialog.PROMPT:
            self.assertFalse(dialog.default_prompt)
        self.assertEqual(self.url, dialog.url)

        # Test dismiss
        dialog.dismiss()

        self.open_dialog(type)
        dialog2 = self.devtools_client.get_opened_javascript_dialog()

        # Test not cached
        self.assertTrue(dialog.is_handled)

        # Test accept (putting this last so we don't refresh the page beforehand)
        dialog2.accept()

        # Test handled
        self.assertTrue(dialog2.is_handled)

        with self.assertRaises(DevToolsException):
            dialog2.dismiss()

    def test_alert(self):
        self.check_dialog(JavascriptDialog.ALERT, "Something important")

    def test_confirm(self):
        self.check_dialog(JavascriptDialog.CONFIRM, "Do you want to confirm?")

    def test_prompt(self):
        type = JavascriptDialog.PROMPT
        self.check_dialog(type, "Enter some text")

        # Test prompt special interactions
        self.open_dialog(type)

        dialog = self.devtools_client.get_opened_javascript_dialog()
        self.assertEqual("default text", dialog.default_prompt)

        dialog.accept_prompt("new text")
        self.assertEqual("new text", self.devtools_client.execute_javascript(
            "document.getElementById('prompt_result').innerHTML"
        ))

    def test_onbeforeunload(self):
        self.check_dialog(JavascriptDialog.BEFORE_UNLOAD, "")


class Test_ChromeInterface_test_javascript_dialogs_headed(
    HeadedChromeInterfaceTest, ChromeInterface_test_javascript_dialogs, TestCase
):
    pass


class Test_ChromeInterface_test_javascript_dialogs_headless(
    HeadlessChromeInterfaceTest, ChromeInterface_test_javascript_dialogs, TestCase
):
    pass


class Test_ChromeInterface_test_get_iframe_source_content(object):

    def setUp(self):

        assert isinstance(self, (ChromeInterfaceTest, TestCase))

        self.devtools_client.enable_domain("Page")

        self.devtools_client.navigate("http://localhost:%s/iframes" % self.testSite.port)

        self._assert_dom_complete()

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test_get_source_ok(self):

        assert isinstance(self, (ChromeInterfaceTest, TestCase))

        expected_main_page = _cleanupHTML(env.get_template('iframes.html').render())
        actual_main_page = _cleanupHTML(self.devtools_client.get_page_source())
        self.assertEqual(expected_main_page, actual_main_page)

        expected_frame_1 = _cleanupHTML(env.get_template('simple_page.html').render())
        actual_frame_1 = _cleanupHTML( self.devtools_client.get_iframe_source_content(
            "//iframe[@id='simple_page_frame']"
        ))
        self.assertEqual(expected_frame_1, actual_frame_1)

        # Check that we don't fail using invalid backend node id cache

        self.devtools_client.navigate("http://localhost:%s/iframes" % self.testSite.port)
        self._assert_dom_complete()

        expected_frame_1 = _cleanupHTML(env.get_template('simple_page.html').render())
        actual_frame_1 = _cleanupHTML(self.devtools_client.get_iframe_source_content(
            "//iframe[@id='simple_page_frame']"
        ))
        self.assertEqual(expected_frame_1, actual_frame_1)

        expected_frame_2 = _cleanupHTML(env.get_template('simple_page_2.html').render())
        actual_frame_2 = _cleanupHTML(self.devtools_client.get_iframe_source_content(
            "//iframe[@id='simple_page_frame_2']"
        ))
        self.assertEqual(expected_frame_2, actual_frame_2)

    def test_node_not_found(self):

        assert isinstance(self, (ChromeInterfaceTest, TestCase))

        with self.assertRaises(ResourceNotFoundError):
            self.devtools_client.get_iframe_source_content("//iframe[@id='unknown']")

    def test_node_found_but_its_not_an_iframe(self):

        assert isinstance(self, (ChromeInterfaceTest, TestCase))

        with self.assertRaises(ResourceNotFoundError):
            self.devtools_client.get_iframe_source_content("//div")

    def test_invalid_xpath(self):

        assert isinstance(self, (ChromeInterfaceTest, TestCase))

        with self.assertRaises(InvalidXPathError):
            self.devtools_client.get_iframe_source_content("@@")


class Test_ChromeInterface_test_get_frame_html_headed(
    HeadedChromeInterfaceTest, Test_ChromeInterface_test_get_iframe_source_content, TestCase
):
    pass


class Test_ChromeInterface_test_get_frame_html_headless(
    HeadlessChromeInterfaceTest, Test_ChromeInterface_test_get_iframe_source_content, TestCase
):
    pass


def _cleanupHTML(html):
    return html.replace("\n", "").replace("  ", "")
