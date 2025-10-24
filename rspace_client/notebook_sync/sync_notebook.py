from notebook import app
from rspace_client.eln import eln
import os
import hashlib
import dill
import ipynbname
from ipylab import JupyterFrontEnd
import traceback
from bs4 import BeautifulSoup
import nbformat
import asyncio
import getpass
import keyring
from urllib.parse import urlparse
import time

RSPACE_DOC_FOR_NOTEBOOK = 'rspace_doc_for_notebook'
RSPACE_ATTACHMENTS_FOR_NOTEBOOK = 'data_attached_to_notebook'
RSPACE_GALLERY_FILE_FOR_NOTEBOOK = 'file_for_notebook'
RSPACE_EXECUTION_COUNT_FOR_NOTEBOOK = 'RSPACE_EXECUTION_COUNT_FOR_NOTEBOOK'
RSPACE_HISTORY_DATA = 'RSPACE_HISTORY_DATA'
RSPACE_DOC_URL = 'workspace/editor/structuredDocument/'
RSPACE_DOC_VERSION_URL_START = 'workspace/editor/structuredDocument/audit/view?globalId='
RSPACE_KEYRING_SERVICE_ID = 'RSpaceSyncJupyterNotebookApp'

rspace_client = None
app = JupyterFrontEnd()


def set_password(rspace_username=None):
    """
    sets password for 'rspace_username' in keyring
    """
    if rspace_username is None:
        raise Exception("You must provide an rspace_username.")
    service_id = RSPACE_KEYRING_SERVICE_ID
    retrieved_password = getpass.getpass("Please enter the RSpace Api key for the provided username: ")
    keyring.set_password(service_id, rspace_username, retrieved_password)
    return "password set"


