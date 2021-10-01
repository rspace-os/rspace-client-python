class ClientBase:
    """ Base class of common methods for all API clients """

    class ConnectionError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class NoSuchLinkRel(Exception):
        pass

    class ApiError(Exception):
        def __init__(self, error_message, response_status_code=None):
            Exception.__init__(self, error_message)
            self.response_status_code = response_status_code