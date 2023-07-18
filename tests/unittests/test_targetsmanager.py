import collections
import copy
import socket
import unittest

import pytest
import time
from unittest import TestCase
from unittest.mock import patch, MagicMock, call, PropertyMock

from typing import Dict
from websocket import WebSocketConnectionClosedException

from browserdebuggertools.exceptions import (
    DevToolsException,
    DomainNotEnabledError, DevToolsTimeoutException, MethodNotFoundError,
    InvalidParametersError, WebSocketBlockedException, MessagingThreadIsDeadError,
    MaxRetriesException, ResourceNotFoundError
)
from browserdebuggertools.targetsmanager import (
    _WSSessionManager, _WSMessageProducer, TargetsManager, _Target, _DOMManager
)

MODULE_PATH = "browserdebuggertools.targetsmanager."


@pytest.fixture()
def ws():
    _ws = MagicMock()
    _ws.side_effect = [
        '{"foo": "bar"}'
    ]
    return _ws


@pytest.fixture()
def producer(ws):
    with patch(MODULE_PATH + "websocket.create_connection"):
        p = _WSMessageProducer("wss://foo.com", MagicMock(), MagicMock())
        p.ws = ws
    return p


@pytest.fixture()
def wssessionmanager(producer):
    with patch(MODULE_PATH + "_WSMessageProducer"):
        w = _WSSessionManager("wss://foo.com", 30)
        w._message_producer = producer
    return w


@pytest.fixture()
def target_info():
    class InfoFactory:

        def __init__(self):
            self._id = 0

        def get(self):
            self._id += 1
            return {
                "id": f"{self._id}",
                "type": "page",
                "webSocketDebuggerUrl": f"ws://localhost:9222/devtools/page/{self._id}"
            }
    return InfoFactory()


class _TestTarget(_Target):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wsm: MagicMock = MagicMock(timeout=10)
        self.dom_manager: MagicMock = MagicMock()


@pytest.fixture()
def target(target_info):

    class TargetFactory:
        @staticmethod
        def get():
            return _TestTarget(target_info.get(), 10, domains={"Network": {}, "Page": {}})

    return TargetFactory()


@pytest.fixture
def targets_manager(target, target_info):

    class _TargetsManager(TargetsManager):

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._targets: Dict[str, _TestTarget] = {}
            while len(self._targets) < 5:
                t = target.get()
                self._targets[t.id] = t
            self.current_target_id = next(iter(self._targets.keys()))

        def _get_targets(self):
            return [target_info.get(), target_info.get()]

    return _TargetsManager(10, 9222)


class MockException(Exception):
    pass


class WSMessageProducerTest(TestCase):

    class MockWSMessageProducer(_WSMessageProducer):

        def _get_websocket(self):
            return MagicMock()



    def setUp(self):
        self.send_queue = collections.deque()
        self.messaging_thread = self.MockWSMessageProducer(
            "localhost:1111", self.send_queue, MagicMock()
        )
        self.ws_message_producer = self.messaging_thread


class SessionManagerTest(TestCase):

    class _NoWSSessionManager(_WSSessionManager):

        def _setup_ws_session(self):
            self._message_producer = MagicMock(is_alive=MagicMock(return_value=False))

    def setUp(self):
        self.session_manager = self._NoWSSessionManager(1234, "10")


@patch(MODULE_PATH + "requests")
class Test_TargetsManager__get_targets(unittest.TestCase):

    def setUp(self):
        self._targetsManager = TargetsManager(10, 9222)

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
            expected, self._targetsManager._get_targets()
        )

    def test_not_ok_response(self, requests):
        requests.get.return_value.ok = False

        with self.assertRaises(DevToolsException):
            self._targetsManager._get_targets()


