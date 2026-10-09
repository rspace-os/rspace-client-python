# Changelog

All notable changes to this project will be documented in this file

## Proposed breaking changes
 - replace naming of classes and methods using 'Workbench' to 'Bench'
 - replace create_sample, create_container long argument lists with new XXXPost objects

## 2.8.0 (unreleased)

- New `rspace_client.fs`: RSpace as an [fsspec](https://filesystem-spec.readthedocs.io)
  filesystem. `RSpaceFilesystem` mounts `gallery/`, `inventory/` and `workspace/` (Gallery
  folders and files; Inventory benches, containers, samples, subsamples, templates and
  instruments as folders of their records and attachments, attachment fields as one-file
  folders; ELN folders, notebooks and documents, a document as a folder of its text fields
  and a field as a folder of its linked files). Paths are record names; duplicate names
  and names that read as addresses carry their global ID (`data [GL112].csv`);
  `path_style="labelled"` / `"id"` for stable paths. Read-only by default (`writable=True`,
  `allow_delete=True`). Uploads into Inventory and the Workspace go through the Gallery and
  link; `cp_file` from any Gallery-backed file links instead of copying bytes. Transactions
  defer uploads. `rspace://host` URLs via `fsspec.open`, `fsspec.filesystem("rspace")` and
  `UPath` (registered as an `fsspec.specs` entry point), key from `RSPACE_API_KEY` only. `glob("<dir>/*<text>*")` answers Galaxy's search
  including bracketed names. New dependency `fsspec`.
- Deprecated `rspace_client.eln.fs.GalleryFilesystem` and
  `rspace_client.inv.attachment_fs.InventoryAttachmentFilesystem` (PyFilesystem2, unmaintained
  upstream). Unchanged in behaviour, now emit a `DeprecationWarning`; removal together with
  the `fs` dependency in 3.0, after Galaxy's shipped plugin has moved to `rspace_client.fs`.
- Fix: uploads accept a file object that forwards `read` through `__getattr__`. requests 2.34
  refuses such objects on Python 3.12+, which broke exports from Galaxy 26.1 (it pins requests
  2.34.2) to RSpace through Galaxy's shipped `rspace` file source.
- `rspace_client/tests/galaxy_plugin_contract_test.py` pins what Galaxy's shipped plugin relies
  on; a failure there is a release blocker.
- `tools/galaxy/rspace_fsspec_source.py`: the reference Galaxy file source for the new
  filesystem, to be proposed upstream.
- Security: the client never follows an HTTP redirect, since `requests` would carry the
  `apiKey` header to the new host.
- Client-level changes: `_links` URLs are rebased onto the configured host so paging and
  download links work behind a proxy; `doDelete` tolerates a leading slash (fixes
  `delete_document`); `upload_file` and `upload_attachment_by_global_id` take an optional
  `filename=`; `list_folder_tree` takes `page_size=`; new `get_workbench_by_id`; Inventory
  CSV import uses the shared session.
- Removed a stray debug print from `InventoryClient.upload_attachment_by_global_id`.
- Added `rspace_client/tests/mock_rspace`, an offline mock of the ELN and Inventory REST
  endpoints the PyFilesystem classes use, shared by the unit suite. Not installed.

## Unreleased

- Gallery upload routing and section-mismatch handling (PR #56): clearer
  `GallerySectionMismatch` exception, optional `on_mismatch="reroute"`
  policy to auto-reroute uploads into the server-chosen section, `upload()` now
  returns a `Placement` describing where the file landed (including a
  `rerouted` flag), Galaxy compatibility fixes for callers that return `None`,
  and a corrected media-type classifier. See `docs/usage-guide.md` and
  `examples` for usage.

- Added support for importing Inventory CSV files (issue #32 / PR #55): `parse_csv_import_file`,
  `import_csv_files`, `import_samples_csv`, `import_containers_csv` and
  `import_subsamples_csv`, plus a new `ImportRecordType` enum. Supports samples,
  subsamples and LIST containers; Instruments and Instrument Templates cannot be
  imported from CSV. See `examples/import_inventory_csv.py`.

## 2.7.4 2026-08-26

- reliability improvements, more robust error handling, increased test coverage

## 2.7.2 2026-07-13

- Added support for the Inventory "Link" extra-field type (server PR #803 /
  RSDEV-1131): a new `ExtraFieldType.LINK`, a `RelationType` enum of the 40
  DataCite/PIDINST relationship values, and an `InventoryLink` value object.
  `ExtraField` now accepts Link fields, with an `ExtraField.link(...)`
  convenience constructor. `TemplateBuilder`/`InstrumentTemplateBuilder` gain a
  `link()` field with an optional relationship-type whitelist, and the client
  gains `get_link_target_summary()` and `get_referencing_items()`. See
  `examples/inventory_link_field.py`. Requires an RSpace server that supports
  Link fields; integration tests are opt-in via `RSPACE_SUPPORTS_LINK_FIELDS`.

## 2.7.0  2026-07-03

- Added support for Inventory Instruments and Instrument Templates (beta RSpace 2.24
  feature): `create_instrument`, `get_instrument_by_id`, `list_instruments`,
  `delete_instrument`, `restore_instrument`, `transfer_instrument_owner`,
  `update_instrument_to_latest_template_version`, `get_instrument_revisions`,
  `get_instrument_revision`, `create_instrument_template`,
  `get_instrument_template_by_id`, `delete_instrument_template`,
  `list_instrument_templates`, `restore_instrument_template`,
  `transfer_instrument_template_owner`, `set_instrument_template_icon`,
  `get_instrument_template_icon`, `get_instrument_template_version`,
  `update_instrument_template_instruments`, and a new `InstrumentTemplateBuilder`.
  `rename`, `set_image`, `duplicate` and `add_extra_fields` now also work on
  Instruments and Instrument Templates.

## 2.6.0  2025-02-25

- implementing pyfilesystem API methods for browsing RSpace Gallery and RSpace Inventory 

## 2.5.0  2022-06-12

- Deprecated method `download_export()`. Use `export_and_download()` instead.
- ELN: Add optional `progress_log` argument to `export_and_download()`

## 2.4.1  2022-03-19

- ImageContainerPost can take a file object as well as a string path

## 2.4.0  2022-02-18

### Breaking change

- renamed inv.uploadAttachment method to 'upload_attachment'

### Added

 - set_image sets a preview image for a sample,container or subsample
 - add_locations_to_image_container adds new marked locations to an image
 - delete_locations_from_image_container removes marked locations from an image


## 2.3.3  2022-02-11

- Removed print statements from builk_create_sample

## 2.3.2 2022-02-09

### Fixed

- #31 Extra fields ignored in bulk/ sample posts

## 2.3.1 2022-02-09

### Added

- static method Id.is_valid_id() to check if an object can be parsed as an id
- bulk 'createContainer' methods 
- methods 'error_results' and 'success_results' on BulkOperationResult
- methods in Id: is_bench, is_sample
- Classes to  define new Containers: GridContainerPost, ListContainerPost
- Classes to define where new items are placed: ListContainerTargetLocation,
    GridContainerTargetLocation, BenchTargetLocation, TopLevelTargetLocation
- create ImageContainerPost, createInImageContainer,add_items_to_image_container
- create ImageContainer class to wrap dicts of ImageContainers from the server.

### Changed
- BREAKING: altered create_grid_container and create_list_container location arguments

## 2.3.0 2022-02-01
- incorrectly built. Obsolete 

## 2.2.2 2022-02-01

### Added

- Example script 'freezer.py' to set up a -80 freezer for testing
- 'bulk_create_sample' method to create many samples at once.
 
### Fixed
- 'canStoreSamples' flag now set correctly when creating a  grid container

## 2.2.1 2022-01-28

### Fixed

- case-insensitive parsing of sample field types
- enable definition of sample radio field with no selected option
- handle variability in choice/radio field definition

## 2.2.0 2022-01-27

### Added
- Upload directories of files into ELN via import_tree() - #17
- Added str/repr implementations for inventory value objects - #23
- Added eq methods for inventory  value objects - #26

## 2.1.0 2022-01-22

Requires RSpace 1.73 or later

### Added 

- Support for sample templates: create, get/set icon, delete/restore
- Dynamically generated classes from template definitions
- Transfer ownership of samples and templates
- Create samples from a template, and set field content
- export_selection to export specific items
- optionally include revision history in exports

### Changed

- create_sample now accepts sample template ID and an optional list of Fields with values.

### Deprecated

### Removed

### Fixed

### Security
