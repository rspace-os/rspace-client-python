import os
import rspace_client
import argparse;
import xml.etree.ElementTree as ET
import tempfile
import zipfile
import time

'''
This code imports to RSpace an eCAT export that has already had its .odt files converted to .docx files.
You can use it as an example of code to walk a tree of folders containing files, .docx documents to
become RSpace documents, and images, which will be uploaded to RSpace as a tree of folders of documents
in the Workspace and trees of folders of images and files in the Gallery sections.
It ignores any .pdfs so if you need any of those uploaded then rename them to .PDF.
By default it simulates the API calls rather than running them, so you can generate a log
file with listings of what it will do when run with api_simulate set to False
In API simulate mode it still needs all the command line parameters, but it won't actually
interact with the RSpace specified (and that may not need to be a valid RSpace)
'''
# initial timestamp string to use as default log folder
default_log_folder  = "ecat_to_rspace_" + time.asctime().replace(" ", "_")
parser = argparse.ArgumentParser()
parser.add_argument("--logFolder", "-l", help="abs or relative path to folder to log progress, will be created if not exists",
                     type=str, default=default_log_folder)
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
parser.add_argument("srcDir", help="Root of uplod, for example 'eCAT''", type=str)
parser.add_argument("workspaceFolder", help="Folder ID in Workspace (number only)", type=int)
parser.add_argument("sharedFolder", help="Folder ID in Shared area (number only)", type=int)
parser.add_argument("galleryDocFolder", help="Folder ID in Gallery Docs area (number only)", type=int)
parser.add_argument("galleryImageFolder", help="Folder ID in Gallery Images area (number only)", type=int)


args = parser.parse_args()



api_simulate = True
log_folder_path = args.logFolder
logs = {}

def log_folder(workspace_or_shared, localPath, rspaceId):
    if workspace_or_shared != "S" and workspace_or_shared != "W":
        raise ValueError("workspace or shared must be 'W' or 'S'")
    print(logs['folder'])
    with open(logs['folder'], 'a+') as folder_log:
        folder_log.write("{ftype}|{localPath}|{rspace_id}\n"
                         .format(ftype=workspace_or_shared,localPath=localPath,rspace_id=rspaceId))
        

def setUpProgressLogFolder():
    if not os.path.exists(log_folder_path):
        print ("Creating log folder {}".format(log_folder_path))
        os.makedirs(log_folder_path)
        logs['folder']=os.path.join(log_folder_path, "folders.log")
        logs['gallery']=os.path.join(log_folder_path,"gallery.log")
        logs['word']=os.path.join(log_folder_path,"converted_word.log")
        

def isFolder(odtfname):
    print ('checking %s for folder' % odtfname)
    with tempfile.TemporaryDirectory() as tmpdirname:
        zip_ref = zipfile.ZipFile(odtfname, 'r')
        zip_ref.extract('content.xml',tmpdirname)
        zip_ref.close()

        tree = ET.parse(tmpdirname+'/content.xml')
        root = tree.getroot()

        count=0
        for child in root[3][0][2]:
            if child.tag[-9:] == 'table-row':
                count += 1
        if count == 2:
            print ('Folder!!')
        else:
            print ('Not folder!!')
        return (count == 2)
simulated_id=1000
simulated_response = {'id': simulated_id,'globalId': simulated_id,'name': "No Name"}
def api_call(callname, apiCall):
    returnval = ''
    start = time.time()
    if api_simulate:
        simulated_response['id']+=1
        simulated_response['globalId']+=1
        returnval = simulated_response
    else:
        returnval = apiCall()
    finish = time.time()
    print('API call {} took {:.1f} seconds'.format(callname, finish - start))
    if not api_simulate:
        time.sleep(0.5)
    return returnval

def create_dir_and_ancestors(fdict, dir):
    if dir in fdict:  # recursion termination
        return
    parent = os.path.dirname(dir)
    create_dir_and_ancestors(fdict, parent) # recurse, on return ancestor will exist
    # create folder for dir in parent and store id in dictionary
    print ('creating folder for {child} in {par} ({parentid})'.format(
        child = dir, par = parent, parentid = fdict[parent]))
    response = api_call('create_folder', lambda: client.create_folder(os.path.basename(dir), parent_folder_id=fdict[parent]))
    fdict[dir] = response['id']

def share_document(docId, groupId, folderId):
    print("Sharing document {} with group {} into folder {}".format(docId, groupId, folderId))
    shared = api_call('shareDocuments', lambda: client.shareDocuments([docId], groupId, sharedFolderId=folderId))

setUpProgressLogFolder()
client = rspace_client.Client(args.server, args.apiKey)

sharingGroupId = 0
if not api_simulate:
    groups = client.get_groups()
    if len(groups) == 0:
        raise Exception("Cannot proceed as you are not a member of a group")
    sharingGroupId = groups[0]['id']
    print("Sharing into the first group found - '{}' ({}) - shareFolder = {}".format(groups[0]['name'],
                                                                                     groups[0]['id'], groups[0]['sharedFolderId']))

wfolders = {args.srcDir : args.workspaceFolder} # workspace folders dictionary, keyed on source path
sfolders = {args.srcDir : args.sharedFolder} # shared folders dictionary, keyed on source path
gdfolders = {args.srcDir : args.galleryDocFolder} # gallery document folders dictionary, keyed on source path
gifolders = {args.srcDir : args.galleryImageFolder} # gallery image folders dictionary, keyed on source path

