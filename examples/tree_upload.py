import os
import rspace_client
import argparse;
import xml.etree.ElementTree as ET
import tempfile
import zipfile
import time
import re

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

This script will log progress in a log file. Please do not delete this file while the script is running.
'''
# initial timestamp string to use as default log folder
default_log_file  = "ecat_to_rspace_" + time.asctime().replace(" ", "_") +".log"
LOG_FILE_HEADER="EcatToRSpaceFolderLog"
parser = argparse.ArgumentParser()
parser.add_argument("--logfile", "--l", help="abs or relative path to a log file, will be created if not exists",
                     type=str, default=default_log_file)
parser.add_argument("--resume", "--r", help="Runs script in 'resume' mode, continuing a previous import process",
                     action='store_true', default=False)
parser.add_argument("--simulate", "-s", help="Use this flag to run in simulation mode",
                     action='store_true')
parser.add_argument("server", help="RSpace server URL (for example, https://community.researchspace.com)", type=str)
parser.add_argument("apiKey", help="RSpace API key can be found on 'My Profile'", type=str)
parser.add_argument("srcDir", help="Root of uplod, for example 'eCAT''", type=str)
parser.add_argument("workspaceFolder", help="Folder ID in Workspace (number only)", type=int)
parser.add_argument("sharedFolder", help="Folder ID in Shared area (number only)", type=int)
parser.add_argument("galleryDocFolder", help="Folder ID in Gallery Docs area (number only)", type=int)
parser.add_argument("galleryImageFolder", help="Folder ID in Gallery Images area (number only)", type=int)

ResumeMode = False
args = parser.parse_args()
ResumeMode = args.resume
api_simulate = args.simulate
log_file_path = args.logfile

def log_api_success(workspace_or_shared,  rspaceId, localPath="none"):
    """
        Logs successful completion of an API call to RSpace.
        :param workspace_or_shared: A code for the type of API call: SD (document creation),
          GFD (Gallery doc folder), GFI (Gallery image folder), FLW (Workspace folder), FLS (Shared folder),
          GL (Gallery item) or SDS (document shared)
        :param rspaceId: The ID of the RSpace instance
        :param localPath: The full path to a local resource that was uploaed to RSpace. If the API 
         call is unrelated to a local resource, this argument can be left blank and "none" will be set in logs
    """
    if not re.match("^(SD)|(GFD)|(GFI)|(FLW)|(FLS)|(GL)|(SDS)$", workspace_or_shared): 
        raise ValueError("workspace or shared must match (SD)|(GF)|(FLW)|(FLS)|(GL)|(SDS)")
   
    with open(log_file_path, 'a+') as folder_log:
        folder_log.write("{ftype}|{rspace_id}|{localPath}\n"
                         .format(ftype=workspace_or_shared,rspace_id=rspaceId,localPath=localPath))

## writes header used to identify active log file
## should be called only for a clean run, starting a new log file
def initialiseLogFile():
    if  ResumeMode:
        raise ValueError("Resume mode must not initialise new log file")
    with open(log_file_path, 'a+') as folder_log:
        folder_log.write("{}\n".format(LOG_FILE_HEADER))

## parses log file into array of triples (type, RSpaceId, localPath | none)
## validates log file existence etc.\
## TODO use returned data structure to initialise the data structures
## used by import script. e.g. 
def parse_log_file():
    if not ResumeMode:
        raise ValueError("This method should only be called in 'resume' mode")
    if not os.path.exists(log_file_path):
        raise ValueError("Log path {} does not exist".format("log_file_path"))
    logFileData = {}
    with open(log_file_path, 'r') as folder_log:
        lines =  folder_log.readlines()
        ## quick  check on contents, is this a likely log file??
        if len(lines) == 0:
            raise ValueError("Log file {} is empty.".format("log_file_path"))
        if re.search( LOG_FILE_HEADER, lines[0]) == None:
            raise ValueError("Log file {} does not have correct header, are you sure it's a log file?".format("log_file_path"))
        if len(lines) < 3:
            raise ValueError("There is no content in this log file, there is nothing to resume from,this will upload all content as new.")
       
        logFileData['lines'] =[]
        for line in lines:
            logFileData['lines'].append(line.rstrip("\r\n").split("|"))
    return logFileData
        
# def setUpProgressLogFolder():
#     if not os.path.exists(log_folder_path):
#         print ("Creating log folder {}".format(log_folder_path))
#         os.makedirs(log_folder_path)
        

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
    """
     Makes API call. Is running in 'simulate' mode, returns a simulated response
      with auto-incrementing IDs for creation methods
    """
    returnval = ''
    start = time.time()
    if api_simulate:
        if callname != 'shareDocuments':
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

def create_dir_and_ancestors(fdict, directory, galleryType):
    if directory in fdict:  # recursion termination
        return
    parent = os.path.dirname(directory)
    create_dir_and_ancestors(fdict, parent, galleryType) # recurse, on return ancestor will exist
    # create folder for dir in parent and store id in dictionary
    print ('creating folder for {child} in {par} ({parentid})'.format(
        child = directory, par = parent, parentid = fdict[parent]))
    response = api_call('create_folder', lambda: client.create_folder(os.path.basename(directory), parent_folder_id=fdict[parent]))
    fdict[directory] = response['id']
    log_api_success(galleryType,  response['id'], directory )

def share_document(docId, groupId, folderId, origFilePath="None"):
    if not origFilePath in shared_sdocs:
        print("Sharing document {} with group {} into folder {}".format(docId, groupId, folderId))
        shared = api_call('shareDocuments', lambda: client.shareDocuments([docId], groupId, sharedFolderId=folderId))
        log_api_success('SDS',  docId, origFilePath )
        shared_sdocs[origFilePath] = docId
    
def _init_wfolders():
    rc = {args.srcDir : args.workspaceFolder}
    _populateFromLog("FLW", rc)
    return rc

def _init_sfolders():
    rc = {args.srcDir : args.sharedFolder}
    _populateFromLog("FLS", rc) 
    return rc

def _init_gdfolders():
    rc = {args.srcDir : args.galleryDocFolder}
    _populateFromLog("GFD", rc) 
    return rc

def _init_gifolders():
    rc = {args.srcDir : args.galleryImageFolder}
    _populateFromLog("GFI", rc) 
    return rc

def _init_sdocs():
    rc = {}
    _populateFromLog("SD", rc) 
    return rc

def _init_shared_sdocs():
    rc = {}
    _populateFromLog("SDS", rc) 
    return rc

def _init_glfiles():
    rc = {}
    _populateFromLog("GL", rc) 
    return rc

def _populateFromLog(itemType, folderDict):
    if ResumeMode:
        for line in  toResume:
            if itemType == line[0]:
                folderDict[line[2]] = line[1]
    
                

######## Start of main script #####
toResume = {"lines":[]}
sharingGroupId = 0
if ResumeMode:
    toResume  = parse_log_file()['lines']
else:
    initialiseLogFile()

client = rspace_client.Client(args.server, args.apiKey)


if ResumeMode == True:
    sharingGroupId = int(toResume[1][1])
    print ("Resuming with group {}".format(sharingGroupId))
elif not api_simulate:    
    groups = client.get_groups()
    if len(groups) == 0:
        raise Exception("Cannot proceed as you are not a member of a group")
    sharingGroupId = groups[0]['id']
    print("Sharing into the first group found - '{}' ({}) - shareFolder = {}".format(groups[0]['name'],
                                                                                     groups[0]['id'], groups[0]['sharedFolderId']))
    with open(log_file_path, 'a+') as folder_log:
        folder_log.write("{ftype}|{rspace_id}|{localPath}\n"
                         .format(ftype="GP",rspace_id=sharingGroupId,localPath="none"))
        
wfolders = _init_wfolders()# workspace folders dictionary, keyed on source path
sfolders = _init_sfolders()# shared folders dictionary, keyed on source path
gdfolders = _init_gdfolders() # gallery document folders dictionary, keyed on source path
gifolders = _init_gifolders() # gallery image folders dictionary, keyed on source path
sdocs = _init_sdocs() # documents already converted
shared_sdocs = _init_shared_sdocs()
glfiles= _init_glfiles()

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
                log_api_success('FLW',  response['id'],dirName)
                
            if not dirName in sfolders: #folder does not exist yet
                response = api_call('create_folder', lambda: client.create_folder(dirname, parent_folder_id=sfolders[parname]))
                sfolders[dirName] = response['id']
                print('Created shared folder {dir} ({dirnum}) in {par} ({parnum})'.format(
                    dir = dirname, dirnum = sfolders[dirName], par = os.path.basename(parname), parnum = sfolders[parname]))
                log_api_success('FLS',  response['id'],dirName)
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
                            # if not already created
                            docId = -1
                            if not docxname in sdocs:
                                new_document = api_call('import_word', lambda: client.import_word(f, wfolders[dirName]))
                                docCount += 1
                                print('Document "{}" was imported to  folder {} as {} ({})'
                                  .format(f.name,wfolders[dirName], new_document['name'], new_document['globalId']))
                                log_api_success('SD',  new_document['id'],docxname)
                                sdocs[docxname] = new_document['id']
                                docId = new_document['id']
                            else:
                                docId = sdocs[docxname]   ## resume mode
                                
                            print('sharing into {}'.format(sfolders[dirName]))
                            share_document(docId, sharingGroupId, sfolders[dirName], docxname)
                                
                else: # some other kind of file, to go in document gallery
                    # create gdfolders[dirName] and parents if needed
                    print('creating Gallery Docs folder and parents for %s' % dirName)
                    create_dir_and_ancestors(gdfolders, dirName,'GFD')
                    # upload to gdfolders[dirName]
                    galleryItemPath = os.path.join(dirName,filename)
                    
                    print('uploading %s to Gallery Docs' % galleryItemPath)
                    with open(galleryItemPath, 'rb') as f:
                            new_file_id=-1
                            if not galleryItemPath in glfiles:
                                new_file = api_call('upload_file', lambda: client.upload_file(f, caption=filename, folder_id=gdfolders[dirName]))
                                new_file_id = new_file['id']
                                print('File "{}" was uploaded to Gallery as {} ({})'.format(f.name, new_file['name'], new_file_id))
                                log_api_success('GL',  new_file_id,galleryItemPath )
                                glfiles[galleryItemPath] = new_file_id
                                fileCount += 1
                            else:
                                new_file_id = glfiles[galleryItemPath]
                                print ("File  {} was already uploaded".format(galleryItemPath))
                            # create a basic document with the same name and a link to the uploaded gallery file.
                            if not new_file_id in sdocs:
                                print('creating basic document, should be in {}'.format(wfolders[dirName]))
                                new_document = api_call('create_document', lambda: client.create_document(
                                    name=filename, parent_folder_id=wfolders[dirName], fields=[
                                        {'content': 'Link to the gallery file: <fileId={}>'.format(new_file_id)}
                                        ]))
                                sdocs[new_file_id] = new_document['id']
                                ## we log the new file ID and the linked doc. We use this so as to know if 
                                ## this doc was previously created, if resuming
                                log_api_success('SD',  new_document['id'], new_file_id)
                                print('New document was successfully created with global ID {}'.format(new_document['id']))
                  
                                print('sharing into {}'.format(sfolders[dirName]))
                                share_document(new_document['id'], sharingGroupId, sfolders[dirName], new_file_id)
                            else:
                                print ("Document linking to {} was already created".format(new_file['id']))
                                
                    
        else: # images folder
            ## TODO complete resume code
            parentDir = os.path.dirname(dirName)
            # create gifolders[parentDir] and parents as needed
            print ('creating Gallery Images folder and parents for %s' % parentDir)
            create_dir_and_ancestors(gifolders, parentDir,'GFI')
            # TODO this needs refactoring to create document with a link to the folder instead of all the images
            for filename in fileList:
                # upload filename to gifolders[parentDir]
                print('uploading %s to GalleryImages' % filename)
                galleryItemPath = os.path.join(dirName, filename)
                if not galleryItemPath in glfiles:
                    with open(galleryItemPath, 'rb') as f:
                        new_file = api_call('upload_file', lambda: client.upload_file(f, folder_id=gifolders[parentDir]))
                        print('Image "{}" was uploaded as {} ({})'.format(f.name, new_file['name'], new_file['id']))
                        imgCount += 1
                        log_api_success('GL',  new_file['id'], galleryItemPath)
                        glfiles[galleryItemPath] = new_file['id']
                else:
                    print ("Image '{}' was already uploaded".format(galleryItemPath))
            # create imageDoc = "eCAT gallery images" basic document in wfolders[parentDir]
           
            print('creating basic document for link to gallery images folder, should be in {}'.format(wfolders[parentDir]))
            docname = 'eCAT gallery images for documents in ' + os.path.basename(parentDir)
            folder_link = 'Gallery Images in Documents in this folder:\n<docId={}>\n'.format(gifolders[parentDir])
            new_document_id = -1
            if not dirName in sdocs:
                new_document = api_call('create_document', lambda: client.create_document(
                    name=docname, parent_folder_id=wfolders[parentDir], fields=[{'content': folder_link}]
                ))
                new_document_id =  new_document['id']
                log_api_success('SD',new_document_id , dirName)
                sdocs[dirName] =  new_document_id;
                print('New document was successfully created with global ID {}'.format(new_document_id))
            else:
                new_document_id = sdocs[dirName]
                print ("Folder link doc was already created")
            print('sharing into {}'.format(sfolders[parentDir]))
            share_document(new_document_id, sharingGroupId, sfolders[parentDir], dirName)

print ("Done!")
print('Processed (folders/instances): Docs {}/{}; Images {}/{}; Files {}/{}'.format(
    len(wfolders), docCount, len(gifolders), imgCount, len(gdfolders), fileCount))
