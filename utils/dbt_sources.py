import json
from pathlib import Path

from utils.data_layers import (
    DataLayer,
    validate_dataset_name,
)
from utils.exceptions import (
    DatasetError,
)


class DBTSourceRegistry:
    """
    Deterministically generate dbt Bronze source definitions
    from successful warehouse synchronization metadata.

    The LLM does not control:
    - source YAML paths
    - database schema
    - physical table names
    - source registration
    """

    SOURCE_FILE_NAME = (
        "bronze_sources.yml"
    )

    METADATA_VERSION = 1

    def __init__(
        self,
        *,
        data_root: Path,
        dbt_project_dir: Path,
    ):
        self.data_root = (
            data_root.resolve()
        )

        self.dbt_project_dir = (
            dbt_project_dir.resolve()
        )

        self.bronze_root = (
            self.data_root
            / DataLayer.BRONZE.value
        ).resolve()

        self.source_directory = (
            self.dbt_project_dir
            / "models"
            / "sources"
        ).resolve()

        self.source_file = (
            self.source_directory
            / self.SOURCE_FILE_NAME
        )

        try:
            self.bronze_root.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Bronze root escaped the "
                "configured data directory."
            ) from exc

        try:
            self.source_directory.relative_to(
                self.dbt_project_dir
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt source directory escaped "
                "the configured dbt project."
            ) from exc

    # ============================================================
    # METADATA LOADING
    # ============================================================

    def _load_sync_metadata(
        self,
        metadata_file: Path,
    ) -> dict:
        """
        Load and validate one successful Bronze
        warehouse synchronization record.
        """

        try:
            with metadata_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                metadata = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DatasetError(
                "Failed to load warehouse "
                "synchronization metadata."
            ) from exc

        if not isinstance(
            metadata,
            dict,
        ):
            raise DatasetError(
                "Warehouse synchronization metadata "
                "must be a JSON object."
            )

        if (
            metadata.get(
                "metadata_version"
            )
            != self.METADATA_VERSION
        ):
            raise DatasetError(
                "Unsupported warehouse synchronization "
                "metadata version."
            )

        dataset = metadata.get(
            "dataset"
        )

        if not isinstance(
            dataset,
            str,
        ):
            raise DatasetError(
                "Warehouse synchronization metadata "
                "contains an invalid dataset name."
            )

        safe_dataset = (
            validate_dataset_name(
                dataset
            )
        )

        if (
            metadata.get(
                "source_layer"
            )
            != DataLayer.BRONZE.value
        ):
            raise DatasetError(
                "dbt Bronze source metadata must "
                "originate from the Bronze layer."
            )

        if (
            metadata.get(
                "warehouse_schema"
            )
            != DataLayer.BRONZE.value
        ):
            raise DatasetError(
                "dbt Bronze sources must target "
                "the PostgreSQL Bronze schema."
            )

        if (
            metadata.get(
                "warehouse_table"
            )
            != safe_dataset
        ):
            raise DatasetError(
                "Warehouse table does not match "
                "the logical Bronze dataset."
            )

        fingerprint = metadata.get(
            "source_schema_fingerprint"
        )

        if (
            not isinstance(
                fingerprint,
                str,
            )
            or not fingerprint
        ):
            raise DatasetError(
                "Warehouse synchronization metadata "
                "is missing its schema fingerprint."
            )

        return metadata

    # ============================================================
    # DISCOVERY
    # ============================================================

    def _discover_sources(
        self,
    ) -> list[dict]:
        """
        Discover all successfully synchronized
        Bronze datasets.
        """

        if not self.bronze_root.exists():
            return []

        sources: list[
            dict
        ] = []

        for dataset_directory in (
            sorted(
                self.bronze_root.iterdir(),
                key=lambda path: (
                    path.name
                ),
            )
        ):
            if not dataset_directory.is_dir():
                continue

            metadata_file = (
                dataset_directory
                / "warehouse_sync_metadata.json"
            )

            if not metadata_file.exists():
                continue

            metadata = (
                self._load_sync_metadata(
                    metadata_file
                )
            )

            dataset = (
                validate_dataset_name(
                    metadata[
                        "dataset"
                    ]
                )
            )

            if (
                dataset_directory.name
                != dataset
            ):
                raise DatasetError(
                    "Warehouse synchronization metadata "
                    "does not match its Bronze "
                    "dataset directory."
                )

            sources.append(
                metadata
            )

        return sources

    # ============================================================
    # YAML GENERATION
    # ============================================================

    @staticmethod
    def _yaml_string(
        value: str,
    ) -> str:
        """
        JSON string syntax is valid YAML syntax.

        Using JSON escaping also prevents dataset names
        such as 'yes', dots, or hyphens from being
        misinterpreted as YAML primitives.
        """

        return json.dumps(
            value,
            ensure_ascii=False,
        )

    def _render_sources_yaml(
        self,
        sources: list[dict],
    ) -> str:
        """
        Render a deterministic dbt source properties file.
        """

        lines = [
            "version: 2",
            "",
            "sources:",
            '  - name: "bronze"',
            '    schema: "bronze"',
            (
                "    description: "
                '"Application-controlled Bronze '
                'warehouse sources."'
            ),
            "    quoting:",
            "      database: false",
            "      schema: false",
            "      identifier: true",
            "    tables:",
        ]

        if not sources:
            lines.append(
                "      []"
            )

        else:
            for metadata in sources:
                dataset = (
                    metadata[
                        "dataset"
                    ]
                )

                quoted_dataset = (
                    self._yaml_string(
                        dataset
                    )
                )

                lines.extend(
                    [
                        (
                            "      - name: "
                            f"{quoted_dataset}"
                        ),
                        (
                            "        description: "
                            + self._yaml_string(
                                "Bronze warehouse "
                                "representation of "
                                f"dataset '{dataset}'."
                            )
                        ),
                    ]
                )

        return (
            "\n".join(
                lines
            )
            + "\n"
        )

    # ============================================================
    # ATOMIC REGISTRY REFRESH
    # ============================================================

    def refresh_bronze_sources(
        self,
    ) -> Path:
        """
        Rebuild the dbt Bronze source registry from
        successful warehouse synchronization metadata.
        """

        sources = (
            self._discover_sources()
        )

        payload = (
            self._render_sources_yaml(
                sources
            )
        )

        temp_file = (
            self.source_file
            .with_name(
                ".bronze_sources.yml.tmp"
            )
        )

        try:
            self.source_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            temp_file.write_text(
                payload,
                encoding="utf-8",
            )

            temp_file.replace(
                self.source_file
            )

        except OSError as exc:
            try:
                if temp_file.exists():
                    temp_file.unlink()

            except OSError:
                pass

            raise DatasetError(
                "Failed to persist dbt "
                "Bronze source registry."
            ) from exc

        return self.source_file


    def get_registered_source(
        self,
        dataset_name: str,
    ) -> dict:
        """
        Return validated warehouse-sync metadata for one
        registered Bronze dbt source.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        for metadata in (
            self._discover_sources()
        ):
            if (
                metadata["dataset"]
                == safe_dataset_name
            ):
                return dict(
                    metadata
                )

        raise DatasetError(
            "Bronze dataset is not registered "
            f"as a dbt source: "
            f"{safe_dataset_name}"
        )