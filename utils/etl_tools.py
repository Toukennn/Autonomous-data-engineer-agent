import json
from pathlib import Path

import pandas as pd
import requests

from config.settings import get_runtime_settings
from models.schema import (
    CastColumnsOperation,
    DropColumnsOperation,
    DropDuplicatesOperation,
    FillMissingOperation,
    FilterRowsOperation,
    GroupByAggregateOperation,
    RenameColumnsOperation,
    SelectColumnsOperation,
    SortValuesOperation,
    StringTransformOperation,
    TransformPlan,
)
from utils.exceptions import (
    DatasetError,
    ExternalAPIError,
    UnsupportedFormatError,
)


class ETLTools:
    """
    Deterministic ETL operations used by the ETL agent.

    The LLM decides WHAT transformation should happen by generating
    a validated TransformPlan.

    This class controls HOW the transformation happens using a
    restricted set of deterministic Pandas operations.

    Arbitrary Python execution is intentionally not supported.
    """

    SUPPORTED_FORMATS = {
        "csv",
        "json",
        "parquet",
    }

    def __init__(self):
        """
        Load runtime configuration.
        """

        settings = get_runtime_settings()

        self.project_root = settings.project_root
        self.data_root = settings.data_root

        self.http_timeout = (
            settings.http_timeout_seconds
        )

        self.api_max_response_bytes = (
            settings.api_max_response_bytes
        )

    # ============================================================
    # PATH SAFETY
    # ============================================================

    def _resolve_data_path(
        self,
        path: str,
        must_exist: bool = False,
    ) -> Path:
        """
        Resolve a path while ensuring it remains inside
        the project's data directory.

        This prevents the ETL agent from accessing arbitrary
        files elsewhere on the machine.
        """

        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = (
                self.project_root
                / candidate
            )

        candidate = candidate.resolve()

        try:
            candidate.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "ETL file operations are restricted "
                "to the project's data directory."
            ) from exc

        if must_exist and not candidate.exists():
            raise DatasetError(
                f"Dataset does not exist: {candidate}"
            )

        return candidate

    # ============================================================
    # FORMAT VALIDATION
    # ============================================================

    def _validate_format(
        self,
        file_format: str,
    ) -> str:
        """
        Validate and normalize a dataset format.
        """

        normalized = (
            file_format
            .lower()
            .strip()
            .lstrip(".")
        )

        if normalized not in self.SUPPORTED_FORMATS:
            raise UnsupportedFormatError(
                f"Unsupported format: {file_format}. "
                f"Supported formats: "
                f"{sorted(self.SUPPORTED_FORMATS)}"
            )

        return normalized

    # ============================================================
    # DATAFRAME LOADING
    # ============================================================

    def _load_dataframe(
        self,
        file_path: str,
    ) -> pd.DataFrame:
        """
        Load a supported dataset from the project's data directory.
        """

        path = self._resolve_data_path(
            file_path,
            must_exist=True,
        )

        extension = (
            path.suffix
            .lower()
        )

        try:

            if extension == ".csv":
                return pd.read_csv(
                    path
                )

            if extension == ".json":

                try:
                    return pd.read_json(
                        path,
                        lines=True,
                    )

                except ValueError:
                    return pd.read_json(
                        path
                    )

            if extension == ".parquet":
                return pd.read_parquet(
                    path
                )

        except Exception as exc:
            raise DatasetError(
                f"Failed to load dataset: {path.name}"
            ) from exc

        raise UnsupportedFormatError(
            f"Unsupported input format: {extension}"
        )

    # ============================================================
    # DATAFRAME SAVING
    # ============================================================

    def _save_dataframe(
        self,
        dataframe: pd.DataFrame,
        file_path: Path,
        file_format: str,
    ) -> None:
        """
        Save a DataFrame using a supported output format.
        """

        file_format = self._validate_format(
            file_format
        )

        try:
            file_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if file_format == "csv":

                dataframe.to_csv(
                    file_path,
                    index=False,
                )

                return

            if file_format == "json":

                dataframe.to_json(
                    file_path,
                    orient="records",
                    lines=True,
                )

                return

            if file_format == "parquet":

                dataframe.to_parquet(
                    file_path,
                    index=False,
                )

                return

        except Exception as exc:
            raise DatasetError(
                f"Failed to save dataset to: {file_path}"
            ) from exc

    # ============================================================
    # API EXTRACTION
    # ============================================================

    def extract_load(
        self,
        url: str,
        output_folder: str,
        format: str,
    ) -> str:
        """
        Extract JSON data from an API endpoint and store it locally.

        Protections include:

        - HTTP timeout
        - response size limit
        - output path restriction
        - supported format validation
        """

        file_format = (
            self._validate_format(
                format
            )
        )

        output_directory = (
            self._resolve_data_path(
                output_folder
            )
        )

        try:
            response = requests.get(
                url,
                timeout=self.http_timeout,
            )

            response.raise_for_status()

        except requests.Timeout as exc:
            raise ExternalAPIError(
                "API request timed out after "
                f"{self.http_timeout} seconds."
            ) from exc

        except requests.RequestException as exc:
            raise ExternalAPIError(
                "API extraction request failed."
            ) from exc

        # --------------------------------------------------------
        # RESPONSE SIZE CHECK
        # --------------------------------------------------------

        content_length = (
            response.headers.get(
                "Content-Length"
            )
        )

        if content_length is not None:

            try:
                response_size = int(
                    content_length
                )

            except ValueError:
                response_size = None

            if (
                response_size is not None
                and response_size
                > self.api_max_response_bytes
            ):
                raise ExternalAPIError(
                    "API response exceeds the configured "
                    "maximum response size."
                )

        # Fallback in case Content-Length is missing or incorrect
        if (
            len(response.content)
            > self.api_max_response_bytes
        ):
            raise ExternalAPIError(
                "API response exceeds the configured "
                "maximum response size."
            )

        # --------------------------------------------------------
        # JSON PARSING
        # --------------------------------------------------------

        try:
            payload = response.json()

        except ValueError as exc:
            raise ExternalAPIError(
                "API response is not valid JSON."
            ) from exc

        # --------------------------------------------------------
        # COMMON API STRUCTURES
        # --------------------------------------------------------

        if (
            isinstance(payload, dict)
            and isinstance(
                payload.get("results"),
                list,
            )
        ):
            records = payload["results"]

        elif isinstance(
            payload,
            list,
        ):
            records = payload

        elif isinstance(
            payload,
            dict,
        ):
            records = [payload]

        else:
            raise ExternalAPIError(
                "API returned an unsupported JSON structure."
            )

        # --------------------------------------------------------
        # NORMALIZE
        # --------------------------------------------------------

        try:
            dataframe = pd.json_normalize(
                records
            )

        except Exception as exc:
            raise DatasetError(
                "Failed to convert API response "
                "into a tabular dataset."
            ) from exc

        output_file = (
            output_directory
            / f"extracted_data.{file_format}"
        )

        self._save_dataframe(
            dataframe=dataframe,
            file_path=output_file,
            file_format=file_format,
        )

        return (
            "Data successfully extracted.\n"
            f"Rows: {len(dataframe)}\n"
            f"Columns: {len(dataframe.columns)}\n"
            f"Output: {output_file}"
        )

    # ============================================================
    # DATASET CONTEXT
    # ============================================================

    def get_dataset_context(
        self,
        file_path: str,
    ) -> str:
        """
        Return metadata and a small sample for the ETL planner.

        The complete dataset is not sent to the LLM.
        """

        dataframe = (
            self._load_dataframe(
                file_path
            )
        )

        try:
            sample_json = (
                dataframe
                .head(5)
                .to_json(
                    orient="records",
                    date_format="iso",
                )
            )

            context = {
                "row_count": len(
                    dataframe
                ),
                "columns": list(
                    dataframe.columns
                ),
                "dtypes": {
                    column: str(dtype)
                    for column, dtype
                    in dataframe.dtypes.items()
                },
                "null_counts": {
                    column: int(count)
                    for column, count
                    in dataframe
                    .isnull()
                    .sum()
                    .items()
                },
                "sample_rows": (
                    json.loads(
                        sample_json
                    )
                ),
            }

            return json.dumps(
                context,
                indent=2,
                default=str,
            )

        except Exception as exc:
            raise DatasetError(
                "Failed to generate dataset context."
            ) from exc

    # ============================================================
    # COLUMN VALIDATION
    # ============================================================

    @staticmethod
    def _validate_columns(
        dataframe: pd.DataFrame,
        columns: list[str],
    ) -> None:
        """
        Ensure all requested columns exist.
        """

        missing = [
            column
            for column in columns
            if column not in dataframe.columns
        ]

        if missing:
            raise DatasetError(
                "Transformation references missing "
                f"columns: {missing}"
            )

    # ============================================================
    # FILTERING
    # ============================================================

    def _apply_filter(
        self,
        dataframe: pd.DataFrame,
        operation: FilterRowsOperation,
    ) -> pd.DataFrame:
        """
        Apply a validated row filter.
        """

        self._validate_columns(
            dataframe,
            [operation.column],
        )

        series = dataframe[
            operation.column
        ]

        operator = (
            operation.operator
        )

        value = (
            operation.value
        )

        try:

            if operator == "is_null":

                mask = series.isna()

            elif operator == "not_null":

                mask = series.notna()

            elif operator == "contains":

                if not isinstance(
                    value,
                    str,
                ):
                    raise DatasetError(
                        "'contains' requires "
                        "a string value."
                    )

                mask = (
                    series
                    .astype("string")
                    .str.contains(
                        value,
                        case=(
                            operation
                            .case_sensitive
                        ),
                        regex=False,
                        na=False,
                    )
                )

            elif operator in {
                "in",
                "not_in",
            }:

                if not isinstance(
                    value,
                    list,
                ):
                    raise DatasetError(
                        f"'{operator}' requires "
                        "a list value."
                    )

                mask = series.isin(
                    value
                )

                if operator == "not_in":
                    mask = ~mask

            elif operator == "eq":

                mask = (
                    series == value
                )

            elif operator == "ne":

                mask = (
                    series != value
                )

            elif operator == "gt":

                mask = (
                    series > value
                )

            elif operator == "gte":

                mask = (
                    series >= value
                )

            elif operator == "lt":

                mask = (
                    series < value
                )

            elif operator == "lte":

                mask = (
                    series <= value
                )

            else:
                raise DatasetError(
                    "Unsupported filter operator: "
                    f"{operator}"
                )

        except DatasetError:
            raise

        except Exception as exc:
            raise DatasetError(
                "Failed to apply filter on column "
                f"'{operation.column}'."
            ) from exc

        return dataframe.loc[
            mask
        ].copy()

    # ============================================================
    # TYPE CASTING
    # ============================================================

    def _cast_columns(
        self,
        dataframe: pd.DataFrame,
        operation: CastColumnsOperation,
    ) -> pd.DataFrame:
        """
        Safely cast selected columns.
        """

        self._validate_columns(
            dataframe,
            list(
                operation.dtypes.keys()
            ),
        )

        result = dataframe.copy()

        try:

            for column, target_type in (
                operation.dtypes.items()
            ):

                if target_type == "string":

                    result[column] = (
                        result[column]
                        .astype("string")
                    )

                elif target_type == "integer":

                    result[column] = (
                        pd.to_numeric(
                            result[column],
                            errors="raise",
                        )
                        .astype("Int64")
                    )

                elif target_type == "float":

                    result[column] = (
                        pd.to_numeric(
                            result[column],
                            errors="raise",
                        )
                        .astype(float)
                    )

                elif target_type == "datetime":

                    result[column] = (
                        pd.to_datetime(
                            result[column],
                            errors="raise",
                        )
                    )

                elif target_type == "category":

                    result[column] = (
                        result[column]
                        .astype("category")
                    )

                elif target_type == "boolean":

                    if (
                        pd.api.types
                        .is_bool_dtype(
                            result[column]
                        )
                    ):

                        result[column] = (
                            result[column]
                            .astype("boolean")
                        )

                    else:

                        normalized = (
                            result[column]
                            .astype("string")
                            .str.strip()
                            .str.lower()
                        )

                        mapping = {
                            "true": True,
                            "1": True,
                            "yes": True,
                            "false": False,
                            "0": False,
                            "no": False,
                        }

                        non_null_values = (
                            normalized
                            .dropna()
                        )

                        unknown = (
                            non_null_values[
                                ~non_null_values
                                .isin(mapping)
                            ]
                            .unique()
                        )

                        if len(
                            unknown
                        ) > 0:
                            raise DatasetError(
                                "Cannot safely convert "
                                f"'{column}' to boolean. "
                                "Unknown values: "
                                f"{list(unknown)}"
                            )

                        result[column] = (
                            normalized
                            .map(mapping)
                            .astype("boolean")
                        )

        except DatasetError:
            raise

        except Exception as exc:
            raise DatasetError(
                "Failed to cast one or more columns."
            ) from exc

        return result

    # ============================================================
    # APPLY ONE OPERATION
    # ============================================================

    def _apply_operation(
        self,
        dataframe: pd.DataFrame,
        operation,
    ) -> pd.DataFrame:
        """
        Apply one allowed transformation operation.
        """

        # --------------------------------------------------------
        # SELECT COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            SelectColumnsOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            return dataframe.loc[
                :,
                operation.columns,
            ].copy()

        # --------------------------------------------------------
        # DROP COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            DropColumnsOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            return dataframe.drop(
                columns=operation.columns
            )

        # --------------------------------------------------------
        # RENAME COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            RenameColumnsOperation,
        ):

            self._validate_columns(
                dataframe,
                list(
                    operation.mapping.keys()
                ),
            )

            return dataframe.rename(
                columns=operation.mapping
            )

        # --------------------------------------------------------
        # FILTER ROWS
        # --------------------------------------------------------

        if isinstance(
            operation,
            FilterRowsOperation,
        ):

            return self._apply_filter(
                dataframe,
                operation,
            )

        # --------------------------------------------------------
        # DROP DUPLICATES
        # --------------------------------------------------------

        if isinstance(
            operation,
            DropDuplicatesOperation,
        ):

            if operation.subset:

                self._validate_columns(
                    dataframe,
                    operation.subset,
                )

            return (
                dataframe
                .drop_duplicates(
                    subset=operation.subset,
                    keep=operation.keep,
                )
                .copy()
            )

        # --------------------------------------------------------
        # SORT VALUES
        # --------------------------------------------------------

        if isinstance(
            operation,
            SortValuesOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            return (
                dataframe
                .sort_values(
                    by=operation.columns,
                    ascending=(
                        operation.ascending
                    ),
                    kind="stable",
                )
                .copy()
            )

        # --------------------------------------------------------
        # FILL MISSING
        # --------------------------------------------------------

        if isinstance(
            operation,
            FillMissingOperation,
        ):

            self._validate_columns(
                dataframe,
                list(
                    operation.values.keys()
                ),
            )

            try:
                return dataframe.fillna(
                    value=operation.values
                )

            except Exception as exc:
                raise DatasetError(
                    "Failed to fill missing values."
                ) from exc

        # --------------------------------------------------------
        # CAST COLUMNS
        # --------------------------------------------------------

        if isinstance(
            operation,
            CastColumnsOperation,
        ):

            return self._cast_columns(
                dataframe,
                operation,
            )

        # --------------------------------------------------------
        # STRING TRANSFORMS
        # --------------------------------------------------------

        if isinstance(
            operation,
            StringTransformOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.columns,
            )

            result = dataframe.copy()

            try:

                for column in (
                    operation.columns
                ):

                    values = (
                        result[column]
                        .astype("string")
                    )

                    if (
                        operation.action
                        == "strip"
                    ):

                        values = (
                            values
                            .str.strip()
                        )

                    elif (
                        operation.action
                        == "lower"
                    ):

                        values = (
                            values
                            .str.lower()
                        )

                    elif (
                        operation.action
                        == "upper"
                    ):

                        values = (
                            values
                            .str.upper()
                        )

                    result[column] = values

            except Exception as exc:
                raise DatasetError(
                    "Failed to apply string "
                    "transformation."
                ) from exc

            return result

        # --------------------------------------------------------
        # GROUP BY / AGGREGATE
        # --------------------------------------------------------

        if isinstance(
            operation,
            GroupByAggregateOperation,
        ):

            self._validate_columns(
                dataframe,
                operation.group_by,
            )

            aggregation_columns = [
                item.column
                for item
                in operation.aggregations
            ]

            self._validate_columns(
                dataframe,
                aggregation_columns,
            )

            named_aggregations = {}

            for item in (
                operation.aggregations
            ):

                if (
                    item.alias
                    in named_aggregations
                ):
                    raise DatasetError(
                        "Duplicate aggregation alias: "
                        f"{item.alias}"
                    )

                named_aggregations[
                    item.alias
                ] = pd.NamedAgg(
                    column=item.column,
                    aggfunc=item.function,
                )

            try:
                return (
                    dataframe
                    .groupby(
                        operation.group_by,
                        dropna=False,
                    )
                    .agg(
                        **named_aggregations
                    )
                    .reset_index()
                )

            except Exception as exc:
                raise DatasetError(
                    "Failed to perform grouped "
                    "aggregation."
                ) from exc

        raise DatasetError(
            "Unsupported transformation operation: "
            f"{type(operation).__name__}"
        )

    # ============================================================
    # APPLY TRANSFORMATION PLAN
    # ============================================================

    def apply_transform_plan(
        self,
        dataframe: pd.DataFrame,
        plan: TransformPlan,
    ) -> pd.DataFrame:
        """
        Apply a validated sequence of deterministic transformations.
        """

        result = dataframe.copy()

        for index, operation in enumerate(
            plan.operations,
            start=1,
        ):

            try:
                result = (
                    self._apply_operation(
                        result,
                        operation,
                    )
                )

            except DatasetError as exc:
                raise DatasetError(
                    "Transformation failed at "
                    f"operation {index} "
                    f"({operation.type}): {exc}"
                ) from exc

        return result

    # ============================================================
    # TRANSFORM + LOAD
    # ============================================================

    def transform_load(
        self,
        input_file_path: str,
        output_folder: str,
        output_format: str,
        plan: TransformPlan,
    ) -> str:
        """
        Load a dataset, execute a validated transformation plan,
        and save the transformed result.
        """

        file_format = (
            self._validate_format(
                output_format
            )
        )

        dataframe = (
            self._load_dataframe(
                input_file_path
            )
        )

        original_rows = len(
            dataframe
        )

        original_columns = len(
            dataframe.columns
        )

        transformed = (
            self.apply_transform_plan(
                dataframe,
                plan,
            )
        )

        output_directory = (
            self._resolve_data_path(
                output_folder
            )
        )

        output_file = (
            output_directory
            / (
                "transformed_data."
                f"{file_format}"
            )
        )

        self._save_dataframe(
            dataframe=transformed,
            file_path=output_file,
            file_format=file_format,
        )

        return (
            "Transformation completed successfully.\n"
            f"Input rows: {original_rows}\n"
            f"Input columns: {original_columns}\n"
            f"Output rows: {len(transformed)}\n"
            f"Output columns: "
            f"{list(transformed.columns)}\n"
            f"Output file: {output_file}\n"
            f"Plan summary: {plan.summary}"
        )