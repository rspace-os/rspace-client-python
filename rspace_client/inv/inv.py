from enum import Enum
import datetime
import json
import requests
from rspace_client.client_base import ClientBase
from rspace_client.inv import quantity_unit as qu
from typing import Optional, Sequence, Union
import re


class DeletedItemFilter(Enum):
    EXCLUDE = 1
    INCLUDE = 2
    DELETED_ONLY = 3


class SampleFilter:
    def __init__(
        self, deleted_item_filter=DeletedItemFilter.EXCLUDE, owned_by: str = None
    ):
        self.data = {}
        if deleted_item_filter is not None:
            self.data["deletedItems"] = deleted_item_filter.name
        if owned_by is not None and len(owned_by) > 0:
            self.data["ownedBy"] = owned_by


class Pagination:
    def __init__(
        self,
        page_nunber: int = 0,
        page_size: int = 10,
        order_by: str = None,
        sort_order: str = "asc",
    ):
        self.data = {
            "pageNumber": page_nunber,
            "pageSize": page_size,
        }
        if order_by is not None:
            self.data["orderBy"] = f"{order_by} {sort_order}"


class ResultType(Enum):
    SAMPLE = (1,)
    SUBSAMPLE = (2,)
    TEMPLATE = (3,)
    CONTAINER = 4


class Id:
    """
    Supports integer or string representation of a globalId or
    numeric ID
    """

    Pattern = r"([A-Z]{2})?\d+"

    def __init__(self, value: Union[int, str]):

        if isinstance(value, str):
            if re.match(Id.Pattern, value) is None:
                raise ValueError("incorrect global id format")

            if len(value) > 2 and value[0:2].isalpha():
                self.prefix = value[0:2]
                self.id = int(value[2:])
            else:
                self.id = int(value)
        else:
            self.id = value

    def as_id(self) -> int:
        return self.id
        """
        Returns
        -------
        int 
            Numeric part of identifier.
        """

    def is_container(self, maybe: bool = False):
        if maybe:
            return not hasattr(self, "prefix") or self.prefix == "IC"
        else:
            return hasattr(self, "prefix") and self.prefix == "IC"


class ExtraFieldType(Enum):
    TEXT = "text"
    NUMBER = "number"


class TemperatureUnit(Enum):
    CELSIUS = 8
    KELVIN = 9


class StorageTemperature:
    def __init__(
        self, degrees: float, units: TemperatureUnit = TemperatureUnit.CELSIUS
    ):
        self.degrees = degrees
        self.units = units

    def _toDict(self) -> dict:
        return {"unitId": self.units.value, "numericValue": self.degrees}


class Quantity:
    def __init__(self, value: float, units: qu.QuantityUnit):
        self.value = value
        self.units = units

    def _toDict(self) -> dict:
        return {"numericValue": self.value, "unitId": self.units["id"]}


class ExtraField:
    """
    The data in the 'content' field must be of the type set in the 'fieldType' field
    """

    def __init__(
        self,
        name: str,
        fieldType: ExtraFieldType = ExtraFieldType.TEXT,
        content: Union[str, int, float] = "",
    ):
        self.data = {"name": name, "type": fieldType.value, "content": content}


