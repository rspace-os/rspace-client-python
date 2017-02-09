#!/usr/bin/env python3

from __future__ import print_function
import argparse
import json
import rspace_client
import sys

# Parse command line parameters
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)

print('Form ID to search for (for example, FM123)?')
form_id = sys.stdin.readline().strip()

advanced_query = json.dumps({
    'operator': 'and',
    'terms': [
        {
            'query': form_id,
            'queryType': 'form'
        }
    ]
})

# Alternatively, the same advanced query can be constructed

advanced_query = rspace_client.AdvancedQueryBuilder(operator='and').\
    add_term(form_id, rspace_client.AdvancedQueryBuilder.QueryType.FORM).\
    get_advanced_query()

response = client.get_documents_advanced_query(advanced_query)

print('Found answers:')
for document in response['documents']:
    print('Answer name:', document['name'])
    document_response = client.get_document_csv(document['id'])
    print(document_response)
