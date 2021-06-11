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
    def _responseContainsJson(response):
        return 'Content-Type' in response.headers and 'application/json' in response.headers['Content-Type']

    @staticmethod
    def _handle_response(response):
        # Check whether response includes UNAUTHORIZED response code
        # print("status: {}, header: {}".format(response.headers, response.status_code))
        if response.status_code == 401:
            raise Client.AuthenticationError(response.json()['message'])

        try:
            response.raise_for_status()

            if Client._responseContainsJson(response):
                return response.json()
            elif response.text:
                return response.text
            else:
                return response
        except:
            if 'application/json' in response.headers['Content-Type']:
                error = 'Error code: {}, {}'.format(response.status_code,
                                                    Client._get_formated_error_message(response.json()))
            else:
                error = 'Error code: {}, error message: {}'.format(response.status_code, response.text)
            raise Client.ApiError(error, response_status_code=response.status_code)

    def doDelete(self, path, resource_id):
        """
        Performs a delete operation for a given resource
        """
        numeric_id = self._get_numeric_record_id(resource_id)
        return self.retrieve_api_results(self._get_api_url() + '/{}/{}'.format(path,numeric_id),
                                          content_type=None, request_type='DELETE')
        
    
    def retrieve_api_results(self, url, params=None, content_type='application/json', request_type='GET'):
        """
        Makes the requested API call and returns either an exception or a parsed JSON response as a dictionary.
        Authentication header is automatically added. In most cases, a specialised method can be used instead.
        :param url: URL to retrieve
        :param request_type: 'GET', 'POST', 'PUT', 'DELETE'
        :param params: arguments to be added to the API request
        :param content_type: content type
        :return: parsed JSON response as a dictionary
        """
        headers = self._get_headers(content_type)
        try:
            if request_type == 'GET':
                response = requests.get(url, params=params, headers=headers)
            elif request_type == 'PUT' or request_type == 'POST' or  request_type == 'DELETE':
                response = requests.request(request_type, url, json=params, headers=headers)
            else:
                raise ValueError('Expected GET / PUT / POST / DELETE request type, received {} instead'.format(request_type))

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
    
    def delete_document(self, doc_id):
        """
         Marks document as deleted.
         :param doc_id: numeric document ID or global ID
        """
        return self.doDelete( "documents", doc_id)
        
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


    def create_document(self, name=None, parent_folder_id=None, tags=None, form_id=None, fields=None):

        """
        Creates a new document in user's Api Inbox folder. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param name: name of the document (can be omitted)
        :param tags: list of tags (['tag1', 'tag2']) or comma separated string of tags ('tag1,tag2'); optional
        :param form_id: numeric document ID or global ID' optional; defaults to BasicDocument
        :param parent_folder_id: ID of workspace folder or subfolder; optional; defaults to ApiInbox folder
        :param fields: list of fields (dictionaries of (optionally) ids and contents). For example,
        [{'content': 'some example text'}] or [{'id': 123, 'content': 'some example text'}].
        :return: parsed response as a dictionary
        """
        data = {}

        if name is not None:
            data['name'] = name

        if parent_folder_id is not None:
            numeric_folder_id = self._get_numeric_record_id(parent_folder_id)
            data['parentFolderId'] = numeric_folder_id

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

    def prepend_content(self, document_id, html_content, field_index=0):
        """
         Prepends content to the beginning of a field. If the field_id is omitted,
         this will prepend content to the first field.  
         
        If field_id is set, this must be a field_id that belongs to  the document.

        Parameters
        ----------
        document_id : Integer
            The id of the document that is being modified.
        htmlContent : String
            HTML snippet.
        field_index : Integer, optional, default = 0
            Index of the field ( 0-based)

        Returns
        -------
        The updated document
        """
        return self._add_content(document_id, html_content, field_index, False)
    
    def append_content(self, document_id, html_content, field_index=0):
        """
         Appends content to the end of a field. If the field_id is omitted,
         this will append content to the end of the first field.  
         
        If field_id is set, this must be a field_id that belongs to  the document.

        Parameters
        ----------
        document_id : Integer
            The id of the document that is being modified.
        htmlContent : String
            HTML snippet.
        field_index : Integer, optional - default = 0
            Index of the field ( 0-based)

        Returns
        -------
        The updated document
        """
        return self._add_content(document_id, html_content, field_index, True)
     
    
    def _add_content (self, document_id, html_content, field_index=0, append=True):
        if document_id is None:
            raise ValueError("No document ID was set")
        if html_content is None:
            raise ValueError("No HTML content was set")
        doc = self.get_document(document_id)
        field = None
        
        if  field_index > 0:
            fields = doc['fields']
            if field_index >= len(fields):
                raise ValueError("Field at index {} doesn't exist, document {} has {} fields".format(field_index, document_id, len(fields)))
            field = fields[field_index]
        
        else:
            field = doc['fields'][0]
        if append:
            new_content = field['content'] + html_content
        else:
            new_content = html_content + field['content'] 
        to_update = [{'id': field['id'], 'content': new_content}]
        return self.update_document(document_id, form_id=doc['form']['id'], fields=to_update)
        
        
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

    # Sharing methods
    def shareDocuments(self, itemsToShare, groupId, sharedFolderId=None, permission="READ"):
        """
        Shares 1 or more notebooks or documents with 1 group. You can optionally
         specify the id of a folder to share into. If not set will share into the 
          top level of the group shared folder.
         with read permission into
        :param itemsToShare: A list of document/notebook IDs to share
        :param groupId: The ID of a group to share with
        :param sharedFolderId: The ID of a subfolder of the group's shared folder.
        :param permission: The permission to use, default is "READ", or "EDIT"
        
        """
        if len(itemsToShare) == 0:
            raise ValueError("Must be at least 1 item to share")
        
        sharePost = dict()
        sharePost['itemsToShare']=itemsToShare
        groupShare= {"id":groupId, "permission":permission}
        if(sharedFolderId is not None):
            groupShare['sharedFolderId']=sharedFolderId
        sharePost["groups"]=[groupShare]
        return self.retrieve_api_results(self._get_api_url() 
                                         + '/share', request_type='POST', params=sharePost)
    def unshareItem(self, sharingId):
        return self.doDelete("share", sharingId)
    
    def get_shared_items(self,query=None, order_by='name asc', page_number=0, page_size=20):
        """
         Paginated listing of shared items; default ordering is by document/notebook name.
        :param page_number: For paginated results, this is the number of the page requested, 0 based.
        :param page_size: The maximum number of items to retrieve.
        :param order_by: Sort order for sharedItems - either 'name' or 'sharee' - the name of user
         or group item is shared with.
         
        """
        params = {
            'orderBy': order_by,
            'pageSize': page_size,
            'pageNumber': page_number
        }
        if query is not None:
            params['query'] = query
        return self.retrieve_api_results(self._get_api_url() + '/share', params)
    
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
    
    def update_file(self, file, fileId):
        """
        Upload a file to the gallery. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param file: open file object
        :param fileId: Id of the file to replace
        :return: updated File response as a dictionary
        """
        response = requests.post(self._get_api_url() + '/files/{}/file'.format(fileId), files={"file": file}, 
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
    def start_export(self, export_format, scope, uid=None):
        """
        Starts an asynchronous export of user's or group's records. Currently export of selections of documents is
        unsupported.
        :param format: 'xml' or 'html'
        :param scope: 'user' or 'group'
        :param id: id of a user or a group depending on the scope (current user or group will be used if not provided)
        :return: job id
        """
        if export_format != 'xml' and export_format != 'html':
            raise ValueError('format must be either "xml" or "html", got "{}" instead'.format(export_format))

        if scope != 'user' and scope != 'group':
            raise ValueError('scope must be either "user" or "group", got "{}" instead'.format(scope))

        if id is not None:
            request_url = self._get_api_url() + '/export/{}/{}/{}'.format(export_format, scope, uid)
        else:
            request_url = self._get_api_url() + '/export/{}/{}'.format(export_format, scope)

        return self.retrieve_api_results(request_url, request_type='POST')

    def download_export(self, export_format, scope, file_path, uid=None, wait_between_requests=30):
        """
        Exports user's or group's records and downloads the exported archive to a specified location.
        :param format: 'xml' or 'html'
        :param scope: 'user' or 'group'
        :param file_path: can be either a directory or a new file in an existing directory
        :param id: id of a user or a group depending on the scope (current user or group will be used if not provided)
        :param wait_between_requests: seconds to wait between job status requests (30 seconds default)
        :return: file path to the downloaded export archive
        """
        job_id = self.start_export(format=export_format, scope=scope, uid=uid)['id']

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
    

    # Form related methods
    def get_forms(self, query=None, order_by='lastModified desc', page_number=0, page_size=20):
        """
        Provides a paginated list of Forms. You can use this endpoint to retrieve the IDs of the forms from which you
        want to create documents. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param (optional) query: Whole or part of a Form's name or tag.
        :param order_by: Sort order for Forms.
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

        return self.retrieve_api_results(self._get_api_url() + '/forms', params)

    def create_form(self, name, tags=None, fields=None):
        """
        Create a new Form, supplying the field definitions. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param name: name of the form
        :param tags: list of tags (['tag1', 'tag2']) or comma separated string of tags ('tag1,tag2') (optional)
        :param fields: list of fields (dictionaries of 'name', 'type' and optionally other parameters). Currently,
        supported types of Form fields are: 'String', 'Text', 'Number', 'Radio', 'Date'. More information can be found
        on /public/apiDocs.
        :return: parsed response as a dictionary
        """
        data = {}

        if name is None or len(name) == 0:
            raise ValueError('Name is a required argument')
        data['name'] = name

        if tags is not None:
            if isinstance(tags, list):
                tags = ','.join(tags)
            data['tags'] = tags

        if fields is not None and len(fields) > 0:
            data['fields'] = fields
        else:
            raise ValueError('There has to be at least one field')

        return self.retrieve_api_results(self._get_api_url() + '/forms', request_type='POST', params=data)

    def get_form(self, form_id):
        """
        Gets information about a Form. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param form_id: numeric form ID or global ID
        :return: a dictionary that includes: form metadata, fields
        """
        numeric_doc_id = self._get_numeric_record_id(form_id)
        return self.retrieve_api_results(self._get_api_url() + '/forms/{}'.format(numeric_doc_id))

    def delete_form(self, form_id):
        """
         Deletes form by its ID, if it is in 'NEW' state or has not been deleted.
         :param form_id: numeric Form ID or global ID
        """
        return self.doDelete( "forms", form_id)
    
    def publish_form(self, form_id):
        """
        A newly created form is not available to create documents from until it has been published. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param form_id: numeric form ID or global ID
        :return: a dictionary that includes: form metadata, fields
        """
        numeric_doc_id = self._get_numeric_record_id(form_id)
        return self.retrieve_api_results(self._get_api_url() + '/forms/{}/publish'.format(numeric_doc_id),
                                         request_type='PUT')

    def unpublish_form(self, form_id):
        """
        Unpublishing a form hides it from being available to create documents. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param form_id: numeric form ID or global ID
        :return: a dictionary that includes: form metadata, fields
        """
        numeric_doc_id = self._get_numeric_record_id(form_id)
        return self.retrieve_api_results(self._get_api_url() + '/forms/{}/unpublish'.format(numeric_doc_id),
                                         request_type='PUT')

    def share_form(self, form_id):
        """
        Shares this form with your groups. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param form_id: numeric form ID or global ID
        :return: a dictionary that includes: form metadata, fields
        """
        numeric_doc_id = self._get_numeric_record_id(form_id)
        return self.retrieve_api_results(self._get_api_url() + '/forms/{}/share'.format(numeric_doc_id),
                                         request_type='PUT')

    def unshare_form(self, form_id):
        """
        Unshares this form with your groups. Only the owner of the Form (its creator) will be able to read or modify
        this Form after this action is performed. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param form_id: numeric form ID or global ID
        :return: a dictionary that includes: form metadata, fields
        """
        numeric_doc_id = self._get_numeric_record_id(form_id)
        return self.retrieve_api_results(self._get_api_url() + '/forms/{}/unshare'.format(numeric_doc_id),
                                         request_type='PUT')

    # Folder / notebook methods

    def create_folder(self, name, parent_folder_id=None, notebook=False):
        """
        Creates containers to hold RSpace documents and notebook entries. You can create folders in your Workspace and
        Gallery folders, and notebooks in your Workspace. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :param name: name of the folder or notebook
        :param parent_folder_id: numeric form ID or global ID
        :param notebook: True to create a notebook, False to create a folder
        :return: metadata about the created notebook or folder
        """
        data = {
            'notebook': notebook
        }

        if name is None or len(name) == 0:
            raise ValueError('Name is a required argument')
        data['name'] = name

        if parent_folder_id is not None:
            numeric_folder_id = self._get_numeric_record_id(parent_folder_id)
            data['parentFolderId'] = numeric_folder_id

        return self.retrieve_api_results(self._get_api_url() + '/folders', request_type='POST', params=data)
    
    def delete_folder(self, folder_id):
        """
         Deletes a folder or notebook by its ID.
         :param form_id: numeric Folder/Notebook ID or global ID
        """
        return self.doDelete( "folders", folder_id)
    
    def get_folder(self, folder_id):
        """
        Getter for a Folder or notebook that you are authorised to view.
        :param folder_id: numeric folder ID or global ID
        :return: metadata about the folder or notebook
        """
        numeric_folder_id = self._get_numeric_record_id(folder_id)
        return self.retrieve_api_results(self._get_api_url() + '/folders/{}'.format(numeric_folder_id))

    def list_folder_tree (self, folder_id=None, typesToInclude=[]):
        """
         Lists contents of a folder by its ID.
         :param folder_id. Optional folderId. If none, will return listing of Home Folder
         :param typesToInclude: An optional list of any of 'folder', 'notebook' or 'document'. Results
          will be restricted to these types
         :return a paginated folder listing
        """
        url = ""
        if folder_id is not None:
            url = self._get_api_url() + '/folders/tree/{}'.format(folder_id)
        else:
            url = self._get_api_url() + '/folders/tree'
        params = {}
        if len(typesToInclude) > 0:
            if 'document' not in typesToInclude and 'notebook' not in typesToInclude and 'folder' not in typesToInclude:
                raise ValueError('typesToInclude must be contain "document", "notebook" and/or "folder"')
            params['typesToInclude'] =",".join(typesToInclude)
        return self.retrieve_api_results(url, params)
        
                 
    # Groups methods
    def get_groups(self):
        """ 
        Gets a list of groups that you belong to. May be empty if you are not
        in any groups.
        """
        return self.retrieve_api_results(self._get_api_url()+'/groups')
    
    # Import methods
    def import_word(self, file, folder_id=None ,image_folder_id=None):
        """
         Imports a Word file into RSpace and creates an RSpace document from it.
         :param file: The Word file to import
         :param folder_id: Optionally, the ID of a folder in which to create the
          new document
         :param folder_id: Optionally, the ID of a folder in the image gallery
          into which images extracted from Word documents will be placed. By default, these
           will be placed in the top-level of the Gallery. 
        """
        data = {}
        if folder_id is not None:
            numeric_folder_id = self._get_numeric_record_id(folder_id)
            data['folderId'] = numeric_folder_id
        if image_folder_id is not None:
            numeric_imagefolder_id = self._get_numeric_record_id(image_folder_id)
            data['imageFolderId'] = numeric_imagefolder_id
            

        response = requests.post(self._get_api_url() + '/import/word', files={"file": file}, data=data,
                                 headers=self._get_headers())
        return self._handle_response(response)
    
    # Miscellaneous methods
    def get_status(self):
        """
        Simple API call to check that API service is available. Throws an AuthenticationError if authentication fails.
        More information on https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        :return: parsed response as a dictionary (most important field is 'message' which is supposed to be 'OK')
        """
        return self.retrieve_api_results(self._get_api_url() + '/status')
    
    ##### Non - documented, non public API methods:
    # Sysadmin methods
    def get_users(self, page_number=0, page_size=20, tempaccount_only=True, created_before="2018-04-30",last_login_before=None):
        """
        Gets list of temporary users
        """
        params = {
            'pageSize': page_size,
            'pageNumber': page_number,
            'createdBefore' : created_before,
            'tempAccountsOnly': tempaccount_only
        }
        if last_login_before is not None:
            params['lastLoginBefore'] = last_login_before

        return self.retrieve_api_results(self._get_api_url() + '/sysadmin/users', params)
    
    def deleteTempUser(self, user_id):
        return self.doDelete( "sysadmin/users", user_id)
        


