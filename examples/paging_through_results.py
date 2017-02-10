#!/usr/bin/env python3

from __future__ import print_function
import argparse
import rspace_client


def print_document_names(response):
    print('Documents in response:')
    for document in response['documents']:
        print(document['name'], document['id'], document['lastModified'])

# Parse command line parameters
parser = argparse.ArgumentParser()
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
args = parser.parse_args()

client = rspace_client.Client(args.server, args.apiKey)

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