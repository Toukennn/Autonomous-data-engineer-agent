import re
from enum import Enum
from pathlib import Path

from utils.exceptions import DatasetError


class DataLayer(str, Enum):
    """
    Deterministic medallion-layer identifiers.
    """

    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


_DATASET_NAME_PATTERN = re.compile(
    r"^[a-z0-9]"
    r"(?:[a-z0-9._-]{0,126}[a-z0-9_-])?$"
)


_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *{
        f"com{number}"
        for number in range(
            1,
            10,
        )
    },
    *{
        f"lpt{number}"
        for number in range(
            1,
            10,
        )
    },
}


def validate_dataset_name(
    dataset_name: str,
) -> str:
    """
    Validate and normalize a logical dataset identifier.

    Dataset names are identifiers, not paths.
    """

    if not isinstance(
        dataset_name,
        str,
    ):
        raise DatasetError(
            "Dataset name must be a string."
        )

    normalized = (
        dataset_name
        .strip()
        .lower()
    )

    if not normalized:
        raise DatasetError(
            "Dataset name cannot be empty."
        )

    if not _DATASET_NAME_PATTERN.fullmatch(
        normalized
    ):
        raise DatasetError(
            "Invalid dataset name. "
            "Use only letters, numbers, dots, "
            "underscores, and hyphens. "
            "Path separators are not allowed."
        )

    windows_stem = (
        normalized
        .split(
            ".",
            maxsplit=1,
        )[0]
    )

    if (
        windows_stem
        in _WINDOWS_RESERVED_NAMES
    ):
        raise DatasetError(
            "Dataset name is reserved by the "
            "operating system."
        )

    return normalized


def resolve_layer_dataset_directory(
    *,
    data_root: Path,
    layer: DataLayer,
    dataset_name: str,
) -> Path:
    """
    Resolve a deterministic dataset directory inside a
    medallion data layer.
    """

    safe_dataset_name = (
        validate_dataset_name(
            dataset_name
        )
    )

    root = data_root.resolve()

    layer_root = (
        root
        / layer.value
    ).resolve()

    dataset_directory = (
        layer_root
        / safe_dataset_name
    ).resolve()

    try:
        dataset_directory.relative_to(
            layer_root
        )

    except ValueError as exc:
        raise DatasetError(
            "Dataset directory escaped its "
            "configured data layer."
        ) from exc

    return dataset_directory