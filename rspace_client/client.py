import requests
import json
from enum import Enum


class Client:
    class ConnectionError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    class NoSuchLinkRel(Exception):
        pass

    API_VERSION = 'v1'

    def __init__(self, rspace_url, api_key):
        self.rspace_url = rspace_url
        self.api_key = api_key

    def _get_api_url(self):
        return '%s/api/%s' % (self.rspace_url, Client.API_VERSION)

    def retrieve_api_results(self, url, params=None, content_type='application/json'):
        headers = {
            'apiKey': self.api_key,
            'Accept': content_type
        }
        try:
            response = requests.get(url, params=params, headers=headers)

            # Check whether response includes UNAUTHORIZED response code
            if response.status_code == 401:
                raise Client.AuthenticationError(response.json()['message'])

            if response.status_code != 200:
                raise ValueError(next(iter(response.json()['errors'] or []), None) or response.json()['message'])

            if content_type == 'application/json':
                return response.json()
            else:
                return response.text
        except requests.exceptions.ConnectionError as e:
            raise Client.ConnectionError(e)

    @staticmethod
    def _get_links(response):
        try:
            return response['_links']
        except KeyError:
            raise Client.NoSuchLinkRel('There are no links!')

    def get_link_contents(self, response, link_rel):
        return self.retrieve_api_results(self.get_link(response, link_rel))

    def get_link(self, response, link_rel):
        for link in self._get_links(response):
            if link['rel'] == link_rel:
                return link['link']
        raise Client.NoSuchLinkRel('Requested link rel "%s", available rel(s): %s' %
                                   (link_rel, ', '.join([x['rel'] for x in self._get_links(response)])))

    def download_link_to_file(self, url, filename):
        headers = {
            'apiKey': self.api_key,
            'Accept': 'application/octet-stream'
        }
        with open(filename, 'wb') as fd:
            for chunk in requests.get(url, headers=headers).iter_content(chunk_size=128):
                fd.write(chunk)

    @staticmethod
    def link_exists(response, link_rel):
        return link_rel in [x['rel'] for x in Client._get_links(response)]

    # Documents methods
    def get_documents(self, query, order_by='lastModified desc', page_number=0, page_size=20):
        params = {
            'query': query,
            'orderBy': order_by,
            'pageSize': page_size,
            'pageNumber': page_number
        }
        return self.retrieve_api_results(self._get_api_url() + '/documents', params)

    def get_documents_advanced_query(self, advanced_query, order_by='lastModified desc', page_number=0, page_size=20):
        params = {
            'advancedQuery': json.dumps(advanced_query),
            'orderBy': order_by,
            'pageSize': page_size,
            'pageNumber': page_number
        }
        return self.retrieve_api_results(self._get_api_url() + '/documents', params)

    def get_document(self, doc_id):
        return self.retrieve_api_results(self._get_api_url() + '/documents/' + str(doc_id))

    def get_document_csv(self, doc_id):
        return self.retrieve_api_results(self._get_api_url() + '/documents/' + str(doc_id), content_type='text/csv')

    # Miscellaneous methods
    def get_status(self):
        return self.retrieve_api_results(self._get_api_url() + '/status')


class AdvancedQueryBuilder:
    class QueryType(Enum):
        GLOBAL = 'global'
        FULL_TEXT = 'fullText'
        TAG = 'tag'
        NAME = 'name'
        CREATED = 'created'
        LAST_MODIFIED = 'lastModified'
        FORM = 'form'
        ATTACHMENT = 'attachment'

    # Operand can be either 'and' or 'or'
    def __init__(self, operator='and'):
        self.operand = operator
        self.terms = []

    # query_type is of type QueryType
    def add_term(self, query, query_type):
        if not isinstance(query_type, AdvancedQueryBuilder.QueryType):
            raise TypeError('query_type must be an instance of QueryType (for example, QueryType.GLOBAL)')
        self.terms.append({
            'query': query,
            'queryType': query_type.value
        })
        return self

    def get_advanced_query(self):
        return {
            'operator': self.operand,
            'terms': self.terms
        }

    def __str__(self):
        return str(self.get_advanced_query())