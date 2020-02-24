import os
import subprocess
import shutil
import time
import tempfile
from base64 import b64decode, b64encode
from unittest import TestCase

from requests import ConnectionError

from browserdebuggertools.exceptions import (
    DevToolsException, DevToolsTimeoutException, JavascriptDialogNotFoundError,
    ResourceNotFoundError
)
from browserdebuggertools.models import JavascriptDialog
from tests.e2etests.testsite.start import Server as TestSiteServer, env
from browserdebuggertools.utils import get_free_port
from browserdebuggertools.chrome.interface import ChromeInterface


BROWSER_PATH = os.environ.get("DEFAULT_CHROME_BROWSER_PATH", "/sv/browsers/chrome_76/chrome")
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

        start = time.time()
        while (time.time() - start) < timeout:
            page_events = self.devtools_client.get_events("Page")
            for event in page_events:
                if event.get("method") == "Page.domContentEventFired":
                    return

        raise Exception("Did not find Page.domContentEventFired within timeout")

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


class Test_ChromeInterface_test_get_frame_html_headed(
    HeadedChromeInterfaceTest, Test_ChromeInterface_test_get_iframe_source_content, TestCase
):
    pass


class Test_ChromeInterface_test_get_frame_html_headless(
    HeadlessChromeInterfaceTest, Test_ChromeInterface_test_get_iframe_source_content, TestCase
):
    pass


