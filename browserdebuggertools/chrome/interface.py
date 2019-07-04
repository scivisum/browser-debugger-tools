import contextlib
import json
import socket
import time
import logging
from base64 import b64decode

import requests
import websocket


logging.basicConfig(format='%(levelname)s:%(message)s')


class DevToolsTimeoutException(Exception):
    """"""


class ChromeInterface(object):
    """ The Chrome Interface communicates with the browser through the remote-debugging-port using
        the Chrome DevTools Protocol.
        For a thorough reference check: https://chromedevtools.github.io/devtools-protocol/

        Usage example:

            interface = ChromeInterface(9123)
            interface.navigate(url="https://github.com/scivisum/browser-debugger-tools")
    """

    CONN_TIMEOUT = 15  # Connection timeout

    def __init__(self, port, timeout=30, domains=None):
        """ Initialises the interface starting the websocket connection and enabling
            a series of domains.

        :param port: remote-debugging-port to connect.
        :param timeout: Timeout between executing a command and receiving a result.
        :param domains: List of domains to be enabled. By default Page, Network and Runtime are
                        automatically enabled.
        """

        self.port = port
        self.timeout = timeout
        self.async = False

        self._messages = []
        self._next_result_id = 0
        self.ws = self._get_ws_connection()

        if not domains:
            domains = []

        domains += ["Page", "Network", "Runtime"]

        for domain in domains:
            self.enable_domain(domain)

    def __del__(self):
        """ Attempts to close the websocket and free up resources,
            prefer to call self.close() explicitly whenever possible.
        """
        if hasattr(self, "_ws") and self._ws:
            self.close()

    def close(self):
        self.ws.close()
            
    def enable_domain(self, domain):
        self.execute(domain, "enable")
        logging.info("Domain {} has been enabled".format(domain))

    def navigate(self, url):
        self.execute("Page", "navigate", {
            "url": url
        })

    def take_screenshot(self, filepath):
        response = self.execute("Page", "captureScreenshot")
        imageData = response["result"]["data"]
        with open(filepath, "wb") as f:

            f.write(b64decode(imageData))

    def get_document_readystate(self):
        response = self.execute("Runtime", "evaluate", {"expression": "document.readyState"})
        return response["result"]["result"]["value"]

    def pop_messages(self):
        """ Retrieves all messages, and clear the cache.
        :return: All messages in the cache.
        """

        # Retrieve messages and store it in the cache.
        while self._read_socket():
            pass

        messages = self._messages
        self._messages = []
        return messages

    def execute(self, domain, method, args=None):
        """ Execute can be used both synchronously or asynchronously, depending if
        self.async is true.

        Usage example:

        self.execute("Network", "Cookies", args={"urls": ["http://www.urls.com/"]})

        https://chromedevtools.github.io/devtools-protocol/tot/Network#method-getCookies

        :param domain: Chrome DevTools Protocol Domain
        :param method: Domain specific method.
        :param args: Parameters to be executed
        :return: If run synchronously, it waits for and retrieves a message, otherwise None
        """
        if method == "disable":
            logging.warning("{} domain has been disabled, "
                            "some functionality may not work as expected".format(domain))

        if not args:
            args = {}

        self._next_result_id += 1
        self.ws.send(json.dumps({
            "id": self._next_result_id, "method": "{}.{}".format(domain, method), "params": args
        }, sort_keys=True))

        if self.async:
            return None

        return self._wait_for_result()

    @contextlib.contextmanager
    def run_async(self):
        self.async = True
        try:
            yield
        finally:
            self.async = False

    @contextlib.contextmanager
    def set_timeout(self, value):
        _timeout = self.timeout
        self.timeout = value
        try:
            yield
        finally:
            self.timeout = _timeout

    def _wait_for_result(self):
        start = time.time()
        while (time.time() - start) < self.timeout:
            message = self._read_socket()
            if message and "result" in message and message['id'] == self._next_result_id:
                return message
        raise DevToolsTimeoutException(
            "Reached timeout limit of {}, waiting for a response message".format(self.timeout)
        )

    def _get_ws_connection(self):
        response = requests.get(
            'http://localhost:{}/json'.format(self.port), timeout=self.CONN_TIMEOUT
        )
        wsurl = json.loads(response.text)[-1]['webSocketDebuggerUrl']
        ws = websocket.create_connection(wsurl, timeout=self.CONN_TIMEOUT)
        ws.settimeout(0)  # Don't wait for new messages
        return ws

    def _read_socket(self):
        """ Reads and cache messages.
        :return: a dict containing the message response
        """
        try:
            message = self.ws.recv()
        except socket.error:
            return None
        message = json.loads(message)
        self._messages.append(message)
        return message
