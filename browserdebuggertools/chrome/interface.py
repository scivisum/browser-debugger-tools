import contextlib
import time
import logging
from base64 import b64decode, b64encode

from browserdebuggertools.sockethandler import SocketHandler
from browserdebuggertools.exceptions import (
    DevToolsTimeoutException, ResultNotFoundError, DomainNotFoundError
)

logging.basicConfig(format='%(levelname)s:%(message)s')


class ChromeInterface(object):
    """ The Chrome Interface communicates with the browser through the remote-debugging-port using
        the Chrome DevTools Protocol.
        For a thorough reference check: https://chromedevtools.github.io/devtools-protocol/

        Usage example:

            interface = ChromeInterface(9123)
            interface.navigate(url="https://github.com/scivisum/browser-debugger-tools")
    """

    def __init__(self, port, timeout=30, domains=None):
        """ Initialises the interface starting the websocket connection and enabling
            a series of domains.

        :param port: remote-debugging-port to connect.
        :param timeout: Timeout between executing a command and receiving a result.
        :param domains: List of domains to be enabled. By default Page, Network and Runtime are
                        automatically enabled.
        """
        self.timeout = timeout
        self._socket_handler = SocketHandler(port)

        if domains:
            for domain in domains:
                self.enable_domain(domain)

    def quit(self):
        self._socket_handler.close()

    def wait_for_result(self, result_id):
        """ Waits for a result to complete within the timeout duration then returns it.
            Raises a DevToolsTimeoutException if it cannot find the result.

        :param result_id: The result id.
        :return: The result.
          """
        start = time.time()
        while not self.timeout or (time.time() - start) < self.timeout:
            try:
                return self._socket_handler.find_result(result_id)
            except ResultNotFoundError:
                time.sleep(0.5)
        raise DevToolsTimeoutException(
            "Reached timeout limit of {}, waiting for a response message".format(self.timeout)
        )

    def get_result(self, result_id):
        """ Gets the result for a given id, if it has finished executing
            Raises a ResultNotFoundError if it cannot find the result.

        :param result_id: The result id.
        :return: The result.
          """
        return self._socket_handler.find_result(result_id)

    def get_results(self):
        """ Retrieves a dictionary containing all the results indexed by result_id
        """
        self._socket_handler.flush_messages()
        return self._socket_handler.results

    def clear_results(self):
        """ Clears all results in the cache
        """
        self._socket_handler.results.clear()

    def get_events(self, domain, clear=False):
        """ Retrieves all events for a given domain
          :param domain: The domain to get the events for.
          :param clear: Removes the stored events if set to true.
          :return: List of events.
          """
        return self._socket_handler.get_events(domain, clear)

    def execute(self, domain, method, args=None):
        """ Executes a command and returns the result.

        Usage example:

        self.execute("Network", "Cookies", args={"urls": ["http://www.urls.com/"]})

        https://chromedevtools.github.io/devtools-protocol/tot/Network#method-getCookies

        :param domain: Chrome DevTools Protocol Domain
        :param method: Domain specific method.
        :param args: Parameters to be executed
        :return: The result of the command
        """
        result_id = self._socket_handler.execute("{}.{}".format(domain, method), args)

        return self.wait_for_result(result_id)

    def execute_async(self, domain, method, args=None):
        """ Same as execute but doesn't wait for the result.

        :param domain: chrome devtools protocol domain
        :param method: domain specific method.
        :param args: parameters to be executed
        :return: id of the request
        """
        return self._socket_handler.execute("{}.{}".format(domain, method), args)

    def enable_domain(self, domain):
        """ Enables notifications for the given domain.
        """
        self._socket_handler.add_domain(domain)
        result = self.execute(domain, "enable")
        if "error" in result:
            self._socket_handler.remove_domain(domain)
            raise DomainNotFoundError("Domain \"{}\" not found.".format(domain))

        logging.info("\"{}\" domain has been enabled".format(domain))

    def disable_domain(self, domain):
        """ Disables further notifications from the given domain.
        """
        self._socket_handler.remove_domain(domain)
        result = self.execute(domain, "disable")
        if "error" in result:
            logging.warn("Domain \"{}\" doesn't exist".format(domain))
        else:
            logging.info("Domain {} has been disabled".format(domain))

    @contextlib.contextmanager
    def set_timeout(self, value):
        """ Switches the timeout to the given value.
        """
        _timeout = self.timeout
        self.timeout = value
        try:
            yield
        finally:
            self.timeout = _timeout

    def navigate(self, url):
        """ Navigates to the given url asynchronously
        """
        return self.execute_async("Page", "navigate", {
            "url": url
        })

    def take_screenshot(self, filepath):
        """ Takes a screenshot of the current page
        """
        response = self.execute("Page", "captureScreenshot")
        image_data = response["data"]
        with open(filepath, "wb") as f:
            f.write(b64decode(image_data))

    def stop_page_load(self):
        return self.execute("Page", "stopLoading")

    def execute_javascript(self, script):
        result = self.execute("Runtime", "evaluate", {
            "expression": script,
            "returnByValue": True
        })["result"]

        return result.get("value")

    def get_url(self):
        return self.execute_javascript("document.URL")

    def get_document_readystate(self):
        """ Gets the document.readyState of the page.
        """
        return self.execute_javascript("document.readyState")

    def get_page_source(self):
        """ Returns a string serialization of the active document's DOM
        """
        return self.execute_javascript("document.documentElement.innerHTML")

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
        # i.e setting download to -1, therefore we enforce that all parameters must be passed with
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
        auth = "Basic " + b64encode("%s:%s" % (username, password))
        self.set_request_headers({"Authorization": auth})

    def set_request_headers(self, headers):
        """
        The specified headers are applied to all requests
        :param headers: A dictionary of the form {"headerKey": "headerValue"}
        """
        self.execute("Network", "setExtraHTTPHeaders", {"headers": headers})
