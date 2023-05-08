import collections
import copy
import socket
import time
from unittest import TestCase
from unittest.mock import patch, MagicMock, call, PropertyMock

from websocket import WebSocketConnectionClosedException

from browserdebuggertools.exceptions import (
    DevToolsException,
    DomainNotEnabledError, DevToolsTimeoutException, MethodNotFoundError,
    InvalidParametersError, WebSocketBlockedException, MessagingThreadIsDeadError,
    MaxRetriesException
)
from browserdebuggertools.wssessionmanager import (
    WSSessionManager, _WSMessageProducer
)

MODULE_PATH = "browserdebuggertools.wssessionmanager."


class MockException(Exception):
    pass


class WSMessageProducerTest(TestCase):

    class MockWSMessageProducer(_WSMessageProducer):

        def _get_websocket(self):
            return MagicMock()

    def setUp(self):
        self.send_queue = collections.deque()
        self.messaging_thread = self.MockWSMessageProducer(1111, self.send_queue, MagicMock())
        self.ws_message_producer = self.messaging_thread


class SessionManagerTest(TestCase):

    class _NoWSSessionManager(WSSessionManager):

        def _setup_ws_session(self):
            self._message_producer = MagicMock(is_alive=MagicMock(return_value=False))

    def setUp(self):
        self.session_manager = self._NoWSSessionManager(1234, 30)


class Test___WSMessageProducer__get_websocket_url(WSMessageProducerTest):

    def setUp(self):
        super().setUp()
        self.messaging_thread._get_targets = MagicMock()
        self.messaging_thread._create_tab = MagicMock()
        self.mock_websocket_url = "ws://localhost:1234/devtools/page/test"

    def test_existing_targets(self):
        self.messaging_thread._get_targets.return_value = [
            {
                "type": "extension",
                "webSocketDebuggerUrl": "chrome://foo"
            },
            {
                "type": "page",
                "webSocketDebuggerUrl": self.mock_websocket_url
            },
            {
                "type": "page",
                "webSocketDebuggerUrl": "ws://bar"
            },
        ]

        websocket_url = self.messaging_thread._get_websocket_url()

        self.assertEqual(self.mock_websocket_url, websocket_url)
        self.messaging_thread._create_tab.assert_not_called()

    def test_create_tab(self):
        self.messaging_thread._get_targets.return_value = []
        self.messaging_thread._create_tab.return_value = {
            "type": "page",
            "webSocketDebuggerUrl": self.mock_websocket_url
        }

        websocket_url = self.messaging_thread._get_websocket_url()

        self.messaging_thread._get_targets.assert_called_once_with()
        self.messaging_thread._create_tab.assert_called_once_with()
        self.assertEqual(self.mock_websocket_url, websocket_url)


@patch(MODULE_PATH + "requests")
class Test___WSMessageProducer__get_targets(WSMessageProducerTest):

    def test_ok(self, requests):
        expected = [
            {
                "type": "extension",
                "webSocketDebuggerUrl": "chrome://foo"
            },
            {
                "type": "page",
                "webSocketDebuggerUrl": "ws://localhost:1234/devtools/page/test"
            }
        ]
        requests.get.return_value.ok = True
        requests.get.return_value.json.return_value = expected

        self.assertEqual(
            expected, self.messaging_thread._get_targets()
        )

    def test_not_ok_response(self, requests):
        requests.get.return_value.ok = False

        with self.assertRaises(DevToolsException):
            self.messaging_thread._get_targets()


@patch(MODULE_PATH + "requests")
class Test___WSMessageProducer__create_tab(WSMessageProducerTest):

    def test_ok(self, requests):
        expected = {
            "type": "page",
            "webSocketDebuggerUrl": "ws://localhost:1234/devtools/page/test"
        }
        requests.put.return_value.ok = True
        requests.put.return_value.json.return_value = expected

        self.assertEqual(
            expected, self.messaging_thread._create_tab()
        )

    def test_not_ok_response(self, requests):
        requests.put.return_value.ok = False

        with self.assertRaises(DevToolsException):
            self.messaging_thread._create_tab()


