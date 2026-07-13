from dataclasses import dataclass
from enum import Enum
import datetime, math

import json
import re
import sys, io, base64
import requests
import pprint
import requests
from typing import Optional, Sequence, Union, List, TypedDict, BinaryIO

from rspace_client.client_base import ClientBase, Pagination
from rspace_client.inv import quantity_unit as qu


class DeletedItemFilter(Enum):
    EXCLUDE = 1
    INCLUDE = 2
    DELETED_ONLY = 3


class BarcodeFormat(str, Enum):
    BARCODE = "BARCODE"
    QR = "QR"


class Tag(TypedDict):
  value: str
  uri: str
  ontologyName: str
  ontologyVersion: str

@dataclass
class Barcode:
    data: str
    format: BarcodeFormat
    description: str = ""
    newBarcodeRequest: bool = True
    id: Optional[str] = ""

    def to_dict(self):
        return{
            "data": self.data,
            "format": self.format.value,
            "description": self.description,
            "newBarcodeRequest": self.newBarcodeRequest
        }


class FillingStrategy(Enum):
    """
    Strategy for filling grid containers
    """

    BY_ROW = 1
    BY_COLUMN = 2
    EXACT = 3


class Sample:
    """
    Wraps a dict of Sample data returned from samples/{id} GET API call
    """

    def __init__(self, data: dict):
        self.data = data

    def wherep(self) -> List[str]:
        """
        Returns a list of breadcrumb names of all containers that subsamples
        of this sample are located in.

        Returns
        -------
        A List of Strings like "Mikes fridge->shelf 2-> Blue box #23"

        """
        bcumbs = set()
        for ss in self.data["subSamples"]:
            b_crumb = " -> ".join([x["name"] for x in ss["parentContainers"]][::-1])
            bcumbs.add(b_crumb)
        return bcumbs

    def __repr__(self):
        return f"Sample: id = {self.data['id']}, name = {self.data['name']}, creationDate = {self.data['created']}"


class GridPlacement:
    """
    Superclass of all grid placement strategies
    """

    def __init__(self, items_to_move: str, filling_strategy: FillingStrategy):
        ids = []
        for item in items_to_move:
            toMove = Id(item)
            if not toMove.is_movable():
                raise ValueError(f" Can't move {item} - not a movable type")
            ids.append(toMove)
        self.items_to_move = ids
        self.filling_strategy = filling_strategy


class AutoFit(GridPlacement):
    """
    Base class of ByRow and ByColumn filling strategies.
    """

    def __init__(
        self,
        column_index: int,
        row_index: int,
        total_columns: int,
        total_rows: int,
        items_to_move,
        filling_strategy,
    ):
        if len(items_to_move) == 0:
            raise ValueError("Provide at least one item to move")
        for arg in (row_index, column_index, total_columns, total_rows):
            if arg < 1:
                raise ValueError("All row/column indices must be >= 1")
        if column_index > total_columns or row_index > total_rows:
            raise ValueError(
                f"Column and row indexes({column_index},{row_index}"
                + " must fit in dimensions ({total_columns}, {total_rows}"
            )
        super().__init__(items_to_move, filling_strategy)
        self.row_index = row_index
        self.column_index = column_index
        self.total_columns = total_columns
        self.total_rows = total_rows

    def __repr__(self):
        return f"""<{self.__class__.__name__}: Items {len(self.items_to_move)}, column_index={self.column_index}
                row_index = {self.row_index}, total_columns={self.total_columns}, total_rows={self.total_rows},
                filling_strategy = {self.filling_strategy!r}
                """


class GridLocation:
    """
    Stores column(x) and row(y) indices of a GridContainer
    """

    def __init__(self, x: int, y: int):
        if x < 1 or y < 1:
            raise ValueError("Grid location coordinates must be >= 1")
        self.x = x
        self.y = y

    def __repr__(self):
        return f"{self.__class__.__name__}({self.x}, {self.y})"

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return self.x == other.x and self.y == other.y


class ByRow(AutoFit):
    """
    Defines a strategy for filling a grid container with a list of items, filling rows
    in turn, from a starting location.
    """

    def __init__(
        self,
        column_index: int,
        row_index: int,
        total_columns: int,
        total_rows: int,
        *items_to_move,
    ):
        """

        Parameters
        ----------
        column_index : int
            The column (x) index, 1-based, to start placing items.
        row_index : int
           The row (y) index, 1-based, from top->bottom, to start placing items.
        total_columns : int
            The total number of columns in the grid
        total_rows : int
            The total number of rows in the grid
        *items_to_move :
            One or more global Ids.

        Returns
        -------
        None.

        """
        super().__init__(
            column_index,
            row_index,
            total_columns,
            total_rows,
            items_to_move,
            filling_strategy=FillingStrategy.BY_ROW,
        )


class ByColumn(AutoFit):
    """
    Defines a strategy for filling a grid container with a list of items, filling columns
    in turn, from a starting location.
    """

    def __init__(
        self,
        column_index: int,
        row_index: int,
        total_columns: int,
        total_rows: int,
        *items_to_move,
    ):
        """
        Parameters
        ----------
        column_index : int
            The column (x) index, 1-based, to start placing items.
        row_index : int
           The row (y) index, 1-based, from top->bottom, to start placing items.
        total_columns : int
            The total number of columns in the grid
        total_rows : int
            The total number of rows in the grid
        *items_to_move :
            One or more global Ids.
        """
        super().__init__(
            column_index,
            row_index,
            total_columns,
            total_rows,
            items_to_move,
            filling_strategy=FillingStrategy.BY_COLUMN,
        )


class ByLocation(GridPlacement):
    """
    Place one or more items by exact location
    """

    def __init__(self, locations: List[GridLocation], *items_to_move):
        if len(locations) != len(items_to_move):
            raise ValueError(
                f"locations list (length {len(locations)}) is not the same length as items list ({len(items_to_move)})"
            )
        super().__init__(items_to_move, filling_strategy=FillingStrategy.EXACT)
        self.locations = locations


class BulkOperationResult:
    """
    Encapsulates the return value from any bulk operation
    """

    def __init__(self, json):
        self.data = json

    def is_ok(self):
        return self.data["status"] == "COMPLETED"

    def results(self):
        return self.data["results"]

    def success_results(self):
        """
        Returns results as list of dicts{record: error:} where result was successful
        """
        return list(filter(lambda x: x["record"] is not None, self.results()))

    def error_results(self):
        """
        Returns results as list of dicts{record: error:} where  error field is not None
        """
        return list(filter(lambda x: x["error"] is not None, self.results()))

    def is_failed(self):
        return not self.is_ok()

    def __str__(self):
        return f"Succeeded: {self.is_ok()}: Result JSON: {self.data}"

    def __repr__(self):
        return f"Succeeded: {self.is_ok()}: Result JSON: {self.data!r}"


class Container:
    """
    Base class of all Container types (representing Container data obtained from RSpace).
    """

    @classmethod
    def of(clz, container: dict):
        """
        Factory method to create a specific container object from raw JSON

        Parameters
        ----------
        container : dict
          JSON returned from get_container_by_id or create_container methods

        Raises
        ------
        ValueError
            if the JSON is not of the correct type

        Returns
        -------
            A subclass based on the 'cType' value of the container's JSON

        """
        Container._is_valid_container(container)
        if container["cType"] == "GRID":
            return GridContainer(container)
        elif container["cType"] == "LIST":
            return ListContainer(container)
        elif container["cType"] == "WORKBENCH":
            return Workbench(container)
        elif container["cType"] == "IMAGE":
            return ImageContainer(container)
        else:
            raise ValueError(f"unsupported container type {container['cType']}")

    @staticmethod
    def _is_valid_container(container):
        if "cType" not in container.keys():
            raise ValueError(
                "no 'cType' container type entry - is this really a container?"
            )

    def __init__(self, container: dict):
        Container._is_valid_container(container)
        self.data = container

    def _validate_type(self, c, expected_c_type):
        if c["cType"] != expected_c_type:
            raise ValueError(
                f"required {expected_c_type} container but is of cType {c['cType']}"
            )

    def is_grid(self) -> bool:
        return False

    def is_list(self) -> bool:
        return False

    def is_workbench(self) -> bool:
        return False

    def is_image(self) -> bool:
        return False

    def accept_subsamples(self) -> bool:
        return self.data["canStoreSamples"] == True

    def accept_containers(self) -> bool:
        return self.data["canStoreContainers"] == True

    def capacity(self) -> int:
        pass


class ListContainer(Container):
    """
    A ListContainer is an ordered container of unlimited capacity
    """

    def __init__(self, list_container: dict):
        super().__init__(list_container)
        self._validate_type(list_container, "LIST")

    def is_list() -> bool:
        return True

    def capacity(self) -> int:
        """
        Unlimited capacity, returns sys.maxsize
        """
        return sys.maxsize

    def __repr__(self):
        return f"{self.__class__.__name__}, id={self.data['globalId']!r},storesContainers={self.accept_containers()},\
storesSubsamples={self.accept_subsamples}"


class ImageContainer(Container):
    """
    Wrapper around dict of ImageContainer JSON
    """

    def __init__(self, image_container: dict):
        super().__init__(image_container)
        self._validate_type(image_container, "IMAGE")

    def is_image(self) -> bool:
        return True

    def capacity(self) -> int:
        """
        Returns number of locations defined.
        """
        return len(self.data["locations"])

    def free_locations(self) -> int:
        """
        Returns
        -------
        int
            Number of locations with no content.

        """
        return len(list(filter(lambda x: x["content"] is None, self.data["locations"])))

    def used_locations(self) -> int:
        """
        Returns
        -------
        int
            Number of locations with content.
        """
        return self.capacity() - self.free_locations()


