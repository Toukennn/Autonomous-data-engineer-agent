import json
import re
from dataclasses import (
    dataclass,
)
from pathlib import Path
from uuid import UUID

from utils.exceptions import (
    DBTArtifactError,
)

import math

@dataclass(
    frozen=True
)
class DBTTestArtifactResult:
    unique_id: str
    name: str
    status: str
    execution_time_seconds: float
    failures: int | None
    directly_tests_target: bool


@dataclass(
    frozen=True
)
class DBTBuildArtifactSummary:
    invocation_id: str | None
    command: str

    target_model_unique_id: str
    target_model_name: str
    target_status: str
    target_execution_time_seconds: float

    relation_schema: str
    relation_name: str

    dependency_unique_ids: tuple[
        str,
        ...
    ]

    executed_model_unique_ids: tuple[
        str,
        ...
    ]

    tests: tuple[
        DBTTestArtifactResult,
        ...
    ]

    elapsed_time_seconds: float


class DBTArtifactReader:
    """
    Read a bounded, safe subset of dbt artifacts.

    Important:

    This component deliberately does NOT expose:

    - compiled SQL
    - raw dbt messages
    - adapter responses
    - CLI argument dictionaries
    - filesystem paths
    - credentials

    Only application-safe execution and lineage
    metadata is returned.
    """

    MODEL_NAME_PATTERN = re.compile(
        r"^[a-z0-9_]+$"
    )

    RELATION_IDENTIFIER_PATTERN = re.compile(
        r"^[A-Za-z_][A-Za-z0-9_]*$"
    )

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    def __init__(
        self,
        *,
        dbt_project_dir: Path,
    ):
        self.dbt_project_dir = (
            dbt_project_dir.resolve()
        )

        self.target_directory = (
            self.dbt_project_dir
            / "target"
        ).resolve()

        try:
            self.target_directory\
                .relative_to(
                    self.dbt_project_dir
                )

        except ValueError as exc:
            raise DBTArtifactError(
                "dbt artifact directory escaped "
                "the configured dbt project."
            ) from exc

    def _artifact_file(
        self,
        filename: str,
    ) -> Path:
        file_path = (
            self.target_directory
            / filename
        ).resolve()

        try:
            file_path.relative_to(
                self.target_directory
            )

        except ValueError as exc:
            raise DBTArtifactError(
                "dbt artifact path escaped "
                "the target directory."
            ) from exc

        return file_path

    def _load_json(
        self,
        filename: str,
    ) -> dict:
        file_path = (
            self._artifact_file(
                filename
            )
        )

        if not file_path.is_file():
            raise DBTArtifactError(
                "Required dbt artifact does "
                f"not exist: {filename}"
            )

        try:
            payload = json.loads(
                file_path.read_text(
                    encoding="utf-8"
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DBTArtifactError(
                "Failed to read dbt artifact: "
                f"{filename}"
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise DBTArtifactError(
                "dbt artifact must contain "
                "a JSON object."
            )

        return payload

    @staticmethod
    def _safe_text(
        value,
        *,
        field: str,
        max_length: int = 512,
    ) -> str:
        if (
            not isinstance(
                value,
                str,
            )
            or not value
        ):
            raise DBTArtifactError(
                f"Invalid dbt artifact field: "
                f"{field}"
            )

        if len(value) > max_length:
            raise DBTArtifactError(
                f"dbt artifact field is too long: "
                f"{field}"
            )

        if any(
            ord(character) < 32
            for character in value
        ):
            raise DBTArtifactError(
                f"dbt artifact field contains "
                f"control characters: {field}"
            )

        return value

    @classmethod
    def _relation_identifier(
        cls,
        value,
        *,
        field: str,
    ) -> str:
        value = cls._safe_text(
            value,
            field=field,
            max_length=(
                cls
                .POSTGRES_IDENTIFIER_MAX_BYTES
            ),
        )

        if not (
            cls
            .RELATION_IDENTIFIER_PATTERN
            .fullmatch(
                value
            )
        ):
            raise DBTArtifactError(
                "Unsafe dbt relation identifier "
                f"in field: {field}"
            )

        if (
            len(
                value.encode(
                    "utf-8"
                )
            )
            > cls
            .POSTGRES_IDENTIFIER_MAX_BYTES
        ):
            raise DBTArtifactError(
                "dbt relation identifier exceeds "
                "PostgreSQL's 63-byte limit."
            )

        return value

    @staticmethod
    def _duration(
        value,
        *,
        field: str,
    ) -> float:
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                (
                    int,
                    float,
                ),
            )
            or not math.isfinite(
                value
            )
            or value < 0
        ):
            raise DBTArtifactError(
                "Invalid non-negative dbt duration "
                f"field: {field}"
            )

        return float(
            value
        )

    @staticmethod
    def _test_failures(
        value,
    ) -> int | None:
        if value is None:
            return None

        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
            or value < 0
        ):
            raise DBTArtifactError(
                "Invalid dbt test failure count."
            )

        return value

    @classmethod
    def _dependencies(
        cls,
        node: dict,
    ) -> tuple[str, ...]:
        depends_on = (
            node.get(
                "depends_on",
                {},
            )
        )

        if not isinstance(
            depends_on,
            dict,
        ):
            raise DBTArtifactError(
                "Invalid dbt node dependency metadata."
            )

        nodes = (
            depends_on.get(
                "nodes",
                [],
            )
        )

        if not isinstance(
            nodes,
            list,
        ):
            raise DBTArtifactError(
                "Invalid dbt node dependency list."
            )

        result: list[str] = []

        for unique_id in nodes:
            result.append(
                cls._safe_text(
                    unique_id,
                    field=(
                        "dependency unique_id"
                    ),
                )
            )

        return tuple(
            result
        )

    @staticmethod
    def _invocation_id(
        metadata: dict,
    ) -> str | None:
        value = (
            metadata.get(
                "invocation_id"
            )
        )

        if value is None:
            return None

        try:
            return str(
                UUID(
                    value
                )
            )

        except (
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            raise DBTArtifactError(
                "Invalid dbt invocation ID."
            ) from exc

    def parse_build(
        self,
        *,
        model_name: str,
    ) -> DBTBuildArtifactSummary:
        """
        Parse manifest.json and run_results.json
        for one application-controlled dbt build.
        """

        if not (
            isinstance(
                model_name,
                str,
            )
            and self
            .MODEL_NAME_PATTERN
            .fullmatch(
                model_name
            )
        ):
            raise DBTArtifactError(
                "Invalid target dbt model name."
            )

        manifest = (
            self._load_json(
                "manifest.json"
            )
        )

        run_results = (
            self._load_json(
                "run_results.json"
            )
        )

        # ========================================================
        # COMMAND
        # ========================================================

        args = (
            run_results.get(
                "args"
            )
        )

        if not isinstance(
            args,
            dict,
        ):
            raise DBTArtifactError(
                "dbt run results are missing "
                "their argument metadata."
            )

        command = (
            self._safe_text(
                args.get(
                    "which"
                ),
                field="command",
                max_length=64,
            )
        )

        if command != "build":
            raise DBTArtifactError(
                "Expected dbt build artifacts."
            )

        # ========================================================
        # MANIFEST MODEL
        # ========================================================

        nodes = (
            manifest.get(
                "nodes"
            )
        )

        if not isinstance(
            nodes,
            dict,
        ):
            raise DBTArtifactError(
                "dbt manifest contains an "
                "invalid nodes mapping."
            )

        candidates: list[
            tuple[
                str,
                dict,
            ]
        ] = []

        for (
            unique_id,
            node,
        ) in nodes.items():

            if not isinstance(
                node,
                dict,
            ):
                raise DBTArtifactError(
                    "dbt manifest contains "
                    "an invalid node."
                )

            if (
                node.get(
                    "resource_type"
                )
                == "model"
                and node.get(
                    "name"
                )
                == model_name
            ):
                candidates.append(
                    (
                        unique_id,
                        node,
                    )
                )

        if len(
            candidates
        ) != 1:
            raise DBTArtifactError(
                "Could not resolve exactly one "
                "target model in dbt manifest."
            )

        (
            target_unique_id,
            target_node,
        ) = candidates[0]

        target_unique_id = (
            self._safe_text(
                target_unique_id,
                field=(
                    "target model unique_id"
                ),
            )
        )

        if (
            target_node.get(
                "unique_id"
            )
            != target_unique_id
        ):
            raise DBTArtifactError(
                "dbt manifest model identity "
                "is inconsistent."
            )

        relation_schema = (
            self._relation_identifier(
                target_node.get(
                    "schema"
                ),
                field=(
                    "target relation schema"
                ),
            )
        )

        relation_name = (
            self._relation_identifier(
                target_node.get(
                    "alias"
                ),
                field=(
                    "target relation name"
                ),
            )
        )

        if relation_name != model_name:
            raise DBTArtifactError(
                "dbt target relation alias does "
                "not match the expected model."
            )

        dependency_unique_ids = (
            self._dependencies(
                target_node
            )
        )

        # ========================================================
        # RUN RESULTS
        # ========================================================

        results = (
            run_results.get(
                "results"
            )
        )

        if not isinstance(
            results,
            list,
        ):
            raise DBTArtifactError(
                "dbt run results contain an "
                "invalid results list."
            )

        results_by_id: dict[
            str,
            dict,
        ] = {}

        for result in results:

            if not isinstance(
                result,
                dict,
            ):
                raise DBTArtifactError(
                    "dbt run results contain "
                    "an invalid result."
                )

            unique_id = (
                self._safe_text(
                    result.get(
                        "unique_id"
                    ),
                    field=(
                        "result unique_id"
                    ),
                )
            )

            if (
                unique_id
                in results_by_id
            ):
                raise DBTArtifactError(
                    "dbt run results contain "
                    "duplicate unique IDs."
                )

            results_by_id[
                unique_id
            ] = result

        target_result = (
            results_by_id.get(
                target_unique_id
            )
        )

        if target_result is None:
            raise DBTArtifactError(
                "Target dbt model does not appear "
                "in run results."
            )

        target_status = (
            self._safe_text(
                target_result.get(
                    "status"
                ),
                field=(
                    "target model status"
                ),
                max_length=64,
            )
        )

        target_execution_time = (
            self._duration(
                target_result.get(
                    "execution_time"
                ),
                field=(
                    "target execution time"
                ),
            )
        )

        # ========================================================
        # EXECUTED MODELS + TESTS
        # ========================================================

        executed_models: list[
            str
        ] = []

        test_results: list[
            DBTTestArtifactResult
        ] = []

        for result in results:

            unique_id = (
                result[
                    "unique_id"
                ]
            )

            manifest_node = (
                nodes.get(
                    unique_id
                )
            )

            if manifest_node is None:
                continue

            resource_type = (
                manifest_node.get(
                    "resource_type"
                )
            )

            if resource_type == "model":
                executed_models.append(
                    unique_id
                )

                continue

            if resource_type != "test":
                continue

            test_name = (
                self._safe_text(
                    manifest_node.get(
                        "name"
                    ),
                    field="test name",
                )
            )

            test_status = (
                self._safe_text(
                    result.get(
                        "status"
                    ),
                    field="test status",
                    max_length=64,
                )
            )

            test_execution_time = (
                self._duration(
                    result.get(
                        "execution_time"
                    ),
                    field=(
                        "test execution time"
                    ),
                )
            )

            test_dependencies = (
                self._dependencies(
                    manifest_node
                )
            )

            test_results.append(
                DBTTestArtifactResult(
                    unique_id=(
                        unique_id
                    ),
                    name=test_name,
                    status=(
                        test_status
                    ),
                    execution_time_seconds=(
                        test_execution_time
                    ),
                    failures=(
                        self._test_failures(
                            result.get(
                                "failures"
                            )
                        )
                    ),
                    directly_tests_target=(
                        target_unique_id
                        in test_dependencies
                    ),
                )
            )

        # ========================================================
        # TOP-LEVEL METADATA
        # ========================================================

        metadata = (
            run_results.get(
                "metadata",
                {},
            )
        )

        if not isinstance(
            metadata,
            dict,
        ):
            raise DBTArtifactError(
                "Invalid dbt run-result metadata."
            )

        invocation_id = (
            self._invocation_id(
                metadata
            )
        )

        elapsed_time = (
            self._duration(
                run_results.get(
                    "elapsed_time"
                ),
                field=(
                    "dbt elapsed time"
                ),
            )
        )

        return (
            DBTBuildArtifactSummary(
                invocation_id=(
                    invocation_id
                ),
                command=command,
                target_model_unique_id=(
                    target_unique_id
                ),
                target_model_name=(
                    model_name
                ),
                target_status=(
                    target_status
                ),
                target_execution_time_seconds=(
                    target_execution_time
                ),
                relation_schema=(
                    relation_schema
                ),
                relation_name=(
                    relation_name
                ),
                dependency_unique_ids=(
                    dependency_unique_ids
                ),
                executed_model_unique_ids=(
                    tuple(
                        executed_models
                    )
                ),
                tests=tuple(
                    test_results
                ),
                elapsed_time_seconds=(
                    elapsed_time
                ),
            )
        )