docCount = 0
imgCount = 0
fileCount = 0
for dirName, subdirList, fileList in os.walk(args.srcDir):
        print('Found directory: %s' % dirName)
        print('Processed (folders/instances): Docs {}/{}; Images {}/{}; Files {}/{}'.format(
            len(wfolders), docCount, len(gifolders), imgCount, len(gdfolders), fileCount))
        # always create w and s folders, only creat gd and gi as needed
        # "images" folders specially treated
        
        if os.path.basename(dirName) != "images":
            dirname = os.path.basename(dirName)
            parname = os.path.dirname(dirName)
            if not dirName in wfolders: #folders does not exist yet
                response = api_call('create_folder', lambda: client.create_folder(dirname, parent_folder_id=wfolders[parname]))
                wfolders[dirName] = response['id']
                print('Created workspacefolder {dir} ({dirnum}) in {par} ({parnum})'.format(
                    dir = dirname, dirnum = wfolders[dirName], par = os.path.basename(parname), parnum = wfolders[parname]))
                log_folder('W', dirName, response['id'])
                
            if not dirName in sfolders: #folder does not exist yet
                response = api_call('create_folder', lambda: client.create_folder(dirname, parent_folder_id=sfolders[parname]))
                sfolders[dirName] = response['id']
                print('Created shared folder {dir} ({dirnum}) in {par} ({parnum})'.format(
                    dir = dirname, dirnum = sfolders[dirName], par = os.path.basename(parname), parnum = sfolders[parname]))
                log_folder('S', dirName, response['id'])
            for filename in fileList:
                print ('considering: %s' % os.path.join(dirName, filename))
                if filename[-4:] == '.pdf' or filename[-5:] == '.docx':
                    print('ignoring %s ...' % os.path.join(dirName, filename))
                    continue
                if filename[-4:] == '.odt':
                    # if the odt isn't a folder odt import the .docx to wfolders[dirName]
                    # and share the RSpace document into sfolders[dirName]
                    if isFolder(os.path.join(dirName, filename)):
                        print('ignoring Folder odt %s' % os.path.join(dirName, filename))
                    else:
                        docxname = os.path.join(dirName, os.path.splitext(filename)[0] + '.docx')
                        print('importing %s to workspace and sharing' % docxname)
                        with open(docxname, 'rb') as f:
                            new_document = api_call('import_word', lambda: client.import_word(f, wfolders[dirName]))
                            docCount += 1
                            print('Document "{}" was imported to  folder {} as {} ({})'
                                  .format(f.name,wfolders[dirName], new_document['name'], new_document['globalId']))
                            print('sharing into {}'.format(sfolders[dirName]))
                            share_document(new_document['id'], sharingGroupId, sfolders[dirName])
                else: # some other kind of file, to go in document gallery
                    # create gdfolders[dirName] and parents if needed
                    print('creating Gallery Docs folder and parents for %s' % dirName)
                    create_dir_and_ancestors(gdfolders, dirName)
                    # upload to gdfolders[dirName]
                    print('uploading %s to Gallery Docs' % os.path.join(dirName,filename))
                    with open(os.path.join(dirName, filename), 'rb') as f:
                        new_file = api_call('upload_file', lambda: client.upload_file(f, caption=filename, folder_id=gdfolders[dirName]))
                        print('File "{}" was uploaded as {} ({})'.format(f.name, new_file['name'], new_file['id']))
                        fileCount += 1
                    # create a basic document with the same name and a link to the uploaded gallery file.
                    print('creating basic document, should be in {}'.format(wfolders[dirName]))
                    new_document = api_call('create_document', lambda: client.create_document(
                        name=filename, parent_folder_id=wfolders[dirName], fields=[{'content': 'Link to gallery file'}]
                    ))
                    print('New document was successfully created with global ID {}'.format(new_document['id']))

                    print('linking to gallery file')
                    updated_document = api_call('update_document', lambda: client.update_document(new_document['id'], fields=[{
                        'content': 'Link to the gallery file: <fileId={}>'.format(new_file['id'])
                    }]))
                    print('sharing into {}'.format(sfolders[dirName]))
                    share_document(new_document['id'], sharingGroupId, sfolders[dirName])
        else: # images folder
            parentDir = os.path.dirname(dirName)
            # create gifolders[parentDir] and parents as needed
            print ('creating Gallery Images folder and parents for %s' % parentDir)
            create_dir_and_ancestors(gifolders, parentDir)
            # TODO this needs refactoring to create document with a link to the folder instead of all the images
            for filename in fileList:
                # upload filename to gifolders[parentDir]
                print('uploading %s to GalleryImages' % filename)
                with open(os.path.join(dirName, filename), 'rb') as f:
                    new_file = api_call('upload_file', lambda: client.upload_file(f, folder_id=gifolders[parentDir]))
                    print('Image "{}" was uploaded as {} ({})'.format(f.name, new_file['name'], new_file['id']))
                    imgCount += 1
            # create imageDoc = "eCAT gallery images" basic document in wfolders[parentDir]
            print('creating basic document for link to gallery images folder, should be in {}'.format(wfolders[parentDir]))
            docname = 'eCAT gallery images for documents in ' + os.path.basename(parentDir)
            folder_link = 'Gallery Images in Documents in this folder:\n<docId={}>\n'.format(gifolders[parentDir])
            new_document = api_call('create_document', lambda: client.create_document(
                name=docname, parent_folder_id=wfolders[parentDir], fields=[{'content': folder_link}]
            ))
            print('New document was successfully created with global ID {}'.format(new_document['id']))
            print('sharing into {}'.format(sfolders[parentDir]))
            share_document(new_document['id'], sharingGroupId, sfolders[parentDir])

print ("Done!")
print('Processed (folders/instances): Docs {}/{}; Images {}/{}; Files {}/{}'.format(
    len(wfolders), docCount, len(gifolders), imgCount, len(gdfolders), fileCount))
