import pytest

from utils.data_layers import (
    DataLayer,
    resolve_layer_dataset_directory,
    validate_dataset_name,
)
from utils.exceptions import DatasetError


def test_dataset_name_is_normalized():
    assert (
        validate_dataset_name(
            "  Orders  "
        )
        == "orders"
    )


@pytest.mark.parametrize(
    "dataset_name",
    [
        "../orders",
        "../../secret",
        "orders/2026",
        r"orders\2026",
        "",
        "   ",
        ".hidden",
        "orders.",
        "CON",
        "nul",
    ],
)
def test_unsafe_dataset_names_are_rejected(
    dataset_name,
):
    with pytest.raises(
        DatasetError
    ):
        validate_dataset_name(
            dataset_name
        )


def test_bronze_dataset_directory_is_deterministic(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    result = (
        resolve_layer_dataset_directory(
            data_root=data_root,
            layer=DataLayer.BRONZE,
            dataset_name="orders",
        )
    )

    assert result == (
        data_root
        / "bronze"
        / "orders"
    ).resolve()


def test_different_layers_have_different_roots(
    tmp_path,
):
    data_root = (
        tmp_path
        / "data"
    )

    bronze = (
        resolve_layer_dataset_directory(
            data_root=data_root,
            layer=DataLayer.BRONZE,
            dataset_name="orders",
        )
    )

    silver = (
        resolve_layer_dataset_directory(
            data_root=data_root,
            layer=DataLayer.SILVER,
            dataset_name="orders",
        )
    )

    assert bronze != silver