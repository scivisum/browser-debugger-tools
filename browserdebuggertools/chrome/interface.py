import contextlib
import logging
import re
from base64 import b64decode, b64encode
from typing import Optional

from browserdebuggertools import models
from browserdebuggertools.exceptions import TargetNotFoundError
from browserdebuggertools.targetsmanager import TargetsManager

logging.basicConfig(format='%(levelname)s:%(message)s')


class ChromeInterface(object):
    """ The Chrome Interface communicates with the browser through the remote-debugging-port using
        the Chrome DevTools Protocol.
        For a thorough reference check: https://chromedevtools.github.io/devtools-protocol/

        Usage example:

            interface = ChromeInterface(9123)
            interface.navigate(url="https://github.com/scivisum/browser-debugger-tools")
    """

    def __init__(
        self,
        port: int,
        host: str = "localhost",
        timeout: int = 30,
        domains: Optional[dict] = None,
        attach: bool = True
    ):
        """ Initialises the interface starting the websocket connection and enabling
            a series of domains.

        :param port: remote-debugging-port to connect.
        :param host: host where the browser is
        :param timeout: Timeout between executing a command and receiving a result.
        :param domains: Dictionary of dictionaries where the Key is the domain string and the Value
            is a dictionary of the arguments passed with the domain upon enabling.
        :param attach: If set to true, the interface will attach to the first page target found.
            If there are no  page targets, a new tab will be created.
        """
        self._targets_manager = TargetsManager(timeout, port, host=host, domains=domains)
        if attach:
            self.switch_target()

    @property
    def targets(self):
        return self._targets_manager.refresh_targets()

    def switch_target(self, target_id=None):
        """
        Switches the current target to the one specified by target_id. If no target_id is
        specified, the first page target found will be used. If no page targets are found, a new
        tab will be created.
        """
        self._targets_manager.refresh_targets()
        if target_id:
            if target_id in self._targets_manager.targets:
                self._targets_manager.switch_target(target_id)
            else:
                raise TargetNotFoundError(f"Target with id {target_id} not found")
        else:
            page_targets = [
                target_id for target_id, target in self._targets_manager.targets.items()
                if target.type == "page"
            ]
            if self._targets_manager.targets:
                self._targets_manager.switch_target(page_targets[0])
            else:
                new_target = self.create_tab()
                self._targets_manager.switch_target(new_target.id)

    def create_tab(self):
        """ Creates a new tab and switches to it.
        """
        return self._targets_manager.create_tab()

    def quit(self):
        """
        Close all connections to the browser and reset state
        """
        self._targets_manager.detach_all()
        self.reset()

    def reset(self):
        """ Clears all stored messages
        """
        self._targets_manager.reset()

    def get_events(self, domain, clear=False):
        """ Retrieves all events for a given domain for the current target
          :param domain: The domain to get the events for.
          :param clear: Removes the stored events if set to true.
          :return: List of events.
          """
        return self._targets_manager.get_events(domain, clear=clear)

    def execute(self, domain, method, params=None):
        """ Executes a command against the current target and returns the result.

        Usage example:

        self.execute("Network", "Cookies", args={"urls": ["https://www.urls.com/"]})

        https://chromedevtools.github.io/devtools-protocol/tot/Network#method-getCookies

        :param domain: Chrome DevTools Protocol Domain
        :param method: Domain specific method.
        :param params: Parameters to be executed
        :return: The result of the command
        """
        return self._targets_manager.execute(domain, method, params=params)

    def enable_domain(self, domain, params=None):
        """ Enables events for the given domain for the current target.
        """
        self._targets_manager.enable_domain(domain, parameters=params)

    def disable_domain(self, domain):
        """ Disables further notifications from the given domain. Also clears any events cached for
            that domain, it is recommended that you get events for the domain before disabling it.

        """
        self._targets_manager.disable_domain(domain)

    @contextlib.contextmanager
    def set_timeout(self, value):
        """ Switches the timeout to the given value.
        """
        with self._targets_manager.set_timeout(value):
            yield

    def navigate(self, url):
        """ Navigates to the given url within the current target
        """
        return self.execute("Page", "navigate", {
            "url": url
        })

    def take_screenshot(self, filepath):
        """ Takes a screenshot of the current target
        """
        response = self.execute("Page", "captureScreenshot")
        image_data = response["data"]
        with open(filepath, "wb") as f:
            f.write(b64decode(image_data))

    def stop_page_load(self):
        return self.execute("Page", "stopLoading")

    def execute_javascript(self, script, **kwargs):
        params = {
            "expression": script,
        }
        for k, v in kwargs.items():
            params[k] = v
        result = self.execute("Runtime", "evaluate", params)["result"]

        return result.get("value")

    def get_url(self) -> str:
        """
        Consider enabling the Page domain to increase performance.

        :returns: The url of the current page.
        """
        return self._targets_manager.get_url()

    def get_document_readystate(self):
        """ Gets the document.readyState of the page.
        """
        return self.execute_javascript("document.readyState")

    def set_user_agent_override(self, user_agent):
        """ Overriding user agent with the given string.
        :param user_agent:
        :return:
        """
        return self.execute("Network", "setUserAgentOverride", {
            "userAgent": user_agent
        })

    def emulate_network_conditions(self, latency, download, upload, offline=False):
        """
        :param latency: Minimum latency from request sent to response headers (ms).
        :param download: Maximal aggregated download throughput (bytes/sec).
        :param upload: Maximal aggregated upload throughput (bytes/sec).
        :param offline: Whether to emulate network disconnection
        """

        # Note: Currently, there's a bug in the devtools protocol when disabling parameters,
        # i.e. setting download to -1, therefore we enforce that all parameters must be passed with
        # a sensible value (bigger than 0)
        assert min(latency, download, upload) > 0 or offline

        network_conditions = {
            "offline": offline,
            "latency": latency,
            "downloadThroughput": download,
            "uploadThroughput": upload,
        }

        return self.execute("Network", "emulateNetworkConditions", network_conditions)

    def set_basic_auth(self, username, password):
        """
        Creates a basic type Authorization header from the username and password strings
        and applies it to all requests
        """
        auth = b"Basic " + b64encode("%s:%s" % (username, password))
        self.set_request_headers({"Authorization": auth})

    def set_request_headers(self, headers):
        """
        The specified headers are applied to all requests
        :param headers: A dictionary of the form {"headerKey": "headerValue"}
        """
        self.execute("Network", "setExtraHTTPHeaders", {"headers": headers})

    def get_opened_javascript_dialog(self) -> models.JavascriptDialog:
        """
        Gets the opened javascript dialog for the current target.

        :raises DomainNotEnabledError: If the Page domain isn't enabled
        :raises JavascriptDialogNotFoundError: If there is currently no dialog open
        """
        return self._targets_manager.get_opened_javascript_dialog()

    def get_iframe_source_content(self, xpath: str) -> str:
        """
        Returns the HTML markup for an iframe document, where the iframe node can be located in the
        DOM with the given xpath.

        :param xpath: following the spec 3.1 https://www.w3.org/TR/xpath-31/
        :return: HTML markup
        :raises IFrameNotFoundError: A matching iframe document could not be found
        :raises UnknownError: The socket handler received a message with an unknown error code
        """
        return self._targets_manager.get_iframe_source_content(xpath)

    def get_page_source(self) -> str:
        """
        Returns the HTML markup of the current page. Iframe tags are included but the enclosed
        documents are not. Consider enabling the Page domain to increase performance.

        :return: HTML markup
        """
        return self._targets_manager.get_page_source()

    def block_main_frames(self):
        """
         Don't let the browser load any main frames (i.e. page loadsk and iframes)
        """
        extension_id = self.execute_javascript(
            'localStorage.getItem("requestBlockerExtensionID")',
            returnByValue=True
        )
        self.execute_javascript(
            f'chrome.runtime.sendMessage("{extension_id}",'
            '{method: "blockMainFrames"})',
            returnByValue=True,
            awaitPromise=True
        )

    def unblock_main_frames(self):
        """
        Stop blocking main frames
        """
        extension_id = self.execute_javascript(
            'localStorage.getItem("requestBlockerExtensionID")',
            returnByValue=True
        )
        self.execute_javascript(
            f'chrome.runtime.sendMessage("{extension_id}",'
            '{method: "unblockMainFrames"})',
            returnByValue=True,
            awaitPromise=True
        )

    def get_all_events(self, domain, clear=False):
        """ Retrieves all events for a given domain for all targets
          :param domain: The domain to get the events for.
          :param clear: Removes the stored events if set to true.
          :return: List of events.
          """
        return self._targets_manager.get_all_events(domain, clear=clear)

    def reload(self):
        return self.execute("Page", "reload")