async def sync_notebook_to_rspace(rspace_url="", attached_data_files="", notebook_name=None, server_url=None,
                                  rspace_prexisting_document_id=None, rspace_document_target_field=None,
                                  server_port=None, rspace_username=None):
    """
    Saves notebook using ipylab and then writes notebook to Rspace document as
    an attachment if the execution_count of the notebook has changed since the last time
    this cell was run. Note that the execution count of this cell does not contribute to
    the comparison - we will not write data to RSpace if only this cell has been run
    since the last time data was written to RSpace.
    Attached data is also written to RSpace if its hash_sum has changed.

    The notebook and attached data will always be written to RSpace at least once (on the first time this cell is run).

    Parameters:

    rspace_url :  Your RSpace instance goes here

    attached_data_files :
                        All data that will be saved to RSpace along with this notebook: select the data in the file browser and choose 'copy path'
                        then paste here using a ',' comma to separate files if there is more than one.

        Example:
            attached_data_files = "spectroscopy_data.csv, data/spectroscopy_data2.csv, data/spectroscopy_data3.csv"
            The code in this cell will calculate paths to the data relative to the location of this notebook. Therefore do
            not change the 'paths' to the data, regardless of whether this notebook is in the top directory or in a sub directory.

            If you wish to have no attached data, set this value to be "" (a pair of double quotes)

            Example:
                attached_data_files = ""

    notebook_name:
                This must be set to a the value of the PATH to the notebook (select the notebook in the file browser and choose 'copy path'),
                if exceptions are thrown trying to determine the notebook name.

                If this value is set server_url  MUST also be set.
    server_url:
                This must be set to a value if exceptions are thrown or the calculated value is incorrect when trying to determine the server url. Give the url
                of the server including the port: eg http://localhost:10000 (no trailing '/')

                If this value is set, notebook_name MUST also be set.

    rspace_prexisting_document_id:
                                    Default behaviour creates a new RSpace document when this cell is executed and attached this jupyter notebook to the new document.

                                    Setting rspace_prexisting_document_id to a value other than None will attach this jupyter notebook to the RSpace document
                                    with the given ID instead of creating a new RSpace document.

    rspace_document_target_field:
                                    Default behaviour writes links to this notebook into the 'first' field in an RSpace document (field '0'). Set this to a value
                                    if a different field should be used. For example, to target the third field in a document, use the value '2'.

                                    If this is set to a value other than None, rspace_prexisting_document_id must be set to a value other than None.
    server_port:
                Set this to a value if server_url  is calculated correctly except for the port (which will happen, for example
                if the port is being mapped inside a docker container to an external port)

    rspace_username:
                   This must be set to the name of the rspace user where the notebook is being saved
    """

    def get_server_urls():
        all_urls = []
        if (server_url is not None):
            all_urls.append(server_url + '/lab/tree/' + notebook_name)
        else:
            try:
                for srv in ipynbname._list_maybe_running_servers():
                    srv, path = ipynbname._find_nb_path()
                    if server_port is not None:
                        srv_url = srv['url']
                        part_url = srv_url[:srv_url.rfind(':') + 1]
                        all_urls.append(part_url + str(server_port) + '/lab/tree/' + str(path))
                    else:
                        all_urls.append(srv['url'] + 'lab/tree/' + str(path))
            except Exception:
                print(f"Error determining server urls, please manually set a value for 'server_url'")
                raise  # Code may fail if server has a password/doesnt use token auth - see ipynbname README
        return all_urls

    def get_server_roots():
        """
        this will only be called if ipyname library is working correctly
        """
        all_roots = []
        try:
            if len(all_roots) == 0:
                for srv in ipynbname._list_maybe_running_servers():
                    srv, path = ipynbname._find_nb_path()
                    root = srv['root_dir']
                    all_roots.append(root)
        except Exception:
            print(f"Error determining server roots, please manually set a value for 'server_url'")
            raise  # Code may fail if server has a password/doesnt use token auth - see ipynbname README
        return all_roots

    def get_notebook_name():
        try:
            if notebook_name is not None:
                if '/' in notebook_name:
                    notebook_name_alone = notebook_name[notebook_name.rfind('/') + 1:]
                else:
                    notebook_name_alone = notebook_name
                return {'name': notebook_name_alone, 'root_name': notebook_name_alone[:notebook_name_alone.rfind('.')],
                        'name_path': notebook_name}
            nb_fname = ipynbname.name()
            nb_path = str(ipynbname.path())
            for srv_root in get_server_roots():
                if not srv_root.endswith("/"):
                    srv_root = srv_root + "/"
                if srv_root in nb_path:
                    nb_path = nb_path.replace(srv_root, '')
            ext_pos = ('' + nb_path).rfind('.')
            ext = nb_path[ext_pos:]
            return {'name': nb_fname + ext, 'root_name': nb_fname, 'name_path': nb_path}
        except Exception as e:
            print(f"Error getting notebook name, please manually set a value for 'notebook_name'")
            raise

    def get_password():
        """
        Retrieves password from (or saves a new password to) keyring
        """
        service_id = RSPACE_KEYRING_SERVICE_ID

        retrieved_password = keyring.get_password(service_id, rspace_username)
        if retrieved_password is None:
            retrieved_password = getpass.getpass("Please enter your RSpace Api key: ")
            keyring.set_password(service_id, username, retrieved_password)
        return retrieved_password

    def get_rspace_client():
        """
        Returns rspace ELN API client
        """
        global rspace_client
        if rspace_client is None:
            retrieved_password = get_password()
            rspace_client = eln.ELNClient(rspace_url, retrieved_password)
        return rspace_client

    def save_rspace_data(rspace_doc, attachments, gallery_file, execution_count, history_data):
        # Define the filename to save the state
        state_filename = get_notebook_name()['root_name'] + "_state.pkl"
        with open(state_filename, 'wb') as f:
            dill.dump({RSPACE_DOC_FOR_NOTEBOOK: rspace_doc, RSPACE_ATTACHMENTS_FOR_NOTEBOOK: attachments,
                       RSPACE_GALLERY_FILE_FOR_NOTEBOOK: gallery_file,
                       RSPACE_EXECUTION_COUNT_FOR_NOTEBOOK: execution_count, RSPACE_HISTORY_DATA: history_data}, f)

    def load_data():
        state_filename = get_notebook_name()['root_name'] + "_state.pkl"

        if os.path.exists(state_filename):
            # Load the variables from the file using dill
            with open(state_filename, 'rb') as f:
                try:
                    loaded_state = dill.load(f)
                except Exception as e:
                    loaded_state = {}
        else:
            loaded_state = {}
        return loaded_state

    async def save_notebook():
        '''
        'docmanager:save' does not appear to hook into any callback invoked when the document is actually saved. So we have no
        idea when it has completed. Jupyter Notebooks can be (at least) 100MB in size - there are some limitations imposed by the
        Tornado web server Jupyter uses. When save is called the entire contents of the notebook are sent as the body of a REST
        PUT request, including any images in cell outputs.

        We can write to the notebook data store synchronously using python's file handling API but we cant access the contents of the notebook the user
        actually sees because this runs in the browser and the Jupyter API gives no access. The version of the notebook in the browser does
        not match the version in the back end file store whenever the notebook is in 'unsaved' state (a black circle appears in its Jupyter notebook tab).

        There is a REST API which can get file contents:
        https://github.com/ipython/ipython/wiki/IPEP-27%3A-Contents-Service#get-an-existing-file
        and save:
        https://github.com/ipython/ipython/wiki/IPEP-27%3A-Contents-Service#save-file
        However the GET method of this REST API also fetches its data from the BACK END, not from the document front end contents.
        The rest API would also be difficult to use as its not straightforward to obtain the host location for URL endpoints programatically.

        The ipylab library being used in this code wraps widgets in the UI and calling 'docmanager:save' programatically 'clicks' the save button.

        Solution:
        (We do not get into a infinite loop when save is called because the notebook has ALWAYS changed - the act
        of running the sync code begins *prior to calling save* by outputting text on the screen, causing the notebook to enter 'unsaved' state in the UI.)

        1) Get modified time of file
        2) Loop until modified time changes
        3) Timeout after 30s - infinite loop can happen when user enters an incorrect notebook name and then mistakely saves a different notebook which is unchanged
        '''
        file_path = get_notebook_name()['name_path']
        start_mod_time = os.path.getmtime(file_path)
        curr_mod_time = start_mod_time
        start_watch_time = time.time()
        # this arbitrary 1 second sleep is to allow the UI time to update and register that it is the 'unsaved' state
        await asyncio.sleep(1)
        app.commands.execute('docmanager:save')
        while start_mod_time == curr_mod_time:
            await asyncio.sleep(0.1)
            curr_mod_time = os.path.getmtime(file_path)
            elapsed_time = time.time() - start_watch_time
            if elapsed_time > 30:
                msg = "TIMEOUT ON SAVE ***** DID YOU MEAN TO SAVE NOTEBOOK: " + file_path + " ?"
                raise Exception(msg)

    async def reload_notebook():
        app.commands.execute('docmanager:reload')
        # 'docmanager:reload' does not appear to hook into any callback invoked when the document is actually reloaded
        await asyncio.sleep(1)

    def make_metadata_cell(nb_gallery_file, attachment_files, rspace_doc, history_data):
        rspace_document_file_id = str(rspace_doc['id'])
        # new content plus new attachment data increments the document version by two
        rspace_document_version = 2 if rspace_doc['version'] == 1 else rspace_doc['version'] + 2
        rspace_document_name = rspace_doc['name']
        rspace_document_globalId = rspace_doc['globalId'] + 'v' + str(rspace_document_version)
        nb_gallery_file_id = nb_gallery_file['id']
        nb_gallery_file_version = int(nb_gallery_file['version'])
        nb_gallery_file_version = nb_gallery_file_version + 1
        nb_gallery_file_name = nb_gallery_file['name']
        meta_data_cell = nbformat.v4.new_markdown_cell()
        rspace_doc_for_markdown = f'[The RSpace Document describing this notebook, version: {rspace_document_version}]({rspace_url}{RSPACE_DOC_URL}{rspace_document_file_id})'
        gallery_doc_markdown = f'[This Notebook in RSpace Gallery: {nb_gallery_file_name} version: {nb_gallery_file_version}]({rspace_url}gallery/item/{nb_gallery_file_id})'
        meta_data_cell['source'] = rspace_doc_for_markdown + "<br>" + gallery_doc_markdown
        if len(attached_data_files) != 0:
            attached_data_files_list = attached_data_files.split(",")
            for attached_data in attached_data_files_list:
                attachment_file_id = attachment_files.get(attached_data, {}).get('id')
                attachment_version = attachment_files.get(attached_data, {}).get('version')
                meta_data_cell[
                    'source'] += f'<br>[Attached Data {attached_data} version: {attachment_version} ]({rspace_url}gallery/item/{attachment_file_id})'
        else:
            meta_data_cell['source'] += f'<br> No Attached Data'
        for url in get_server_urls():
            meta_data_cell['source'] += f'<br>[This notebook on the jupyter server]({url})'
        new_history = f'<br>RSpace doc [<strong>{rspace_document_name}</strong> version {rspace_document_version}]({rspace_url}{RSPACE_DOC_VERSION_URL_START}{rspace_document_globalId}) contains this Notebook, version {nb_gallery_file_version}, executed with: '
        if len(attached_data_files) != 0:
            for attached_data in attached_data_files.split(","):
                attachment_version = attachment_files.get(attached_data, {}).get('version')
                new_history += f'Data <strong>{attached_data}</strong> version: {attachment_version} '
        history_data['text'] = new_history + history_data['text']
        meta_data_cell['source'] += f"<br> {history_data['text']}"
        meta_data_cell['metadata'] = {
            "rspace_metadata": {"documentFor": "docid", "notebook_file": "docid", "attachments": [""]}}
        return meta_data_cell

    async def add_rspace_details_to_previously_uploaded_notebook_metadata(fname, notebook, nb_gallery_file,
                                                                          attachment_files,
                                                                          rspace_doc, history_data):
        """
        We have to save meta data about a notebook before its been uploaded to the gallery.
        Therefore increment version by 1 when writing the metadata.

        If nb_gallery_file[id] is None its the initial upload to the Gallery and so do not write any meta data
        """
        if nb_gallery_file.get('id') is None:
            return
        meta_data_cell = make_metadata_cell(nb_gallery_file, attachment_files, rspace_doc, history_data)
        replaced = False
        for i, cell in enumerate(notebook['cells']):
            if 'rspace_metadata' in cell['metadata']:
                notebook["cells"][i] = meta_data_cell
                replaced = True
        if replaced is False:
            notebook["cells"].extend([meta_data_cell])
        with open(fname, 'w', encoding='utf-8') as modified:
            nbformat.write(notebook, modified)

    def get_notebook_execution_count(notebook):
        """
        return the sum of all execution counts for code cells
        note that this code cell does not contribute to the count:
        it is always saved before its execution_count gets updated
        and so the value of execution_count for this cell is always 'None'
        """
        new_executed_count = 0
        for i, cell in enumerate(notebook['cells']):
            if cell['cell_type'] == 'code':
                cell_count = cell['execution_count']
                if cell_count is None:
                    cell_count = 0
                new_executed_count += cell_count
        return new_executed_count

    def make_content(nb_gallery_file_id, attachment_files):
        content = f"""
                    <fileId={nb_gallery_file_id}>
                    """
        if len(attached_data_files) != 0:
            for attachment_file in attached_data_files.split(","):
                content += f"""
                <fileId={attachment_files.get(attachment_file)['id']}>
                """
        return content

    def remove_jupyter_attachment_divs(content, nb_gallery_file_id, attachment_files):
        """
        Iterate all attachments in the document field and if any have ids matching the stored ids for this notebook
        then remove them
        """
        soup = BeautifulSoup(content, 'html.parser')
        attachment_divs = soup.find_all("div", {"class": "attachmentDiv"})
        for attachment_div in attachment_divs:
            href_tag = attachment_div.find('a')
            gallery_link = '/Streamfile/' + str(nb_gallery_file_id)
            if gallery_link == href_tag['href']:
                attachment_div.decompose()
                continue
            if len(attached_data_files) != 0:
                for attachment_file in attached_data_files.split(","):
                    attachment_file_id = attachment_files.get(attachment_file, {}).get('id')
                    attachment_link = '/Streamfile/' + str(attachment_file_id)
                    if attachment_link == href_tag['href']:
                        attachment_div.decompose()
                        break
        return soup.prettify()

    def upload_file_to_gallery(rspaceid, file, client):
        if rspaceid is None:
            data = client.upload_file(file)
        else:
            data = client.update_file(file, rspaceid)
        return data

    def calc_hash(filename):
        sha256_hash = hashlib.sha256()
        with open(filename, "rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def upload_attached_data(attachment_files):
        client = get_rspace_client()
        if len(attached_data_files) != 0:
            attached_data_files_list = attached_data_files.split(",")
            for attached_data in attached_data_files_list:
                if attached_data:
                    # make file paths to data relative to the location of this notebook
                    nested_dir_pos = get_notebook_name()['name_path'].count('/')
                    relative_attached_data = attached_data
                    for i in range(nested_dir_pos):
                        relative_attached_data = "../" + relative_attached_data
                    with open(relative_attached_data, 'r', encoding='utf-8') as attch:
                        attachment_file_id = attachment_files.get(attached_data, {}).get('id')
                        attachment_file_hash = attachment_files.get(attached_data, {}).get('hash')
                        calc_latest_hash = calc_hash(relative_attached_data)
                        if calc_latest_hash != attachment_file_hash:
                            attachment_file_data = upload_file_to_gallery(attachment_file_id, attch, client)
                            attachment_file_data['hash'] = calc_latest_hash
                            attachment_files[attached_data] = attachment_file_data

    async def upload_notebook_to_gallery(current_notebook, notebook, nb_gallery_file, attachment_files,
                                         rspace_doc, history_data):
        """
        Metadata about the notebook is written to the notebook before it us uploaded to the Gallery (and the version incremented predictively by one).
        If the notebook has never been uploaded to the Gallery we have no stored rspace-id to write to the meta data and so we do not write any meta data.
        We do the initial upload (which creates a Gallery file with version = '1'.  Then we write meta data (incrementing the version to '2' and upload the notebook
        a second time.
        """
        await add_rspace_details_to_previously_uploaded_notebook_metadata(current_notebook, notebook, nb_gallery_file,
                                                                          attachment_files,
                                                                          rspace_doc, history_data)
        with open(current_notebook, 'r', encoding='utf-8') as nb_file:
            client = get_rspace_client()
            nb_gallery_file = upload_file_to_gallery(nb_gallery_file.get('id'), nb_file, client)
        if nb_gallery_file.get('version') == 1:
            await asyncio.sleep(1)
            await add_rspace_details_to_previously_uploaded_notebook_metadata(current_notebook, notebook,
                                                                              nb_gallery_file, attachment_files,
                                                                              rspace_doc, history_data)
            with open(current_notebook, 'r', encoding='utf-8') as nb_file:
                nb_gallery_file = upload_file_to_gallery(nb_gallery_file.get('id'), nb_file, client)
                await asyncio.sleep(1)
        return nb_gallery_file

    def get_field_content(rspace_doc):
        if rspace_document_target_field is None:
            return rspace_doc['fields'][0]['content']
        else:
            return rspace_doc['fields'][int(rspace_document_target_field)]['content']

    def assert_invariants():
        if (len(rspace_url) == 0):
            raise Exception("You must provide a URL for your RSpace instance.")

        parsed_url = urlparse(rspace_url)
        if not (parsed_url.scheme and parsed_url.netloc):
            raise Exception("Your value for RSpace url is not a valid url.")

        if rspace_username is None:
            raise Exception("You must provide an rspace_username.")

        if rspace_document_target_field is not None and rspace_prexisting_document_id is None:
            raise Exception("If rspace_document_target_field has a value rspace_prexisting_document_id must also.")

        if server_url is not None and notebook_name is None or notebook_name is not None and server_url is None:
            raise Exception("Both server_url  and notebook_name must be either None or have a value")

    def notebook_can_be_saved(current_notebook):
        with open(current_notebook, 'r') as notebook:
            notebook_node = nbformat.read(notebook, nbformat.NO_CONVERT)
            kernel_type = notebook_node.metadata.kernelspec.display_name.lower()
            if 'python' in kernel_type:
                return True
        return False

    assert_invariants()
    current_notebook = get_notebook_name()['name']
    # do not remove this print statement as it is required to ensure notebook is always in modified state when we call save_notebook
    print(f'Running sync on notebook:{current_notebook}')
    if notebook_can_be_saved(current_notebook):
        await save_notebook()
    get_server_urls()
    with open(current_notebook, 'r') as notebook:
        notebook_node = nbformat.read(notebook, nbformat.NO_CONVERT)
    try:
        loaded_state = load_data()
        execution_count = loaded_state.get(RSPACE_EXECUTION_COUNT_FOR_NOTEBOOK)
        new_execution_count = get_notebook_execution_count(notebook_node)
        if execution_count == new_execution_count:
            print("No execution since last sync: no data updated in RSpace")
            return
        client = get_rspace_client()
        rspace_doc = loaded_state.get(RSPACE_DOC_FOR_NOTEBOOK)
        attachment_files = loaded_state.get(RSPACE_ATTACHMENTS_FOR_NOTEBOOK, {})
        nb_gallery_file = loaded_state.get(RSPACE_GALLERY_FILE_FOR_NOTEBOOK, {})
        history_data = loaded_state.get(RSPACE_HISTORY_DATA, {'text': ''})
        current_notebook = get_notebook_name()['name']
        upload_attached_data(attachment_files)
        if rspace_doc is None and rspace_prexisting_document_id is None:
            rspace_doc = client.create_document(name="DocumentFor_" + current_notebook,
                                                tags=["Python", "API", "Jupyter"])
        if rspace_document_target_field is not None:
            rspace_document_target_field_id = str(rspace_doc['fields'][int(rspace_document_target_field)]['id'])
        else:
            rspace_document_target_field_id = str(rspace_doc['fields'][0]['id'])
        rspace_document_file_id = str(
            rspace_doc['id']) if rspace_prexisting_document_id is None else rspace_prexisting_document_id
        rspace_doc = client.get_document(rspace_document_file_id)
        nb_gallery_file = await upload_notebook_to_gallery(current_notebook, notebook_node, nb_gallery_file,
                                                           attachment_files, rspace_doc, history_data)
        nb_gallery_file_id = nb_gallery_file.get('id')
        previous_content = get_field_content(rspace_doc)
        previous_content = remove_jupyter_attachment_divs(previous_content, nb_gallery_file_id, attachment_files)
        new_content = make_content(nb_gallery_file_id, attachment_files) + previous_content
        rspace_doc = client.update_document(rspace_document_file_id, tags=['Python', 'API', 'Jupyter'],
                                            fields=[
                                                {'id': rspace_document_target_field_id, "content": new_content}])
        await reload_notebook()
        save_rspace_data(rspace_doc, attachment_files, nb_gallery_file, new_execution_count, history_data)
        return 'success'
    except Exception as e:
        print(traceback.format_exc())
        print(f"Error reading notebook file: {e}")
        return traceback.format_exc()
