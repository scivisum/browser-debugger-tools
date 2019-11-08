class DevToolsException(Exception):
    pass


class ProtocolError(DevToolsException):
    pass


class NotFoundError(DevToolsException):
    pass


class DevToolsTimeoutException(DevToolsException):
    pass


class TabNotFoundError(NotFoundError):
    pass


class DomainNotEnabledError(DevToolsException):
    pass


class DomainNotFoundError(ProtocolError, NotFoundError):
    pass


class ResultNotFoundError(NotFoundError):
    pass


class MaxRetriesException(DevToolsException):
    pass