class Workbench(Container):
    """
    A specialised Container holding currently active samples and containers.
    """

    def __init__(self, workbench: dict):
        super().__init__(workbench)
        self._validate_type(workbench, "WORKBENCH")

    def is_workbench(self) -> bool:
        return True


class GridContainer(Container):
    """
    Encapsulates results from create_grid_container() or get_container_by_id()
    """

    def __init__(self, grid_container: dict):
        super().__init__(grid_container)
        self._validate_type(grid_container, "GRID")

    def is_grid(self) -> bool:
        return True

    def row_count(self) -> int:
        return self.data["gridLayout"]["rowsNumber"]

    def column_count(self) -> int:
        return self.data["gridLayout"]["columnsNumber"]

    def capacity(self) -> int:
        """
        The number of cells in the grid - product of row and column counts
        """
        return self.row_count() * self.column_count()

    def free(self) -> int:
        """
        Returns
        -------
        int Number of free cells available to hold new content
        """
        return self.capacity() - self.in_use()

    def in_use(self) -> int:
        """
        Returns
        -------
        int Number of cells holding content
        """
        return len(self.data["locations"])

    def percent_full(self) -> float:
        return (self.in_use() / self.capacity()) * 100

    def used_locations(self):
        """
        Returns
        -------
        list of tuples of x,y coords of cells with content; 1-based, where x is column number and y is row number

        """
        return [(item["coordX"], item["coordY"]) for item in self.data["locations"]]

    def free_locations(self):
        """
        The inverse of 'used_locations' - gets empty grid cells
        Returns
        -------
        list of tuples of x,y coords of empty cells; 1-based, where x is column number and y is row number
        """
        rc = []
        used = self.used_locations()
        for col in range(1, self.column_count() + 1):
            for row in range(1, self.row_count() + 1):
                if (col, row) not in used:
                    rc.append((col, row))
        return rc

    def __repr__(self):
        return f"{self.__class__.__name__} id={self.data['globalId']!r}, storesContainers={self.accept_containers()},\
 storesSubsamples={self.accept_subsamples()}, percent_full={self.percent_full():.2f}"


class SearchFilter:
    def __init__(
        self, deleted_item_filter=DeletedItemFilter.EXCLUDE, owned_by: str = None
    ):
        self.data = {}
        if deleted_item_filter is not None:
            self.data["deletedItems"] = deleted_item_filter.name
        if owned_by is not None and len(owned_by) > 0:
            self.data["ownedBy"] = owned_by

    def __str__(self):
        return f"{str(self.data)}"

    def __repr__(self):
        return f"{self.__class__.__name__}({self.data['deletedItems']!r}, '{self.data['ownedBy']!r}')"

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return (
            self.deleted_item_filter == other.deleted_item_filter
            and self.data["ownedBy"] == other.data["ownedBy"]
        )


class ResultType(Enum):
    SAMPLE = 1
    SUBSAMPLE = 2
    TEMPLATE = 3
    CONTAINER = 4
    INSTRUMENT = 5
    INSTRUMENT_TEMPLATE = 6


class Id:
    """
    Supports integer or string representation of a globalId or
    numeric ID or a dict / object representation of an Inventory item.
    If a dict is passed, it must have 'id' and 'globalId' properties.

    Two Ids are equal in 2 cases:
        - if their prefix and id are both equal
        - if only IDs are equal, and neither prefix is defined
    """

    Pattern = r"([A-Z]{2})?\d+"

    PREFIX_TO_TYPE = {
        "IC": "CONTAINER",
        "SS": "SUBSAMPLE",
        "SA": "SAMPLE",
        "IT": "SAMPLE_TEMPLATE",
        "IN": "INSTRUMENT",
        "NT": "INSTRUMENT_TEMPLATE",
    }
    PREFIX_TO_API = {
        "IC": "containers",
        "SS": "subSamples",
        "SA": "samples",
        "IT": "sampleTemplates",
        "IN": "instruments",
        "NT": "instrumentTemplates",
    }

    @staticmethod
    def is_valid_id(arg):
        try:
            Id(arg)
        except ValueError:
            return False
        return True

    def __init__(self, value: Union[int, str, dict, Container, Workbench, Sample]):

        if isinstance(value, str):
            if re.match(Id.Pattern, value) is None:
                raise ValueError("incorrect global id format")

            if len(value) > 2 and value[0:2].isalpha():
                self.prefix = value[0:2]
                self.id = int(value[2:])
            else:
                self.id = int(value)
        elif isinstance(value, Workbench):
            self.prefix = "BE"
            self.id = value.data["id"]
        elif isinstance(value, Container):
            self.prefix = "IC"
            self.id = value.data["id"]
        elif isinstance(value, dict):
            if "id" in value.keys():
                self.id = value["id"]
            else:
                raise TypeError(
                    "Could not interpet dict as an identifiable Inventory item."
                )

            if "globalId" in value.keys():
                self.prefix = value["globalId"][0:2]

        elif isinstance(value, int):
            self.id = value
        else:
            raise TypeError(
                f"Could not interpet {value!r} as an identifiable Inventory item."
            )

    def __repr__(self):
        rc = str(self.id)
        if hasattr(self, "prefix"):
            rc = "'" + self.prefix + rc + "'"
        return f"{self.__class__.__name__}({rc})"

    def __str__(self):
        rc = str(self.id)
        if hasattr(self, "prefix"):
            rc = self.prefix + rc
        return rc

    def __eq__(self, o):
        if not isinstance(o, self.__class__):
            return False
        if self.id != o.id:
            return False
        pref_s = hasattr(self, "prefix")
        pref_o = hasattr(o, "prefix")
        if (pref_s and pref_o and self.prefix == o.prefix) or (
            not pref_s and not pref_o
        ):
            return True
        return False

    def as_id(self) -> int:
        return self.id

    def as_global_id(self) -> str:
        """
        Assumes that prefix has been set

        Returns
        -------
        str global_id

        """
        return self.prefix + str(self.id)

    def is_container(self, maybe: bool = False) -> bool:
        return self._check("IC", maybe)

    def is_subsample(self, maybe: bool = False) -> bool:
        return self._check("SS", maybe)

    def is_bench(self, maybe: bool = False) -> bool:
        return self._check("BE", maybe)

    def is_sample(self, maybe: bool = False) -> bool:
        return self._check("SA", maybe)

    def is_movable(self, maybe: bool = False) -> bool:
        return self.is_subsample(maybe) or self.is_container(maybe)

    def get_type(self):
        return Id.PREFIX_TO_TYPE[self.prefix]

    def get_api_endpoint(self):
        return Id.PREFIX_TO_API[self.prefix]

    def _check(self, prefix, maybe: bool):
        if maybe:
            return not hasattr(self, "prefix") or self.prefix == prefix
        else:
            return hasattr(self, "prefix") and self.prefix == prefix


class ExtraFieldType(Enum):
    TEXT = "text"
    NUMBER = "number"
    LINK = "link"


class RelationType(Enum):
    """
    The vocabulary of relationship types permitted on an Inventory Link field.

    These are the DataCite 4.7 ``relationType`` values plus the PIDINST
    ``IsCalibratedBy``/``Calibrates`` pair. A Link field, or a template Link
    field's whitelist, may use any of these values.
    """

    IS_CITED_BY = "IsCitedBy"
    CITES = "Cites"
    IS_SUPPLEMENT_TO = "IsSupplementTo"
    IS_SUPPLEMENTED_BY = "IsSupplementedBy"
    IS_CONTINUED_BY = "IsContinuedBy"
    CONTINUES = "Continues"
    IS_DESCRIBED_BY = "IsDescribedBy"
    DESCRIBES = "Describes"
    HAS_METADATA = "HasMetadata"
    IS_METADATA_FOR = "IsMetadataFor"
    HAS_VERSION = "HasVersion"
    IS_VERSION_OF = "IsVersionOf"
    IS_NEW_VERSION_OF = "IsNewVersionOf"
    IS_PREVIOUS_VERSION_OF = "IsPreviousVersionOf"
    IS_PART_OF = "IsPartOf"
    HAS_PART = "HasPart"
    IS_PUBLISHED_IN = "IsPublishedIn"
    IS_REFERENCED_BY = "IsReferencedBy"
    REFERENCES = "References"
    IS_DOCUMENTED_BY = "IsDocumentedBy"
    DOCUMENTS = "Documents"
    IS_COMPILED_BY = "IsCompiledBy"
    COMPILES = "Compiles"
    IS_VARIANT_FORM_OF = "IsVariantFormOf"
    IS_ORIGINAL_FORM_OF = "IsOriginalFormOf"
    IS_IDENTICAL_TO = "IsIdenticalTo"
    IS_REVIEWED_BY = "IsReviewedBy"
    REVIEWS = "Reviews"
    IS_DERIVED_FROM = "IsDerivedFrom"
    IS_SOURCE_OF = "IsSourceOf"
    IS_REQUIRED_BY = "IsRequiredBy"
    REQUIRES = "Requires"
    IS_OBSOLETED_BY = "IsObsoletedBy"
    OBSOLETES = "Obsoletes"
    IS_COLLECTED_BY = "IsCollectedBy"
    COLLECTS = "Collects"
    IS_TRANSLATION_OF = "IsTranslationOf"
    HAS_TRANSLATION = "HasTranslation"
    IS_CALIBRATED_BY = "IsCalibratedBy"
    CALIBRATES = "Calibrates"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """True if ``value`` is one of the known relationType string values."""
        return value in cls._value2member_map_


