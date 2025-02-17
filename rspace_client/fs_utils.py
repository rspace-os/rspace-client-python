# This script contains utility functions for working with pyfilesystems.

def path_to_id(path):
    """
        A path is a slash-delimited string of Global Ids. The last element is
        the global id of the file or folder. This function extract just the id
        of the file or folder, which will be a string-encoding of a number.
    """
    global_id = path
    if '/' in path:
        global_id = path.split('/')[-1]
    return global_id[2:]
