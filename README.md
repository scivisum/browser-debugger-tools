# browser-debugger-tools
[![Build Status](https://img.shields.io/travis/scivisum/browser-debugger-tools/master.svg?style=flat-square)](https://travis-ci.org/scivisum/browser-debugger-tools)
[![PyPI](https://img.shields.io/pypi/v/browserdebuggertools.svg?style=flat-square)](https://pypi.python.org/pypi/browserdebuggertools)
![Python](https://img.shields.io/pypi/pyversions/browserdebuggertools.svg?style=flat-square)
![License](https://img.shields.io/pypi/l/browserdebuggertools.svg?style=flat-square)
## Overview
The purpose is to provide a python client to connect to the debugger tools of a web-browser.

**Currently supports** connecting to **Google-Chrome/Chromium** over the devtools protocol, via a wrapped websockets client. **Feel free to extend and add support for other browsers** as required.

For improved performance, install the wsaccel python lib https://pypi.org/project/wsaccel/

## Example Usage

Start Google-Chrome, passing a remote debugger port argument, for example on Ubuntu:
```
$ google-chrome-stable --remote-debugging-port=9899
```

In a python console, you can connect to the remote debugging port and enable the Page domain.
```
>> self.devtools_client = ChromeInterface(9899, domains=["Page"])
```

The client provides some devtools interface methods, for example:
```
>> with self.devtools_client.set_timeout(10):
   ... self.devtools_client.take_screenshot("/tmp/screenshot.png")
```

Or more generally you can call remote methods according to the devtools protocol spec (https://chromedevtools.github.io/devtools-protocol/tot/Network), for example
```
>> self.devtools_client.execute(domain="Emulation", method="enable")
>> self.devtools_client.execute("Emulation", "setGeolocationOverride", args={"latitude": 20, "longitude": 35})
````
