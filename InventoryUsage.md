# RSpace Inventory API usage examples

This document provides some code snippets to help getting started with
the RSpace Inventory API Client. 

For authoratative examples see the test cases in `rspace_client/tests/invapi_test.py`

## Get the client

    ```python
    API_KEY="your api key"
    RSPACE_URL="https://your-rspace.com"
    from rspace_client.inv.inv import InventoryClient 
    cli = InventoryClient(RSPACE_URL, API_KEY)
    ```

## Creating content

### Create a sample on the Workbench

```python
  sample = cli.create_sample("sample_name", description="My first sample", subsample_count=10)
  print(sample['globalId'])
```
    
### Create a List Container

```python
  list_container = cli.create_list_container("shelf", can_store_samples=False,
        can_store_containerS=True)
  print(list_container['globalId'])
```
    
### Create a Grid Container

```python
  ## 8 rows and 12 columns
  grid_container = cli.create_grid_container("Enzyme box", 8, 12, description="restriction enzymes")
  print(grid_container['globalId'])
```

### Add a file attachment to a sample, subsample or container

```python
  data_file="path/to/attachment.txt"
  with open(data_file, "rb") as f:
      updated_sample =  cli.upload_attachment(sample["globalId"], f)
```
     