class Test__WSMessageProducer__empty_send_queue(WSMessageProducerTest):

    def test(self):
        message1, message2, message3 = MagicMock(), MagicMock(), MagicMock()
        self.ws_message_producer._send_queue.append(message1)
        self.ws_message_producer._send_queue.append(message2)
        self.ws_message_producer._send_queue.append(message3)

        self.ws_message_producer._empty_send_queue()

        self.assertListEqual([
            call.send(message1),
            call.send(message2),
            call.send(message3)
        ], self.ws_message_producer.ws.mock_calls)
        self.assertFalse(self.ws_message_producer._send_queue)

    def test_fail(self):
        message1, message2, message3 = MagicMock(), MagicMock(), MagicMock()
        self.ws_message_producer._send_queue.append(message1)
        self.ws_message_producer._send_queue.append(message2)
        self.ws_message_producer._send_queue.append(message3)
        self.ws_message_producer.ws.send.side_effect = [None, MockException(), None]

        with self.assertRaises(MockException):
            self.ws_message_producer._empty_send_queue()

        self.assertListEqual([
            call.send(message1),
            call.send(message2),
        ], self.ws_message_producer.ws.mock_calls)
        self.assertListEqual([
            message2,
            message3,
        ], list(self.ws_message_producer._send_queue))


class Test__WSMessageProducer__empty_websocket(WSMessageProducerTest):

    def setUp(self):
        super(Test__WSMessageProducer__empty_websocket, self).setUp()
        self.message1 = '{"1": "foo"}'
        self.message2 = '{"2": "foo"}'
        self.message3 = '{"3": "foo"}'
        self.message4 = '{"4": "foo"}'
        self.processed_messages = []

        def callback(message):
            self.processed_messages.append(message)

        self.ws_message_producer._on_message = callback

    def test(self):


        self.ws_message_producer.ws.recv.side_effect = [
            self.message1, self.message2, self.message3,
            socket.error("[Errno 11] Resource temporarily unavailable"),
        ]

        self.ws_message_producer._empty_websocket()

        self.assertListEqual([
            {"1": "foo"},
            {"2": "foo"},
            {"3": "foo"},
        ], self.processed_messages)

    def test_other_socket_error(self):
        self.ws_message_producer.ws.recv.side_effect = [
            self.message1, self.message2, socket.error(), self.message3
        ]

        with self.assertRaises(socket.error):
            self.ws_message_producer._empty_websocket()

        self.assertListEqual([
            {"1": "foo"},
            {"2": "foo"},
        ], self.processed_messages)

    def test_fail(self):
        self.ws_message_producer.ws.recv.side_effect = [
            self.message1, self.message2, MockException(), self.message3
        ]

        with self.assertRaises(MockException):
            self.ws_message_producer._empty_websocket()

        self.assertListEqual([
            {"1": "foo"},
            {"2": "foo"},
        ], self.processed_messages)


