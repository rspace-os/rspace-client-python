#!/usr/bin/env python3

from __future__ import print_function
import rspace_client


def print_document_names(response):
    print('Documents in response:')
    for document in response['documents']:
        print(document['name'], document['id'], document['lastModified'])

# Parse command line parameters
client = rspace_client.utils.createClient()

# Simple search
response = client.get_documents()
print_document_names(response)

# Creation date (documents created between 2017-01-01 and 2017-12-01
advanced_query = rspace_client.AdvancedQueryBuilder().\
    add_term('2017-01-01;2017-12-01', rspace_client.AdvancedQueryBuilder.QueryType.CREATED).\
    get_advanced_query()

response = client.get_documents_advanced_query(advanced_query)
print_document_names(response)
while client.link_exists(response, 'next'):
    print('Retrieving next page...')
    response = client.get_link_contents(response, 'next')
    print_document_names(response)