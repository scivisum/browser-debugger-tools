import json
import logging
import socket
import time
from unittest import TestCase

import websocket
from mock import MagicMock, patch

from browserdebuggertools.exceptions import DevToolsTimeoutException, MaxRetriesException
from browserdebuggertools.wssessionmanager import WSSessionManager, _WSMessagingThread

MODULE_PATH = "browserdebuggertools.WSSessionManager."


class _DummyWebsocket(object):

    def __init__(self):
        self.queue = []
        self.recv_message = None

    def set_recv_message(self, data):
        self.recv_message = json.dumps(data)

    def send(self, data):
        data = json.loads(data)
        result = {"result": "Some result", "id": data["id"]}
        self.queue.append(json.dumps(result))

    def close(self):
        pass

    def recv(self):
        if self.queue:
            return self.queue.pop(0)
        if self.recv_message:
            return self.recv_message
        raise socket.error()


class Test_WSSessionManager_get_events(TestCase):

    def test_timeout_when_getting_events(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=_DummyWebsocket())):
            self.session_manager = WSSessionManager(1234, 1)

            self.session_manager.enable_domain("Network")
            with self.assertRaises(DevToolsTimeoutException):
                self.session_manager.messaging_thread.ws.set_recv_message(
                    {"method": "Network.Something", "params": {}}
                )
                time.sleep(1)
                self.session_manager.get_events("Network")


class Test_WSSessionManager_wait_for_result(TestCase):

    def test_no_messages_with_result_timeout(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=_DummyWebsocket())):
            self.session_manager = WSSessionManager(1234, 1)

            with self.assertRaises(DevToolsTimeoutException):
                self.session_manager._wait_for_result()

    def test_message_spamming_with_result_timeout(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=_DummyWebsocket())):
            self.session_manager = WSSessionManager(1234, 1)

            with self.assertRaises(DevToolsTimeoutException):
                self.session_manager.messaging_thread.ws.set_recv_message(
                    {"method": "Network.Something", "params": {}}
                )
                self.session_manager._wait_for_result()


class BlockingWS(_DummyWebsocket):

    blocked = 0

    def __init__(self, times_to_block=1):
        super(BlockingWS, self).__init__()
        self.times_to_block = times_to_block

    def recv(self):
        if BlockingWS.blocked < self.times_to_block:
            BlockingWS.blocked += 1
            while True:
                time.sleep(5)

        else:
            return super(BlockingWS, self).recv()


class ExceptionThrowingWS(_DummyWebsocket):

    exceptions = 0

    def __init__(self, times_to_except=1):
        super(ExceptionThrowingWS, self).__init__()
        self.times_to_except = times_to_except

    def recv(self):

        if ExceptionThrowingWS.exceptions < self.times_to_except:
            ExceptionThrowingWS.exceptions += 1
            raise websocket.WebSocketConnectionClosedException()

        else:
            return super(ExceptionThrowingWS, self).recv()


class Test_WSSessionManager_execute(TestCase):

    def setUp(self):
        ExceptionThrowingWS.exceptions = 0
        BlockingWS.blocked = 0
        time.sleep(0.1)

    def tearDown(self):
        ExceptionThrowingWS.exceptions = 0
        BlockingWS.blocked = 0
        time.sleep(0.1)

    def test_thread_blocked_once(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS())):

            self.session_manager = WSSessionManager(1234, 30)

            start = time.time()
            self.session_manager.execute("Network", "enable")

            # We should find the execution result after 10 seconds because
            # we give the thread 5 seconds to poll before we consider it blocked,
            # and then we give the thread a maximum of 5 seconds to finish before
            # we replace it
            self.assertAlmostEqual(10, time.time() - start, 0)

    def test_thread_blocked_twice(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS(times_to_block=2))):

            self.session_manager = WSSessionManager(1234, 30)

            start = time.time()
            self.session_manager.execute("Network", "enable")

            self.assertAlmostEqual(20, time.time() - start, 0)

    def test_thread_blocks_causes_timeout(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS())):

            self.session_manager = WSSessionManager(1234, 3)

            with self.assertRaises(DevToolsTimeoutException):
                start = time.time()
                self.session_manager.execute("Network", "enable")
                self.assertAlmostEqual(3, time.time() - start, 0)

    def test_max_thread_blocks_exceeded(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS(times_to_block=4))):

            self.session_manager = WSSessionManager(1234, 60)

            start = time.time()
            with self.assertRaises(MaxRetriesException):
                self.session_manager.execute("Network", "enable")
            self.assertAlmostEqual(40, time.time() - start, 0)

    def test_thread_died_once(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=ExceptionThrowingWS())):

            self.session_manager = WSSessionManager(1234, 60)

            start = time.time()
            self.session_manager.execute("Network", "enable")
            self.assertLess(time.time() - start, 1)

    def test_thread_died_twice(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=ExceptionThrowingWS(times_to_except=2))):

            self.session_manager = WSSessionManager(1234, 30)

            start = time.time()
            self.session_manager.execute("Network", "enable")
            self.assertLess(time.time() - start, 1)

    def test_thread_died_too_many_times(self):

        with patch.object(_WSMessagingThread, "_get_websocket",
                          new=MagicMock(return_value=ExceptionThrowingWS(times_to_except=4))):

            self.session_manager = WSSessionManager(1234, 30)

            start = time.time()
            with self.assertRaises(MaxRetriesException):
                self.session_manager.execute("Network", "enable")
            self.assertLess(time.time() - start, 1)