@patch(MODULE_PATH + "_WSMessageProducer._empty_send_queue", MagicMock())
@patch(MODULE_PATH + "_WSMessageProducer._empty_websocket", MagicMock())
class Test__WSMessageProducer_run(WSMessageProducerTest):

    def prepare(self, time_):
        self.next_time = 0

        def increment_time():
            current_time = self.next_time
            self.next_time += 1
            if current_time == 10:
                self.ws_message_producer.stop()

            return current_time

        time_.time = increment_time

    @patch(MODULE_PATH + "_WSMessageProducer._POLL_INTERVAL", 0)
    @patch(MODULE_PATH + "time")
    def test(self, time_):
        self.prepare(time_)

        self.ws_message_producer.run()

        self.assertEqual(10, self.ws_message_producer._last_ws_attempt)

    @patch(MODULE_PATH + "_WSMessageProducer._POLL_INTERVAL", 0)
    @patch(MODULE_PATH + "time")
    def test_exception(self, time_):
        exception = Exception()
        self.ws_message_producer._empty_send_queue.side_effect = exception
        self.prepare(time_)

        self.ws_message_producer.run()

        self.assertEqual(0, self.ws_message_producer._last_ws_attempt)
        self.assertEqual(exception, self.ws_message_producer.exception)

    def test_wait_timeout(self):

        def _stop():
            self.ws_message_producer._continue = False

        self.ws_message_producer._empty_send_queue = MagicMock()
        self.ws_message_producer._empty_websocket.side_effect = _stop
        self.ws_message_producer.poll_signal.clear = MagicMock()
        start = time.time()

        self.ws_message_producer.run()

        self.assertGreater(time.time() - start, 1)
        self.ws_message_producer.poll_signal.clear.assert_not_called()

    def test_poll_signal_set(self):

        def _stop():
            self.ws_message_producer._continue = False

        self.ws_message_producer._empty_send_queue = MagicMock()
        self.ws_message_producer._empty_websocket.side_effect = _stop
        self.ws_message_producer.poll_signal.set()
        self.ws_message_producer.poll_signal.clear = MagicMock()

        start = time.time()
        self.ws_message_producer.run()

        self.assertLess(time.time() - start, 1)
        self.ws_message_producer.poll_signal.clear.assert_called_once_with()


class Test__WSMessagingThread_blocked(WSMessageProducerTest):

    def test_thread_not_started(self):

        self.messaging_thread._last_ws_attempt = None

        self.assertFalse(self.messaging_thread.blocked)

    @patch("browserdebuggertools.wssessionmanager.time")
    def test_thread_blocked(self, _time):

        now = 100
        _time.time.return_value = now

        self.messaging_thread._last_ws_attempt = now - self.messaging_thread._BLOCKED_TIMEOUT - 1

        self.assertTrue(self.messaging_thread.blocked)

    @patch("browserdebuggertools.wssessionmanager.time")
    def test_thread_not_blocked(self, _time):

        now = 100
        _time.time.return_value = now

        self.messaging_thread._last_ws_attempt = now - self.messaging_thread._BLOCKED_TIMEOUT + 1

        self.assertFalse(self.messaging_thread.blocked)


@patch(MODULE_PATH + "_WSMessageProducer.is_alive", MagicMock())
class Test__WSMessageProducer_health_check(WSMessageProducerTest):

    @patch(MODULE_PATH + "_WSMessageProducer.blocked", new_callable=PropertyMock)
    def test_fine(self, blocked):
        self.ws_message_producer.is_alive.return_value = True
        blocked.return_value = False

        self.ws_message_producer.health_check()

    @patch(MODULE_PATH + "_WSMessageProducer.close", MagicMock())
    @patch(MODULE_PATH + "_WSMessageProducer.blocked", new_callable=PropertyMock)
    def test_blocked(self, blocked):
        self.ws_message_producer.is_alive.return_value = True
        blocked.return_value = True

        with self.assertRaises(WebSocketBlockedException):
            self.ws_message_producer.health_check()

        self.ws_message_producer.close.assert_called_once_with()

    def test_stopped_with_exception(self):
        self.ws_message_producer.is_alive.return_value = False
        self.ws_message_producer.exception = MockException()

        with self.assertRaises(MockException):
            self.ws_message_producer.health_check()

    def test_stopped_no_exception(self):
        self.ws_message_producer.is_alive.return_value = False
        self.ws_message_producer.exception = None

        with self.assertRaises(MessagingThreadIsDeadError):
            self.ws_message_producer.health_check()


