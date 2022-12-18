#!/bin/env python3

import cmd
import boto3
import os
import requests
import shutil
import mimetypes

from botocore import UNSIGNED
from botocore.client import Config

def red(skk): return f"\033[91m {skk}\033[00m"
# def prCyan(skk): print("\033[96m {}\033[00m" .format(skk))
# def prGreen(skk): print("\033[92m {}\033[00m" .format(skk))
# def prLightGray(skk): print("\033[97m {}\033[00m" .format(skk))
# def prYellow(skk): print("\033[93m {}\033[00m" .format(skk))
# def prLightPurple(skk): print("\033[94m {}\033[00m" .format(skk))
# def prBlack(skk): print("\033[98m {}\033[00m" .format(skk))
# def prPurple(skk): print("\033[95m {}\033[00m" .format(skk))

def represent_size(size):
    if size < 1024:
        return f"{size} bytes"
    elif size < 1024 ** 2:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 ** 3:
        return f"{size / (1024 ** 2):.2f} MB"
    else:
        return f"{size / (1024 ** 3):.2f} GB"


def get_content_type(filename):
    # Determine the content type of the file
    content_type, encoding = mimetypes.guess_type(filename)

    # If the content type couldn't be determined, default to 'application/octet-stream'
    if content_type is None:
        content_type = 'application/octet-stream'

    return content_type

wd = boto3.client('workdocs', config=Config(signature_version=UNSIGNED))

AUTH_TOKEN = os.environ['AUTH_TOKEN']

rootFolders = wd.describe_root_folders(
             AuthenticationToken=AUTH_TOKEN
        )

class WorkdocsTool(cmd.Cmd):
    """An interactive command line tool"""
    prompt = 'workdocs> '
    resp = None
    rootFolderId = rootFolders['Folders'][0]['Id']
    currentFolderId = rootFolders['Folders'][0]['Id']
    parentFolderId = rootFolders['Folders'][0]['Id']

    def do_cd(self, name):
        """
        Change folder

        Usage: cd folder
        """
        if name == '..':
            self.currentFolderId = self.parentFolderId
            self.parentFolderId = wd.get_folder(AuthenticationToken = AUTH_TOKEN, FolderId=self.currentFolderId)['Metadata']['ParentFolderId']
            self.resp = None
            return 
        try:
            id = [f['Id'] for f in self.resp['Folders'] if f['Name'] == name][0]
            self.parentFolderId = self.currentFolderId
            self.currentFolderId = id
            self.resp = None
            self.prompt = f"{self.prompt[:-2]}/{name}> "
        except Exception as e:
            print("Error")


    def do_ls(self, arg):
        """
        List the content of the current folder

        Usage: ls
        """

        if self.resp is None:
            resp = wd.describe_folder_contents(
                AuthenticationToken=AUTH_TOKEN,
                FolderId=self.currentFolderId,
                Sort='NAME',
                Order='ASCENDING',
                Type='ALL'
            )
            self.resp = resp

        folders = [red(f['Name']) for f in self.resp['Folders']]
        #print('\n'.join(folders))
        self.columnize(folders)
        #print(resp['Documents'][0])
        docs = [f['LatestVersionMetadata']['Name'] for f in self.resp['Documents']]
        #print('\n'.join(docs))
        self.columnize(docs,80)
    
    def do_ll(self, arg):
        """
        List the content of the current folder

        Usage: ls
        """
        if self.resp is None:
            resp = wd.describe_folder_contents(
                AuthenticationToken=AUTH_TOKEN,
                FolderId=self.currentFolderId,
                Sort='NAME',
                Order='ASCENDING',
                Type='ALL'
            )
            self.resp = resp

        folders = [f"{red(f['Name'])}" for f in self.resp['Folders']]

        print('\n'.join(folders))
        #print(resp['Documents'][0])
        docs = [f"{f['LatestVersionMetadata']['Name']}\t{represent_size(f['LatestVersionMetadata']['Size'])}\t{f['LatestVersionMetadata']['ModifiedTimestamp'].isoformat()}" for f in self.resp['Documents']]
        print('\n'.join(docs))
        

    def do_get(self, args):
        """
        Get the Workdocs file to the local system

        Usage: get FROM TO
        """
        args = args.split(" ")
        from_file = to_file = args[0]

        if len(args) > 1:
            to_file = args[1]
        di = [d for d in self.resp['Documents'] if d['LatestVersionMetadata']['Name'] == from_file][0]

        v = wd.get_document_version(AuthenticationToken = AUTH_TOKEN,
                VersionId=di['LatestVersionMetadata']['Id'], 
                DocumentId=di['Id'], Fields="SOURCE")
        url = v['Metadata']['Source']['ORIGINAL'] 

        with requests.get(url, stream=True) as r:
            with open(to_file, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
            
    def do_put(self, args):
        """
        Copies a file from local folder to workdocs

        Usage put FROM TO
        """

        args = args.split(" ")
        to_path = from_path = args[0]
        if len(args) > 1:
            to_path = args[1]
        size = os.path.getsize(from_path)
        ctime = os.path.getctime(from_path)
        mtime = os.path.getmtime(from_path)

        if to_path is None:
            to_path = from_path
        resp = wd.initiate_document_version_upload(
            AuthenticationToken=AUTH_TOKEN,
            Name=to_path,
            ContentCreatedTimestamp=ctime,
            ContentModifiedTimestamp=mtime,
            ContentType=get_content_type(from_path),
            DocumentSizeInBytes=size,
            ParentFolderId=self.currentFolderId
        )

        _id = resp['Metadata']['Id']
        version_id = resp['Metadata']['LatestVersionMetadata']['Id']
        url = resp['UploadMetadata']['UploadUrl']
        with open(from_path, 'rb') as file:
            # Set the content length to the size of the file
            headers = { k : v for k, v in resp['UploadMetadata']['SignedHeaders'].items() } 

            # Send a PUT request to the S3 signed URL
            response = requests.put(url, data=file, headers=headers)

            # Check the status code of the response
            if response.status_code == 200:
                print('File successfully uploaded')
                wd.update_document_version(
                    AuthenticationToken=AUTH_TOKEN,
                    DocumentId=_id,
                    VersionId=version_id,
                    VersionStatus='ACTIVE'
                )
            else:
                print('Error uploading file')

    def do_exit(self, arg):
        """Exit the tool"""
        return True

if __name__ == '__main__':
    WorkdocsTool().cmdloop()

# https://auth.amazonworkdocs.com/oauth?app_id=dbee8d42-aab6-49b5-ad3f-4f4452421f40&auth_type=ImplicitGrant&redirect_uri=http://angelino.nu/done



