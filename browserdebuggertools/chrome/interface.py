import contextlib
import logging
from base64 import b64decode, b64encode

from lxml.etree import XPath, XPathSyntaxError

from browserdebuggertools.exceptions import InvalidXPathError, ResourceNotFoundError
from browserdebuggertools.sockethandler import SocketHandler


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
        :param domains: Dictionary of dictionaries where the Key is the domain string and the Value
        is a dictionary of the arguments passed with the domain upon enabling.
        """
        self._socket_handler = SocketHandler(port, timeout, domains=domains)  # type: SocketHandler
        self._dom_manager = _DOMManager(self._socket_handler)

    def quit(self):
        self._socket_handler.close()

    def reset(self):
        """ Clears all stored messages
        """
        self._socket_handler.reset()
        self._dom_manager.reset()

    def get_events(self, domain, clear=False):
        """ Retrieves all events for a given domain
          :param domain: The domain to get the events for.
          :param clear: Removes the stored events if set to true.
          :return: List of events.
          """
        return self._socket_handler.get_events(domain, clear)

    def execute(self, domain, method, params=None):
        """ Executes a command and returns the result.

        Usage example:

        self.execute("Network", "Cookies", args={"urls": ["http://www.urls.com/"]})

        https://chromedevtools.github.io/devtools-protocol/tot/Network#method-getCookies

        :param domain: Chrome DevTools Protocol Domain
        :param method: Domain specific method.
        :param params: Parameters to be executed
        :return: The result of the command
        """
        return self._socket_handler.execute(domain, method, params=params)

    def enable_domain(self, domain, params=None):
        """ Enables notifications for the given domain.
        """
        self._socket_handler.enable_domain(domain, parameters=params)

    def disable_domain(self, domain):
        """ Disables further notifications from the given domain. Also clears any events cached for
            that domain, it is recommended that you get events for the domain before disabling it.

        """
        self._socket_handler.disable_domain(domain)

    @contextlib.contextmanager
    def set_timeout(self, value):
        """ Switches the timeout to the given value.
        """
        _timeout = self._socket_handler.timeout
        self._socket_handler.timer.timeout = value
        try:
            yield
        finally:
            self._socket_handler.timeout = _timeout

    def navigate(self, url):
        """ Navigates to the given url asynchronously
        """
        return self.execute("Page", "navigate", {
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
        # type: () -> str
        """
        Consider enabling the Page domain to increase performance.

        :returns: The url of the current page.
        """
        return self._socket_handler.event_handlers["PageLoad"].get_current_url()

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

    def get_opened_javascript_dialog(self):
        # type: () -> JavascriptDialog
        """
        Gets the opened javascript dialog.

        :raises DomainNotEnabledError: If the Page domain isn't enabled
        :raises JavascriptDialogNotFoundError: If there is currently no dialog open
        """
        return (
            self._socket_handler.event_handlers["JavascriptDialog"].get_opened_javascript_dialog()
        )

    def get_iframe_source_content(self, xpath):
        # type: (str) -> str
        """
        Returns the HTML markup for an iframe document, where the iframe node can be located in the
        DOM with the given xpath.

        :param xpath: following the spec 3.1 https://www.w3.org/TR/xpath-31/
        :return: HTML markup
        :raises XPathSyntaxError: The given xpath is invalid
        :raises IFrameNotFoundError: A matching iframe document could not be found
        :raises UnknownError: The socket handler received a message with an unknown error code
        """

        try:
            XPath(xpath)  # Validates the xpath

        except XPathSyntaxError:
            raise InvalidXPathError("{0} is not a valid xpath".format(xpath))

        return self._dom_manager.get_iframe_html(xpath)

    def get_page_source(self):
        # type: () -> str
        """
        Returns the HTML markup of the current page. Iframe tags are included but the enclosed
        documents are not. Consider enabling the Page domain to increase performance.

        :return: HTML markup
        """

        root_node_id = self._socket_handler.event_handlers["PageLoad"].get_root_backend_node_id()
        return self._dom_manager.get_outer_html(root_node_id)


class _DOMManager(object):

    def __init__(self, socket_handler):
        self._socket_handler = socket_handler
        self._node_map = {}

    def get_outer_html(self, backend_node_id):
        # type: (int) -> str
        return self._socket_handler.execute(
            "DOM", "getOuterHTML", {"backendNodeId": backend_node_id}
        )["outerHTML"]

    def get_iframe_html(self, xpath):
        # type: (str) -> str

        backend_node_id = self._get_iframe_backend_node_id(xpath)
        try:
            return self.get_outer_html(backend_node_id)
        except ResourceNotFoundError:
            # The cached node doesn't exist any more, so we need to find a new one that matches
            # the xpath. Backend node IDs are unique, so there is not a risk of getting the
            # outer html of the wrong node.
            if xpath in self._node_map:
                del self._node_map[xpath]
            backend_node_id = self._get_iframe_backend_node_id(xpath)
            return self.get_outer_html(backend_node_id)

    def _get_iframe_backend_node_id(self, xpath):
        # type: (str) -> int

        if xpath in self._node_map:
            return self._node_map[xpath]

        node_info = self._get_info_for_first_matching_node(xpath)
        try:

            backend_node_id = node_info["node"]["contentDocument"]["backendNodeId"]
        except KeyError:
            raise ResourceNotFoundError("The node found by xpath '%s' is not an iframe" % xpath)

        self._node_map[xpath] = backend_node_id
        return backend_node_id

    def _get_info_for_first_matching_node(self, xpath):
        # type: (str) -> dict

        with self._get_node_ids(xpath) as node_ids:
            if node_ids:
                return self._describe_node(node_ids[0])
        raise ResourceNotFoundError("No matching nodes for xpath: %s" % xpath)

    @contextlib.contextmanager
    def _get_node_ids(self, xpath, max_matches=1):
        # type: (str, int) -> list

        assert max_matches > 0
        search_info = self._perform_search(xpath)
        try:
            results = []
            if search_info["resultCount"] > 0:
                results = self._get_search_results(
                    search_info["searchId"], 0, min([max_matches, search_info["resultCount"]])
                )["nodeIds"]
            yield results

        finally:
            self._discard_search(search_info["searchId"])

    def _perform_search(self, xpath):
        # type: (str) -> dict

        # DOM.getDocument must have been called on the current page first otherwise performSearch
        # returns an array of 0s.
        self._socket_handler.event_handlers["PageLoad"].check_page_load()
        return self._socket_handler.execute("DOM", "performSearch", {"query": xpath})

    def _get_search_results(self, search_id, from_index, to_index):
        # type: (str, int, int) -> dict

        return self._socket_handler.execute("DOM", "getSearchResults", {
            "searchId": search_id, "fromIndex": from_index, "toIndex": to_index
        })

    def _discard_search(self, search_id):
        # type: (str) -> None
        """
        Discards search results for the session with the given id. get_search_results should no
        longer be called for that search.
        """

        self._socket_handler.execute("DOM", "discardSearchResults", {"searchId": search_id})

    def _describe_node(self, node_id):
        # type: (str) -> dict

        return self._socket_handler.execute("DOM", "describeNode", {"nodeId": node_id})

    def reset(self):
        self._node_map = {}
