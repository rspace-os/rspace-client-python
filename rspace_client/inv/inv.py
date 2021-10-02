from rspace_client.client_base import ClientBase


class InventoryClient(ClientBase):
    API_VERSION="v1"
    
    def _get_api_url(self):
        """
        Returns an API server URL.
        :return: string URL
        """
        
        return "{}/api/inventory/{}".format(self.rspace_url, self.API_VERSION)
    
    def create_sample(self, name: str =None, tags: str=None) -> dict :
        """
        Creates a new sample with optional attributes
        """
        data = {}
        if name is not None:
            data["name"] = name
        if tags is not None:
            data["tags"] = name
        return self.retrieve_api_results(
            self._get_api_url() + "/samples", request_type="POST", params=data
        )
        
    