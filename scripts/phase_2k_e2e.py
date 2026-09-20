import json
import subprocess
import time
import urllib.error
import urllib.request

from uuid import uuid4

from config.settings import (
    get_service_api_settings,
)


BASE_URL = "http://127.0.0.1:8000"


def request_json(
    path: str,
    *,
    payload: dict | None = None,
    timeout: int = 600,
) -> dict:
    body = None

    headers = {
        "Accept": "application/json",
    }

    method = "GET"

    if payload is not None:
        body = json.dumps(
            payload
        ).encode(
            "utf-8"
        )

        headers[
            "Content-Type"
        ] = "application/json"

        method = "POST"

        headers[
            "X-API-Key"
        ] = (
            get_service_api_settings()
            .service_api_key
            .get_secret_value()
        )

    request = (
        urllib.request.Request(
            f"{BASE_URL}{path}",
            data=body,
            headers=headers,
            method=method,
        )
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            content = (
                response.read()
                .decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:
        error_body = (
            exc.read()
            .decode(
                "utf-8",
                errors="replace",
            )
        )

        raise RuntimeError(
            f"HTTP {exc.code}: "
            f"{error_body}"
        ) from exc

    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Failed to reach the "
            "containerized API."
        ) from exc

    return json.loads(
        content
    )


def wait_for_health() -> None:
    for _ in range(
        30
    ):
        try:
            response = (
                request_json(
                    "/health",
                    timeout=5,
                )
            )

            if (
                response.get(
                    "status"
                )
                == "ok"
            ):
                return

        except Exception:
            pass

        time.sleep(
            2
        )

    raise RuntimeError(
        "Containerized application "
        "did not become healthy."
    )


def verify_runtime_state(
    *,
    bronze_dataset: str,
    silver_dataset: str,
    gold_dataset: str,
) -> dict:
    """
    Execute deterministic verification inside
    the running application container.

    This proves:
    - persistent Bronze exists
    - PostgreSQL Bronze exists
    - dbt Silver exists
    - dbt Gold exists
    - governed SQL accepts Gold
    - governed read-only execution works
    """

    verification_code = r"""
import json
import os

import psycopg2

from psycopg2 import sql

from config.settings import (
    get_database_settings,
    get_runtime_settings,
)

from utils.database import (
    DatabaseUtil,
)

from utils.sql_safety import (
    SQLSafetyValidator,
)


bronze_dataset = os.environ[
    "E2E_BRONZE"
]

silver_dataset = os.environ[
    "E2E_SILVER"
]

gold_dataset = os.environ[
    "E2E_GOLD"
]

database_settings = (
    get_database_settings()
)

runtime_settings = (
    get_runtime_settings()
)

bronze_file = (
    runtime_settings.data_root
    / "bronze"
    / bronze_dataset
    / "extracted_data.csv"
)

if not bronze_file.exists():
    raise RuntimeError(
        "Container E2E Bronze file "
        "does not exist."
    )


def relation_count(
    cursor,
    *,
    schema_name,
    relation_name,
):
    query = sql.SQL(
        "SELECT COUNT(*) "
        "FROM {}.{}"
    ).format(
        sql.Identifier(
            schema_name
        ),
        sql.Identifier(
            relation_name
        ),
    )

    cursor.execute(
        query
    )

    return (
        cursor.fetchone()[0]
    )


silver_schema = (
    f"{runtime_settings.dbt_target_schema}"
    "_silver"
)

gold_schema = (
    f"{runtime_settings.dbt_target_schema}"
    "_gold"
)

silver_model = (
    f"stg_{silver_dataset}"
)

gold_model = (
    f"mart_{gold_dataset}"
)

connection = (
    psycopg2.connect(
        **database_settings
        .psycopg_config()
    )
)

try:
    with connection.cursor() as cursor:

        bronze_count = (
            relation_count(
                cursor,
                schema_name="bronze",
                relation_name=(
                    bronze_dataset
                ),
            )
        )

        silver_count = (
            relation_count(
                cursor,
                schema_name=(
                    silver_schema
                ),
                relation_name=(
                    silver_model
                ),
            )
        )

        gold_count = (
            relation_count(
                cursor,
                schema_name=(
                    gold_schema
                ),
                relation_name=(
                    gold_model
                ),
            )
        )

finally:
    connection.close()


database = (
    DatabaseUtil(
        database_settings
        .psycopg_config()
    )
)

catalog = (
    database.analytics_catalog(
        target_schema=(
            runtime_settings
            .dbt_target_schema
        )
    )
)

governed_query = (
    "SELECT COUNT(*) AS row_count "
    f"FROM {gold_schema}."
    f"{gold_model};"
)

validation = (
    SQLSafetyValidator.validate(
        governed_query,
        analytics_catalog=(
            catalog
        ),
    )
)

if not validation.is_safe:
    raise RuntimeError(
        "Container E2E Gold query "
        "failed governed SQL validation: "
        f"{validation.reason}"
    )

query_result = (
    database
    .execute_read_only_result(
        governed_query
    )
)

governed_gold_count = (
    query_result.rows[0][0]
)

print(
    json.dumps(
        {
            "data_root": str(
                runtime_settings
                .data_root
            ),
            "bronze_file_exists": (
                bronze_file.exists()
            ),
            "bronze_count": (
                bronze_count
            ),
            "silver_count": (
                silver_count
            ),
            "gold_count": (
                gold_count
            ),
            "governed_gold_count": (
                governed_gold_count
            ),
            "governed_sql_safe": (
                validation.is_safe
            ),
            "gold_relation": (
                f"{gold_schema}."
                f"{gold_model}"
            ),
        }
    )
)
"""

    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "-e",
        (
            "E2E_BRONZE="
            f"{bronze_dataset}"
        ),
        "-e",
        (
            "E2E_SILVER="
            f"{silver_dataset}"
        ),
        "-e",
        (
            "E2E_GOLD="
            f"{gold_dataset}"
        ),
        "app",
        "python",
        "-c",
        verification_code,
    ]

    result = (
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    )

    if (
        result.returncode
        != 0
    ):
        raise RuntimeError(
            "Container state verification "
            "failed.\n\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    output_lines = [
        line
        for line
        in result.stdout.splitlines()
        if line.strip()
    ]

    if not output_lines:
        raise RuntimeError(
            "Container verification "
            "returned no output."
        )

    try:
        return json.loads(
            output_lines[-1]
        )

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Could not parse container "
            "verification output."
        ) from exc