class Test_WSSessionManager__process_message(SessionManagerTest):

    def test_result(self):
        mock_result = MagicMock()
        message = {"id": 1, "result": mock_result}

        self.session_manager._process_message(message)

        self.assertEqual(mock_result, self.session_manager._results[1])

    def test_error(self):
        mock_result = MagicMock()
        mock_error = {"error": mock_result}
        message = {"id": 1, "error": mock_result}

        self.session_manager._process_message(message)

        self.assertEqual(mock_error, self.session_manager._results[1])

    def test_event(self):
        self.session_manager._events["MockDomain"] = []
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.session_manager._process_message(mock_event)

        self.assertIn(mock_event, self.session_manager._events["MockDomain"])

    def test_internal_event(self):
        self.session_manager._events["MockDomain"] = []
        mock_event_handler = MagicMock()
        self.session_manager.event_handlers = {
            "MockEvent": mock_event_handler
        }
        self.session_manager._internal_events = {"MockDomain.mockMethod": mock_event_handler}
        mock_event = {"method": "MockDomain.mockMethod", "params": MagicMock}

        self.session_manager._process_message(mock_event)

        self.assertIn(mock_event, self.session_manager._events["MockDomain"])
        self.assertTrue(mock_event_handler.handle.called)


@patch(MODULE_PATH + "websocket.send", MagicMock())
class Test_WSSessionManager_execute(SessionManagerTest):

    def test(self):

        domain = "Page"
        method = "navigate"

        self.session_manager._wait_for_result = MagicMock()
        self.session_manager._send = MagicMock()
        self.session_manager._next_result_id = 3

        self.session_manager.execute(domain, method, None)

        self.assertEqual(4, self.session_manager._next_result_id)
        self.session_manager._wait_for_result.assert_called_once_with(4)
        self.session_manager._send.assert_called_once_with({
            "id": 4, "method": "%s.%s" % (domain, method), "params": {}
        })

    @patch(MODULE_PATH + "WSSessionManager._execute", new=MagicMock())
    def test_error(self):

        self.session_manager._wait_for_result = MagicMock(
            return_value={"error": {"code": -32602, "message": "Invalid interceptionId"}}
        )

        with self.assertRaises(InvalidParametersError):
            self.session_manager.execute(MagicMock(), MagicMock(), None)


class Test_WSSessionManager_add_domain(SessionManagerTest):

    def test_new_domain(self):
        self.session_manager._domains = {}
        self.session_manager._add_domain("MockDomain", {})

        self.assertEqual({"MockDomain": {}}, self.session_manager._domains)
        self.assertEqual({"MockDomain": []}, self.session_manager._events)

    def test_existing_domain(self):
        self.session_manager._domains = {"MockDomain": {}}
        mock_events = [MagicMock(), MagicMock()]
        self.session_manager._events["MockDomain"] = mock_events
        self.session_manager._add_domain("MockDomain", {"test": 1})

        self.assertEqual({"MockDomain": {}}, self.session_manager._domains)
        self.assertEqual({"MockDomain": mock_events}, self.session_manager._events)


class Test_WSSessionManager_remove_domain(SessionManagerTest):

    def test_existing_domain(self):

        domain = "MockDomain"

        self.session_manager._domains = {domain: {}}
        self.session_manager._events = {domain: []}

        self.session_manager._remove_domain(domain)

        self.assertEqual(self.session_manager._domains, {})
        self.assertEqual(self.session_manager._events, {})

    def test_invalid(self):

        domain = "MockDomain"

        self.session_manager._domains = {domain: {}}
        self.session_manager._events = {domain: []}

        self.session_manager._remove_domain("InvalidMockDomain")

        self.assertEqual(self.session_manager._domains, {domain: {}})
        self.assertEqual(self.session_manager._events, {domain: []})