class InventoryLink:
    """
    Value object describing the target of a Link extra-field.

    A link records a ``relation_type`` (how the source relates to the target),
    a ``target_global_id`` (the linked record) and an optional ``version_pin``
    that pins the link to a specific version of the target.

    ``relation_type`` accepts either a :class:`RelationType` or a raw string.
    Raw strings that are not in the known vocabulary are allowed through with
    no client-side error, so callers are not blocked if the server vocabulary
    grows ahead of this client; the server remains the source of truth.
    """

    # Global ID prefixes the server accepts as link targets: Inventory items
    # (samples, subsamples, containers, instruments, sample templates) and ELN
    # records (documents, notebooks, gallery files).
    ALLOWED_TARGET_PREFIXES = ("SA", "SS", "IC", "IN", "IT", "SD", "NB", "GL")

    def __init__(
        self,
        relation_type: Union["RelationType", str],
        target_global_id: str,
        version_pin: Optional[int] = None,
    ):
        if isinstance(relation_type, RelationType):
            self.relation_type = relation_type.value
        else:
            self.relation_type = relation_type
        if not target_global_id or not str(target_global_id).strip():
            raise ValueError("target_global_id cannot be empty or None")
        prefix = re.match(r"^[A-Z]+", str(target_global_id))
        if prefix is None or prefix.group(0) not in self.ALLOWED_TARGET_PREFIXES:
            raise ValueError(
                f"target_global_id '{target_global_id}' must start with one of "
                f"the allowed prefixes {self.ALLOWED_TARGET_PREFIXES}"
            )
        self.target_global_id = target_global_id
        self.version_pin = version_pin

    def _toDict(self) -> dict:
        d = {
            "relationType": self.relation_type,
            "targetGlobalId": self.target_global_id,
        }
        if self.version_pin is not None:
            d["versionPin"] = self.version_pin
        return d

    def __repr__(self):
        return (
            f"{self.__class__.__name__} ({self.relation_type!r}, "
            f"{self.target_global_id!r}, {self.version_pin!r})"
        )


class TemperatureUnit(Enum):
    CELSIUS = 8
    KELVIN = 9


class StorageTemperature:
    """
    Value object that stores  degrees and units.
    Two temperatures are considered equal if they differ by less
     than 1 part in 1e4
    """

    def __init__(
        self, degrees: float, units: TemperatureUnit = TemperatureUnit.CELSIUS
    ):
        self.degrees = degrees
        self.units = units

    def _toDict(self) -> dict:
        return {"unitId": self.units.value, "numericValue": self.degrees}

    def __repr__(self):
        return f"{self.__class__.__name__} ({self.degrees}, {self.units!r})"

    def __str__(self):
        return f"{self.degrees} {self.units}"

    def __eq__(self, o):
        if not isinstance(o, self.__class__):
            return False
        return (
            math.isclose(self.degrees, o.degrees, rel_tol=1e-4)
            and self.units == o.units
        )


class Quantity:
    """
    Two quantities are considered equal if they differ by less than 1 part in 1e4
    """

    def __init__(self, value: float, units: dict):
        self.value = value
        self.units = units

    def _toDict(self) -> dict:
        return {"numericValue": self.value, "unitId": self.units["id"]}

    def __repr__(self):
        return f"{self.__class__.__name__} ({self.value}, '{self.units['label']}')"

    def __str__(self):
        return f"{self.value} {self.units['label']}"

    def __eq__(self, o):
        if not isinstance(o, self.__class__):
            return False
        return (
            math.isclose(self.value, o.value, rel_tol=1e-4)
            and self.units["id"] == o.units["id"]
        )


class ExtraField:
    """
    A custom field that can be added to an Inventory item.

    For ``TEXT`` and ``NUMBER`` fields the value is held in ``content``, which
    must match the type set in ``fieldType``.

    For ``LINK`` fields the value is a :class:`InventoryLink` supplied via the
    ``link`` argument (or via the :meth:`link` convenience constructor) instead
    of ``content``.
    """

    def __init__(
        self,
        name: str,
        fieldType: ExtraFieldType = ExtraFieldType.TEXT,
        content: Union[str, int, float] = "",
        link: Optional["InventoryLink"] = None,
    ):
        if fieldType == ExtraFieldType.LINK:
            if link is None:
                raise ValueError("A LINK ExtraField requires a 'link' argument")
            if content:
                raise ValueError("A LINK ExtraField cannot also set 'content'")
            self.data = {"name": name, "type": fieldType.value, "link": link._toDict()}
        else:
            if link is not None:
                raise ValueError(
                    f"'link' is only valid for LINK fields, not {fieldType.value}"
                )
            self.data = {"name": name, "type": fieldType.value, "content": content}

    @classmethod
    def link(
        cls,
        name: str,
        relation_type: Union["RelationType", str],
        target_global_id: str,
        version_pin: Optional[int] = None,
    ) -> "ExtraField":
        """
        Convenience constructor for a Link extra-field.

        Parameters
        ----------
        name : str
            The field name.
        relation_type : RelationType or str
            How the source item relates to the target.
        target_global_id : str
            The Global ID of the linked record (e.g. 'SA123', 'IT42', 'GL9').
        version_pin : int, optional
            Pins the link to a specific version of the target.
        """
        return cls(
            name,
            ExtraFieldType.LINK,
            link=InventoryLink(relation_type, target_global_id, version_pin),
        )

    def __repr__(self):
        if self.data["type"] == ExtraFieldType.LINK.value:
            return (
                f"{self.__class__.__name__} ({self.data['name']!r}, "
                f"{self.data['type']!r}, {self.data['link']!r})"
            )
        return f"{self.__class__.__name__} ({self.data['name']!r}, {self.data['type']!r},\
{self.data['content']!r})"


class ItemPost:
    """
    Help define core properties of an Inventory item
    """

    def __init__(
        self,
        name: str,
        itemType: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
    ):
        self.data = {}
        self.data["type"] = itemType
        self.data["name"] = name
        self.data["tags"] = tags
        if description is not None:
            self.data["description"] = description
        if extra_fields is not None:
            self.data["extraFields"] = [ef.data for ef in extra_fields]


class SamplePost(ItemPost):
    """
    Help define sample data structures to create or modify samples
    """

    def __init__(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        sample_template_id=None,
        fields=None,
        storage_temperature_min: StorageTemperature = None,
        storage_temperature_max: StorageTemperature = None,
        expiry_date: datetime.datetime = None,
        subsample_count: int = None,
        total_quantity: Quantity = None,
        attachments=None,
        barcodes: Optional[List[Barcode]] = None,
        location: "TargetLocation" = None,
    ):
        super().__init__(name, "SAMPLE", tags, description, extra_fields)
        ## converts arguments into JSON POST syntax

        if storage_temperature_min is not None:
            self.data["storageTempMin"] = storage_temperature_min._toDict()
        if storage_temperature_max is not None:
            self.data["storageTempMax"] = storage_temperature_max._toDict()
        if expiry_date is not None:
            self.data["expiryDate"] = expiry_date.isoformat()
        if subsample_count is not None:
            self.data["newSampleSubSamplesCount"] = subsample_count
        if total_quantity is not None:
            self.data["quantity"] = total_quantity._toDict()
        if sample_template_id is not None:
            self.data["templateId"] = sample_template_id
        if fields is not None:
            self.data["fields"] = fields
        if location is not None:
            self.data.update(location.data)
        ## fail early
        if attachments is not None and not isinstance(attachments, list):
            raise ValueError("attachments must be a list of open files")
        if barcodes is not None:
            self.data["barcodes"] = [barcode.to_dict() for barcode in barcodes]


class InstrumentPost(ItemPost):
    """
    Help define instrument data structures to create or modify instruments
    """

    def __init__(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        instrument_template_id=None,
        fields=None,
        attachments=None,
        barcodes: Optional[List[Barcode]] = None,
    ):
        super().__init__(name, "INSTRUMENT", tags, description, extra_fields)
        ## converts arguments into JSON POST syntax

        if instrument_template_id is not None:
            self.data["templateId"] = instrument_template_id
        if fields is not None:
            self.data["fields"] = fields
        ## fail early
        if attachments is not None:
            if not isinstance(attachments, list):
                raise ValueError("attachments must be a list of open files")
        if barcodes is not None:
            self.data["barcodes"] = [barcode.to_dict() for barcode in barcodes]


class TargetLocation:
    """
    Base class of target locations. It is recommended to use one of the subclasses
    and not instantiate this directly.
    """

    def __init__(self, target_container: Union[str, int, dict, Container]):
        """
        Parameters
        ----------
        target_container : Union[str, int, dict, Container]
            A numeric or global ID of a container, or a Container object, or a dict of a Container,
            or a string: 'w' for workbench, 't' for top-level.
        Raises
        ------
        ValueError
            If the global id is not 'IC' or the argument is a dict but not that of a container
        TypeError
            If type is not supported
        """
        self.data = {}
        if target_container == "t":
            self.data["removeFromParentContainerRequest"] = True
        elif target_container == "w":
            self.data = {}

        elif Id.is_valid_id(target_container):
            parent_id = Id(target_container)
            if not parent_id.is_container(True):
                raise ValueError("Id must be that of a container")
            self.data["parentContainers"] = [{"id": parent_id.as_id()}]
        else:
            raise TypeError("location must be 'w', 't' or a Container, id or global Id")

    def __repr__(self):
        return f"{self.__class__.__name__}: {self.data!r}"


class BenchTargetLocation(TargetLocation):
    def __init__(self):
        super().__init__("w")


class TopLevelTargetLocation(TargetLocation):
    def __init__(self):
        super().__init__("t")


class ListContainerTargetLocation(TargetLocation):
    def __init__(self, target_container: Union[str, int, dict, Container]):
        super().__init__(target_container)


class ImageContainerTargetLocation(TargetLocation):
    """
    An location in an ImageContainer is specified by the the container, and the
    ID of the location within the container.
    """

    def __init__(
        self,
        target_container: Union[str, int, dict, Container],
        target_location_id: int,
    ):
        super().__init__(target_container)
        self.data["parentLocation"] = {"id": target_location_id}
        del self.data["parentContainers"]


