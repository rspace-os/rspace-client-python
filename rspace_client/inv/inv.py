from enum import Enum
from rspace_client.client_base import ClientBase
from rspace_client.inv import quantity_unit as qu
from typing import Optional, Sequence, Any
import datetime


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
    def __init__(self, value:float, units:qu.QuantityUnit):
        self.value = value
        self.units=units
    def _toDict(self) -> dict:
        return {'numericValue': self.value,
                'unitId':self.units['id']}
    
class ExtraField:
    def __init__(
        self,
        name: str,
        fieldType: ExtraFieldType = ExtraFieldType.TEXT,
        content: Any = "",
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
        extra_fields: Optional[Sequence] = [],
        storage_temperature_min: StorageTemperature = None,
        storage_temperature_max: StorageTemperature = None,
        expiry_date: datetime.datetime = None,
        subsample_count: int = None,
        total_quantity: Quantity = None
    ) -> dict:
        """
        Creates a new sample with a mandatory name optional attributes
        """
        data = {}
        data['name'] = name
        if tags is not None:
            data["tags"] = name
        if extra_fields is not None:
            data["extraFields"] = [ef.data for ef in extra_fields]
        if storage_temperature_min is not None:
            data["storageTempMin"] = storage_temperature_min._toDict()
        if storage_temperature_max is not None:
            data["storageTempMax"] = storage_temperature_max._toDict()
        if expiry_date is not None:
            data["expiryDate"] = expiry_date.isoformat()
        if subsample_count is not None:
            data["newSampleSubSamplesCount"]=subsample_count
        if total_quantity is not None:
            data['quantity']=total_quantity._toDict()
            
            
        return self.retrieve_api_results(
            self._get_api_url() + "/samples", request_type="POST", params=data
        )
