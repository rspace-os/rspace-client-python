import requests
import datetime
import time
import os.path
import re
import six


class Client:
    """Client for RSpace API v1.

    Most methods return a dictionary with fields described in the API documentation. The documentation can be found at
    https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).

    For authentication, an API key must be provided. It can be found by logging in and navigating to 'My Profile' page.
    """
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

    API_VERSION = 'v1'

    def __init__(self, rspace_url, api_key):
        """
        Initializes RSpace client.
        :param rspace_url: RSpace server URL (for example, https://community.researchspace.com)
        :param api_key: RSpace API key of a user can be found on 'My Profile' page
        """
        self.rspace_url = rspace_url
        self.api_key = api_key

    def _get_api_url(self):
        """
        Returns an API server URL.
        :return: string URL
        """
        return '{}/api/{}'.format(self.rspace_url, self.API_VERSION)

    def _get_headers(self, content_type='application/json'):
        return {
            'apiKey': self.api_key,
            'Accept': content_type
        }

    @staticmethod
    def _get_numeric_record_id(global_id):
        """
        Gets numeric part of a global ID.
        :param global_id: global ID (for example, SD123 or FM12)
        :return: numeric record id
        """
        if re.match(r'[a-zA-Z]{2}\d+$', str(global_id)) is not None:
            return int(global_id[2:])
        elif re.match(r'\d+$', str(global_id)) is not None:
            return int(global_id)
        else:
            raise ValueError('{} is not a valid global ID'.format(global_id))

    @staticmethod
    def _get_formated_error_message(json_error):
        return 'error message: {}, errors: {}'.format(json_error.get('message', ''),
                                                      ', '.join(json_error.get('errors', [])) or 'no error list')

    @staticmethod
    def _handle_response(response):
        # Check whether response includes UNAUTHORIZED response code
        if response.status_code == 401:
            raise Client.AuthenticationError(response.json()['message'])

        try:
            response.raise_for_status()

            if 'application/json' in response.headers['Content-Type']:
                return response.json()
            else:
                return response.text
        except:
            if 'application/json' in response.headers['Content-Type']:
                error = 'Error code: {}, {}'.format(response.status_code,
                                                    Client._get_formated_error_message(response.json()))
            else:
                error = 'Error code: {}, error message: {}'.format(response.status_code, response.text)
            raise Client.ApiError(error, response_status_code=response.status_code)

    def retrieve_api_results(self, url, params=None, content_type='application/json', request_type='GET'):
        """
        Makes the requested API call and returns either an exception or a parsed JSON response as a dictionary.
        Authentication header is automatically added. In most cases, a specialised method can be used instead.
        :param url: URL to retrieve
        :param request_type: 'GET', 'POST', 'PUT'
        :param params: arguments to be added to the API request
        :param content_type: content type
        :return: parsed JSON response as a dictionary
        """
        headers = self._get_headers(content_type)
        try:
            if request_type == 'GET':
                response = requests.get(url, params=params, headers=headers)
            elif request_type == 'PUT' or request_type == 'POST':
                response = requests.request(request_type, url, json=params, headers=headers)
            else:
                raise ValueError('Expected GET / PUT / POST request type, received {} instead'.format(request_type))

            return self._handle_response(response)
        except requests.exceptions.ConnectionError as e:
            raise Client.ConnectionError(e)

    @staticmethod
    def _get_links(response):
        """
        Finds links part of the response. Most responses contain links section with URLs that might be useful to query
        for further information.
        :param response: response from the API server
        :return: links section of the response
        """
        try:
            return response['_links']
        except KeyError:
            raise Client.NoSuchLinkRel('There are no links!')

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
            if link['rel'] == link_rel:
                return link['link']
        raise Client.NoSuchLinkRel('Requested link rel "{}", available rel(s): {}'.format(
            link_rel, (', '.join(x['rel'] for x in self._get_links(response)))))

    def download_link_to_file(self, url, filename):
        """
        Downloads a file from the API server.
        :param url: URL of the file to be downloaded
        :param filename: file path to save the file to
        """
        headers = {
            'apiKey': self.api_key,
            'Accept': 'application/octet-stream'
        }
        with open(filename, 'wb') as fd:
            for chunk in requests.get(url, headers=headers).iter_content(chunk_size=128):
                fd.write(chunk)

    def link_exists(self, response, link_rel):
        """
        Checks whether there is a link with rel attribute equal to link_rel in the links section of the response.
        :param response: response from the API server
        :param link_rel: rel attribute value to look for
        :return: True, if the link exists
        """
        return link_rel in [x['rel'] for x in self._get_links(response)]

    # Documents methods
    def get_documents(self, query=None, order_by='lastModified desc', page_number=0, page_size=20):
        """
        The Documents endpoint returns a paginated list of summary information about Documents in the RSpace workspace.
        These can be individual documents or notebook entries. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param (optional) query: Global search for a term, works identically to the simple "All' search in RSpace
        Workspace.
        :param order_by: Sort order for documents.
        :param page_number: For paginated results, this is the number of the page requested, 0 based.
        :param page_size: The maximum number of items to retrieve.
        :return: parsed response as a dictionary
        """
        params = {
            'orderBy': order_by,
            'pageSize': page_size,
            'pageNumber': page_number
        }
        if query is not None:
            params['query'] = query

        return self.retrieve_api_results(self._get_api_url() + '/documents', params)

    def get_documents_advanced_query(self, advanced_query, order_by='lastModified desc', page_number=0, page_size=20):
        """
        The Documents endpoint returns a paginated list of summary information about Documents in the RSpace workspace.
        These can be individual documents or notebook entries. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param advanced_query: JSON representation of a search query. This can be built using AdvancedQueryBuilder.
        :param order_by: Sort order for documents.
        :param page_number: For paginated results, this is the number of the page requested, 0 based.
        :param page_size: The maximum number of items to retrieve.
        :return: parsed response as a dictionary
        """
        params = {
            'advancedQuery': advanced_query,
            'orderBy': order_by,
            'pageSize': page_size,
            'pageNumber': page_number
        }
        return self.retrieve_api_results(self._get_api_url() + '/documents', params)

    def get_document(self, doc_id):
        """
        Gets information about a document. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param doc_id: numeric document ID or global ID
        :return: a dictionary that includes: document metadata, field content, metadata about media items belonging to
        this document, links to download the content of media files
        """
        numeric_doc_id = self._get_numeric_record_id(doc_id)
        return self.retrieve_api_results(self._get_api_url() + '/documents/{}'.format(numeric_doc_id))

    def get_document_csv(self, doc_id):
        """
        Gets information about a document. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param doc_id: numeric document ID or global ID
        :return: CSV that includes: document metadata, field content, metadata about media items belonging to
        this document, links to download the content of media files
        """
        numeric_doc_id = self._get_numeric_record_id(doc_id)
        return self.retrieve_api_results(self._get_api_url() + '/documents/{}'.format(numeric_doc_id),
                                         content_type='text/csv')

    def create_document(self, name=None, tags=None, form_id=None, fields=None):
        """
        Creates a new document in user's Api Inbox folder. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param name: name of the document (can be omitted)
        :param tags: list of tags (['tag1', 'tag2']) or comma separated string of tags ('tag1,tag2')
        :param form_id: numeric document ID or global ID
        :param fields: list of fields (dictionaries of (optionally) ids and contents). For example,
        [{'content': 'some example text'}] or [{'id': 123, 'content': 'some example text'}].
        :return: parsed response as a dictionary
        """
        data = {}

        if name is not None:
            data['name'] = name

        if tags is not None:
            if isinstance(tags, list):
                tags = ','.join(tags)
            data['tags'] = tags

        if form_id is not None:
            numeric_form_id = self._get_numeric_record_id(form_id)
            data['form'] = {"id": int(numeric_form_id)}

        if fields is not None and len(fields) > 0:
            data['fields'] = fields

        return self.retrieve_api_results(self._get_api_url() + '/documents', request_type='POST', params=data)

    def update_document(self, document_id, name=None, tags=None, form_id=None, fields=None):
        """
        Updates a document with a given document id. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param document_id: numeric document ID or global ID
        :param name: name of the document (can be omitted)
        :param tags: list of tags (['tag1', 'tag2']) or comma separated string of tags ('tag1,tag2') (can be omitted)
        :param form_id: numeric document ID or global ID (should be left None or otherwise should match the form id
        of the document)
        :param fields: list of fields (dictionaries of (optionally) ids and contents). For example,
        [{'content': 'some example text'}] or [{'id': 123, 'content': 'some example text'}]. (can be omitted)
        :return:
        """
        data = {}

        if name is not None:
            data['name'] = name

        if tags is not None:
            if isinstance(tags, list):
                tags = ','.join(tags)
            data['tags'] = tags

        if form_id is not None:
            numeric_form_id = self._get_numeric_record_id(form_id)
            data['form'] = {"id": int(numeric_form_id)}

        if fields is not None and len(fields) > 0:
            data['fields'] = fields

        numeric_doc_id = self._get_numeric_record_id(document_id)
        return self.retrieve_api_results(self._get_api_url() + '/documents/{}'.format(numeric_doc_id),
                                         request_type='PUT', params=data)

    # File methods

    def get_files(self, page_number=0, page_size=20, order_by="lastModified desc", media_type="image"):
        """
        Lists media items - i.e. content shown in the Gallery in RSpace web application. Note that this does not include
        files linked from external file systems or 3rd party providers. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param page_number: For paginated results, this is the number of the page requested, 0 based.
        :param page_size: The maximum number of items to retrieve.
        :param order_by: Sort order for documents.
        :param media_type: can be 'image', 'av' (audio or video), 'document' (any other file)
        :return: parsed response as a dictionary
        """
        params = {
            'pageNumber': page_number,
            'pageSize': page_size,
            'orderBy': order_by,
            'mediaType': media_type
        }
        return self.retrieve_api_results(self._get_api_url() + '/files', params)

    def get_file_info(self, file_id):
        """
        Gets metadata of a single file by its id. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param file_id: numeric document ID or global ID
        :return: parsed response as a dictionary
        """
        numeric_file_id = self._get_numeric_record_id(file_id)
        return self.retrieve_api_results(self._get_api_url() + '/files/{}'.format(numeric_file_id))

    def download_file(self, file_id, filename):
        """
        Downloads file contents. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param file_id: numeric document ID or global ID
        :param filename: file path to save the file to
        """
        numeric_file_id = self._get_numeric_record_id(file_id)
        return self.download_link_to_file(self._get_api_url() + '/files/{}/file'.format(numeric_file_id), filename)

    def upload_file(self, file, folder_id=None, caption=None):
        """
        Upload a file to the gallery. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param file: open file object
        :param folder_id: folder id of the destination folder
        :param caption: optional caption
        :return: parsed response as a dictionary
        """
        data = {}

        if folder_id is not None:
            numeric_folder_id = self._get_numeric_record_id(folder_id)
            data['folderId'] = numeric_folder_id

        if caption is not None:
            data['caption'] = caption

        response = requests.post(self._get_api_url() + '/files', files={"file": file}, data=data,
                                 headers=self._get_headers())
        return self._handle_response(response)

    # Activity methods
    def get_activity(self, page_number=0, page_size=100, order_by=None, date_from=None, date_to=None, actions=None,
                     domains=None, global_id=None, users=None):
        """
        Returns all activity for a particular document. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param page_number: for paginated results, this is the number of the page requested, 0 based.
        :param page_size: the maximum number of items to retrieve.
        :param order_by: sort order for activities.
        :param date_from: yyyy-mm-dd string or datetime.date object. The earliest date to retrieve activity from.
        :param date_to: yyyy-mm-dd string or datetime.date object. The latest date to retrieve activity from.
        :param actions: a comma separated string or list of strings. Actions to restrict the query.
        :param domains: a comma separated string or list of strings. Domains to restrict the query.
        :param global_id: the global ID of a resource, e.g. SD12345
        :param users: a comma separated string or list of strings. Users to restrict the query.
        :return:
        """
        params = {
            'pageNumber': page_number,
            'pageSize': page_size
        }

        if order_by is not None:
            params['orderBy'] = order_by

        if date_from is not None:
            if isinstance(date_from, datetime.date):
                params['dateFrom'] = date_from.isoformat()
            elif isinstance(date_from, six.string_types):
                params['dateFrom'] = date_from
            else:
                raise TypeError('Unexpected date_from type {}'.format(type(date_from)))

        if date_to is not None:
            if isinstance(date_to, datetime.date):
                params['dateTo'] = date_to.isoformat()
            elif isinstance(date_to, six.string_types):
                params['dateTo'] = date_to
            else:
                raise TypeError('Unexpected date_from type {}'.format(type(date_to)))

        if actions is not None:
            if isinstance(actions, list):
                params['actions'] = ','.join(actions)
            elif isinstance(actions, six.string_types):
                params['actions'] = actions
            else:
                raise TypeError('Unexpected actions type {}'.format(type(actions)))

        if domains is not None:
            if isinstance(domains, list):
                params['domains'] = ','.join(domains)
            elif isinstance(domains, six.string_types):
                params['domains'] = domains
            else:
                raise TypeError('Unexpected domains type {}'.format(type(domains)))

        if global_id is not None:
            params['oid'] = str(global_id)

        if users is not None:
            if isinstance(users, list):
                params['users'] = ','.join(users)
            elif isinstance(users, six.string_types):
                params['users'] = users
            else:
                raise TypeError('Unexpected users type {}'.format(type(users)))

        return self.retrieve_api_results(self._get_api_url() + '/activity', params=params)

    # Export
    def start_export(self, format, scope, id=None):
        """
        Starts an asynchronous export of user's or group's records. Currently export of selections of documents is
        unsupported.
        :param format: 'xml' or 'html'
        :param scope: 'user' or 'group'
        :param id: id of a user or a group depending on the scope (current user or group will be used if not provided)
        :return: job id
        """
        if format != 'xml' and format != 'html':
            raise ValueError('format must be either "xml" or "html", got "{}" instead'.format(format))

        if scope != 'user' and scope != 'group':
            raise ValueError('scope must be either "user" or "group", got "{}" instead'.format(scope))

        if id is not None:
            request_url = self._get_api_url() + '/export/{}/{}/{}'.format(format, scope, id)
        else:
            request_url = self._get_api_url() + '/export/{}/{}'.format(format, scope)

        return self.retrieve_api_results(request_url, request_type='POST')

    def download_export(self, format, scope, file_path, id=None, wait_between_requests=30):
        """
        Exports user's or group's records and downloads the exported archive to a specified location.
        :param format: 'xml' or 'html'
        :param scope: 'user' or 'group'
        :param file_path: can be either a directory or a new file in an existing directory
        :param id: id of a user or a group depending on the scope (current user or group will be used if not provided)
        :param wait_between_requests: seconds to wait between job status requests (30 seconds default)
        :return: file path to the downloaded export archive
        """
        job_id = self.start_export(format=format, scope=scope, id=id)['id']

        while True:
            status_response = self.get_job_status(job_id)

            if status_response['status'] == 'COMPLETED':
                download_url = self.get_link(status_response, 'enclosure')

                if os.path.isdir(file_path):
                    file_path = os.path.join(file_path, download_url.split('/')[-1])
                self.download_link_to_file(download_url, file_path)

                return file_path
            elif status_response['status'] == 'FAILED':
                raise Client.ApiError('Export job failed: ' +
                                      self._get_formated_error_message(status_response['result']))
            elif status_response['status'] == 'ABANDONED':
                raise Client.ApiError('Export job was abandoned: ' +
                                      self._get_formated_error_message(status_response['result']))
            elif status_response['status'] == 'RUNNING' or status_response['status'] == 'STARTING' or \
                    status_response['status'] == 'STARTED':
                time.sleep(wait_between_requests)
                continue
            else:
                raise Client.ApiError('Unknown job status: ' + status_response['status'])

    def get_job_status(self, job_id):
        """
        Return a job status.
        :param job_id: job id
        :return: parsed response as a dictionary (most important field is 'status' which is supposed to one of:
        'STARTED', 'STARTING', 'RUNNING', 'COMPLETED', 'FAILED', 'ABANDONED')
        """
        return self.retrieve_api_results(self._get_api_url() + '/jobs/{}'.format(job_id))

    # Miscellaneous methods
    def get_status(self):
        """
        Simple API call to check that API service is available. Throws an AuthenticationError if authentication fails.
        More information on https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :return: parsed response as a dictionary (most important field is 'message' which is supposed to be 'OK')
        """
        return self.retrieve_api_results(self._get_api_url() + '/status')
