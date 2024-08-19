import os
import subprocess
import shutil
import time
import tempfile
from abc import ABC
from typing import Union
from unittest import TestCase

from requests import ConnectionError

from browserdebuggertools.chrome import CHROME_EXTENSIONS
from browserdebuggertools.exceptions import (
    DevToolsException, DevToolsTimeoutException, JavascriptDialogNotFoundError,
    ResourceNotFoundError, MessagingThreadIsDeadError
)
from browserdebuggertools.models import JavascriptDialog
from tests.e2etests.testsite.start import Server as LocalTestSite, env
from browserdebuggertools.utils import get_free_port
from browserdebuggertools.chrome.interface import ChromeInterface


BROWSER_PATH = os.environ.get("DEFAULT_CHROME_BROWSER_PATH", "/opt/google/chrome/chrome")
TEMP = tempfile.gettempdir()


class ChromeInterfaceTest(ABC):

    testSite = None
    browser = None
    browser_cache_dir = TEMP + "/ChromeInterfaceTest_%s" % (time.time() * 1000)
    devtools_client = None
    headless = True
    browser_version = None

    @classmethod
    def setUpClass(cls):

        completed = subprocess.run([BROWSER_PATH, "--version"], check=True,
                                   capture_output=True, text=True)
        cls.browser_version = int(completed.stdout.split(" ")[2].split(".")[0])

        cls.testSite = LocalTestSite()
        cls.testSite.start()

        devtools_port = get_free_port()

        cmd = [
            BROWSER_PATH,
            "--remote-debugging-port=%s" % devtools_port,
            "--no-default-browser-check",
            "--headless=new" if cls.headless else "",
            "--user-data-dir=%s" % cls.browser_cache_dir,
            "--no-first-run", "--disable-gpu",
            "--no-sandbox", "--remote-allow-origins=*"
        ]
        cmd += [
            f"--load-extension={extension}" for extension in CHROME_EXTENSIONS
        ]
        cls.browser = subprocess.Popen(cmd)

        start = time.time()
        while time.time() - start < 30:

            time.sleep(3)

            try:
                cls.devtools_client = ChromeInterface(devtools_port)
                break

            except ConnectionError:
                pass

        else:
            raise Exception("Devtools client could not connect to browser")

    def _execute_async(self, *args, **kwargs):
        return self.devtools_client._targets_manager.current_target.wsm.execute_async(*args, **kwargs)

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

    def _click(self, id_):
        self.devtools_client.execute_javascript(f"document.getElementById({id_}).click()")

    @classmethod
    def tearDownClass(cls):
        cls.devtools_client.quit()
        cls.browser.kill()
        time.sleep(3)
        shutil.rmtree(cls.browser_cache_dir)
        cls.testSite.stop()


