from websocket import WebSocketException


class DevToolsException(Exception):
    pass


class ProtocolError(DevToolsException):
    pass


class NotFoundError(DevToolsException):
    pass


class TargetNotFoundError(NotFoundError):
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
