from enum import Enum
import json


class AdvancedQueryBuilder:
    """
    AdvancedQueryBuilder helps to build an advanced query for /documents API endpoint.
    """
    class QueryType(Enum):
        """
        Lists all query types available in /documents API endpoint. More information on
        https://community.researchspace.com/public/apiDocs (or your own instance's /public/apiDocs).
        """
        GLOBAL = 'global'
        FULL_TEXT = 'fullText'
        TAG = 'tag'
        NAME = 'name'
        CREATED = 'created'
        LAST_MODIFIED = 'lastModified'
        FORM = 'form'
        ATTACHMENT = 'attachment'

    def __init__(self, operator='and'):
        """
        :param operator: either 'and' or 'or'
        """
        self.operand = operator
        self.terms = []

    def add_term(self, query, query_type):
        """
        Adds an additional search term to the query.
        :param query: query depending on the query_type can be either a text, date or Global ID
        :param query_type: query type from the QueryType enum
        :return: self
        """
        if not isinstance(query_type, AdvancedQueryBuilder.QueryType):
            raise TypeError('query_type must be an instance of QueryType (for example, QueryType.GLOBAL)')
        self.terms.append({
            'query': query,
            'queryType': query_type.value
        })
        return self

    def get_advanced_query(self):
        """
        Builds an advanced query.
        :return: JSON representation of the built advanced query
        """
        return json.dumps({
            'operator': self.operand,
            'terms': self.terms
        })

    def __str__(self):
        """
        :return: JSON representation of the built advanced query
        """
        return self.get_advanced_query()
