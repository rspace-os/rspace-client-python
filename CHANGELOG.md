# Changelog

All notable changes to this project will be documented in this file

## Proposed breaking changes
 - replace naming of classes and methods using 'Workbench' to 'Bench'
 - replace create_sample, create_container long argument lists with new XXXPost objects

## Unreleased

### Added

- static method Id.is_valid_id() to check if an object can be parsed as an id
- bulk 'createContainer' methods 
- methods 'error_results' and 'success_results' on BulkOperationResult
- methods in Id: is_bench, is_sample
- Classes to  define new Containers: GridContainerPost, ListContainerPost
- Classes to define where new items are placed: ListContainerTargetLocation,
    GridContainerTargetLocation, BenchTargetLocation, TopLevelTargetLocation

### Changed
- BREAKING: altered create_grid_container and create_list_container location arguments

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