class GridContainerTargetLocation(TargetLocation):
    """
    Defines the identity of a grid location to move into, and its coordinates in the grid.
    """

    def __init__(
        self,
        target_container: Union[str, int, dict, Container],
        col_index: int,
        row_index: int,
    ):
        super().__init__(target_container)
        gl = GridLocation(col_index, row_index)  ## validates coords
        self.data["parentLocation"] = {"coordX": gl.x, "coordY": gl.y}


class ContainerPost(ItemPost):
    """
    Base class for defining a new Container
    """

    def __init__(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_samples: bool = True,
        location: TargetLocation = TopLevelTargetLocation(),
    ):
        super().__init__(name, "CONTAINER", tags, description, extra_fields)
        if not can_store_containers and not can_store_samples:
            raise ValueError(
                "At least one of 'canStoreContainers' and 'canStoreSamples' must be True"
            )
        self.data["type"] = "CONTAINER"
        self.data["canStoreContainers"] = can_store_containers
        self.data["canStoreSamples"] = can_store_samples
        self.data.update(location.data)

    def __repr__(self):
        return f"{self.__class__.__name__}: {self.data!r}"


class ListContainerPost(ContainerPost):
    """
    Define a new ListContainer to create
    """

    def __init__(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_samples: bool = True,
        location: TargetLocation = TopLevelTargetLocation(),
    ):
        super().__init__(
            name,
            tags,
            description,
            extra_fields,
            can_store_containers,
            can_store_samples,
            location,
        )
        self.data["cType"] = "LIST"


class ImageContainerPost(ContainerPost):
    """
    Define a new ImageContainer to create.
    """

    def _setencoded(self, img_file):
        image_b64 = base64.b64encode(img_file.read()).decode("ascii")
        self.data["newBase64LocationsImage"] = "data:image/png;base64," + str(image_b64)

    def __init__(
        self,
        name: str,
        image_file: Union[str, io.BufferedReader],
        locations: Optional[Sequence] = [],
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_samples: bool = True,
        location: TargetLocation = TopLevelTargetLocation(),
    ):
        """
        Parameters
        ----------
        name : str
            Name of the image container.
        image_file_path : str
            A full file path to the image to use, or BufferedReader file object.
        locations : Optional[Sequence], optional
            An optional list of (x,y) coordinate tuples of marked locations within
            the image container.
        tags : List[Tag], list
            List of tags
        description : Optional[str], optional
        extra_fields : Optional[Sequence], optional
        can_store_containers : bool, optional
            The default is True.
        can_store_samples : bool, optional
            The default is True.
        location : TargetLocation, optional
            Where this new container will be located. The default is TopLevelTargetLocation.
        """
        super().__init__(
            name,
            tags,
            description,
            extra_fields,
            can_store_containers,
            can_store_samples,
            location,
        )

        if isinstance(image_file, str):
            with open(image_file, "rb") as img_file:
                self._setencoded(img_file)
        elif isinstance(image_file, io.BufferedReader):
            self._setencoded(image_file)
        locs = [{"coordX": p[0], "coordY": p[1]} for p in locations]
        self.data["locations"] = locs
        self.data["cType"] = "IMAGE"


class GridContainerPost(ContainerPost):
    """
    Define a new grid container to create
    """

    def __init__(
        self,
        name: str,
        row_count: int,
        column_count: int,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_samples: bool = True,
        location: TargetLocation = TopLevelTargetLocation(),
    ):
        super().__init__(
            name,
            tags,
            description,
            extra_fields,
            can_store_containers,
            can_store_samples,
            location,
        )
        self.data["cType"] = "LIST"
        self.data["gridLayout"] = {
            "columnsNumber": column_count,
            "rowsNumber": row_count,
        }


