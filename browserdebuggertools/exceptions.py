from websocket import WebSocketException


class DevToolsException(Exception):
    pass


class ProtocolError(DevToolsException):
    pass


class NotFoundError(DevToolsException):
    pass


class TargetNotFoundError(NotFoundError):
    pass


class TargetNotAttachedError(DevToolsException):
    pass


class DevToolsTimeoutException(DevToolsException):
    pass


class DomainNotEnabledError(DevToolsException):
    pass


class MethodNotFoundError(ProtocolError, NotFoundError):
    pass


class ResourceNotFoundError(NotFoundError):
    pass


class JavascriptDialogNotFoundError(NotFoundError):
    pass


class JavascriptError(DevToolsException):
    pass


class NoSWError(DevToolsException):
    """ Raised when an extension's MV3 service worker has been evicted by Chrome and is gone.

        Talking to it over the DevTools protocol fails with "Error: No SW". The worker
        self-heals via a chrome.alarms keep-alive, so callers can retry to pick up the
        re-spawned worker.
    """
    pass


class MaxRetriesException(DevToolsException):
    pass


class UnknownError(ProtocolError):
    pass


class MessagingThreadIsDeadError(DevToolsException):
    pass


class InvalidParametersError(ProtocolError):
    pass


class WebSocketBlockedException(WebSocketException, DevToolsException):
    pass