class Test_WSSessionManager_get_events(SessionManagerTest):

    def setUp(self):
        super(Test_WSSessionManager_get_events, self).setUp()
        self.domain = "MockDomain"
        self.session_manager._domains = {self.domain: {}}

    @patch(MODULE_PATH + "WSSessionManager._check_message_producer")
    def test_no_clear(self, _check_message_producer):

        self.mock_events = {self.domain: [MagicMock()]}
        self.session_manager._events = self.mock_events

        events = self.session_manager.get_events(self.domain)

        self.assertEqual(self.mock_events[self.domain], events)
        self.assertEqual(self.mock_events, self.session_manager._events)

    def test_domain_not_enabled(self):
        self.session_manager._domains = {}
        with self.assertRaises(DomainNotEnabledError):
            self.session_manager.get_events("MockDomain")

    @patch(MODULE_PATH + "WSSessionManager._check_message_producer")
    def test_clear(self, _check_message_producer):

        self.mock_events = {self.domain: [MagicMock()]}
        self.session_manager._events = copy.deepcopy(self.mock_events)

        events = self.session_manager.get_events(self.domain, clear=True)

        self.assertEqual(self.mock_events[self.domain], events)
        self.assertEqual([], self.session_manager._events[self.domain])


class Test_wssessionmanager_reset(SessionManagerTest):

    def test(self):
        self.session_manager.domains = ["Page", "Network"]
        self.session_manager._events = {
            "Page": [MagicMock(), MagicMock()],
            "Network": [MagicMock(), MagicMock()]
        }
        self.session_manager._results = {1: MagicMock()}
        self.session_manager._next_result_id = 2
        self.session_manager._send_queue.append(MagicMock())

        self.session_manager.reset()

        for key, value in self.session_manager._events.items():
            self.assertEqual([], value)
        self.assertFalse(self.session_manager._results)
        self.assertEqual(0, self.session_manager._next_result_id)
        self.assertFalse(self.session_manager._send_queue)


@patch(MODULE_PATH + "WSSessionManager.execute")
@patch(MODULE_PATH + "WSSessionManager._add_domain")
class Test_WSSessionManager_enable_domain(SessionManagerTest):

    def test_no_parameters(self, _add_domain, execute):

        domain_name = "Network"

        self.session_manager.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_called_once_with(domain_name, {})

    def test_with_parameters(self, _add_domain, execute):

        domain_name = "Network"
        parameters = {"some": "param"}

        self.session_manager.enable_domain(domain_name, parameters=parameters)

        execute.assert_called_once_with(domain_name, "enable", parameters)
        _add_domain.assert_called_once_with(domain_name, parameters)

    def test_invalid_domain(self, _add_domain, execute):

        domain_name = "Network"
        execute.side_effect = [MethodNotFoundError("Domain not found")]

        with self.assertRaises(MethodNotFoundError):
            self.session_manager.enable_domain(domain_name)

        execute.assert_called_once_with(domain_name, "enable", {})
        _add_domain.assert_not_called()


class Test_WSSessionManager_wait_for_result(SessionManagerTest):

    @patch(MODULE_PATH + "_Timer", new=MagicMock(return_value=MagicMock(timed_out=False)))
    def test_succeed_immediately(self):
        mock_result = MagicMock()
        self.session_manager._results[1] = mock_result

        result = self.session_manager._wait_for_result(1)
        self.assertEqual(mock_result, result)

    @patch(MODULE_PATH + "time")
    @patch(MODULE_PATH + "_Timer", new=MagicMock(return_value=MagicMock(timed_out=False)))
    def test_wait_and_then_succeeed(self, time):
        mock_result = MagicMock()
        self.session_manager._results = {}

        def sleep(wait):
            self.session_manager._results[1] = mock_result

        time.sleep = sleep

        self.session_manager.timer = MagicMock(timed_out=False)

        result = self.session_manager._wait_for_result(1)

        self.assertEqual(mock_result, result)

    @patch(MODULE_PATH + "_Timer", new=MagicMock(return_value=MagicMock(timed_out=True)))
    def test_timed_out(self):
        self.session_manager.timer = MagicMock(timed_out=True)
        with self.assertRaises(DevToolsTimeoutException):
            self.session_manager._wait_for_result(1)