class InventoryClient(ClientBase):
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

    MAX_BULK = 100
    ## Helper method for generic bulk post
    def _do_bulk(self, post_json):
        resp_json = self.retrieve_api_results(
            "/bulk", request_type="POST", params=post_json
        )
        return BulkOperationResult(resp_json)

    def bulk_create_sample(self, *sample_posts):
        """
        Create up to MAX_BULK samples at once.
        Parameters
        ----------
        *sample_posts : An unpacked iterable of >=1 SamplePost objects
            Up to MAX_BULK SamplePost objects can be sent at once.

        Returns
        -------
        BulkOperationResult
        """
        if len(sample_posts) > InventoryClient.MAX_BULK:
            raise ValueError(
                f"Max permitted samples is {InventoryClient.MAX_BULK} but was {len(sample_posts)}"
            )
        toPost = [s.data for s in sample_posts]
        bulk_post = {"operationType": "CREATE", "records": toPost}
        return self._do_bulk(bulk_post)

    def create_sample(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        sample_template_id=None,
        fields=None,
        storage_temperature_min: StorageTemperature = None,
        storage_temperature_max: StorageTemperature = None,
        expiry_date: datetime.datetime = None,
        subsample_count: int = None,
        total_quantity: Quantity = None,
        attachments=None,
        barcodes: Optional[List[Barcode]] = None,
    ) -> dict:
        """
        Creates a new sample with a mandatory name, optional attributes
        If no template id is specified, the default template will be used,
        whose quantity is measured as a volume.

        Note that including files to attach to Attachment fields is not supported
        by this method.
        """
        toPost = SamplePost(
            name,
            tags,
            description,
            extra_fields,
            sample_template_id,
            fields,
            storage_temperature_min,
            storage_temperature_max,
            expiry_date,
            subsample_count,
            total_quantity,
            attachments,
            barcodes
        )

        sample = self.retrieve_api_results(
            "/samples", request_type="POST", params=toPost.data
        )
        if attachments is not None:
            for file in attachments:
                self.upload_attachment(sample["globalId"], file)
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
        return self.retrieve_api_results(f"/samples/{s_id.as_id()}")

    def get_subsample_by_id(self, subsample_id: Union[str, int]) -> dict:
        ss_id = Id(subsample_id)
        if ss_id.is_subsample is False:
            raise ValueError(f"{ss_id} is not id of a subsample")
        return self.retrieve_api_results(f"/subSamples/{ss_id.as_id()}")

    def list_samples(
        self, pagination: Pagination = Pagination(), sample_filter: SearchFilter = None
    ) -> dict:
        """
        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        Returns
        -------
        Paginated Search result. Use 'next' and 'prev' links to navigate
        """
        return self._do_simple_list("samples", pagination, sample_filter)

    def list_top_level_containers(
        self, pagination: Pagination = Pagination(), sample_filter: SearchFilter = None
    ) -> dict:
        """
        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        Returns
        -------
        Paginated Search result. Use 'next' and 'prev' links to navigate
        """
        return self._do_simple_list("containers", pagination, sample_filter)

    def list_subsamples(
        self, pagination: Pagination = Pagination(), sample_filter: SearchFilter = None
    ) -> dict:
        """
        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        Returns
        -------
        Paginated Search result. Use 'next' and 'prev' links to navigate
        """
        return self._do_simple_list("subSamples", pagination, sample_filter)

    def _do_simple_list(self, endpoint, pagination, sample_filter):
        if sample_filter is not None:
            pagination.data.update(sample_filter.data)
        return self.retrieve_api_results(
            f"/{endpoint}",
            request_type="GET",
            params=pagination.data,
        )

    def stream_samples(
        self, pagination: Pagination = Pagination(), sample_filter: SearchFilter = None
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
        if sample_filter is not None:
            pagination.data.update(sample_filter.data)
        return self._stream("samples", pagination)

    def stream_top_level_containers(
        self, pagination: Pagination = Pagination(), sample_filter: SearchFilter = None
    ):
        """
        Streams all containers. Pagination argument sets batch size and ordering.
        Parameters
        ----------
        pagination : Pagination, optional. The default is Pagination().

        Yields
        ------
        item : One Container at a time
        """
        if sample_filter is not None:
            pagination.data.update(sample_filter.data)
        return self._stream("containers", pagination)

    def rename(self, item_id: Union[str, dict], new_name: str) -> dict:
        """
        Renames an inventory item
        Parameters
        ----------
            id : Global Id of item, or a dict representation of the item to rename
            new_name : str The new name.
        Returns
        -------
            dict : The updated item
        """
        s_id = Id(item_id)
        endpoint = s_id.get_api_endpoint()
        return self.retrieve_api_results(
            f"/{endpoint}/{s_id.as_id()}", request_type="PUT", params={"name": new_name}
        )

    def set_image(self, item_id: Union[str, dict], file) -> dict:
        """
        Sets image for a sample, subsample or container

        Parameters
        ----------
        item_id : Union[str, dict]
            The id or dict of the item to set the image for.
        file : File object
            An open file object.

        Returns
        -------
        dict
            The upddated item with links of rel=image and rel=thumnail set.

        """
        s_id = Id(item_id)
        endpoint = s_id.get_api_endpoint()
        image_b64 = base64.b64encode(file.read()).decode("ascii")
        data = {"newBase64Image": "data:image/png;base64," + str(image_b64)}
        return self.retrieve_api_results(
            f"/{endpoint}/{s_id.as_id()}", request_type="PUT", params=data
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

    def create_instrument(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        instrument_template_id=None,
        fields=None,
        attachments=None,
        barcodes: Optional[List[Barcode]] = None,
    ) -> dict:
        """
        Creates a new instrument with a mandatory name and optional attributes.
        If no template id is specified, the default Instrument template will be used.

        Note that including files to attach to Attachment fields is not supported
        by this method.
        """
        toPost = InstrumentPost(
            name,
            tags,
            description,
            extra_fields,
            instrument_template_id,
            fields,
            attachments,
            barcodes,
        )

        instrument = self.retrieve_api_results(
            "/instruments", request_type="POST", params=toPost.data
        )
        if attachments is not None:
            for file in attachments:
                self.upload_attachment(instrument["globalId"], file)
            ## get latest version
            instrument = self.get_instrument_by_id(instrument["id"])
        return instrument

    def get_instrument_by_id(self, instrument_id: Union[str, int]) -> dict:
        """
        Gets a full instrument information by id or global id
        Parameters
        ----------
        id : Union[int, str]
            An integer ID e.g 1234 or a global ID e.g. IN1234
        Returns
        -------
        dict
            A full description of one instrument
        """
        i_id = Id(instrument_id)
        return self.retrieve_api_results(f"/instruments/{i_id.as_id()}")

    def list_instruments(
        self, pagination: Pagination = Pagination(), search_filter: SearchFilter = None
    ) -> dict:
        """
        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        Returns
        -------
        Paginated Search result. Use 'next' and 'prev' links to navigate
        """
        return self._do_simple_list("instruments", pagination, search_filter)

    def delete_instrument(self, instrument_id: Union[int, str]):
        """
        Marks an instrument as deleted, so it won't appear in Inventory UI and
        default listings.
        Parameters
        ----------
        instrument_id : Union[int, str]
            A integer id, or a string id or global ID.

        Returns
        -------
        None.
        """
        id_to_delete = Id(instrument_id)
        self.doDelete("instruments", id_to_delete.as_id())

    def restore_instrument(self, instrument_id: Union[int, str]) -> dict:
        """
        Restores a previously deleted instrument.
        Parameters
        ----------
        instrument_id : Union[int, str]
            The id of the deleted instrument to restore.
        Returns
        -------
        dict
            The updated instrument.
        """
        id_to_restore = Id(instrument_id)
        return self.retrieve_api_results(
            f"/instruments/{id_to_restore.as_id()}/restore",
            request_type="PUT",
        )

    def transfer_instrument_owner(self, instrument_id: Union[int, str], new_owner: str):
        """
        Transfers the instrument to the new owner
        Parameters
        ----------
        instrument_id : Union[int, str]
            The id of the instrument to transfer
        new_owner : str
            The username of the new owner

        Returns
        -------
        dict
            The updated instrument.
        """
        i_id = Id(instrument_id)
        return self._do_transfer_owner("instruments", i_id, new_owner)

    def update_instrument_to_latest_template_version(
        self, instrument_id: Union[int, str]
    ) -> dict:
        """
        If the Instrument Template used to create this instrument has been updated
        since, applies those changes to this instrument (e.g. adds newly added
        template fields, renames existing fields). No-op if already on the latest
        template version.
        Parameters
        ----------
        instrument_id : Union[int, str]
            The id of the instrument to update.
        Returns
        -------
        dict
            The updated instrument.
        """
        i_id = Id(instrument_id)
        return self.retrieve_api_results(
            f"/instruments/{i_id.as_id()}/actions/updateToLatestTemplateVersion",
            request_type="POST",
        )

    def get_instrument_revisions(self, instrument_id: Union[int, str]) -> Sequence[dict]:
        """
        Returns list of historical revisions saved for the Instrument, starting from
        the earliest revision.
        """
        i_id = Id(instrument_id)
        return self.retrieve_api_results(f"/instruments/{i_id.as_id()}/revisions")

    def get_instrument_revision(
        self, instrument_id: Union[int, str], revision_id: Union[int, str]
    ) -> dict:
        """
        Returns full details of a historical revision saved for the Instrument.
        """
        i_id = Id(instrument_id)
        return self.retrieve_api_results(
            f"/instruments/{i_id.as_id()}/revisions/{revision_id}"
        )

    def add_extra_fields(self, item_id: Union[str, dict], *ExtraField) -> dict:
        s_id = Id(item_id)
        endpoint = s_id.get_api_endpoint()
        toPut = []
        for ef in ExtraField:
            ef.data["newFieldRequest"] = True
            toPut.append(ef.data)
        return self.retrieve_api_results(
            f"/{endpoint}/{s_id.as_id()}",
            request_type="PUT",
            params={"extraFields": toPut},
        )

    def get_link_target_summary(self, global_id: Union[str, dict]) -> dict:
        """
        Returns a read-time summary of an Inventory Link target: its current
        state as {globalId, name, type, deleted, readable}, permission-redacted
        for the current user (targets the caller cannot read return a
        globalId-only summary).

        Parameters
        ----------
        global_id : Union[str, dict]
            The Global ID (or item dict) of a link target. May be an Inventory
            item or an ELN record (document, notebook, gallery file).

        Returns
        -------
        dict
            The link target summary.
        """
        gid = Id(global_id).as_global_id()
        return self.retrieve_api_results(f"/linkTargets/{gid}/summary")

    def get_referencing_items(self, global_id: Union[str, dict]) -> dict:
        """
        Returns the Inventory items whose Link extra-field points at the
        supplied target, i.e. the back-references to ``global_id``. The result
        is permission-filtered to sources the current user can read.

        Parameters
        ----------
        global_id : Union[str, dict]
            The Global ID (or item dict) of the target. May be an Inventory
            item or an ELN record (document, notebook, gallery file).

        Returns
        -------
        dict
            The referencing (linking) items.
        """
        gid = Id(global_id).as_global_id()
        return self.retrieve_api_results(f"/referencingItems/{gid}")

    def get_attachment_by_id(self, attachment_id: Union[str, int]) -> dict:
        """
        Parameters
        ----------
        attachment_id : Union[str, int]
            The id of the file to retrieve

        Returns
        -------
        dict
            The file metadata
        """
        return self.retrieve_api_results(f"/files/{attachment_id}")

    def upload_attachment(self, inventory_item: Union[str, dict], file) -> dict:
        """
        Uploads an attachment file to a sample, subsample or container.
        Parameters
        ----------
        - inventory_item : str
            Global id or dictionary of a sample (SA...), Subsample (SS...) Container (IC...), or SampleField (SF...)
            If the item is a SampleField id, then the field must be of type 'Attachment'
        - file : an open file
            An open file stream.

        Returns
        -------
        Dict of the created InventoryFile
        """
        global_id = Id(inventory_item)
        fs = {"parentGlobalId": global_id.as_global_id()}
        fsStr = json.dumps(fs)
        headers = self._get_headers()
        response = requests.post(
            self._get_api_url() + "/files",
            files={"file": file, "fileSettings": (None, fsStr, "application/json")},
            headers=headers,
        )
        return self._handle_response(response)

    def delete_attachment_by_id(self, attachment_id: Union[str, int]) -> None:
        """
        Parameters
        ----------
        attachment_id : Union[str, int]
            The id of the file to delete

        Returns
        -------
        None
        """
        self.doDelete("files", attachment_id)

    def download_attachment_by_id(self, attachment_id: Union[str, int], file_path: Union[str, BinaryIO], chunk_size=128) -> None:
        url_base = self._get_api_url()
        return self.download_link_to_file(
            f"{url_base}/files/{attachment_id}/file", file_path, chunk_size
        )

    def upload_attachment_by_global_id(self, record_global_id: str, file: BinaryIO) -> None:
        print(record_global_id, json.dumps({"parentGlobalId": record_global_id}))
        response = requests.post(
            self._get_api_url() + "/files",
            data={"fileSettings": json.dumps({"parentGlobalId": record_global_id})},
            files={"file": file },
            headers=self._get_headers(),
        )
        return self._handle_response(response)

    def split_subsample(
        self,
        subsample: Union[int, str, dict],
        num_new_subsamples: int,
        quantity_per_subsample: float = None,
    ):
        """
        Supports splitting of all or part of a subsample into 1 or more new
        subsamples.

        Parameters
        ----------
        subsample : Union[int, str, dict]
            The ID, global Id or dict of the subsample to split.
        num_new_subsamples : int
            The number of new subsamples to create
        quantity_per_subsample : float, optional
            The quantity per subsample If not set, the whole subsample will
            be split equally. Use this parameter to set a smaller quantity per subsample.

        Returns
        -------
        A list of split subsamples
        """

        def _do_call(ss_id, params):
            return self.retrieve_api_results(
                f"/subSamples/{ss_id.as_id()}/actions/split",
                request_type="POST",
                params=params,
            )

        ss_id = Id(subsample)
        if quantity_per_subsample is None:
            to_post = {"numSubSamples": num_new_subsamples + 1, "split": True}
            return _do_call(ss_id, to_post)
        else:
            qu_to_decrement_from_original = num_new_subsamples * quantity_per_subsample
            curr_quantity = None
            if isinstance(subsample, dict) and ss_id.is_subsample(True):
                ## we already have quantity info, don't need to call
                curr_quantity = subsample["quantity"]
            else:
                full_ss = self.get_subsample_by_id(ss_id.as_id())
                curr_quantity = full_ss["quantity"]
            if qu_to_decrement_from_original > curr_quantity["numericValue"]:
                raise ValueError(
                    f"Attempting to remove {qu_to_decrement_from_original}, but original subsample {ss_id.as_id()} has amount {curr_quantity['numericValue']}."
                )
            to_post = {"numSubSamples": num_new_subsamples + 1, "split": True}
            new_ss = _do_call(ss_id, to_post)
            curr_quantity["numericValue"] = (
                curr_quantity["numericValue"] - qu_to_decrement_from_original
            )
            unit_id = curr_quantity["unitId"]
            records = []
            records.append(
                {
                    "id": ss_id.as_id(),
                    "type": ss_id.get_type(),
                    "quantity": curr_quantity,
                }
            )
            for split_ss in new_ss:
                split_ss_id = Id(split_ss)
                records.append(
                    {
                        "id": split_ss_id.as_id(),
                        "type": split_ss_id.get_type(),
                        "quantity": {
                            "unitId": unit_id,
                            "numericValue": quantity_per_subsample,
                        },
                    }
                )
            bulk_post = {"records": records, "operationType": "UPDATE"}
            rc = self.retrieve_api_results(
                "/bulk", request_type="POST", params=bulk_post
            )
            return BulkOperationResult(rc)

    def duplicate(
        self, item_to_duplicate: Union[str, dict], new_name: str = None
    ) -> dict:
        """
        Parameters
        ----------
        global_id : str
            Global id  of template,sample, subsample or container or dict containing global_id
        new_name : optional new name of the copy

        Returns
        -------
        The duplicated item
        """
        id_to_copy = Id(item_to_duplicate)
        endpoint = id_to_copy.get_api_endpoint()
        rc = self.retrieve_api_results(
            f"/{endpoint}/{id_to_copy.as_id()}/actions/duplicate",
            request_type="POST",
        )
        if new_name is not None:
            rc = self.rename(rc, new_name)
        return rc

    def search(
        self, query: str, pagination=Pagination(), result_type: ResultType = None
    ) -> dict:
        """
        Searches by a query, optionally paginated or restricted to a particular type (container,
                                                                                      sample, subsample or template)
        Parameters
        ----------
        query : str
            Any text string. Will search against name, tag, description
        pagination : optional
            The default is Pagination().
        result_type : ResultType, optional
         The default is None.

        Returns
        -------
        dict
            Search result summary and first page of results.

        """
        params = {"query": query}
        params.update(pagination.data)
        if result_type is not None:
            params["resultType"] = result_type.name
        return self.retrieve_api_results("/search", params=params)

    def add_note_to_subsample(
        self, subsample: Union[str, int, dict], note: str
    ) -> dict:
        ss_id = Id(subsample)
        if not ss_id.is_subsample(True):
            raise ValueError("Supplied id is not a subsamples")
        data = {"content": note}
        return self.retrieve_api_results(
            f"/subSamples/{ss_id.as_id()}/notes",
            request_type="POST",
            params=data,
        )

    def get_workbenches(self) -> Sequence[dict]:
        """
        Returns
        -------
        Sequence[dict]
            A list of Workbenches that you have permission to see. You will also retrieve
            your own workbench

        """
        result = self.retrieve_api_results("/workbenches")
        return [wb for wb in result["containers"]]

    def bulk_create_container(self, *container_posts):
        """
        Create up to MAX_BULK containers at once.
        Parameters
        ----------
        *container_posts : An unpacked iterable of >=1 ContainerPost objects
            Up to MAX_BULK ContainerPost objects can be sent at once.

        Returns
        -------
        BulkOperationResult
        """

        if len(container_posts) > InventoryClient.MAX_BULK:
            raise ValueError(
                f"Max permitted samples is {InventoryClient.MAX_BULK} but was {len(container_posts)}"
            )
        toPost = [c.data for c in container_posts]
        bulk_post = {"operationType": "CREATE", "records": toPost}
        return self._do_bulk(bulk_post)

    def create_image_container(self, imageContainerPost: ImageContainerPost):
        """
        Create a single image container

        Parameters
        ----------
        imageContainerPost : ImageContainerPost
            A definition of the ImageContainerPost to create.

        Returns
        -------
        container : A dict of JSON data representing the newly created container.
        """
        container = self.retrieve_api_results(
            "/containers", request_type="POST", params=imageContainerPost.data
        )
        return container

    def add_locations_to_image_container(
        self,
        image_container: Union[int, str, Container, dict],
        *locations: Sequence[tuple],
    ) -> dict:
        """
        Adds 1 or more new locations to an existing image container.
        If locations are empty, this  method has no effect.

        Parameters
        ----------
        image_container : Union[int, str, Container, dict]
            An identifier or representation of the iamge container to update.
        *locations : Sequence[tuple]
            A sequence of (x,y) coordinate tuples
        Returns
        -------
        dict
            The updated image container.
        """
        if len(locations) == 0:
            return
        image_c_id = self._id_as_container_id(image_container)
        loci = [
            {"newLocationRequest": True, "coordX": p[0], "coordY": p[1]}
            for p in locations
        ]
        data = {"locations": loci}

        updated = self.retrieve_api_results(
            f"/containers/{image_c_id.as_id()}", request_type="PUT", params=data
        )
        return updated

    def delete_locations_from_image_container(
        self,
        image_container: Union[int, str, Container, dict],
        *locations: Sequence[int],
    ):
        if len(locations) == 0:
            return
        image_c_id = self._id_as_container_id(image_container)
        to_delete = [
            {"id": loc_id, "deleteLocationRequest": True} for loc_id in locations
        ]
        data = {"locations": to_delete}
        updated = self.retrieve_api_results(
            f"/containers/{image_c_id.as_id()}", request_type="PUT", params=data
        )
        return updated

    ## TODO

    def create_list_container(
        self,
        name: str,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_samples: bool = True,
        location: TargetLocation = TopLevelTargetLocation(),
    ) -> dict:
        """
        Creates a single List Container, either 'top-level',  on the Workbench,
         or inside an existing Grid or List Container

        """
        data = ListContainerPost(
            name,
            tags,
            description,
            extra_fields,
            can_store_containers,
            can_store_samples,
            location,
        ).data

        container = self.retrieve_api_results(
            "/containers", request_type="POST", params=data
        )
        return container

    def get_container_by_id(self, container_id: Union[str, int], include_content = False) -> dict:
        c_id = Id(container_id)
        return self.retrieve_api_results(f"/containers/{c_id.as_id()}?includeContent={include_content}")

    def create_grid_container(
        self,
        name: str,
        row_count: int,
        column_count: int,
        tags: List[Tag] = [],
        description: Optional[str] = None,
        extra_fields: Optional[Sequence] = [],
        can_store_containers: bool = True,
        can_store_samples: bool = True,
        location: TargetLocation = TopLevelTargetLocation(),
    ) -> dict:
        """
        Parameters
        ----------
        name : str
            The container name.
        row_count : int
            Then number of rows (max 24).
        column_count : int
            The number of columns (max 24)
        tags : List[Tag]
            List of tags
        description : Optional[str], optional
            A description for this contaier. The default is None.
        extra_fields : Optional[Sequence], optional
            One or more ExtraFields. The default is [].
        can_store_containers : bool, optional
            Whether this container can store containers inside it. The default is True.
        can_store_samples : bool, optional
            Whether this container can store subsamples inside it. The default is True.
        location : TargetLocation
            A subclass of TargetLocation. Defaults to TopLevel
        Returns
        -------
        dict
            The created container.
        """

        data = GridContainerPost(
            name,
            row_count,
            column_count,
            tags,
            description,
            extra_fields,
            can_store_containers,
            can_store_samples,
            location,
        ).data
        data["cType"] = "GRID"

        container = self.retrieve_api_results(
            "/containers", request_type="POST", params=data
        )
        return container

    def set_as_top_level_container(
        self, container: Union[int, str, dict, Container]
    ) -> dict:
        """
        Moves a container from its current location to be a top-level container

        Parameters
        ----------
        container : Union[int, str, dict, Container]
            Id, dict or container object.
        Returns
        -------
        The updated container
        """
        data = {"removeFromParentContainerRequest": True}
        c_id = Id(container)

        return self.retrieve_api_results(
            f"/containers/{c_id.as_id()}", request_type="PUT", params=data
        )

    def _id_as_container_id(self, target_container_id):
        id_target = Id(target_container_id)
        if not id_target.is_container(maybe=True):
            raise ValueError("Target must be a container")
        return id_target

    def add_items_to_list_container(
        self,
        target_container_id,
        *item_ids: str,
    ) -> list:
        """
        Adds 1 or more items to a list container

        Parameters
        ----------
        target_container_id : Union[str, int]
            The id of a List container

        *item_ids : Union[str, int]
            One or more globalids of items  to move into the target container

        Raises
        ------
        ValueError
            If any item_id is not movable

        Returns
        -------
        BulkoperationResult
        """

        id_target = self._id_as_container_id(target_container_id)
        valid_item_ids = []

        ## assert there are no invalid globai ids
        for item_id in item_ids:
            id_ob = Id(item_id)
            if not id_ob.is_movable():
                raise ValueError(
                    f"Item to move '{item_id}' must be a container or subsample"
                )
            valid_item_ids.append(id_ob)

        return self._do_add_to_list_container(valid_item_ids, id_target)

    def add_items_to_image_container(
        self,
        target_container_id: Union[str, int, dict],
        items_to_move: Sequence,
        location_ids: Sequence,
    ) -> BulkOperationResult:
        """
        Adds a list of items to move to a list of  locations in an image container.
        The 2 lists must be of equal length. If unequal length, items in the longer list
         will be ignored once items in the shorter list are exhausted (like 'zip' function)
        Parameters
        ----------
        target_container_id : Union[str, int, dict]
            An identifier for the container.
        items_to_move : Sequence
            A list of globalIds or dicts of items to move.
        location_ids : Sequence
            A List of location identifiers that are the ids of image container locations.
        Returns
        -------
        BulkOperationResult
        """
        self._id_as_container_id(target_container_id)

        loci = []
        for (item, loc_id) in zip(items_to_move, location_ids):
            item_id = Id(item)
            loci.append(
                {
                    "type": item_id.get_type(),
                    "id": item_id.as_id(),
                    "parentLocation": {"id": loc_id},
                }
            )
        bulk_post = {"operationType": "MOVE", "records": loci}
        return self._do_bulk(bulk_post)

    def add_items_to_grid_container(
        self,
        target_container_id: Union[str, int, GridContainer],
        grid_placement: GridPlacement,
    ) -> BulkOperationResult:
        """
        Add one or more subsamples or containers to a grid container, starting at given row/ column
        index

        Parameters
        ----------
        target_container_id : Union[str, int]
            The Grid container to move to.
        grid_placement: configuration for how to place items in the grid
        Raises
        ------
        ValueError
            If items are the wrong or inconsistent type
        Returns
        -------
        list
            A list of updated items showing their current position
        """
        if isinstance(target_container_id, GridContainer):
            if target_container_id.free() < len(grid_placement.items_to_move):
                raise ValueError(
                    f"not enough space in {target_container_id.data['globalId']} to store {len(grid_placement.items_to_move)} - only {target_container_id.free()} spaces free."
                )
        id_target = self._id_as_container_id(target_container_id)
        ## assert there are no invalid global ids (things that are not subsamples)

        bulk_post = self._create_bulk_move(id_target, grid_placement)
        return self._do_bulk(bulk_post)

    def _do_add_to_list_container(self, items, id_target):
        coords = []
        for item in items:
            coords.append(
                {
                    "type": item.get_type(),
                    "id": item.as_id(),
                    "parentContainers": [{"id": id_target.as_id()}],
                }
            )
        to_post = {"operationType": "MOVE", "records": coords}
        return self._do_bulk(to_post)

    def _create_bulk_move(self, grid_id: Id, gp: GridPlacement):
        coords = []  # array of x,y coords
        ##
        if FillingStrategy.EXACT == gp.filling_strategy:
            for (item, coord) in zip(gp.items_to_move, gp.locations):
                coords.append(
                    {
                        "type": item.get_type(),
                        "id": item.as_id(),
                        "parentContainers": [{"id": grid_id.as_id()}],
                        "parentLocation": {"coordX": coord.x, "coordY": coord.y},
                    }
                )

            return {"operationType": "MOVE", "records": coords}
        else:
            counter = _calculate_start_index(
                gp.column_index,
                gp.row_index,
                gp.total_columns,
                gp.total_rows,
                gp.filling_strategy,
            )
            for ss_id in gp.items_to_move:

                x = gp.column_index
                y = gp.row_index
                if FillingStrategy.BY_ROW == gp.filling_strategy:
                    x = counter % gp.total_columns + 1
                    y = int(counter / gp.total_columns) + 1
                elif FillingStrategy.BY_COLUMN == gp.filling_strategy:
                    x = int(counter / gp.total_rows) + 1
                    y = counter % gp.total_rows + 1
                coords.append(
                    {
                        "type": ss_id.get_type(),
                        "id": ss_id.as_id(),
                        "parentContainers": [{"id": grid_id.as_id()}],
                        "parentLocation": {"coordX": x, "coordY": y},
                    }
                )
                counter = counter + 1
            return {"operationType": "MOVE", "records": coords}

    def create_list_of_materials(
        self,
        eln_field_id: int,
        name: str,
        *materials: Union[str, dict],
        description: str = None,
    ) -> dict:
        """
        Creates a new ListOfMaterials, attached to an ELN text field.

        Parameters
        ----------
        eln_field_id : int
            The ID of the field
        name : str
            A label for the LoM
        *materials : Union[str, dict]
            One or more globalIds or objects representing samples, subsamples or containers
        description : str, optional
            DESC. The default is None.
         : TYPE
            A decription of the purpose or the LoM

        Returns
        -------
        dict
            The newly created ListOfMaterials.

        """
        id_list = [Id(item) for item in materials]
        materials = []
        for item_id in id_list:
            materials.append(
                {"invRec": {"id": item_id.as_id(), "type": item_id.get_type()}}
            )

        to_post = {"name": name, "elnFieldId": eln_field_id, "materials": materials}
        if description is not None:
            to_post["description"] = description
        return self.retrieve_api_results(
            "/listOfMaterials", request_type="POST", params=to_post
        )

    def get_list_of_materials_for_document(self, document_id: Union[str, int, dict]):
        """
        Gets all ListsOfMaterials belonging to one ELN document

        Parameters
        ----------
        document_id : Union[str, int, dict]
            The document id, globalId or a dict of the document

        Returns
        -------
        A List of List Of Materials

        """
        doc_id = self._get_numeric_record_id(document_id)
        return self.retrieve_api_results(f"/listOfMaterials/forDocument/{doc_id}")

    def get_list_of_materials_for_field(self, field_id: Union[str, int]):
        """
        Gets all lists of materials belongong to an ELN document field

        Parameters
        ----------
        field_id : Union[str, int]

        Returns
        -------
        A List of List Of Materials

        """
        doc_id = self._get_numeric_record_id(field_id)
        return self.retrieve_api_results(f"/listOfMaterials/forField/{doc_id}")

    def get_list_of_materials(self, lom_id: int) -> dict:
        """
        Gets one List Of Materials by its id

        Parameters
        ----------
        lom_id : int

        Returns
        -------
        dict
            The list of materials.

        """
        return self.retrieve_api_results(f"/listOfMaterials/{lom_id}")

    def create_sample_template(self, sample_template_post: dict):
        """
        Creates a new SampleTemplate. Use  TemplateBuilder to create the
        template data structure required as sample_template_post parameter.

        Parameters
        ----------
        sample_template_post : A Dict
            A Dictionary of the SampleTemplate definition to post.

        Returns
        -------
        Dict
            The newly created template.
        """
        return self.retrieve_api_results(
            "/sampleTemplates", request_type="POST", params=sample_template_post
        )

    def get_sample_template_by_id(self, sample_template_id: Union[str, int]) -> dict:
        """
        Gets a full sampleTemplate information by id or global id
        Parameters
        ----------
        id : Union[int, str]
            An integer ID e.g 1234 or a global ID e.g. IT1234
        Returns
        -------
        dict
            A full description of one sample template
        """
        s_id = Id(sample_template_id)
        return self.retrieve_api_results(f"/sampleTemplates/{s_id.as_id()}")

    def delete_sample_template(self, sample_template_id: Union[int, str]) -> None:
        """
        Parameters
        ----------
        sample_template_id : Union[int, str]
            A integer id, or a string id or global ID of the template to delete

        Returns
        -------
        None.

        """
        id_to_delete = Id(sample_template_id)
        self.doDelete("sampleTemplates", id_to_delete.as_id())

    def set_sample_template_icon(self, sample_template_id: Union[int, str], file):
        """
        Parameters
        ----------
        sample_template_id : Union[int, str]
            The ID of the template to add the icon too.
        file : an open File
            An icon or image to help identify the template in listings.

        Returns
        -------
        The updated SampleTemplate, with an iconId set.

        """
        st_id = Id(sample_template_id)
        headers = self._get_headers()
        response = requests.post(
            f"{self._get_api_url()}/sampleTemplates/{st_id.as_id()}/icon",
            files={"file": file},
            headers=headers,
        )
        return self._handle_response(response)

    def get_sample_template_icon(
        self, sample_template_id: Union[int, str], icon_id: int, outfile
    ):
        """
        Downloads the Sample Template's icon

        Parameters
        ----------
        sample_template_id : Union[int, str]
            The id of the SampleTemplate.
        icon_id : int
            A numeric ID of the icon.
        outfile : string
            A  path to a writable file to store the downloaded icon.

        Returns
        -------
        void, no return value
        """
        st_id = Id(sample_template_id)
        url_base = self._get_api_url()
        return self.download_link_to_file(
            f"{url_base}/sampleTemplates/{st_id.as_id()}/icon/{icon_id}", outfile
        )

    def list_sample_templates(
        self, pagination: Pagination = Pagination(), search_filter: SearchFilter = None
    ):
        """
        Paginated listing of SampleTemplates, optionally filtering by username (owner) or deletion status

        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        search_filter : SearchFilter, optional
            The default is None.

        Returns
        -------
        A standard SearchResult with 'totalHits' attribute and a list of 'templates' with basic information
        about each template.

        """
        return self._do_simple_list("sampleTemplates", pagination, search_filter)

    def restore_sample_template(self, sample_template_id: Union[int, str]) -> dict:
        """
        Restores a deleted sample template so it will appear in the template listings and
        be usable to create new samples.
        If the template is not in a deleted state, this action has no effect.
        Parameters
        ----------
        sample_template_id : Union[int, str]
            The id of the deleted sample to restore.
        Returns
        -------
        dict
            The updated template.
        """
        id_to_restore = Id(sample_template_id)
        return self.retrieve_api_results(
            f"/sampleTemplates/{id_to_restore.as_id()}/restore",
            request_type="PUT",
        )

    def transfer_sample_template_owner(
        self, sample_template_id: Union[int, str], new_owner: str
    ):
        """
        Transfers the sample template to the new owner
        Parameters
        ----------
        sample_template_id : Union[int, str]
            The  id of the sample template to transfer
        new_owner : str
            The username of the new owner

        Returns
        -------
        dict
            The updated sample template.
        """
        st_id = Id(sample_template_id)
        return self._do_transfer_owner("sampleTemplates", st_id, new_owner)

    def create_instrument_template(self, instrument_template_post: dict) -> dict:
        """
        Creates a new InstrumentTemplate. Use InstrumentTemplateBuilder to create the
        template data structure required as instrument_template_post parameter.

        Parameters
        ----------
        instrument_template_post : A Dict
            A Dictionary of the InstrumentTemplate definition to post.

        Returns
        -------
        Dict
            The newly created template.
        """
        return self.retrieve_api_results(
            "/instrumentTemplates", request_type="POST", params=instrument_template_post
        )

    def get_instrument_template_by_id(
        self, instrument_template_id: Union[str, int]
    ) -> dict:
        """
        Gets a full InstrumentTemplate information by id or global id
        Parameters
        ----------
        id : Union[int, str]
            An integer ID e.g 1234 or a global ID e.g. NT1234
        Returns
        -------
        dict
            A full description of one instrument template
        """
        it_id = Id(instrument_template_id)
        return self.retrieve_api_results(f"/instrumentTemplates/{it_id.as_id()}")

    def delete_instrument_template(
        self, instrument_template_id: Union[int, str]
    ) -> None:
        """
        Parameters
        ----------
        instrument_template_id : Union[int, str]
            A integer id, or a string id or global ID of the template to delete

        Returns
        -------
        None.

        """
        id_to_delete = Id(instrument_template_id)
        self.doDelete("instrumentTemplates", id_to_delete.as_id())

    def set_instrument_template_icon(
        self, instrument_template_id: Union[int, str], file
    ):
        """
        Parameters
        ----------
        instrument_template_id : Union[int, str]
            The ID of the template to add the icon too.
        file : an open File
            An icon or image to help identify the template in listings.

        Returns
        -------
        The updated InstrumentTemplate, with an iconId set.

        """
        it_id = Id(instrument_template_id)
        headers = self._get_headers()
        response = requests.post(
            f"{self._get_api_url()}/instrumentTemplates/{it_id.as_id()}/icon",
            files={"file": file},
            headers=headers,
        )
        return self._handle_response(response)

    def get_instrument_template_icon(
        self, instrument_template_id: Union[int, str], icon_id: int, outfile
    ):
        """
        Downloads the Instrument Template's icon

        Parameters
        ----------
        instrument_template_id : Union[int, str]
            The id of the InstrumentTemplate.
        icon_id : int
            A numeric ID of the icon.
        outfile : string
            A  path to a writable file to store the downloaded icon.

        Returns
        -------
        void, no return value
        """
        it_id = Id(instrument_template_id)
        url_base = self._get_api_url()
        return self.download_link_to_file(
            f"{url_base}/instrumentTemplates/{it_id.as_id()}/icon/{icon_id}", outfile
        )

    def list_instrument_templates(
        self, pagination: Pagination = Pagination(), search_filter: SearchFilter = None
    ):
        """
        Paginated listing of InstrumentTemplates, optionally filtering by username
        (owner) or deletion status

        Parameters
        ----------
        pagination : Pagination, optional
            The default is Pagination().
        search_filter : SearchFilter, optional
            The default is None.

        Returns
        -------
        A standard SearchResult with 'totalHits' attribute and a list of 'templates'
        with basic information about each template.

        """
        return self._do_simple_list("instrumentTemplates", pagination, search_filter)

    def restore_instrument_template(
        self, instrument_template_id: Union[int, str]
    ) -> dict:
        """
        Restores a deleted instrument template so it will appear in the template
        listings and be usable to create new instruments.
        If the template is not in a deleted state, this action has no effect.
        Parameters
        ----------
        instrument_template_id : Union[int, str]
            The id of the deleted instrument template to restore.
        Returns
        -------
        dict
            The updated template.
        """
        id_to_restore = Id(instrument_template_id)
        return self.retrieve_api_results(
            f"/instrumentTemplates/{id_to_restore.as_id()}/restore",
            request_type="PUT",
        )

    def get_instrument_template_version(
        self, instrument_template_id: Union[int, str], version: int
    ) -> dict:
        """
        Retrieves a particular historical version of an InstrumentTemplate. Each
        InstrumentTemplate has a 'version' property starting at 1, incremented on
        each content update.
        """
        it_id = Id(instrument_template_id)
        return self.retrieve_api_results(
            f"/instrumentTemplates/{it_id.as_id()}/versions/{version}"
        )

    def transfer_instrument_template_owner(
        self, instrument_template_id: Union[int, str], new_owner: str
    ):
        """
        Transfers the instrument template to the new owner
        Parameters
        ----------
        instrument_template_id : Union[int, str]
            The  id of the instrument template to transfer
        new_owner : str
            The username of the new owner

        Returns
        -------
        dict
            The updated instrument template.
        """
        it_id = Id(instrument_template_id)
        return self._do_transfer_owner("instrumentTemplates", it_id, new_owner)

    def update_instrument_template_instruments(
        self, instrument_template_id: Union[int, str]
    ) -> dict:
        """
        Walks the current user's instruments that were created from this template at
        an older version and applies the template's latest changes to each (e.g. add
        or rename fields). If updating a particular instrument fails, it is skipped
        and the process continues.

        Returns
        -------
        dict
            The list of updated instruments and any errors encountered.
        """
        it_id = Id(instrument_template_id)
        return self.retrieve_api_results(
            f"/instrumentTemplates/{it_id.as_id()}/actions/updateInstrumentsToLatestTemplateVersion",
            request_type="POST",
        )

    def transfer_sample_owner(self, sample_id: Union[int, str], new_owner: str):
        """
        Transfers the sample  to the new owner
        Parameters
        ----------
        sample_id : Union[int, str]
            The  id of the sample  to transfer
        new_owner : str
            The username of the new owner

        Returns
        -------
        dict
            The updated sample.
        """
        sample_id = Id(sample_id)
        return self._do_transfer_owner("samples", sample_id, new_owner)

    def _do_transfer_owner(self, endpoint, item_id, new_owner):
        return self.retrieve_api_results(
            f"/{endpoint}/{item_id.as_id()}/actions/changeOwner",
            request_type="PUT",
            params={"owner": {"username": new_owner}},
        )

    def barcode(
        self,
        global_id: Union[str, dict],
        outfile: str = None,
        barcode_type: BarcodeFormat = BarcodeFormat.BARCODE,
    ) -> bytes:
        """
        Generates a QR code or barcode image, optionally saving to file if filepath supplied.
        Parameters
        ----------
        global_id : Union[str, dict]

        barcode_type:
             The default is Barcode.BARCODE.

        Returns
        -------
            Bytes of the image.

        """
        Id(global_id)  ## validate is identifier
        data = {"content": global_id, "barcodeType": barcode_type.name}
        url = f"{self._get_api_url()}/barcodes"
        headers = {"apiKey": self.api_key, "Accept": "image/png"}

        resp = requests.get(url, headers=headers, params=data)
        resp.raise_for_status()
        content = resp.content
        if outfile is not None:
            with open(outfile, "wb") as fd:
                fd.write(content)
        return content

    @staticmethod
    def _find_identifier_provider_settings(result: dict, provider: str) -> dict:
        for group in result.get("identifiersSettings", {}).values():
            for entry in group:
                if entry.get("provider") == provider:
                    return entry
        raise ValueError(f"No settings found for provider '{provider}' in /system/settings response")

    def get_datacite_settings(self, provider: str = "IGSN_DATACITE") -> dict:
        """
        Gets the current settings for the given identifier provider.

        Parameters
        ----------
        provider : str, optional
            One of "IGSN_DATACITE", "PIDINST_DATACITE", "PIDINST_B2INST". Defaults to "IGSN_DATACITE".

        Returns
        -------
        dict
            The current settings for the given provider
        """
        result = self.retrieve_api_results("/system/settings", request_type="GET")
        return self._find_identifier_provider_settings(result, provider)

    def update_datacite_settings(
        self,
        enabled: bool,
        provider: str = "IGSN_DATACITE",
        server_url: str = None,
        username: str = None,
        password: str = None,
        repository_prefix: str = None,
    ) -> dict:
        """
        Updates the settings for the given identifier provider.

        Parameters
        ----------
        enabled : bool
            Whether this provider is enabled (True or False)
        provider : str, optional
            One of "IGSN_DATACITE", "PIDINST_DATACITE", "PIDINST_B2INST". Defaults to "IGSN_DATACITE".
        server_url : str, optional
            Server URL. Required when enabled=True
        username : str, optional
            Username. Required when enabled=True
        password : str, optional
            Password. Required when enabled=True
        repository_prefix : str, optional
            Repository prefix. Required when enabled=True

        Returns
        -------
        dict
            The updated settings for the given provider
        """
        if enabled and (server_url is None or username is None or password is None or repository_prefix is None):
            raise ValueError("server_url, username, password, and repository_prefix are required when enabled=True")

        body = {"provider": provider, "enabled": str(enabled).lower()}
        if server_url is not None:
            body["serverUrl"] = server_url
        if username is not None:
            body["username"] = username
        if password is not None:
            body["password"] = password
        if repository_prefix is not None:
            body["repositoryPrefix"] = repository_prefix

        result = self.retrieve_api_results(
            "/system/settings",
            request_type="PUT",
            params=body
        )
        return self._find_identifier_provider_settings(result, provider)

    def test_datacite_connection(self, provider: str = "IGSN_DATACITE") -> bool:
        """
        Tests the connection to the configured server for the given identifier provider.

        Parameters
        ----------
        provider : str, optional
            One of "IGSN_DATACITE", "PIDINST_DATACITE", "PIDINST_B2INST". Defaults to "IGSN_DATACITE".

        Returns
        -------
        bool
            True if the connection test passes, False otherwise
        """
        endpoint_name = "testIgsnConnection" if provider == "IGSN_DATACITE" else "testPidinstConnection"
        url = self._get_api_url() + f"/identifiers/{endpoint_name}"
        headers = self._get_headers("application/json")

        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                return False
            return bool(response.json())
        except (requests.exceptions.RequestException, ValueError):
            return False

def _calculate_start_index(
    col_start, row_start, total_columns, total_rows, filling_strategy
):
    if col_start < 1 or row_start < 1:
        raise ValueError("Columns and row starting position must be >= 1")
    if col_start > total_columns or row_start > total_rows:
        raise ValueError(
            f"Columns and row starting position must fit in grid: {total_rows} rows x {total_columns} columns"
        )

    index = 0
    if FillingStrategy.BY_ROW == filling_strategy:
        index = ((row_start - 1) * total_columns) + col_start
    elif FillingStrategy.BY_COLUMN == filling_strategy:
        index = ((col_start - 1) * total_rows) + row_start
    return index - 1


def gen_tags(tags) -> List[Tag]:
  return [{
    "value": value,
    "ontologyName": None,
    "ontologyVersion": None,
    "uri": None
  } for value in tags]
