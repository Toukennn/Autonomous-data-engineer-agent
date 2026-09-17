import os
import re
import threading
from contextlib import (
    contextmanager,
)
from dataclasses import (
    dataclass,
)
from pathlib import Path

from dbt.cli.main import (
    dbtRunner,
)

from utils.data_layers import (
    DataLayer,
    validate_dataset_name,
)
from utils.exceptions import (
    DBTExecutionError,
    DatasetError,
)


_DBT_EXECUTION_LOCK = (
    threading.Lock()
)


@dataclass(
    frozen=True
)
class DBTBuildResult:
    layer: DataLayer
    dataset_name: str
    model_name: str
    selector: str


class DBTExecutor:
    """
    Execute application-controlled dbt builds.

    Callers provide:
    - a validated logical dataset
    - a controlled medallion layer
    - a deterministic model name

    Callers cannot provide:
    - arbitrary dbt commands
    - arbitrary selectors
    - project directories
    - profiles directories
    - --vars
    - --full-refresh
    - shell arguments
    """

    MODEL_NAME_PATTERN = re.compile(
        r"^[a-z0-9_]+$"
    )

    POSTGRES_IDENTIFIER_MAX_BYTES = 63

    def __init__(
        self,
        *,
        dbt_project_dir: Path,
        db_config: dict,
        target_schema: str,
        threads: int,
        runner_factory=None,
    ):
        self.dbt_project_dir = (
            dbt_project_dir.resolve()
        )

        self.profiles_dir = (
            self.dbt_project_dir
        )

        self.db_config = dict(
            db_config
        )

        self.target_schema = (
            target_schema
        )

        self.threads = threads

        self._runner_factory = (
            runner_factory
            if runner_factory
            is not None
            else dbtRunner
        )

    # ============================================================
    # MODEL LOCATION
    # ============================================================

    def _model_directory(
        self,
        layer: DataLayer,
    ) -> Path:

        if layer == DataLayer.SILVER:
            directory = (
                self.dbt_project_dir
                / "models"
                / "staging"
                / "generated"
            )

        elif layer == DataLayer.GOLD:
            directory = (
                self.dbt_project_dir
                / "models"
                / "marts"
                / "generated"
            )

        else:
            raise DatasetError(
                "dbt execution supports "
                "Silver and Gold only."
            )

        directory = directory.resolve()

        try:
            directory.relative_to(
                self.dbt_project_dir
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt model directory escaped "
                "the configured dbt project."
            ) from exc

        return directory

    # ============================================================
    # MODEL VALIDATION
    # ============================================================

    @classmethod
    def _validate_model_name(
        cls,
        *,
        layer: DataLayer,
        model_name: str,
    ) -> None:

        if (
            not isinstance(
                model_name,
                str,
            )
            or not model_name
        ):
            raise DatasetError(
                "dbt model name must be "
                "a non-empty string."
            )

        if not (
            cls.MODEL_NAME_PATTERN
            .fullmatch(
                model_name
            )
        ):
            raise DatasetError(
                "Invalid dbt model name."
            )

        expected_prefix = (
            "stg_"
            if layer
            == DataLayer.SILVER
            else "mart_"
        )

        if not model_name.startswith(
            expected_prefix
        ):
            raise DatasetError(
                "dbt model does not match "
                "its requested medallion layer."
            )

        if (
            len(
                model_name.encode(
                    "utf-8"
                )
            )
            > cls.POSTGRES_IDENTIFIER_MAX_BYTES
        ):
            raise DatasetError(
                "dbt model name exceeds PostgreSQL's "
                "63-byte identifier limit."
            )

    def _require_model_file(
        self,
        *,
        layer: DataLayer,
        model_name: str,
    ) -> Path:

        directory = (
            self._model_directory(
                layer
            )
        )

        model_file = (
            directory
            / f"{model_name}.sql"
        ).resolve()

        try:
            model_file.relative_to(
                directory
            )

        except ValueError as exc:
            raise DatasetError(
                "dbt model path escaped "
                "its configured directory."
            ) from exc

        if (
            not model_file.exists()
            or not model_file.is_file()
        ):
            raise DatasetError(
                "Generated dbt model does "
                f"not exist: {model_name}"
            )

        return model_file

    # ============================================================
    # ENVIRONMENT
    # ============================================================

    @contextmanager
    def _dbt_environment(
        self,
    ):
        """
        Temporarily expose validated application
        database settings to profiles.yml.

        The previous process environment is restored
        after the dbt invocation.
        """

        values = {
            "DB_HOST": (
                str(
                    self.db_config[
                        "host"
                    ]
                )
            ),
            "DB_PORT": (
                str(
                    self.db_config[
                        "port"
                    ]
                )
            ),
            "DB_USER": (
                str(
                    self.db_config[
                        "user"
                    ]
                )
            ),
            "DB_PASSWORD": (
                str(
                    self.db_config[
                        "password"
                    ]
                )
            ),
            "DB_NAME": (
                str(
                    self.db_config[
                        "dbname"
                    ]
                )
            ),
            "DBT_TARGET_SCHEMA": (
                self.target_schema
            ),
            "DBT_THREADS": (
                str(
                    self.threads
                )
            ),
        }

        previous = {
            key: os.environ.get(
                key
            )
            for key in values
        }

        try:
            for key, value in (
                values.items()
            ):
                os.environ[
                    key
                ] = value

            yield

        finally:
            for key, value in (
                previous.items()
            ):
                if value is None:
                    os.environ.pop(
                        key,
                        None,
                    )

                else:
                    os.environ[
                        key
                    ] = value

    # ============================================================
    # BUILD
    # ============================================================

    def build_model(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        model_name: str,
    ) -> DBTBuildResult:
        """
        Execute one bounded dbt build.

        Silver:
            dbt build --select stg_<dataset>

        Gold:
            dbt build --select +mart_<dataset>

        Gold includes its ancestors so Silver quality
        tests can block the downstream Gold model.
        """

        if layer not in {
            DataLayer.SILVER,
            DataLayer.GOLD,
        }:
            raise DatasetError(
                "dbt execution supports "
                "Silver and Gold only."
            )

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        self._validate_model_name(
            layer=layer,
            model_name=model_name,
        )

        self._require_model_file(
            layer=layer,
            model_name=model_name,
        )

        selector = (
            model_name
            if layer
            == DataLayer.SILVER
            else f"+{model_name}"
        )

        cli_args = [
            "build",
            "--select",
            selector,
            "--project-dir",
            str(
                self.dbt_project_dir
            ),
            "--profiles-dir",
            str(
                self.profiles_dir
            ),
        ]

        # dbtRunner is not intended for concurrent
        # invocations inside one Python process.
        with _DBT_EXECUTION_LOCK:

            with self._dbt_environment():

                try:
                    runner = (
                        self._runner_factory()
                    )

                    result = (
                        runner.invoke(
                            cli_args
                        )
                    )

                except Exception as exc:
                    raise DBTExecutionError(
                        "dbt invocation failed "
                        "before completion.",
                        details={
                            "layer": (
                                layer.value
                            ),
                            "dataset": (
                                safe_dataset_name
                            ),
                            "model": model_name,
                            "failure_kind": (
                                "invocation_error"
                            ),
                            "exception_type": (
                                type(
                                    exc
                                ).__name__
                            ),
                        },
                    ) from None

        if not result.success:

            failure_kind = (
                "unhandled_error"
                if (
                    result.exception
                    is not None
                )
                else "build_failed"
            )

            raise DBTExecutionError(
                "dbt build did not "
                "complete successfully.",
                details={
                    "layer": (
                        layer.value
                    ),
                    "dataset": (
                        safe_dataset_name
                    ),
                    "model": (
                        model_name
                    ),
                    "failure_kind": (
                        failure_kind
                    ),
                },
            )

        return DBTBuildResult(
            layer=layer,
            dataset_name=(
                safe_dataset_name
            ),
            model_name=model_name,
            selector=selector,
        )