class InventoryClient(ClientBase):
    API_VERSION = "v1"

    def _get_api_url(self):
        """
        Returns an API server URL.
        :return: string URL
        """

        return "{}/api/inventory/{}".format(self.rspace_url, self.API_VERSION)

    def create_sample(
        self,
        name: str,
        tags: Optional[str] = None,
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        storage_temperature_min: StorageTemperature = None,
        storage_temperature_max: StorageTemperature = None,
        expiry_date: datetime.datetime = None,
        subsample_count: int = None,
        total_quantity: Quantity = None,
        attachments=None,
    ) -> dict:
        """
        Creates a new sample with a mandatory name, optional attributes
        If no template id is specified, the default template will be used,
        whose quantity is measured as a volume.
        """
        data = self._set_core_properties(name, tags, description, extra_fields)
        if storage_temperature_min is not None:
            data["storageTempMin"] = storage_temperature_min._toDict()
        if storage_temperature_max is not None:
            data["storageTempMax"] = storage_temperature_max._toDict()
        if expiry_date is not None:
            data["expiryDate"] = expiry_date.isoformat()
        if subsample_count is not None:
            data["newSampleSubSamplesCount"] = subsample_count
        if total_quantity is not None:
            data["quantity"] = total_quantity._toDict()
        ## fail early
        if attachments is not None:
            if not isinstance(attachments, list):
                raise ValueError("attachments must be a list of open files")

        sample = self.retrieve_api_results(
            self._get_api_url() + "/samples", request_type="POST", params=data
        )
        if attachments is not None:
            self.serr(f"adding {len(attachments)} attachments")
            for file in attachments:
                self.uploadAttachment(sample["globalId"], file)
            ## get latest version
            sample = self.get_sample_by_id(sample["id"])
        return sample

    def get_sample_by_id(self, sample_id: Union[str, int]) -> dict:
        """
        Gets a full sample information by id or global id
        Parameters
        ----------
        id : Union[int, str]
            An integer ID e.g 1234 or a global ID e.g. SA1234
        Returns
        -------
        dict
            A full description of one sample
        """
        s_id = Id(sample_id)
        return self.retrieve_api_results(
            self._get_api_url() + f"/samples/{s_id.as_id()}", request_type="GET"
        )

    def list_samples(
        self, pagination: Pagination = Pagination(), sample_filter: SampleFilter = None
    ):
        """
        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        Returns
        -------
        Paginated Search result. Use 'next' and 'prev' links to navigate
        """

        if sample_filter is not None:
            pagination.data.update(sample_filter.data)
        self.serr(f"pg is {pagination.data}")
        return self.retrieve_api_results(
            self._get_api_url() + "/samples", request_type="GET", params=pagination.data
        )

    def stream_samples(
        self, pagination: Pagination = Pagination(), sample_filter: SampleFilter = None
    ):
        """
        Streams all samples. Pagination argument sets batch size and ordering.
        Parameters
        ----------
        pagination : Pagination, optional. The default is Pagination().

        Yields
        ------
        item : One Sample at a time
        """
        urlStr = self._get_api_url() + "/samples"
        if sample_filter is not None:
            pagination.data.update(sample_filter.data)
        next_link = (
            requests.Request(method="GET", url=urlStr, params=pagination.data)
            .prepare()
            .url
        )
        while True:
            if next_link is not None:
                samples = self.retrieve_api_results(next_link)
                for item in samples["samples"]:
                    yield item
                if self.link_exists(samples, "next"):
                    next_link = self.get_link(samples, "next")
                else:
                    break

    def rename_sample(self, sample_id: Union[int, str], new_name: str) -> dict:
        """
        Parameters
        ----------
            id : Id Id of sample to rename
            new_name : str The new name.
        Returns
        -------
            dict : The updated sample
        """
        s_id = Id(sample_id)
        return self.retrieve_api_results(
            self._get_api_url() + f"/samples/{s_id.as_id()}",
            request_type="PUT",
            body={"name": new_name},
        )

    def delete_sample(self, sample_id: Union[int, str]):
        """
        Parameters
        ----------
        sample_id : Union[int, str]
            A integer id, or a string id or global ID.

        Returns
        -------
        None.

        """
        id_to_delete = Id(sample_id)
        self.doDelete("samples", id_to_delete.as_id())

    def add_extra_fields(self, sample_id: Union[int, str], *ExtraField):
        toPut = []
        for ef in ExtraField:
            ef.data["newFieldRequest"] = True
            toPut.append(ef.data)
        s_id = Id(sample_id)
        return self.retrieve_api_results(
            self._get_api_url() + f"/samples/{s_id.as_id()}",
            request_type="PUT",
            params={"extraFields": toPut},
        )

    def uploadAttachment(self, globalid: str, file) -> dict:
        """
        Uploads an attachment file to an sample, subsample or container.
        Parameters
        ----------
        - globalid : str
            Global id of  sample (SA...), Subsample (SS...) or Container (IC...)
        - file : an open file
            An open file stream.

        Returns
        -------
        Dict of the created InventoryFile
        """

        fs = {"parentGlobalId": globalid}
        fsStr = json.dumps(fs)
        headers = self._get_headers()
        response = requests.post(
            self._get_api_url() + "/files",
            files={"file": file, "fileSettings": (None, fsStr, "application/json")},
            headers=headers,
        )
        return self._handle_response(response)

    def search(
        self, query: str, pagination=Pagination(), result_type: ResultType = None
    ):
        params = {"query": query}
        params.update(pagination.data)
        if result_type is not None:
            params["resultType"] = result_type.name
        return self.retrieve_api_results(self._get_api_url() + "/search", params=params)

    def _set_core_properties(
        self,
        name: str,
        tags: Optional[str] = None,
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
    ):
        data = {}
        data["name"] = name
        if tags is not None:
            data["tags"] = tags
        if description is not None:
            data["description"] = description
        if extra_fields is not None:
            data["extraFields"] = [ef.data for ef in extra_fields]
        return data

    def create_list_container(
        self,
        name: str,
        tags: Optional[str] = None,
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_subsamples: bool = True,
    ):

        data = self._set_core_properties(name, tags, description, extra_fields)
        data["cType"] = "LIST"
        data["canStoreContainers"] = can_store_containers
        data["canStoreSubsamples"] = can_store_subsamples

        container = self.retrieve_api_results(
            self._get_api_url() + "/containers", request_type="POST", params=data
        )
        return container

    def create_grid_container(
        self,
        name: str,
        row_count: int,
        column_count: int,
        tags: Optional[str] = None,
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_subsamples: bool = True,
    ) -> dict:

        data = self._set_core_properties(name, tags, description, extra_fields)
        data["cType"] = "GRID"
        data["canStoreContainers"] = can_store_containers
        data["canStoreSubsamples"] = can_store_subsamples
        data["gridLayout"]["columnsNumber"] = column_count
        data["gridLayout"]["rowssNumber"] = row_count

        container = self.retrieve_api_results(
            self._get_api_url() + "/containers", request_type="POST", params=data
        )
        return container

    def add_containers_to_list_container(
        self,  target_container_id: Union[str, int], *item_ids: Union[str, int],
    ) -> list:
        """
        Adds 1 or more containers to a list container

        Parameters
        ----------
        target_container_id : Union[str, int]
            The id of a List container
            
        *item_ids : Union[str, int]
            One or more ids of containers  to move into the target container

        Raises
        ------
        ValueError
            If any item_id is not that of a container

        Returns
        -------
        list
            A List of moved containers, showing their new location

        """
        id_target = Id(target_container_id)
        if not id_target.is_container(maybe=True):
            raise ValueError("Target must be a container")
        data = {}
        updated_containers = []
        for item_id in item_ids:
            id_ob = Id(item_id)
            if not id_ob.is_container(maybe=True):
                raise ValueError("Item to move must be a container")
            data["parentContainers"] = [{"id": id_target.as_id()}]
            container = self.retrieve_api_results(
            self._get_api_url() + f"/containers/{id_ob.as_id()}",
            request_type="PUT",
            params=data)
            updated_containers.append(container)

        return container