@patch(MODULE_PATH + "requests")
class Test_TargetsManager__create_tab(WSMessageProducerTest):

    def setUp(self):
        self._targets_manager = TargetsManager(10, 9222)

    def test_ok(self, requests):
        expected = {
            "type": "page",
            "webSocketDebuggerUrl": "ws://localhost:1234/devtools/page/test"
        }
        requests.put.return_value.ok = True
        requests.put.return_value.json.return_value = expected

        self.assertEqual(
            expected, self._targets_manager._create_tab()
        )

    def test_not_ok_response(self, requests):
        requests.put.return_value.ok = False

        with self.assertRaises(DevToolsException):
            self._targets_manager._create_tab()


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

    @patch("browserdebuggertools.targetsmanager.time")
    def test_thread_blocked(self, _time):

        now = 100
        _time.time.return_value = now

        self.messaging_thread._last_ws_attempt = now - self.messaging_thread._BLOCKED_TIMEOUT - 1

        self.assertTrue(self.messaging_thread.blocked)

    @patch("browserdebuggertools.targetsmanager.time")
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

    @patch(MODULE_PATH + "_WSMessageProducer.close")
    @patch(MODULE_PATH + "_WSMessageProducer.blocked", new_callable=PropertyMock)
    def test_blocked(self, close, blocked):
        self.ws_message_producer.is_alive.return_value = True
        blocked.return_value = True

        with self.assertRaises(WebSocketBlockedException):
            self.ws_message_producer.health_check()

        close.assert_called_once_with()

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

    @patch(MODULE_PATH + "_WSSessionManager._execute", new=MagicMock())
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

    @patch(MODULE_PATH + "_WSSessionManager._check_message_producer")
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

    @patch(MODULE_PATH + "_WSSessionManager._check_message_producer")
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


@patch(MODULE_PATH + "_WSSessionManager.execute")
@patch(MODULE_PATH + "_WSSessionManager._add_domain")
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
    def test_wait_and_then_succeed(self, mock_time):
        mock_result = MagicMock()
        self.session_manager._results = {}

        def sleep(_wait):
            self.session_manager._results[1] = mock_result

        mock_time.sleep = sleep

        self.session_manager.timer = MagicMock(timed_out=False)

        result = self.session_manager._wait_for_result(1)

        self.assertEqual(mock_result, result)

    @patch(MODULE_PATH + "_Timer", new=MagicMock(return_value=MagicMock(timed_out=True)))
    def test_timed_out(self):
        self.session_manager.timer = MagicMock(timed_out=True)
        with self.assertRaises(DevToolsTimeoutException):
            self.session_manager._wait_for_result(1)


@patch(MODULE_PATH + "_WSSessionManager._increment_message_producer_not_ok")
class Test_WSSessionManager__check_message_producer(SessionManagerTest):

    def setUp(self):
        super(Test_WSSessionManager__check_message_producer, self).setUp()
        self.setup_ws_session = patch.object(self.session_manager, "_setup_ws_session").start()

    def test_ws_closed(self, _increment_message_producer_not_ok):
        self.session_manager._message_producer.health_check.side_effect = \
            WebSocketConnectionClosedException

        self.session_manager._check_message_producer()

        _increment_message_producer_not_ok.assert_called_once_with()
        self.setup_ws_session.assert_called_once_with()

    def test_ws_blocked(self, _increment_message_producer_not_ok):
        self.session_manager._message_producer.health_check.side_effect = WebSocketBlockedException

        self.session_manager._check_message_producer()

        _increment_message_producer_not_ok.assert_called_once_with()
        self.setup_ws_session.assert_called_once_with()

    def test_other_failure(self, _increment_message_producer_not_ok):
        self.session_manager._message_producer.health_check.side_effect = MockException()

        with self.assertRaises(MockException):
            self.session_manager._check_message_producer()


