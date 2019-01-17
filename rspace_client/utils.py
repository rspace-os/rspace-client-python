import argparse
import rspace_client
def createClient():
    """
    Parses command line arguments: server, apiKey
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
    parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
    args = parser.parse_args()

    client = rspace_client.Client(args.server, args.apiKey)
    return client