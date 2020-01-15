class DevToolsException(Exception):
    pass


class ProtocolError(DevToolsException):
    pass


class NotFoundError(DevToolsException):
    pass


class DevToolsTimeoutException(DevToolsException):
    pass


class TimerException(DevToolsException):
    pass


class TabNotFoundError(NotFoundError):
    pass


class DomainNotEnabledError(DevToolsException):
    pass


class MethodNotFoundError(ProtocolError, NotFoundError):
    pass


class ResultNotFoundError(NotFoundError):
    pass


class ResourceNotFoundError(NotFoundError):
    pass


class JavascriptDialogNotFoundError(NotFoundError):
    pass


class MaxRetriesException(DevToolsException):
    pass


class InvalidXPathError(DevToolsException):
    pass


class UnknownError(ProtocolError):
    pass
