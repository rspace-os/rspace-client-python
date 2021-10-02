from enum import Enum
from rspace_client.client_base import ClientBase
from typing import Optional,Sequence,Any

class ExtraFieldType(Enum):
    TEXT = "text"
    NUMBER= "number"

class TemperatureUnit(Enum):
    CELSIUS=8
    KELVIN=9
    
        
    
class StorageTemperature:
    degrees: float
    units: TemperatureUnit
    
    def __init__(self, degrees: float, units: TemperatureUnit = TemperatureUnit.CELSIUS):
        self.degrees = degrees
        self.units = units
        
    def _toDict (self) -> dict:
        return {'unitId': self.units.value,
                'numericValue': self.degrees}
        
class ExtraField:
    def __init__(self, name: str,
                 fieldType: ExtraFieldType = ExtraFieldType.TEXT, 
                 content: Any =""):
        self.data = {'name': name, 'type': fieldType.value, 'content': content}

class InventoryClient(ClientBase):
    API_VERSION="v1"
    
    def _get_api_url(self):
        """
        Returns an API server URL.
        :return: string URL
        """
        
        return "{}/api/inventory/{}".format(self.rspace_url, self.API_VERSION)
    
    def create_sample(self, name: Optional[str] = None,
                      tags: Optional[str] = None,
                      extra_fields: Optional[Sequence] = [],
                      storage_temperature_min = None,
                      storage_temperature_max = None) -> dict :
        """
        Creates a new sample with optional attributes
        """
        data = {}
        if name is not None:
            data["name"] = name
        if tags is not None:
            data["tags"] = name
        if extra_fields is not None:
            data['extraFields'] = [ ef.data for ef in extra_fields]
        if storage_temperature_min is not None:
           data["storageTempMin"]=storage_temperature_min._toDict()
        if storage_temperature_max is not None:
           data["storageTempMax"]=storage_temperature_max._toDict()
        return self.retrieve_api_results(
            self._get_api_url() + "/samples", request_type="POST", params=data
        )
        
    