class Test_ChromeInterface_test_performance_metrics(object):

    def setUp(self):
        self.devtools_client.enable_domain("Page")

    def tearDown(self):
        self.devtools_client.disable_domain("Page")

    def test_paint_timings(self):

        try:

            self.devtools_client.execute("Performance", "setTimeDomain", {
                "timeDomain": "timeTicks"
            })

            self.devtools_client.enable_domain("Performance")

            self.devtools_client.navigate("http://localhost:%s/iframes" % self.testSite.port)

            self._assert_dom_complete()

            time.sleep(5)

            print("Time to first paint: %sms" % self.devtools_client.execute_javascript(
                "window.performance.getEntriesByType('paint')[0].startTime"
            ))
            print("Time to first contentful paint: %sms" % self.devtools_client.execute_javascript(
                "window.performance.getEntriesByType('paint')[1].startTime"
            ))

            metrics = self.devtools_client.execute("Performance", "getMetrics")["metrics"]

            paintTime = navTime = None
            for metric in metrics:
                if metric["name"] == "FirstMeaningfulPaint":
                    paintTime = metric["value"]
                if metric["name"] == "NavigationStart":
                    navTime = metric["value"]

            if navTime and paintTime:
                print("Time to first meaningful paint: %sms" % (1000 * (paintTime - navTime)))
            else:
                raise Exception("Couldn't determine time to first meaningful paint")

        finally:

            self.devtools_client.disable_domain("Performance")

    def test_time_to_interactive(self):

        try:

            self.devtools_client.enable_domain(
                "Fetch", {"patterns": [{
                    "resourceType": "Document", "requestStage": "Response"
                }]}
            )
            self.devtools_client._socket_handler.execute_async(
                "Page", "navigate", {"url": "https://thinktribe.com"}
            )

            start = time.time()
            while (time.time() - start) < 10:
                page_events = self.devtools_client.get_events("Fetch", clear=True)
                for event in page_events:
                    if event["method"] == "Fetch.requestPaused":
                        body = self.devtools_client.execute(
                            "Fetch", "getResponseBody", {"requestId": event["params"]["requestId"]}
                        )
                        if body["base64Encoded"]:
                            body = b64decode(body["body"])
                        else:
                            body = body["body"]

                        body += """
                        
    <script>
            (function(){var h="undefined"!=typeof window&&window===this?this:"undefined"!=typeof global&&null!=global?global:this,k="function"==typeof Object.defineProperties?Object.defineProperty:function(a,b,c){a!=Array.prototype&&a!=Object.prototype&&(a[b]=c.value)};function l(){l=function(){};h.Symbol||(h.Symbol=m)}var n=0;function m(a){return"jscomp_symbol_"+(a||"")+n++}
        function p(){l();var a=h.Symbol.iterator;a||(a=h.Symbol.iterator=h.Symbol("iterator"));"function"!=typeof Array.prototype[a]&&k(Array.prototype,a,{configurable:!0,writable:!0,value:function(){return q(this)}});p=function(){}}function q(a){var b=0;return r(function(){return b<a.length?{done:!1,value:a[b++]}:{done:!0}})}function r(a){p();a={next:a};a[h.Symbol.iterator]=function(){return this};return a}function t(a){p();var b=a[Symbol.iterator];return b?b.call(a):q(a)}
        function u(a){if(!(a instanceof Array)){a=t(a);for(var b,c=[];!(b=a.next()).done;)c.push(b.value);a=c}return a}var v=0;function w(a,b){var c=XMLHttpRequest.prototype.send,d=v++;XMLHttpRequest.prototype.send=function(f){for(var e=[],g=0;g<arguments.length;++g)e[g-0]=arguments[g];var E=this;a(d);this.addEventListener("readystatechange",function(){4===E.readyState&&b(d)});return c.apply(this,e)}}
        function x(a,b){var c=fetch;fetch=function(d){for(var f=[],e=0;e<arguments.length;++e)f[e-0]=arguments[e];return new Promise(function(d,e){var g=v++;a(g);c.apply(null,[].concat(u(f))).then(function(a){b(g);d(a)},function(a){b(a);e(a)})})}}var y="img script iframe link audio video source".split(" ");function z(a,b){a=t(a);for(var c=a.next();!c.done;c=a.next())if(c=c.value,b.includes(c.nodeName.toLowerCase())||z(c.children,b))return!0;return!1}
        function A(a){var b=new MutationObserver(function(c){c=t(c);for(var b=c.next();!b.done;b=c.next())b=b.value,"childList"==b.type&&z(b.addedNodes,y)?a(b):"attributes"==b.type&&y.includes(b.target.tagName.toLowerCase())&&a(b)});b.observe(document,{attributes:!0,childList:!0,subtree:!0,attributeFilter:["href","src"]});return b}
        function B(a,b){if(2<a.length)return performance.now();var c=[];b=t(b);for(var d=b.next();!d.done;d=b.next())d=d.value,c.push({timestamp:d.start,type:"requestStart"}),c.push({timestamp:d.end,type:"requestEnd"});b=t(a);for(d=b.next();!d.done;d=b.next())c.push({timestamp:d.value,type:"requestStart"});c.sort(function(a,b){return a.timestamp-b.timestamp});a=a.length;for(b=c.length-1;0<=b;b--)switch(d=c[b],d.type){case "requestStart":a--;break;case "requestEnd":a++;if(2<a)return d.timestamp;break;default:throw Error("Internal Error: This should never happen");
        }return 0}function C(a){a=a?a:{};this.w=!!a.useMutationObserver;this.u=a.minValue||null;a=window.__tti&&window.__tti.e;var b=window.__tti&&window.__tti.o;this.a=a?a.map(function(a){return{start:a.startTime,end:a.startTime+a.duration}}):[];b&&b.disconnect();this.b=[];this.f=new Map;this.j=null;this.v=-Infinity;this.i=!1;this.h=this.c=this.s=null;w(this.m.bind(this),this.l.bind(this));x(this.m.bind(this),this.l.bind(this));D(this);this.w&&(this.h=A(this.B.bind(this)))}
        C.prototype.getFirstConsistentlyInteractive=function(){var a=this;return new Promise(function(b){a.s=b;"complete"==document.readyState?F(a):window.addEventListener("load",function(){F(a)})})};function F(a){a.i=!0;var b=0<a.a.length?a.a[a.a.length-1].end:0,c=B(a.g,a.b);G(a,Math.max(c+5E3,b))}
        function G(a,b){!a.i||a.v>b||(clearTimeout(a.j),a.j=setTimeout(function(){var b=performance.timing.navigationStart,d=B(a.g,a.b),b=(window.a&&window.a.A?1E3*window.a.A().C-b:0)||performance.timing.domContentLoadedEventEnd-b;if(a.u)var f=a.u;else performance.timing.domContentLoadedEventEnd?(f=performance.timing,f=f.domContentLoadedEventEnd-f.navigationStart):f=null;var e=performance.now();null===f&&G(a,Math.max(d+5E3,e+1E3));var g=a.a;5E3>e-d?d=null:(d=g.length?g[g.length-1].end:b,d=5E3>e-d?null:Math.max(d,
        f));d&&(a.s(d),clearTimeout(a.j),a.i=!1,a.c&&a.c.disconnect(),a.h&&a.h.disconnect());G(a,performance.now()+1E3)},b-performance.now()),a.v=b)}
        function D(a){a.c=new PerformanceObserver(function(b){b=t(b.getEntries());for(var c=b.next();!c.done;c=b.next())if(c=c.value,"resource"===c.entryType&&(a.b.push({start:c.fetchStart,end:c.responseEnd}),G(a,B(a.g,a.b)+5E3)),"longtask"===c.entryType){var d=c.startTime+c.duration;a.a.push({start:c.startTime,end:d});G(a,d+5E3)}});a.c.observe({entryTypes:["longtask","resource"]})}C.prototype.m=function(a){this.f.set(a,performance.now())};C.prototype.l=function(a){this.f.delete(a)};
        C.prototype.B=function(){G(this,performance.now()+5E3)};h.Object.defineProperties(C.prototype,{g:{configurable:!0,enumerable:!0,get:function(){return[].concat(u(this.f.values()))}}});var H={getFirstConsistentlyInteractive:function(a){a=a?a:{};return"PerformanceLongTaskTiming"in window?(new C(a)).getFirstConsistentlyInteractive():Promise.resolve(null)}};
        "undefined"!=typeof module&&module.exports?module.exports=H:"function"===typeof define&&define.amd?define("ttiPolyfill",[],function(){return H}):window.ttiPolyfill=H;})();
        //# sourceMappingURL=tti-polyfill.js.map
        
        ttiPolyfill.getFirstConsistentlyInteractive().then(function (t) {document.tti = t;})
    
    </script>"""

                        self.devtools_client.execute(
                            "Fetch", "fulfillRequest", {
                                "requestId": event["params"]["requestId"],
                                "responseCode": event["params"]["responseStatusCode"],
                                "responseHeaders": event["params"]["responseHeaders"],
                                "body": b64encode(body)
                            }
                        )

                        self._assert_dom_complete()

                        start = time.time()
                        tti = None
                        while not tti and (time.time() - start) < 10:
                            tti = self.devtools_client.execute_javascript("document.tti;")
                            if tti:
                                print("TTI: %s" % tti)
                        return
        finally:
            self.devtools_client.disable_domain("Fetch")

    def test_time_to_title(self):

        try:

            self.devtools_client.enable_domain("Network")

            self.devtools_client.navigate("https://www.thinktribe.com/")

            self._assert_dom_complete()

            start = time.time()
            while (time.time() - start) < 10:
                for event in self.devtools_client.get_events("Network", clear=True):
                    if event["method"] == "Network.requestWillBeSent":
                        if event["params"]["type"] == "Document":
                            requestId = event["params"]["requestId"]
                            url = event["params"]["request"]["url"]
                            sent = event["params"]["timestamp"]

                    if (event["method"] == "Network.dataReceived"
                            and event["params"]["requestId"] == requestId):
                        bodyReceived = event["params"]["timestamp"]
                        print("Time to Title for %s: %s" % (url, 1000*(bodyReceived-sent)))
                        return

        finally:

            self.devtools_client.disable_domain("Network")



class Test_ChromeInterface_test_performance_metrics_headed(
    HeadedChromeInterfaceTest, Test_ChromeInterface_test_performance_metrics, TestCase
):
    pass


class Test_ChromeInterface_test_time_to_title_headless(
    HeadlessChromeInterfaceTest, Test_ChromeInterface_test_performance_metrics, TestCase
):
    pass


def _cleanupHTML(html):
    return html.replace("\n", "").replace("  ", "")