@patch(MODULE_PATH + "time.time", MagicMock(return_value=100))
class Test_WSSessionManager__increment_message_producer_not_ok:

    @pytest.fixture()
    def _wssessionmanager(self, wssessionmanager):
        wssessionmanager.MAX_RETRY_THREADS = 3
        wssessionmanager.RETRY_COUNT_TIMEOUT = 300
        return wssessionmanager

    def test_first_run_on_ws(self, _wssessionmanager):
        _wssessionmanager._last_not_ok = None

        _wssessionmanager._increment_message_producer_not_ok()

        assert 100 == _wssessionmanager._last_not_ok
        assert 1 == _wssessionmanager._message_producer_not_ok_count

    def test_increment(self, _wssessionmanager):

        _wssessionmanager._last_not_ok = 49
        _wssessionmanager._message_producer_not_ok_count = 1

        _wssessionmanager._increment_message_producer_not_ok()

        assert 100 == _wssessionmanager._last_not_ok
        assert 2 == _wssessionmanager._message_producer_not_ok_count

    def test_timeout_expired(self, _wssessionmanager):
        _wssessionmanager.RETRY_COUNT_TIMEOUT = 50
        _wssessionmanager._last_not_ok = 49
        _wssessionmanager._message_producer_not_ok_count = 3

        _wssessionmanager._increment_message_producer_not_ok()

        assert 100 == _wssessionmanager._last_not_ok
        assert 1 == _wssessionmanager._message_producer_not_ok_count

    def test_exceeded_max_failures(self, _wssessionmanager):
        _wssessionmanager._last_not_ok = 49
        _wssessionmanager._message_producer_not_ok_count = 3
        _wssessionmanager._exception = None

        with pytest.raises(MaxRetriesException):
            _wssessionmanager._increment_message_producer_not_ok()

        assert 100 == _wssessionmanager._last_not_ok
        assert 4 == _wssessionmanager._message_producer_not_ok_count


@patch(MODULE_PATH + "logging")
class Test_WSMessageProducer_ws_io:

    @pytest.fixture
    def _producer(self, producer):
        self._close = patch.object(producer, "close").start()
        return producer

    def test_WebSocketConnectionClosedException(self, _logging, _producer):
        with _producer._ws_io():
            raise WebSocketConnectionClosedException("foo")

        _logging.warning.assert_called_once_with(
            "WS messaging thread terminated due to closed connection"
        )
        self._close.assert_called_once_with()

    def test_other_exception(self, _logging, _producer):

        e = Exception("foo")

        with _producer._ws_io():
            raise e

        _logging.warning.assert_called_once_with(
            "WS messaging thread terminated with exception", exc_info=True
        )
        self._close.assert_called_once_with()
        assert e == _producer.exception


class Test_TargetsManager_set_timeout:

    def test(self, targets_manager):
        assert targets_manager.current_target.wsm.timeout == 10
        with targets_manager.set_timeout(333):
            assert targets_manager.current_target.wsm.timeout == 333
        assert targets_manager.current_target.wsm.timeout == 10


class Test_TargetsManager_refresh_targets:

    @staticmethod
    def _check(expected: Dict[str, dict], actual: Dict[str, _Target]):
        assert expected.keys() == actual.keys()
        for id_ in expected:
            assert expected[id_] == actual[id_].info

    def test(self, targets_manager):
        patch.object(_Target, "attach", MagicMock()).start()
        expected = {
            '1': {
                "id": "1", "type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"
            },
            '2': {
                'id': '2', 'type': 'page', 'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/page/2'
            },
            '3': {
                'id': '3', 'type': 'page', 'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/page/3'
            },
            '4': {
                'id': '4', 'type': 'page', 'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/page/4'
            },
            '5': {
                'id': '5', 'type': 'page', 'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/page/5'
            }
        }
        self._check(actual=targets_manager.targets, expected=expected)
        targets_manager.refresh_targets()
        expected = {
            '6': {
                'id': '6', 'type': 'page', 'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/page/6'
            },
            '7': {
                'id': '7', 'type': 'page', 'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/page/7'
            }
        }
        self._check(actual=targets_manager.targets, expected=expected)


