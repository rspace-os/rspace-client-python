import re
import requests
import sys


class Pagination:
    """
    For setting page size, number and orderby/ sort fields of listings
    """

    def __init__(
        self,
        page_number: int = 0,
        page_size: int = 10,
        order_by: str = None,
        sort_order: str = "asc",
    ):
        self.data = {
            "pageNumber": page_number,
            "pageSize": page_size,
        }
        if order_by is not None:
            self.data["orderBy"] = f"{order_by} {sort_order}"


class ClientBase:
    """Base class of common methods for all API clients"""

    def __init__(self, rspace_url, api_key):
        """
        Initializes RSpace client.
        :param api_key: RSpace API key of a user can be found on 'My Profile' page
        """
        self.rspace_url = rspace_url
        self.api_key = api_key

    def _get_headers(self, content_type="application/json"):
        return {"apiKey": self.api_key, "Accept": content_type}

    @staticmethod
    def _get_numeric_record_id(global_id):
        """
        Gets numeric part of a global ID.
        :param global_id: global ID (for example, SD123 or FM12)
        :return: numeric record id
        """
        if re.match(r"[a-zA-Z]{2}\d+$", str(global_id)) is not None:
            return int(global_id[2:])
        elif re.match(r"\d+$", str(global_id)) is not None:
            return int(global_id)
        else:
            raise ValueError("{} is not a valid global ID".format(global_id))

    @staticmethod
    def _get_formated_error_message(json_error):
        return "error message: {}, errors: {}".format(
            json_error.get("message", ""),
            ", ".join(json_error.get("errors", [])) or "no error list",
        )

    @staticmethod
    def _responseContainsJson(response):
        return (
            "Content-Type" in response.headers
            and "application/json" in response.headers["Content-Type"]
        )

    @staticmethod
    def _handle_response(response):
        # Check whether response includes UNAUTHORIZED response code
        # print("status: {}, header: {}".format(response.headers, response.status_code))
        if response.status_code == 401:
            raise ClientBase.AuthenticationError(response.json()["message"])

        try:
            response.raise_for_status()

            if ClientBase._responseContainsJson(response):
                return response.json()
            elif response.text:
                return response.text
            else:
                return response
        except:
            if "application/json" in response.headers["Content-Type"]:
                error = "Error code: {}, {}".format(
                    response.status_code,
                    ClientBase._get_formated_error_message(response.json()),
                )
            else:
                error = "Error code: {}, error message: {}".format(
                    response.status_code, response.text
                )
            raise ClientBase.ApiError(error, response_status_code=response.status_code)

    def doDelete(self, path, resource_id):
        """
        Performs a delete operation for a given resource
        """
        numeric_id = self._get_numeric_record_id(resource_id)
        return self.retrieve_api_results(
            "/{}/{}".format(path, numeric_id),
            content_type=None,
            request_type="DELETE",
        )

    def retrieve_api_results(
        self, endpoint, params=None, content_type="application/json", request_type="GET"
    ):
        """
        Makes the requested API call and returns either an exception or a parsed JSON response as a dictionary.
        Authentication header is automatically added. In most cases, a specialised method can be used instead.
        :endpoint url: API endpoint
        :param request_type: 'GET', 'POST', 'PUT', 'DELETE'
        :param params: arguments to be added to the API request
        :param content_type: content type
        :return: parsed JSON response as a dictionary
        """
        url = endpoint
        if not endpoint.startswith(self._get_api_url()):
            url = self._get_api_url() + endpoint

        headers = self._get_headers(content_type)
        try:
            if request_type == "GET":
                response = requests.get(url, params=params, headers=headers)
            elif (
                request_type == "PUT"
                or request_type == "POST"
                or request_type == "DELETE"
            ):
                response = requests.request(
                    request_type, url, json=params, headers=headers
                )
            else:
                raise ValueError(
                    "Expected GET / PUT / POST / DELETE request type, received {} instead".format(
                        request_type
                    )
                )

            return self._handle_response(response)
        except requests.exceptions.ConnectionError as e:
            raise ClientBase.ConnectionError(e)

    @staticmethod
    def _get_links(response):
        """
        Finds links part of the response. Most responses contain links section with URLs that might be useful to query
        for further information.
        :param response: response from the API server
        :return: links section of the response
        """
        try:
            return response["_links"]
        except KeyError:
            raise ClientBase.NoSuchLinkRel("There are no links!")

    def get_link_contents(self, response, link_rel):
        """
        Finds a link with rel attribute equal to link_rel and retrieves its contents.
        :param response: response from the API server
        :param link_rel: rel attribute value to look for
        :return: parsed response from the found URL
        """
        return self.retrieve_api_results(self.get_link(response, link_rel))

    def get_link(self, response, link_rel):
        """
        Finds a link with rel attribute equal to link_rel.
        :param response: response from the API server.
        :param link_rel: rel attribute value to look for
        :return: string URL
        """
        for link in self._get_links(response):
            if link["rel"] == link_rel:
                return link["link"]
        raise ClientBase.NoSuchLinkRel(
            'Requested link rel "{}", available rel(s): {}'.format(
                link_rel, (", ".join(x["rel"] for x in self._get_links(response)))
            )
        )

    def download_link_to_file(self, url, filename):
        """
        Downloads a file from the API server.
        :param url: URL of the file to be downloaded
        :param filename: file path to save the file to
        """
        headers = {"apiKey": self.api_key, "Accept": "application/octet-stream"}
        with open(filename, "wb") as fd:
            for chunk in requests.get(url, headers=headers).iter_content(
                chunk_size=128
            ):
                fd.write(chunk)

    def link_exists(self, response, link_rel):
        """
        Checks whether there is a link with rel attribute equal to link_rel in the links section of the response.
        :param response: response from the API server
        :param link_rel: rel attribute value to look for
        :return: True, if the link exists
        """
        return link_rel in [x["rel"] for x in self._get_links(response)]

    def serr(self, msg: str):
        print(msg, file=sys.stderr)

    def _stream(
        self,
        endpoint: str,
        pagination: Pagination = Pagination(),
    ):
        """
        Yields items, making paginated requests to the server as each page
        is consumed by the calling code.

        Note this method assumes that the name of the collection of items in the
        response matches the endpoint name. For example 'samples' returns a response
        with a dictionary entry 'samples'.
        Parameters
        ----------
        endpoint : str
            An endpoint with a GET request that makes paginated listings
        pagination : Pagination, optional
            The pagination control. The default is Pagination().
         : Pagination

        Yields
        ------
        item : A stream of items, depending on the endpoint called
        """

        urlStr = f"{self._get_api_url()}/{endpoint}"

        next_link = requests.Request(url=urlStr, params=pagination.data).prepare().url
        while True:
            if next_link is not None:
                items = self.retrieve_api_results(next_link)
                for item in items[endpoint]:
                    yield item
                if self.link_exists(items, "next"):
                    next_link = self.get_link(items, "next")
                else:
                    break

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
