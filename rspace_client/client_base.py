import logging
import re
import requests

from typing import Optional

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rspace_client.exceptions import (
    ApiError,
    AuthenticationError,
    NoSuchLinkRel,
    RSpaceConnectionError,
    RSpaceError,
)

logger = logging.getLogger("rspace_client")

DEFAULT_TIMEOUT = (3.05, 30)  # (connect, read) seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
RETRY_STATUSES = (429, 500, 502, 503, 504)


class _RSpaceRetry(Retry):
    """
    Retry policy that additionally retries POST requests, but only on
    statuses where the server rejected the request before processing it
    (rate limiting / unavailable), so a replay cannot create duplicates.
    """

    POST_RETRYABLE_STATUSES = frozenset({429, 503})

    def is_retry(self, method, status_code, has_retry_after=False):
        if method and method.upper() == "POST":
            return status_code in self.POST_RETRYABLE_STATUSES
        return super().is_retry(method, status_code, has_retry_after)


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

    def __init__(
        self,
        rspace_url,
        api_key,
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        backoff_factor=DEFAULT_BACKOFF_FACTOR,
    ):
        """
        Initializes RSpace client.
        :param api_key: RSpace API key of a user can be found on 'My Profile' page
        :param timeout: seconds to wait for the server, either a single number
            or a (connect, read) tuple, applied to every request
        :param max_retries: how many times to retry a request that failed with
            a retryable status (429/5xx) or a connection error. Set to 0 to
            disable retries.
        :param backoff_factor: multiplier for exponential backoff between
            retries; the Retry-After header is honored when the server sends it
        """
        self.rspace_url = rspace_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self._session = self._build_session(max_retries, backoff_factor)

    def _build_session(self, max_retries, backoff_factor):
        session = requests.Session()
        retry = _RSpaceRetry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=("GET", "PUT", "DELETE"),
            respect_retry_after_header=True,
            # once retries are exhausted, return the last response so it is
            # mapped to ApiError as usual instead of raising RetryError
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers["apiKey"] = self.api_key
        return session

    def close(self):
        """
        Closes the underlying HTTP session and its pooled connections.
        """
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def _is_absolute_url(url):
        return url.startswith("http://") or url.startswith("https://")

    def _get_headers(self, content_type="application/json"):
        headers = {"apiKey": self.api_key}
        if content_type is not None:
            headers["Accept"] = content_type
        return headers

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
    def _get_error_detail(response):
        """
        Builds an error description from a response body, tolerating bodies
        whose Content-Type claims JSON but do not parse.
        """
        if ClientBase._responseContainsJson(response):
            try:
                return ClientBase._get_formated_error_message(response.json())
            except ValueError:
                pass
        return "error message: {}".format(response.text)

    @staticmethod
    def _check_status(response):
        """
        Raises AuthenticationError on 401 and ApiError on any other HTTP
        error status; returns None for successful responses.
        """
        if response.status_code == 401:
            raise AuthenticationError(
                "Error code: 401, {}".format(ClientBase._get_error_detail(response))
            )

        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise ApiError(
                "Error code: {}, {}".format(
                    response.status_code, ClientBase._get_error_detail(response)
                ),
                response_status_code=response.status_code,
                response=response,
            )

    @staticmethod
    def _handle_response(response):
        ClientBase._check_status(response)

        if ClientBase._responseContainsJson(response):
            return response.json()
        elif response.text:
            return response.text
        else:
            return response

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
        if not self._is_absolute_url(endpoint):
            url = self._get_api_url() + endpoint

        headers = self._get_headers(content_type)
        try:
            if request_type == "GET":
                response = self._session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            elif (
                request_type == "PUT"
                or request_type == "POST"
                or request_type == "DELETE"
            ):
                response = self._session.request(
                    request_type, url, json=params, headers=headers, timeout=self.timeout
                )
            else:
                raise ValueError(
                    "Expected GET / PUT / POST / DELETE request type, received {} instead".format(
                        request_type
                    )
                )

            return self._handle_response(response)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            raise RSpaceConnectionError(e)

    def _post_multipart(self, endpoint, files=None, data=None):
        """
        POSTs a multipart/form-data request (typically a file upload) through
        the shared session, so timeout, retries and error handling behave the
        same as for JSON API calls.
        :param endpoint: full URL or path relative to the API root
        :param files: dict of multipart file parts, passed to requests
        :param data: dict of additional form fields
        :return: parsed response, as for retrieve_api_results
        """
        url = endpoint
        if not self._is_absolute_url(endpoint):
            url = self._get_api_url() + endpoint
        try:
            response = self._session.post(
                url,
                files=files,
                data=data,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            return self._handle_response(response)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            raise RSpaceConnectionError(e)

    def _get_raw_response(self, url, params=None, accept="application/octet-stream"):
        """
        GETs a URL through the shared session and returns the raw response,
        for binary content such as images. Raises AuthenticationError or
        ApiError on HTTP error statuses, like retrieve_api_results.
        """
        try:
            response = self._session.get(
                url,
                params=params,
                headers={"apiKey": self.api_key, "Accept": accept},
                timeout=self.timeout,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            raise RSpaceConnectionError(e)
        self._check_status(response)
        return response

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
            raise NoSuchLinkRel("There are no links!")

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
        raise NoSuchLinkRel(
            'Requested link rel "{}", available rel(s): {}'.format(
                link_rel, (", ".join(x["rel"] for x in self._get_links(response)))
            )
        )

    def download_link_to_file(self, url, filename, chunk_size=8192):
        """
        Downloads a file from the API server, streaming it to disk in chunks
        so large files are not buffered in memory.
        :param url: URL of the file to be downloaded
        :param filename: file path to save the file to or an already opened file object
        :param chunk_size: size of the chunks to download at a time, default is 8192
        """
        headers = {"apiKey": self.api_key, "Accept": "application/octet-stream"}
        try:
            with self._session.get(
                url, headers=headers, stream=True, timeout=self.timeout
            ) as response:
                self._check_status(response)
                if isinstance(filename, str):
                    with open(filename, "wb") as fd:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            fd.write(chunk)
                else:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        filename.write(chunk)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            raise RSpaceConnectionError(e)

    def link_exists(self, response, link_rel):
        """
        Checks whether there is a link with rel attribute equal to link_rel in the links section of the response.
        :param response: response from the API server
        :param link_rel: rel attribute value to look for
        :return: True, if the link exists
        """
        return link_rel in [x["rel"] for x in self._get_links(response)]

    def serr(self, msg: str):
        """
        Deprecated: logs a warning through the 'rspace_client' logger instead
        of printing to stderr. Use the logging module directly; this method
        will be removed in 3.0.
        """
        logger.warning(msg)

    def _stream(
        self,
        endpoint: str,
        pagination: Optional[Pagination] = None,
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

        Yields
        ------
        item : A stream of items, depending on the endpoint called
        """
        if pagination is None:
            pagination = Pagination()

        urlStr = f"{self._get_api_url()}/{endpoint}"

        next_link = requests.Request(url=urlStr, params=pagination.data).prepare().url
        while next_link is not None:
            items = self.retrieve_api_results(next_link)
            for item in items[endpoint]:
                yield item
            if self.link_exists(items, "next"):
                next_link = self.get_link(items, "next")
            else:
                next_link = None

    # Deprecated aliases of the module-level classes in rspace_client.exceptions,
    # kept so existing `except ClientBase.ApiError:` code works. Remove in 3.0.
    ConnectionError = RSpaceConnectionError
    AuthenticationError = AuthenticationError
    NoSuchLinkRel = NoSuchLinkRel
    ApiError = ApiError
