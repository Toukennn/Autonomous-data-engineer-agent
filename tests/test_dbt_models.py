from utils.dbt_models import (
    DBTSilverModelManager,
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