@patch(MODULE_PATH + "WSSessionManager._increment_message_producer_not_ok")
class Test_WSSessionManager__check_message_producer(SessionManagerTest):

    def setUp(self):
        super(Test_WSSessionManager__check_message_producer, self).setUp()
        self.session_manager._setup_ws_session = MagicMock()

    def test_ws_closed(self, _increment_message_producer_not_ok):
        self.session_manager._message_producer.health_check.side_effect = \
            WebSocketConnectionClosedException

        self.session_manager._check_message_producer()

        self.session_manager._increment_message_producer_not_ok.assert_called_once_with()
        self.session_manager._setup_ws_session.assert_called_once_with()

    def test_ws_blocked(self, _increment_message_producer_not_ok):
        self.session_manager._message_producer.health_check.side_effect = WebSocketBlockedException

        self.session_manager._check_message_producer()

        self.session_manager._increment_message_producer_not_ok.assert_called_once_with()
        self.session_manager._setup_ws_session.assert_called_once_with()

    def test_other_failure(self, _increment_message_producer_not_ok):
        self.session_manager._message_producer.health_check.side_effect = MockException()

        with self.assertRaises(MockException):
            self.session_manager._check_message_producer()


@patch(MODULE_PATH + "time.time", MagicMock(return_value=100))
class Test_WSSessionManager__increment_message_producer_not_ok(SessionManagerTest):

    def setUp(self):
        super(Test_WSSessionManager__increment_message_producer_not_ok, self).setUp()
        self.session_manager.MAX_RETRY_THREADS = 3
        self.session_manager.RETRY_COUNT_TIMEOUT = 300

    def test_first_run_on_ws(self):
        self.session_manager._last_not_ok = None

        self.session_manager._increment_message_producer_not_ok()

        self.assertEqual(100, self.session_manager._last_not_ok)
        self.assertEqual(1, self.session_manager._message_producer_not_ok_count)

    def test_increment(self):
        self.session_manager._last_not_ok = 49
        self.session_manager._message_producer_not_ok_count = 1

        self.session_manager._increment_message_producer_not_ok()

        self.assertEqual(100, self.session_manager._last_not_ok)
        self.assertEqual(2, self.session_manager._message_producer_not_ok_count)

    def test_timeout_expired(self):
        self.session_manager.RETRY_COUNT_TIMEOUT = 50
        self.session_manager._last_not_ok = 49
        self.session_manager._message_producer_not_ok_count = 3

        self.session_manager._increment_message_producer_not_ok()

        self.assertEqual(100, self.session_manager._last_not_ok)
        self.assertEqual(1, self.session_manager._message_producer_not_ok_count)

    def test_exceeded_max_failures(self):
        self.session_manager._last_not_ok = 49
        self.session_manager._message_producer_not_ok_count = 3
        self.session_manager._exception = None

        with self.assertRaises(MaxRetriesException):
            self.session_manager._increment_message_producer_not_ok()

        self.assertEqual(100, self.session_manager._last_not_ok)
        self.assertEqual(4, self.session_manager._message_producer_not_ok_count)


@patch(MODULE_PATH + "logging")
class Test_WSMessageProducer_ws_io(WSMessageProducerTest):

    def test_WebSocketConnectionClosedException(self, _logging):
        self.ws_message_producer.close = MagicMock()

        with self.ws_message_producer._ws_io():
            raise WebSocketConnectionClosedException("foo")

        _logging.warning.assert_called_once_with(
            "WS messaging thread terminated due to closed connection"
        )
        self.ws_message_producer.close.assert_called_once_with()

    def test_other_exception(self, _logging):
        self.ws_message_producer.close = MagicMock()

        e = Exception("foo")

        with self.ws_message_producer._ws_io():
            raise e

        _logging.warning.assert_called_once_with(
            "WS messaging thread terminated with exception", exc_info=True
        )
        self.ws_message_producer.close.assert_called_once_with()
        self.assertEqual(e, self.ws_message_producer.exception)