class ChromeInterfaceTakeScreenshot(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Page")
        self.file_path = "/tmp/screenshot%s.png" % int(time.time()*1000000)
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def test_take_screenshot_dom_complete(self):

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.devtools_client.take_screenshot(self.file_path)
        self.assertTrue(os.path.exists(self.file_path))
        # Sanity check the screenshot is a sensible size
        self.assertTrue(os.path.getsize(self.file_path) >= 3000)

    def test_take_screenshot_incomplete_main_exchange(self):

        with self.devtools_client.set_timeout(3):
            with self.assertRaises(DevToolsTimeoutException):
                self.devtools_client.navigate(
                    url="http://localhost:%s?main_exchange_response_time=30" % self.testSite.port
                )

        with self.devtools_client.set_timeout(3):
            with self.assertRaises(DevToolsTimeoutException):
                self.devtools_client.take_screenshot(self.file_path)

    def test_take_screenshot_incomplete_head_component(self):

        self.devtools_client.navigate(
            url="http://localhost:%s?head_component_response_time=30"
                % self.testSite.port
        )

        time.sleep(3)

        with self.devtools_client.set_timeout(3):
            self.assertRaises(
                DevToolsTimeoutException,
                lambda: self.devtools_client.take_screenshot(self.file_path)
            )

    def tearDown(self):
        if os.path.exists(self.file_path):
            os.remove(self.file_path)
        self.devtools_client.disable_domain("Page")


class TestChromeInterfaceTakeScreenshotHeaded(ChromeInterfaceTakeScreenshot, TestCase):
    headless = False


class TestChromeInterfaceTakeScreenshotHeadless(ChromeInterfaceTakeScreenshot, TestCase):
    headless = True


class ChromeInterfaceGetDocumentReadystate(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Page")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test_get_ready_state_dom_complete(self):

        self.devtools_client.navigate(url="http://localhost:%s" % self.testSite.port)
        self._assert_dom_complete()
        self.assertEqual("complete", self.devtools_client.get_document_readystate())

    def test_get_ready_state_incomplete_main_exchange(self):

        with self.devtools_client.set_timeout(3):
            with self.assertRaises(DevToolsTimeoutException):
                self.devtools_client.navigate(
                    url="http://localhost:%s?main_exchange_response_time=30" % self.testSite.port
                )
                self.assertEqual("loading", self.devtools_client.get_document_readystate())

    def test_get_ready_state_incomplete_head_component(self):

        with self.devtools_client.set_timeout(3):
            self.devtools_client.navigate(
                url="http://localhost:%s?head_component_response_time=30" % self.testSite.port
            )
            self.assertEqual("loading", self.devtools_client.get_document_readystate())


class TestChromeInterfaceGetDocumentReadystateHeaded(ChromeInterfaceGetDocumentReadystate, TestCase):
    headless = False


class TestChromeInterfaceGetDocumentReadystateHeadless(ChromeInterfaceGetDocumentReadystate, TestCase):
    headless = True


class ChromeInterfaceEmulateNetworkConditions(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Network")

    def tearDown(self):
        self.devtools_client.disable_domain("Network")

    def waitForEventWithMethod(self, method, timeout=30):

        start = time.time()
        while (time.time() - start) < timeout:
            for event in self.devtools_client.get_events(method.split(".")[0]):
                if event.get("method") == method:
                    return True
        return False

    def test_took_expected_time(self):

        upload = 1000000000000  # 1 terabytes / second (no limit)
        download = 100000  # 100 kilobytes / second

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
        self.assertIn(int(round(time_taken)), [10, 11, 12])  # Headed browser is a bit slower


class TestChromeInterfaceEmulateNetworkConditionsHeaded(ChromeInterfaceEmulateNetworkConditions, TestCase):
    headless = False


class TestChromeInterfaceEmulateNetworkConditionsHeadless(ChromeInterfaceEmulateNetworkConditions, TestCase):
    headless = True


class ChromeInterfaceSetBasicAuth(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Page")
        self.devtools_client.enable_domain("Network")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")
        self.devtools_client.disable_domain("Network")

    def test_standard_auth_page(self):
        # noinspection HttpUrlsUsage
        url = "http://username:password@localhost:%s/auth_challenge" % self.testSite.port
        self.devtools_client.navigate(url=url)
        self._assert_dom_complete()

        responses_received = self._get_responses_received()

        self.assertTrue(len(responses_received) >= 2)  # Headed browser creates extra requests
        self.assertIn(200, responses_received)
        self.assertNotIn(401, responses_received)  # Devtools genuinely doesn't report these


class TestChromeInterfaceSetBasicAuthHeaded(ChromeInterfaceSetBasicAuth, TestCase):
    headless = False


class TestChromeInterfaceSetBasicAuthHeadless(ChromeInterfaceSetBasicAuth, TestCase):
    headless = True


class ChromeInterfaceConnectionUnexpectedlyDead(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Page")
        self.devtools_client.enable_domain("Network")

    def test(self):

        self.devtools_client.quit()

        url = "http://localhost:%s" % self.testSite.port

        with self.assertRaises(MessagingThreadIsDeadError):
            self.devtools_client.navigate(url=url)


class TestChromeInterfaceConnectionUnexpectedlyClosedHeaded(
    ChromeInterfaceConnectionUnexpectedlyDead, TestCase
):
    headless = False


class TestChromeInterfaceConnectionUnexpectedlyClosedHeadless(
    ChromeInterfaceConnectionUnexpectedlyDead, TestCase
):
    headless = True


class ChromeInterfaceCachePage(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Page")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test_with_page(self):

        base_url = "http://localhost:%s/" % self.testSite.port

        simple_page = "<html><head></head><body><h1>Simple Page</h1></body></html>"

        fake_page_load = "<script>" \
                         "function fake_page_load(){" \
                         "document.getElementById('title-text').innerHTML= 'Fake Title';" \
                         "window.history.pushState('fake_page', 'Fake Title', '/fake_page');" \
                         "}" \
                         "</script>"

        simple_page_3 = (
            '<html><head></head><body><h1 id="title-text">Simple Page 3</h1>'
            f'{fake_page_load}</body></html>'
        )
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


class TestChromeInterfaceCachePageHeaded(ChromeInterfaceCachePage, TestCase):
    headless = False


class TestChromeInterfaceCachePageHeadless(ChromeInterfaceCachePage, TestCase):
    headless = True


class ChromeInterfaceTestJavascriptDialogs(ChromeInterfaceTest):

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

        self._execute_async("Runtime", "evaluate", {
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
        self._execute_async("Runtime", "evaluate", {
            "expression": "open_%s()" % dialog, "userGesture": True,
        })
        # wait for the dialog to appear
        time.sleep(2)

    def test_no_dialog(self):
        with self.assertRaises(JavascriptDialogNotFoundError):
            self.devtools_client.get_opened_javascript_dialog()

    def check_dialog(self, dialogType, message=None):
        self.open_dialog(dialogType)

        dialog = self.devtools_client.get_opened_javascript_dialog()

        # Check the dialog
        self.assertTrue(dialog)
        self.assertEqual(dialog, self.devtools_client.get_opened_javascript_dialog())
        self.assertEqual(dialogType, dialog.type)
        self.assertEqual(message, dialog.message)
        self.assertFalse(dialog.is_handled)
        if dialogType != JavascriptDialog.PROMPT:
            self.assertFalse(dialog.default_prompt)
        self.assertEqual(self.url, dialog.url)

        # Test dismiss
        dialog.dismiss()

        self.open_dialog(dialogType)
        dialog2 = self.devtools_client.get_opened_javascript_dialog()

        # Test not cached
        self.assertTrue(dialog.is_handled)

        # Test accept (putting this last, so we don't refresh the page beforehand)
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
        dialogType = JavascriptDialog.PROMPT
        self.check_dialog(dialogType, "Enter some text")

        # Test prompt special interactions
        self.open_dialog(dialogType)

        dialog = self.devtools_client.get_opened_javascript_dialog()
        self.assertEqual("default text", dialog.default_prompt)

        dialog.accept_prompt("new text")
        self.assertEqual("new text", self.devtools_client.execute_javascript(
            "document.getElementById('prompt_result').innerHTML"
        ))

    def test_onbeforeunload(self):
        self.check_dialog(JavascriptDialog.BEFORE_UNLOAD, "")


class TestChromeInterfaceTestJavascriptDialogsHeaded(ChromeInterfaceTestJavascriptDialogs, TestCase):
    headless = False


class TestChromeInterfaceTestJavascriptDialogsHeadless(ChromeInterfaceTestJavascriptDialogs, TestCase):
    headless = True


class ChromeInterfaceTestGetIframeSourceContent(ChromeInterfaceTest):

    def setUp(self):

        self.devtools_client.enable_domain("Page")

        self.devtools_client.navigate("http://localhost:%s/iframes" % self.testSite.port)

        self._assert_dom_complete()

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test_get_source_ok(self):

        expected_main_page = _cleanupHTML(env.get_template('iframes.html').render())
        actual_main_page = _cleanupHTML(self.devtools_client.get_page_source())
        self.assertEqual(expected_main_page, actual_main_page)

        expected_frame_1 = _cleanupHTML(env.get_template('simple_page.html').render())
        actual_frame_1 = _cleanupHTML(
            self.devtools_client.get_iframe_source_content(
                "//iframe[@id='simple_page_frame']"
            )
        )
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

        with self.assertRaises(ResourceNotFoundError):
            self.devtools_client.get_iframe_source_content("//iframe[@id='unknown']")

    def test_node_found_but_its_not_an_iframe(self):

        with self.assertRaises(ResourceNotFoundError):
            self.devtools_client.get_iframe_source_content("//div")


class TestChromeInterfaceTestGetIframeSourceContentHeaded(
    ChromeInterfaceTestGetIframeSourceContent, TestCase
):
    headless = False


class TestChromeInterfaceTestGetIframeSourceContentHeadless(
    ChromeInterfaceTestGetIframeSourceContent, TestCase
):
    headless = True


class SwitchTabTest(ChromeInterfaceTest):

    def setUp(self):
        self.devtools_client.enable_domain("Page")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test(self: Union[TestCase, ChromeInterfaceTest]):

        if self.browser_version < 112:
            self.skipTest("Chrome version too old")
            return

        # Navigate to a simple page in an initial tab
        self.devtools_client.enable_domain("Network")
        self.devtools_client.navigate(f"http://localhost:{self.testSite.port}/simple_page")
        self._assert_dom_complete()
        original_target_id = self.devtools_client._targets_manager.current_target_id

        # Block any new document requests and open url in a new tab
        self.devtools_client.block_main_frames()
        # In Chrome 112 for some reason we can't specify useGesture and returnByValue at the same
        # time, if we do we get an 'Object reference chain is too long' error.
        # So don't use execute_javascript which insists on setting returnByValue.
        self.devtools_client.execute(
            "Runtime", "evaluate",
            {
                "expression": f"window.open('http://localhost:{self.testSite.port}/simple_page_2', '_blank')",
                "userGesture": True
            }
        )

        # The latest version of blocking,
        # does not change the title to 'localhost' for blocked requests
        time.sleep(1)
        new_target_id, new_target = [
            (target_id, target) for target_id, target in self.devtools_client.targets.items() if
            target.info["url"].endswith("/simple_page_2")
        ].pop()
        url = new_target.info["url"]
        self.assertEqual("Simple Page 2", new_target.info["title"])

        # Switch to the new tab and enable the Network domain for it
        self.devtools_client.switch_target(new_target_id)
        self.devtools_client.enable_domain("Network")
        # New blocking system does not show ERR_BLOCKED_BY_CLIENT in the page

        # Switch back to the original tab and unblock requests, then back to the new tab
        self.devtools_client.switch_target(original_target_id)
        self.devtools_client.unblock_main_frames()
        self.devtools_client.switch_target(new_target_id)

        # Reload the original url in the new tab
        self.devtools_client.navigate(url)

        # Verify that we got the requestWillBeSent network event for both tabs
        found = {
            "simple_page": False,
            "simple_page_2": False
        }
        for event in self.devtools_client.get_all_events("Network"):
            if event.get("method") == "Network.requestWillBeSent":
                url = event["params"]["request"]["url"]
                if url.endswith("/simple_page"):
                    found["simple_page"] = True
                elif url.endswith("/simple_page_2"):
                    found["simple_page_2"] = True

        self.assertTrue(found["simple_page"])
        self.assertTrue(found["simple_page_2"])


class TestSwitchTabHeaded(SwitchTabTest, TestCase):
    headless = False


class TestSwitchTabHeadless(SwitchTabTest, TestCase):
    headless = True


def _cleanupHTML(html):
    return html.replace("\n", "").replace("  ", "")
