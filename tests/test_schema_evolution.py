import pandas as pd

from utils.schema_evolution import (
    compare_schemas,
    dataframe_schema,
    dataframe_schema_fingerprint,
    schema_fingerprint,
)


def test_identical_schema_has_no_changes():
    existing = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["a", "b"],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": [3, 4],
            "name": ["c", "d"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.has_changes is False

    assert diff.added_columns == ()
    assert diff.removed_columns == ()
    assert diff.type_changes == {}


def test_added_column_is_detected():
    existing = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": [2],
            "name": ["b"],
            "category": ["x"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.has_changes is True

    assert diff.added_columns == (
        "category",
    )

    assert diff.is_additive_only is True

    assert diff.is_breaking is False


def test_removed_column_is_detected():
    existing = pd.DataFrame(
        {
            "id": [1],
            "name": ["a"],
            "email": ["a@example.com"],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": [2],
            "name": ["b"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.removed_columns == (
        "email",
    )

    assert diff.is_breaking is True


def test_type_change_is_detected():
    existing = pd.DataFrame(
        {
            "id": [1, 2],
        }
    )

    incoming = pd.DataFrame(
        {
            "id": ["one", "two"],
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.type_changes == {
        "id": (
            "number",
            "string",
        )
    }

    assert diff.is_breaking is True


def test_integer_to_float_is_not_schema_change():
    existing = pd.DataFrame(
        {
            "price": [
                10,
                20,
            ]
        }
    )

    incoming = pd.DataFrame(
        {
            "price": [
                10.5,
                20.5,
            ]
        }
    )

    diff = compare_schemas(
        existing,
        incoming,
    )

    assert diff.has_changes is False


def test_dataframe_schema_uses_logical_types():
    dataframe = pd.DataFrame(
        {
            "id": [
                1,
                2,
            ],
            "price": [
                1.5,
                2.5,
            ],
            "active": [
                True,
                False,
            ],
            "name": [
                "a",
                "b",
            ],
        }
    )

    schema = dataframe_schema(
        dataframe
    )

    assert schema == {
        "id": "number",
        "price": "number",
        "active": "boolean",
        "name": "string",
    }


def test_schema_fingerprint_is_stable():
    first = {
        "id": "number",
        "name": "string",
    }

    second = {
        "id": "number",
        "name": "string",
    }

    assert (
        schema_fingerprint(first)
        == schema_fingerprint(second)
    )


def test_schema_fingerprint_changes_when_schema_changes():
    old_schema = {
        "id": "number",
        "name": "string",
    }

    new_schema = {
        "id": "number",
        "name": "string",
        "category": "string",
    }

    assert (
        schema_fingerprint(
            old_schema
        )
        != schema_fingerprint(
            new_schema
        )
    )


def test_dataframe_values_do_not_change_schema_fingerprint():
    first = pd.DataFrame(
        {
            "id": [1, 2],
            "name": ["a", "b"],
        }
    )

    second = pd.DataFrame(
        {
            "id": [100, 200],
            "name": ["x", "y"],
        }
    )

    assert (
        dataframe_schema_fingerprint(
            first
        )
        == dataframe_schema_fingerprint(
            second
        )
    )