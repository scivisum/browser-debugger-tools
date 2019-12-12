import multiprocessing
import time
import os
from base64 import b64decode

import cherrypy
from jinja2 import Environment, FileSystemLoader

from browserdebuggertools.utils import get_free_port


env = Environment(
    loader=FileSystemLoader(os.path.dirname(os.path.abspath(__file__)) + "/templates")
)


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

    @cherrypy.expose
    def big_body(self, size=1000000):
        return "T" * size

    @cherrypy.expose
    def auth_challenge(self, authorized_username="username", authorized_password="password",
                       response_body=None):

        if self.is_authenticated(authorized_username, authorized_password):

            if response_body:
                return response_body

            return """
                <html>
                  <head><script src="/auth_challenge?response_body=null"></script></head>
                  <body>
                    Authorized
                  </body>
                </html>
            """
        cherrypy.response.headers["WWW-Authenticate"] = "basic"
        cherrypy.response.status = 401
        return "Need to authorize"

    @staticmethod
    def is_authenticated(authorized_username, authorized_password):

        if "Authorization" in cherrypy.request.headers:

            auth_string = str(cherrypy.request.headers["Authorization"])
            secret = auth_string.split("Basic ")[1]
            credentials = b64decode(secret).decode()
            this_username, this_password = tuple(credentials.split(":"))
            if (this_username == authorized_username) and (this_password == authorized_password):
                return True
        return False

    @cherrypy.expose
    def simple_page(self):
        return env.get_template('simple_page.html').render()

    @cherrypy.expose
    def simple_page_2(self):
        return env.get_template('simple_page_2.html').render()

    @cherrypy.expose
    def iframes(self):
        return env.get_template('iframes.html').render()

    @cherrypy.expose
    def fake_load_page(self):
        fake_page_script = "<script>" \
                         "function fake_page_load(){" \
                            "document.getElementById('title-text').innerHTML= 'Fake Title';" \
                            "window.history.pushState('fake_page', 'Fake Title', '/fake_page');" \
                         "}" \
                         "</script>"
        return "<html><head></head><body><h1 id='title-text'>Simple Page 3</h1>" \
               "%s</body></html>" % fake_page_script

    @cherrypy.expose
    def javascript_dialog_page(self):
        return '''
<html>
    <head>
        <title>Javascript Dialogs page</title>
    </head>
    <body onbeforeunload="return true;">
        <button onclick="open_alert()">Alert</button>
        <button onclick="open_confirm()">Confirm</button>
        <button onclick="open_prompt()">Prompt</button>
        <button onclick="open_beforeunload()">OnBeforeUnload</button>
        <p id="prompt_result"></p>
        <script>
            function open_alert(){
                alert("Something important");
            }
            function open_confirm(){
                confirm("Do you want to confirm?");
            }
            function open_prompt(){
                prompt_result = prompt("Enter some text", "default text");
                document.getElementById("prompt_result").innerHTML = prompt_result;
            }
            function open_beforeunload(){
                location.reload();
            }
            function reset(){
                window.onbeforeunload = null;
            }
        </script>
    </body>
</html>'''


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