class Test_TargetsManager_get_all_events:

    def test(self, targets_manager):
        get_events1 = patch.object(targets_manager._targets["1"].wsm, "get_events").start()
        get_events1.return_value = [{
            "method": "Network.requestWillBeSent", "params": {"requestId": "1"}
        }]
        get_events2 = patch.object(targets_manager._targets["2"].wsm, "get_events").start()
        get_events2.return_value = [{
            "method": "Network.requestWillBeSent", "params": {"requestId": "2"}
        }]
        assert [
            {'method': 'Network.requestWillBeSent', 'params': {'requestId': '1'}},
            {'method': 'Network.requestWillBeSent', 'params': {'requestId': '2'}}
        ] == targets_manager.get_all_events("Network")
        get_events1.assert_called_once_with("Network")
        get_events2.assert_called_once_with("Network")

    def test_clear_true(self, targets_manager):
        targets_manager.get_all_events("Page", clear=True)
        for target in targets_manager._targets.values():
            target.wsm.get_events.assert_called_once_with("Page", clear=True)

    def test_clear_false(self, targets_manager):
        targets_manager.get_all_events("Page", clear=True)
        for target in targets_manager._targets.values():
            target.wsm.get_events.assert_called_once_with("Page", clear=True)


class Test_TargetsManager_detach_all:

    def test(self, targets_manager):
        targets = targets_manager._targets.values()
        assert len(targets) > 0

        targets_manager.detach_all()

        for target in targets:
            target.wsm.close.assert_called_once_with()


class Test_TargetsManager_reset:

    def test(self, targets_manager):
        targets = targets_manager._targets.values()
        assert len(targets) > 0

        targets_manager.reset()

        for target in targets:
            target.wsm.reset.assert_called_once_with()
            target.dom_manager.reset.assert_called_once_with()


class Test_TargetsManager_enable_domain:

    def test(self, targets_manager):
        targets_manager.enable_domain("Fetch", parameters={"foo": "bar"})
        targets_manager._targets[targets_manager.current_target_id].wsm.enable_domain.assert_called_once_with(
            "Fetch", parameters={"foo": "bar"}
        )


class Test_TargetsManager_create_tab:

    _info = {
        "id": "6", "type": "page", "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/6"
    }

    @pytest.fixture
    def _targets_manager(self, targets_manager):
        patch.object(targets_manager, "refresh_targets").start()
        patched__create_tab = patch.object(targets_manager, "_create_tab").start()

        def _create_tab():
            targets_manager._targets["6"] = _TestTarget(self._info, 10)
            return self._info

        patched__create_tab.side_effect = _create_tab
        return targets_manager

    def test(self, _targets_manager):
        tab = _targets_manager.create_tab()

        assert self._info == tab.info
        assert self._info == _targets_manager._targets["6"].info


class DOMManagerTest(TestCase):

    def setUp(self):
        self.dom_manager = _DOMManager(MagicMock())


class Test_DOMManager_get_iframe_html(DOMManagerTest):

    def test_exception_then_ok(self):

        html = "<html></html>"
        self.dom_manager._get_iframe_backend_node_id = MagicMock()
        self.dom_manager.get_outer_html = MagicMock(
            side_effect=[ResourceNotFoundError(), html]
        )

        self.assertEqual(html,  self.dom_manager.get_iframe_html("//iframe"))
        self.dom_manager._get_iframe_backend_node_id._assert_has_calls([
            call("//iframe"), call("//iframe")
        ])

    def test_exception_then_exception(self):

        self.dom_manager._get_iframe_backend_node_id = MagicMock()
        self.dom_manager.get_outer_html = MagicMock(
            side_effect=[ResourceNotFoundError(), ResourceNotFoundError()]
        )
        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager.get_iframe_html("//iframe")


