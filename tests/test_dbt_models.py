import pytest

from utils.dbt_models import (
    DBTGoldModelManager,
    DBTSilverModelManager,
)
from utils.exceptions import (
    DatasetError,
)

def test_silver_dbt_model_is_generated(
    tmp_path,
):
    manager = DBTSilverModelManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    result = (
        manager
        .create_source_projection(
            source_dataset="orders",
            columns=[
                "order_id",
                "amount",
            ],
        )
    )

    assert (
        result.model_name
        == "stg_orders"
    )

    assert (
        result.model_file.exists()
    )

    sql = (
        result.model_file
        .read_text(
            encoding="utf-8"
        )
    )

    assert (
        '"order_id"'
        in sql
    )

    assert (
        '"amount"'
        in sql
    )

    assert (
        '{{ source("bronze", "orders") }}'
        in sql
    )


def test_dbt_model_names_do_not_collide(
    tmp_path,
):
    manager = DBTSilverModelManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    hyphen_name = (
        manager
        .model_name_for_dataset(
            "order-items"
        )
    )

    dot_name = (
        manager
        .model_name_for_dataset(
            "order.items"
        )
    )

    assert (
        hyphen_name
        != dot_name
    )

    assert (
        "-" not in hyphen_name
    )

    assert (
        "." not in dot_name
    )


def test_dbt_model_name_respects_postgres_limit(
    tmp_path,
):
    manager = DBTSilverModelManager(
        dbt_project_dir=(
            tmp_path
            / "dbt"
        )
    )

    model_name = (
        manager
        .model_name_for_dataset(
            "a" * 63
        )
    )

    assert (
        len(
            model_name.encode(
                "utf-8"
            )
        )
        <= 63
    )


def test_gold_dbt_model_is_generated(
    tmp_path,
):
    dbt_root = (
        tmp_path
        / "dbt"
    )

    silver_manager = (
        DBTSilverModelManager(
            dbt_project_dir=(
                dbt_root
            )
        )
    )

    gold_manager = (
        DBTGoldModelManager(
            dbt_project_dir=(
                dbt_root
            )
        )
    )

    silver_result = (
        silver_manager
        .create_source_projection(
            source_dataset="orders",
            columns=[
                "order_id",
                "amount",
            ],
        )
    )

    result = (
        gold_manager
        .create_silver_projection(
            source_dataset="orders",
            source_model_name=(
                silver_result.model_name
            ),
            columns=[
                "order_id",
                "amount",
            ],
        )
    )

    assert (
        result.model_name
        == "mart_orders"
    )

    assert (
        result.model_file.exists()
    )

    sql = (
        result.model_file
        .read_text(
            encoding="utf-8"
        )
    )

    assert (
        '"order_id"'
        in sql
    )

    assert (
        '"amount"'
        in sql
    )

    assert (
        '{{ ref("stg_orders") }}'
        in sql
    )


def test_gold_dbt_model_names_do_not_collide(
    tmp_path,
):
    manager = (
        DBTGoldModelManager(
            dbt_project_dir=(
                tmp_path
                / "dbt"
            )
        )
    )

    first = (
        manager
        .model_name_for_dataset(
            "order-items"
        )
    )

    second = (
        manager
        .model_name_for_dataset(
            "order.items"
        )
    )

    assert first != second


def test_gold_model_rejects_unsafe_silver_ref(
    tmp_path,
):
    manager = (
        DBTGoldModelManager(
            dbt_project_dir=(
                tmp_path
                / "dbt"
            )
        )
    )

    with pytest.raises(
        DatasetError,
        match=(
            "Invalid Silver dbt "
            "model name"
        ),
    ):
        manager\
            .create_silver_projection(
                source_dataset="orders",
                source_model_name=(
                    "stg_orders); drop_table"
                ),
                columns=[
                    "order_id",
                ],
            )


def test_gold_model_name_respects_postgres_limit(
    tmp_path,
):
    manager = (
        DBTGoldModelManager(
            dbt_project_dir=(
                tmp_path
                / "dbt"
            )
        )
    )

    model_name = (
        manager
        .model_name_for_dataset(
            "a" * 63
        )
    )

    assert (
        len(
            model_name.encode(
                "utf-8"
            )
        )
        <= 63
    )