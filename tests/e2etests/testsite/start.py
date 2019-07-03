import multiprocessing
import time

import cherrypy

from browserdebuggertools.utils.lib import get_free_port


class TestSite(object):

    @cherrypy.expose
    def index(self, main_exchange_response_time=0, head_component_response_time=0):

        if main_exchange_response_time:
            time.sleep(int(main_exchange_response_time))

        return """
        <html>
          <head>
            <script src="/javascript_file?response_time=%s"></script>
          </head>
          <body>This is a page</body>
        </html>
        """ % head_component_response_time

    @cherrypy.expose
    def javascript_file(self, response_time=None):

        if response_time:
            time.sleep(int(response_time))

        return "'foo';"


class Server(object):

    def __init__(self):
        super(Server, self).__init__()
        self.port = get_free_port()
        self.process = multiprocessing.Process(target=self._make_app)

    def _make_app(self):
        cherrypy.quickstart(TestSite(), config={
            "global": {
                "server.socket_port": self.port,
                "engine.autoreload.on": False
            }
        })

    def start(self):
        self.process.start()

    def stop(self):
        self.process.terminate()


if __name__ == "__main__":
    Server().start()
