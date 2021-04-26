import json
import socket
import time
from unittest import TestCase
from multiprocessing.pool import ThreadPool

import websocket
from mock import MagicMock, patch

from browserdebuggertools.exceptions import DevToolsTimeoutException, MaxRetriesException
from browserdebuggertools.wssessionmanager import (
    WSSessionManager, _WSMessageProducer, NotifiableDeque
)

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

    def unblock(self):
        pass

    def close(self):
        pass

    def recv(self):
        if self.queue:
            return self.queue.pop(0)
        if self.recv_message:
            return self.recv_message
        raise socket.error("[Errno 11] Resource temporarily unavailable")


class FullWebSocket(_DummyWebsocket):

    def send(self, data):
        super(FullWebSocket, self).send(data)
        for i in range(9999):
            result = {"method": "Network.Something", "params": {"index": i}}
            self.queue.append(json.dumps(result))


class Test_WSSessionManager__execute(TestCase):
    """ It's very hard to make this test fail but it will catch major regressions
    """
    def setUp(self):
        self.pool = ThreadPool(10)

    def tearDown(self):
        self.pool.close()

    def continually_send(self, key):
        for i in range(500):
            self.session_manager._execute("foo", "bar")

    def test_no_dupe_ids(self):
        with patch.object(
            _WSMessageProducer, "_get_websocket", new=MagicMock(return_value=_DummyWebsocket())
        ):
            self.session_manager = WSSessionManager(1234, 1, {"Network": {}})
            self.ids = []

            def _send(message):
                self.ids.append(message["id"])

            self.session_manager._send = _send

            self.pool.map(self.continually_send, range(10))
            time.sleep(5)

            self.assertEqual(len(set(self.ids)), len(self.ids))


class Test_WSSessionManager_get_events(TestCase):
    """ It's very hard to make this test fail but it will catch major regressions
    """

    def test_locked_get_events(self):
        self.ws = FullWebSocket()
        with patch.object(
            _WSMessageProducer, "_get_websocket", new=MagicMock(return_value=self.ws)
        ):
            NotifiableDeque._MAX_QUEUE_BUFFER = 9999
            self.session_manager = WSSessionManager(1234, 1, {"Network": {}})

            events = list(reversed(self.session_manager.get_events("Network", clear=True)))

            while self.session_manager._message_producer.ws.queue:
                # Wait until all messages have been processed
                pass

            # make sure we don't lose any
            last_event_collected = events[0]
            next_event = {"method": "Network.Something", "params": {"index": -1}}
            first_event = {"method": "Network.Something", "params": {"index": -1}}
            if self.session_manager._events["Network"]:
                first_event = self.session_manager._events["Network"][0]

            assert (
                last_event_collected["params"]["index"] == next_event["params"]["index"] - 1
                or last_event_collected["params"]["index"] == first_event["params"]["index"] - 1
            )


class Test_WSSessionManager_wait_for_result(TestCase):

    def test_no_messages_with_result_timeout(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=_DummyWebsocket())):
            self.session_manager = WSSessionManager(1234, 1)

            with self.assertRaises(DevToolsTimeoutException):
                self.session_manager._wait_for_result(99)

    def test_message_spamming_with_result_timeout(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=_DummyWebsocket())):
            self.session_manager = WSSessionManager(1234, 1)

            with self.assertRaises(DevToolsTimeoutException):
                self.session_manager._message_producer.ws.set_recv_message(
                    {"method": "Network.Something", "params": {}}
                )
                self.session_manager._wait_for_result(99)


class BlockingWS(_DummyWebsocket):

    blocked = 0

    def __init__(self, times_to_block=1):
        super(BlockingWS, self).__init__()
        self.times_to_block = times_to_block
        self._continue = True

    def recv(self):
        if BlockingWS.blocked < self.times_to_block:
            BlockingWS.blocked += 1
            while self._continue:
                time.sleep(0.1)

        return super(BlockingWS, self).recv()

    def unblock(self):
        self._continue = False


class ExceptionThrowingWS(_DummyWebsocket):

    exceptions = 0

    def __init__(self, times_to_except=1):
        super(ExceptionThrowingWS, self).__init__()
        self.times_to_except = times_to_except

    def recv(self):

        if ExceptionThrowingWS.exceptions < self.times_to_except:
            ExceptionThrowingWS.exceptions += 1
            time.sleep(1)
            raise websocket.WebSocketConnectionClosedException()

        else:
            return super(ExceptionThrowingWS, self).recv()

    def close(self):
        pass


class Test_WSSessionManager_execute(TestCase):

    def resetWS(self):
        """ flush_messages runs async so we only want the socket to start blocking when we're
            ready
        """
        ExceptionThrowingWS.exceptions = 0
        BlockingWS.blocked = 0

    def setUp(self):
        """ We don't want the socket to block before we call execute()
        """
        ExceptionThrowingWS.exceptions = 2
        BlockingWS.blocked = 2

    def tearDown(self):
        self.session_manager._message_producer.ws.unblock()
        self.session_manager.close()

    def test_thread_blocked_once(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS(times_to_block=1))):

            self.session_manager = WSSessionManager(1234, 30)

            start = time.time()
            self.session_manager.execute("Network", "enable")

            # We should find the execution result after 5 seconds because
            # we give the thread 5 seconds to poll before we consider it blocked,
            self.assertLess(time.time() - start, 10)

    def test_thread_blocked_twice(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS(times_to_block=2))):

            self.session_manager = WSSessionManager(1234, 30)
            self.resetWS()
            start = time.time()
            self.session_manager.execute("Network", "enable")

            self.assertLess(time.time() - start, 15)

    def test_thread_blocks_causes_timeout(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS(times_to_block=1))):

            self.session_manager = WSSessionManager(1234, 3)
            self.resetWS()
            with self.assertRaises(DevToolsTimeoutException):
                start = time.time()
                self.session_manager.execute("Network", "enable")
                self.assertLess(time.time() - start, 5)

    def test_max_thread_blocks_exceeded(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=BlockingWS(times_to_block=4))):

            self.session_manager = WSSessionManager(1234, 60)
            self.resetWS()
            start = time.time()
            with self.assertRaises(MaxRetriesException):
                self.session_manager.execute("Network", "enable")

            self.assertLess(time.time() - start, 25)

    def test_thread_died_once(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=ExceptionThrowingWS())):

            self.session_manager = WSSessionManager(1234, 60)
            self.resetWS()
            start = time.time()
            self.session_manager.execute("Network", "enable")
            self.assertLess(time.time() - start, 10)

    def test_thread_died_twice(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=ExceptionThrowingWS(times_to_except=2))):

            self.session_manager = WSSessionManager(1234, 30)
            self.resetWS()
            start = time.time()
            self.session_manager.execute("Network", "enable")
            self.assertLess(time.time() - start, 10)

    def test_thread_died_too_many_times(self):

        with patch.object(_WSMessageProducer, "_get_websocket",
                          new=MagicMock(return_value=ExceptionThrowingWS(times_to_except=4))):

            self.session_manager = WSSessionManager(1234, 30)

            self.resetWS()
            start = time.time()
            with self.assertRaises(MaxRetriesException):
                self.session_manager.execute("Network", "enable")
            self.assertLess(time.time() - start, 10)
