from enum import Enum


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
