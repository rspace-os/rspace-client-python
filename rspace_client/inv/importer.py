#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Apr 15 15:21:55 2022

@author: richardadams
"""
import json, requests, csv
from rspace_client.client_base import ClientBase, Pagination


class ContainerColumnMap:
    """
    Builds a column mapping for a CSV file of Container information to import,
    """

    def __init__(self, nameColumn: str):
        """

        Parameters
        ----------
        nameColumn : str
            The column name whos values will be the 'name' property of each container.

        Returns
        -------
        None.

        """
        self._mappings = {}
        self._mappings[nameColumn] = "name"

    def description_column(self, desc_column: str):
        self._mappings[desc_column] = "description"
        return self

    def tag_column(self, tag_column: str):
        self._mappings[tag_column] = "tags"
        return self

    def id_column(self, id_column: str):
        self._mappings[id_column] = "import identifier"
        return self

    def parent_id_ref_column(self, parent_id_ref_column: str):
        self._mappings[parent_id_ref_column] = "parent container import id"
        return self

    def build(self):
        return self._mappings


class ImportResult:
    """
    Wraps JSON returned in response and provides simplified access.
    """

    def __init__(self, import_result):
        self._data = import_result

    def is_ok(self):
        return self._data["status"] == "COMPLETED"

    def containers_imported(self):
        if "containerResults" in self._data:
            return self._data["containerResults"]["successCount"]
        else:
            return 0
        
    ## TODO
    def name2globalid(self):
        """
        Gets a mapping of the row in CSV file to globalId

        Returns
        -------
        rs : TYPE
            DESCRIPTION.

        """
        rs = dict()
        return rs

    def data(self):
        return self._data
    
    def __repr__(self):
        return f"{self.__class__.__name__},ok={self.is_ok()},data={self._data}"


class Importer(ClientBase):
    """
    Wrapper around RSpace Inventory API.
    Enables creation, searching, altering and deleting containers, samples,
    subsamples and templates.
    """

    API_VERSION = "v1"

    def _get_api_url(self):
        """
        Returns an API server URL.
        :return: string URL
        """

        return f"{self.rspace_url}/api/inventory/{self.API_VERSION}"

    def import_container_csv(self, container_csv_stream, column_mappings):
        """
        Imports a CSV of container data  to import.

        Parameters
        ----------
        container_csv_stream :
            An open file or stream on a CSV file

        columnMappings : dict
            A dict where keys are column names and values are RSpace properties.

        Returns
        -------
        ImportResult

        Raises
        -------
        ValueError if the column_mappings is not compatible with CSV headers

        """
        self._validate(container_csv_stream, column_mappings)
        fs = {"containerSettings": {"fieldMappings": column_mappings}}
        fsStr = json.dumps(fs)
        headers = self._get_headers()
        response = requests.post(
            self._get_api_url() + "/import/importFiles",
            files={
                "containersFile": container_csv_stream,
                "importSettings": (None, fsStr, "application/json"),
            },
            headers=headers,
        )
        return ImportResult(self._handle_response(response))

    def _validate(self, container_csv_stream, columnMappings):
        try:
            csv_reader = csv.reader(container_csv_stream)
            header = next(csv_reader)
            if header is None or len(header) == 0:
                raise ValueError("Invalid CSV file - no content?")
    
            missing_cols = [x for x in columnMappings.keys() if x not in header]
            if len(missing_cols) > 0:
                raise ValueError(f"Mapping columns {','.join(missing_cols)} don't exist in the CSV file.")
        finally:
            ## restore stream to start
            container_csv_stream.seek(0)
