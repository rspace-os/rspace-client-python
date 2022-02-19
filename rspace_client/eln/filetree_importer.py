#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov  4 20:56:36 2021

@author: richard
"""
import os
import re

from rspace_client.eln.dcs import DocumentCreationStrategy as DCS


def assert_is_readable_dir(data_dir):
    if not os.access(data_dir, os.R_OK):
        raise ValueError(f"{data_dir} is not readable")
    if not os.path.isdir(data_dir):
        raise ValueError(f"{data_dir} is not a directory")


class TreeImporter:
    def __init__(self, eln_client):
        self.cli = eln_client

    def _create_file_linking_doc(self, content, parent_folder_id, name, path2Id):
        rs_doc = self.cli.create_document(
            name,
            parent_folder_id=parent_folder_id,
            fields=[{"content": content}],
        )
        path2Id[name] = rs_doc["globalId"]

    def _generate_summary_content(self, rs_files: list) -> str:
        s = "<table><tr><th>Original file name</th><th>RSpace file</th></tr>"
        for o, r in rs_files:
            s = s + f"<tr><td>{o}</td><td><fileId={r['id']}></td></tr>"
        s = s + "</table>"
        return s

    def import_tree(
        self,
        data_dir: str,
        parent_folder_id: int = None,
        ignore_hidden_folders: bool = True,
        halt_on_error: bool = False,
        doc_creation=DCS.DOC_PER_FILE,
    ) -> dict:
        def _sanitize(path):
            return re.sub(r"/", "-", path)

        def _filter_dot_files(subdirList):
            for sf in subdirList:
                if os.path.basename(sf)[0] == ".":
                    subdirList.remove(sf)

        assert_is_readable_dir(data_dir)
        path2Id = {}

        def _is_subfolder_tree_required(sf, doc_creation):
            return (sf not in path2Id.keys()) and (
                (DCS.DOC_PER_FILE == doc_creation)
                or (DCS.DOC_PER_SUBFOLDER == doc_creation)
            )

        # maintain mapping of local directory paths to RSpace folder Ids
        result = {}
        result["status"] = "FAILED"
        result["path2Id"] = path2Id
        ## replace any forward slashes (e.g in windows path names)

        folder = self.cli.create_folder(
            _sanitize(os.path.basename(data_dir)), parent_folder_id
        )
        path2Id[data_dir] = folder["globalId"]
        all_rs_files = []

        for dirName, subdirList, fileList in os.walk(data_dir):
            if ignore_hidden_folders:
                _filter_dot_files(subdirList)
                _filter_dot_files(fileList)
            for sf in subdirList:

                if _is_subfolder_tree_required(sf, doc_creation):
                    rs_folder = self.cli.create_folder(
                        _sanitize(os.path.basename(sf)), path2Id[dirName]
                    )
                    sf_path = os.path.join(dirName, sf)
                    path2Id[sf_path] = rs_folder["globalId"]
            rs_files_in_subdir = []

            for f in fileList:
                try:
                    with open(os.path.join(dirName, f), "rb") as reader:
                        rs_file = self.cli.upload_file(reader)
                        all_rs_files.append((f, rs_file))
                        rs_files_in_subdir.append((f, rs_file))
                except IOError as x:
                    if halt_on_error:
                        self.cli.serr(
                            f"{x} raised while opening {f} - halting on error"
                        )
                        result["status"] = "HALTED_ON_ERROR"
                        return result
                    else:
                        self.cli.serr(f"{x} raised while opening {f} - continuing")
                        continue  ## next file
                doc_name = os.path.splitext(f)[0]

                ## just puts link to the document
                if DCS.DOC_PER_FILE == doc_creation:
                    parent_folder_id = path2Id[dirName]
                    content_string = f"<fileId={rs_file['id']}>"
                    self._create_file_linking_doc(
                        content_string, parent_folder_id, doc_name, path2Id
                    )
            if (DCS.DOC_PER_SUBFOLDER == doc_creation) and (
                len(rs_files_in_subdir) > 0
            ):
                parent_folder_id = path2Id[dirName]
                content = self._generate_summary_content(rs_files_in_subdir)
                summary_name = f"Summary-doc{rs_files_in_subdir[0][1]['created']}"
                self._create_file_linking_doc(
                    content, parent_folder_id, summary_name, path2Id
                )
        if (DCS.SUMMARY_DOC == doc_creation) and (len(all_rs_files) > 0):
            content = self._generate_summary_content(all_rs_files)
            summary_name = f"Summary-doc{all_rs_files[0][1]['created']}"
            self._create_file_linking_doc(content, folder["id"], summary_name, path2Id)
        result["status"] = "OK"
        return result