def main() -> None:
    suffix = (
        uuid4()
        .hex[:8]
    )

    bronze_dataset = (
        f"users_phase2k_{suffix}"
    )

    silver_dataset = (
        f"users_phase2k_clean_{suffix}"
    )

    gold_dataset = (
        f"users_phase2k_gold_{suffix}"
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "PHASE 2K — CONTAINERIZED E2E"
    )

    print(
        "=" * 80
    )

    print(
        "\nWaiting for container health..."
    )

    wait_for_health()

    print(
        "Application is healthy."
    )

    # ========================================================
    # REAL HTTP → AGENT → ETL/dbt PIPELINE
    # ========================================================

    etl_request = f"""
Build a warehouse-backed PostgreSQL + dbt pipeline.

Extract only the first 5 users from:

https://dummyjson.com/users?limit=5

Do not paginate.

The API records are located under the top-level field:

users

Save the CSV Bronze dataset as:

{bronze_dataset}

Then create a dbt Silver dataset named:

{silver_dataset}

For Silver:
- keep only id, firstName, lastName, email

Then create a dbt Gold dataset named:

{gold_dataset}

For Gold:
- keep only id, firstName, lastName, email
- do not filter any rows
"""

    print(
        "\nRunning containerized ETL..."
    )

    etl_response = (
        request_json(
            "/query",
            payload={
                "message": (
                    etl_request
                )
            },
        )
    )

    agent_response = (
        etl_response.get(
            "response"
        )
    )

    if (
        not isinstance(
            agent_response,
            str,
        )
        or not agent_response.strip()
    ):
        raise RuntimeError(
            "Containerized ETL returned "
            "no agent response."
        )

    print(
        "\nETL agent response:"
    )

    print(
        agent_response
    )

    # ========================================================
    # DETERMINISTIC STATE VERIFICATION
    # ========================================================

    print(
        "\nVerifying durable container state..."
    )

    verification = (
        verify_runtime_state(
            bronze_dataset=(
                bronze_dataset
            ),
            silver_dataset=(
                silver_dataset
            ),
            gold_dataset=(
                gold_dataset
            ),
        )
    )

    counts = (
        verification[
            "bronze_count"
        ],
        verification[
            "silver_count"
        ],
        verification[
            "gold_count"
        ],
        verification[
            "governed_gold_count"
        ],
    )

    if any(
        count <= 0
        for count in counts
    ):
        raise RuntimeError(
            "Containerized pipeline "
            "produced an empty relation."
        )

    if len(
        set(
            counts
        )
    ) != 1:
        raise RuntimeError(
            "Bronze, Silver, Gold, and "
            "governed SQL row counts "
            "do not match."
        )

    if (
        verification[
            "data_root"
        ]
        != "/app/data"
    ):
        raise RuntimeError(
            "Container is not using "
            "/app/data."
        )

    if not (
        verification[
            "governed_sql_safe"
        ]
    ):
        raise RuntimeError(
            "Gold query was not accepted "
            "by governed SQL."
        )

    print(
        json.dumps(
            verification,
            indent=2,
        )
    )

    # ========================================================
    # REAL HTTP → SQL AGENT
    # ========================================================

    analytics_request = f"""
How many rows are in the Gold dataset
{gold_dataset}?

Use the governed warehouse analytics path.
"""

    print(
        "\nRunning containerized analytics..."
    )

    analytics_response = (
        request_json(
            "/query",
            payload={
                "message": (
                    analytics_request
                )
            },
        )
    )

    final_answer = (
        analytics_response.get(
            "response"
        )
    )

    if (
        not isinstance(
            final_answer,
            str,
        )
        or not final_answer.strip()
    ):
        raise RuntimeError(
            "Containerized analytics "
            "returned no answer."
        )

    print(
        "\nAnalytics response:"
    )

    print(
        final_answer
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "PHASE 2K CONTAINERIZED E2E PASSED"
    )

    print(
        "=" * 80
    )

    print(
        f"\nBronze: {bronze_dataset}"
    )

    print(
        f"Silver: {silver_dataset}"
    )

    print(
        f"Gold: {gold_dataset}"
    )

    print(
        "\nContainerized path verified:"
    )

    print(
        "HTTP → Agent → API → Bronze → "
        "PostgreSQL → dbt → governed SQL"
    )


if __name__ == "__main__":
    main()