class Test_DOMManager__get_iframe_backend_node_id(DOMManagerTest):

    def test_already_cached(self):

        self.dom_manager._node_map = {"//iframe": 5}
        self.assertEqual(5, self.dom_manager._get_iframe_backend_node_id("//iframe"))

    def test_not_already_cached(self):

        node_info = {
            "node": {
                "contentDocument": {
                    "backendNodeId": 10
                }
            }
        }
        self.dom_manager._get_info_for_first_matching_node = MagicMock(return_value=node_info)
        self.dom_manager._node_map = {}

        self.assertEqual(10, self.dom_manager._get_iframe_backend_node_id("//iframe"))
        self.assertEqual({"//iframe": 10}, self.dom_manager._node_map)

    def test_node_found_but_not_an_iframe(self):

        node_info = {"node": {}}
        self.dom_manager._get_info_for_first_matching_node = MagicMock(return_value=node_info)

        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager._get_iframe_backend_node_id("//iframe")

    def test_node_not_found(self):

        self.dom_manager._get_info_for_first_matching_node = MagicMock(
            side_effect=ResourceNotFoundError()
        )
        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager._get_iframe_backend_node_id("//iframe")


class Test__DOMManager__get_node_ids(DOMManagerTest):

    def test_no_matches(self):
        self.dom_manager._discard_search = MagicMock()
        self.dom_manager._perform_search = MagicMock(
            return_value={"resultCount": 0, "searchId": "SomeID"}
        )

        with self.dom_manager._get_node_ids("//iframe") as node_ids:
            self.assertEqual([], node_ids)

        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_exception_getting_search_results(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 1, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(side_effect=ResourceNotFoundError())
        self.dom_manager._discard_search = MagicMock()

        with self.assertRaises(ResourceNotFoundError):
            with self.dom_manager._get_node_ids("//iframe"):
                pass

        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_exception_performing_search(self):

        self.dom_manager._perform_search = MagicMock(side_effect=ResourceNotFoundError())

        with self.assertRaises(ResourceNotFoundError):
            with self.dom_manager._get_node_ids("//iframe"):
                pass

    def test_resultCount_is_max(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 2, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(return_value={"nodeIds": [20, 30]})
        self.dom_manager._discard_search = MagicMock()

        with self.dom_manager._get_node_ids("//iframe", max_matches=2) as node_ids:
            pass

        self.dom_manager._get_search_results.assert_called_once_with("SomeID", 0, 2)
        self.assertEqual([20, 30], node_ids)
        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_resultCount_less_than_max(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 2, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(return_value={"nodeIds": [20, 30]})
        self.dom_manager._discard_search = MagicMock()

        with self.dom_manager._get_node_ids("//iframe", max_matches=3) as node_ids:
            pass

        self.dom_manager._get_search_results.assert_called_once_with("SomeID", 0, 2)
        self.assertEqual([20, 30], node_ids)
        self.dom_manager._discard_search.assert_called_once_with("SomeID")

    def test_resultCount_more_than_max(self):

        self.dom_manager._perform_search = MagicMock(return_value={
            "resultCount": 3, "searchId": "SomeID"
        })
        self.dom_manager._get_search_results = MagicMock(return_value={"nodeIds": [20, 30]})
        self.dom_manager._discard_search = MagicMock()

        with self.dom_manager._get_node_ids("//iframe", max_matches=2) as node_ids:
            pass

        self.assertEqual([20, 30], node_ids)
        self.dom_manager._get_search_results.assert_called_once_with("SomeID", 0, 2)
        self.dom_manager._discard_search.assert_called_once_with("SomeID")


class Test__get_info_for_first_matching_node(DOMManagerTest):

    def test_ok(self):

        self.dom_manager._get_node_ids = MagicMock()
        self.dom_manager._get_node_ids.return_value.__enter__.return_value = [10, 4, 6]
        expected_node_info = MagicMock()
        self.dom_manager._describe_node = MagicMock(return_value=expected_node_info)

        actual_node_info = self.dom_manager._get_info_for_first_matching_node("//iframe")

        self.assertEqual(expected_node_info, actual_node_info)
        self.dom_manager._describe_node.assert_called_once_with(10)

    def test_no_matches(self):

        self.dom_manager._get_node_ids = MagicMock()
        self.dom_manager._get_node_ids.return_value.__enter__.return_value = []

        with self.assertRaises(ResourceNotFoundError):
            self.dom_manager._get_info_for_first_matching_node("//iframe")
