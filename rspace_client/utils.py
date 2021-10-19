import argparse
import rspace_client.eln.eln as eln
import rspace_client.inv.inv as inv


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "server",
        help="RSpace server URL (for example, https://community.researchspace.com)",
        type=str,
    )
    parser.add_argument(
        "apiKey", help="RSpace API key can be found on 'My Profile'", type=str
    )
    args = parser.parse_args()
    return args


def createELNClient():
    """
    Parses command line arguments: server, apiKey
    """
    args = _parse_args()
    client = eln.ELNClient(args.server, args.apiKey)
    return client


def createInventoryClient():
    """
    Parses command line arguments: server, apiKey
    """
    args = _parse_args()
    client = inv.InventoryClient(args.server, args.apiKey)
    return client
