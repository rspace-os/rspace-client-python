# Changelog

All notable changes to this project will be documented in this file

## Proposed breaking changes
 - replace naming of classes and methods using 'Workbench' to 'Bench'
 - replace create_sample, create_container long argument lists with new XXXPost objects

## 2.8.0 (unreleased)

Verified against RSpace 2.27. The minimum server version is still to be established: the new
code calls `/workbenches`, the Inventory files endpoints and `/folders/tree`.

- New `rspace_client.fs` package: a unified PyFilesystem for RSpace (GitHub #58).
  `RSpaceFilesystem` mounts `/gallery`, `/inventory` and `/workspace` over one shared client
  set. Every Inventory record and every ELN folder, notebook and document is a folder;
  documents expose their text fields as sub-folders holding the linked files, so a file can
  be uploaded into or downloaded from a chosen document field. Paths use the records' own
  names (`/gallery/Images/microscope.png`); a sibling sharing a name carries its global ID
  before the extension (`data [GL112].csv`), a segment written as a global ID always
  resolves, and `path_style="labelled"` or `"id"` make every segment carry one. Read-only by
  default (`writable=True`, `allow_delete=True`). One API call per directory listing, with
  `details.size/created/modified` populated, and listings stream page by page. A
  `rspace://host` opener is registered; the key comes from `RSPACE_API_KEY`, never the URL.
  `print_tree`/`format_tree` render the tree. See `docs/usage-guide.md`.
- Inventory attachments uploaded through the filesystem are now Gallery files linked to the
  record, as the web interface's "link from Gallery" produces; `via_gallery=False` restores
  the older Inventory-only file. `RSpaceFilesystem.copy` links a Gallery file into an
  Inventory record or an ELN field instead of duplicating it, via the new
  `InventoryClient.attach_gallery_file_by_global_id`.
- Signed (locked) ELN documents report the lock in the `access` namespace and list their
  fields with a `(signed)` suffix; writes to them are refused before any request is made.
- RSpace client errors surface as PyFilesystem errors: 404 is `ResourceNotFound`, 401 and
  403 `PermissionDenied`, 5xx or a lost connection `RemoteConnectionError`; 400, 409 and 422
  stay `ApiError` with the server's explanation.
- Security: the opener reads the key from `RSPACE_API_KEY` only and accepts `scheme=http`
  for loopback hosts only; a record whose name looks like an address is listed with its
  real ID so it cannot redirect a download or a remove to another record.
- Security: the client never follows an HTTP redirect, since `requests` would carry the
  `apiKey` header to the new host.
- Client-level changes: `_links` URLs are rebased onto the configured host so paging and
  download links work behind a proxy; `doDelete` tolerates a leading slash (fixes
  `delete_document`); `upload_file` and `upload_attachment_by_global_id` take an optional
  `filename=`; `list_folder_tree` takes `page_size=`; new `get_workbench_by_id`; Inventory
  CSV import uses the shared session.
- Removed a stray debug print from `InventoryClient.upload_attachment_by_global_id`.
- Added `rspace_client/tests/mock_rspace`, an offline mock of the endpoints the filesystems
  use, plus a harness that shows what Galaxy's file browser would display. Not installed.
- Known limitation: the Gallery folder-tree endpoint returns no file sizes, so a `details`
  listing fetches each file's record to fill `size` in.

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
