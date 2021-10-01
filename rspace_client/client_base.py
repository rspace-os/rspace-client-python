class ClientBase:
    """ Base class of common methods for all API clients """
    
    def __init__(self, rspace_url, api_key):
        """
        Initializes RSpace client.
        :param rspace_url: RSpace server URL (for example, https://community.researchspace.com)
        :param api_key: RSpace API key of a user can be found on 'My Profile' page
        """
        self.rspace_url = rspace_url
        self.api_key = api_key    

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