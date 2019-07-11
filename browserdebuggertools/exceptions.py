class DevToolsException(Exception):
    pass


class ProtocolError(DevToolsException):
    pass


class DevToolsTimeoutException(DevToolsException):
    pass


class TabNotFoundError(DevToolsException):
    pass


class DomainNotEnabledError(DevToolsException):
    pass


class DomainNotFoundError(ProtocolError):
    pass


class ResultNotFoundError(DevToolsException):
    pass


