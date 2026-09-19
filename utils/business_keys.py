import hashlib
import json

from datetime import (
    datetime,
    timezone,
)

from pathlib import Path

import pandas as pd

from models.warehouse_keys import (
    BusinessKeyContract,
)

from utils.data_layers import (
    validate_dataset_name,
)

from utils.exceptions import (
    BusinessKeyError,
    DatasetError,
)


def business_key_fingerprint(
    contract: BusinessKeyContract,
) -> str:
    """
    Return a stable SHA-256 fingerprint for
    one validated business-key contract.
    """

    canonical = json.dumps(
        contract.model_dump(
            mode="json"
        ),
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()


def validate_business_key(
    *,
    dataframe: pd.DataFrame,
    contract: BusinessKeyContract,
) -> dict[str, object]:
    """
    Deterministically validate one DataFrame
    against a business-key contract.

    Requirements:

    - every key column exists
    - key values are non-null
    - composite key tuples are unique

    Row values are never included in errors.
    """

    if not isinstance(
        dataframe,
        pd.DataFrame,
    ):
        raise DatasetError(
            "Business-key validation "
            "requires a Pandas DataFrame."
        )

    key_columns = tuple(
        contract.columns
    )

    missing_columns = [
        column
        for column
        in key_columns
        if column
        not in dataframe.columns
    ]

    if missing_columns:
        raise BusinessKeyError(
            "Dataset is missing required "
            "business-key columns.",
            details={
                "key_columns": list(
                    key_columns
                ),
                "missing_columns": (
                    missing_columns
                ),
                "row_count": len(
                    dataframe
                ),
            },
        )

    if dataframe.empty:
        return {
            "key_columns": list(
                key_columns
            ),
            "row_count": 0,
            "unique_key_count": 0,
            "null_key_row_count": 0,
            "duplicate_key_row_count": 0,
        }

    key_frame = dataframe.loc[
        :,
        list(
            key_columns
        ),
    ]

    null_mask = (
        key_frame
        .isna()
        .any(
            axis=1
        )
    )

    null_key_row_count = int(
        null_mask.sum()
    )

    if null_key_row_count:
        raise BusinessKeyError(
            "Dataset contains null "
            "business-key values.",
            details={
                "key_columns": list(
                    key_columns
                ),
                "row_count": len(
                    dataframe
                ),
                "null_key_row_count": (
                    null_key_row_count
                ),
            },
        )

    duplicate_mask = (
        dataframe
        .duplicated(
            subset=list(
                key_columns
            ),
            keep=False,
        )
    )

    duplicate_key_row_count = int(
        duplicate_mask.sum()
    )

    if duplicate_key_row_count:
        raise BusinessKeyError(
            "Dataset contains duplicate "
            "business-key values.",
            details={
                "key_columns": list(
                    key_columns
                ),
                "row_count": len(
                    dataframe
                ),
                "duplicate_key_row_count": (
                    duplicate_key_row_count
                ),
            },
        )

    unique_key_count = int(
        key_frame
        .drop_duplicates()
        .shape[0]
    )

    return {
        "key_columns": list(
            key_columns
        ),
        "row_count": len(
            dataframe
        ),
        "unique_key_count": (
            unique_key_count
        ),
        "null_key_row_count": 0,
        "duplicate_key_row_count": 0,
    }


class BusinessKeyContractStore:
    """
    Persistent deterministic store for
    warehouse business-key contracts.

    Business-key bindings are immutable by
    default because changing a key changes
    the meaning of row identity.
    """

    STORE_VERSION = 1

    def __init__(
        self,
        data_root: Path,
    ):
        self.data_root = (
            data_root.resolve()
        )

        self.keys_root = (
            self.data_root
            / "_warehouse_keys"
        ).resolve()

        try:
            self.keys_root.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Business-key directory "
                "escaped the configured "
                "data directory."
            ) from exc

    @staticmethod
    def _utc_now() -> str:
        return (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

    def _resolve_contract_file(
        self,
        *,
        dataset_name: str,
    ) -> Path:

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        contract_file = (
            self.keys_root
            / f"{safe_dataset_name}.json"
        ).resolve()

        try:
            contract_file.relative_to(
                self.keys_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Business-key contract path "
                "escaped the configured "
                "business-key directory."
            ) from exc

        return contract_file

    def _save_atomic(
        self,
        *,
        payload: dict,
        contract_file: Path,
    ) -> None:

        temp_file = (
            contract_file
            .with_name(
                f".{contract_file.name}.tmp"
            )
        )

        try:
            contract_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with temp_file.open(
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    indent=2,
                    ensure_ascii=False,
                )

            temp_file.replace(
                contract_file
            )

        except (
            OSError,
            TypeError,
            ValueError,
        ) as exc:

            try:
                if temp_file.exists():
                    temp_file.unlink()

            except OSError:
                pass

            raise DatasetError(
                "Failed to persist "
                "business-key contract."
            ) from exc

    def save(
        self,
        *,
        dataset_name: str,
        contract: BusinessKeyContract,
    ) -> str:
        """
        Persist a business-key contract.

        Saving the same contract again is
        idempotent.

        Rebinding an existing dataset to a
        different key is rejected.
        """

        safe_dataset_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        contract_file = (
            self._resolve_contract_file(
                dataset_name=(
                    safe_dataset_name
                )
            )
        )

        fingerprint = (
            business_key_fingerprint(
                contract
            )
        )

        if contract_file.exists():

            existing_contract = (
                self.load(
                    dataset_name=(
                        safe_dataset_name
                    )
                )
            )

            if (
                existing_contract
                is None
            ):
                raise DatasetError(
                    "Existing business-key "
                    "contract could not "
                    "be loaded."
                )

            existing_fingerprint = (
                business_key_fingerprint(
                    existing_contract
                )
            )

            if (
                existing_fingerprint
                != fingerprint
            ):
                raise DatasetError(
                    "Business-key contract "
                    "already exists for this "
                    "dataset and cannot be "
                    "changed automatically."
                )

            return fingerprint

        payload = {
            "store_version": (
                self.STORE_VERSION
            ),
            "dataset": (
                safe_dataset_name
            ),
            "contract_fingerprint": (
                fingerprint
            ),
            "created_at": (
                self._utc_now()
            ),
            "contract": (
                contract.model_dump(
                    mode="json"
                )
            ),
        }

        self._save_atomic(
            payload=payload,
            contract_file=(
                contract_file
            ),
        )

        return fingerprint

    def load(
        self,
        *,
        dataset_name: str,
    ) -> BusinessKeyContract | None:

        contract_file = (
            self._resolve_contract_file(
                dataset_name=(
                    dataset_name
                )
            )
        )

        if not contract_file.exists():
            return None

        try:
            with contract_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                payload = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DatasetError(
                "Failed to load "
                "business-key contract."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise DatasetError(
                "Business-key contract "
                "document must be a "
                "JSON object."
            )

        if (
            payload.get(
                "store_version"
            )
            != self.STORE_VERSION
        ):
            raise DatasetError(
                "Unsupported business-key "
                "store version."
            )

        expected_dataset = (
            validate_dataset_name(
                dataset_name
            )
        )

        if (
            payload.get(
                "dataset"
            )
            != expected_dataset
        ):
            raise DatasetError(
                "Business-key dataset "
                "binding does not match "
                "the requested dataset."
            )

        raw_contract = (
            payload.get(
                "contract"
            )
        )

        if not isinstance(
            raw_contract,
            dict,
        ):
            raise DatasetError(
                "Business-key contract "
                "payload is missing "
                "or invalid."
            )

        try:
            contract = (
                BusinessKeyContract
                .model_validate(
                    raw_contract
                )
            )

        except Exception as exc:
            raise DatasetError(
                "Persisted business-key "
                "contract is invalid."
            ) from exc

        actual_fingerprint = (
            business_key_fingerprint(
                contract
            )
        )

        if (
            payload.get(
                "contract_fingerprint"
            )
            != actual_fingerprint
        ):
            raise DatasetError(
                "Persisted business-key "
                "contract fingerprint "
                "does not match its content."
            )

        return contract

    def get_metadata(
        self,
        *,
        dataset_name: str,
    ) -> dict | None:

        contract_file = (
            self._resolve_contract_file(
                dataset_name=(
                    dataset_name
                )
            )
        )

        if not contract_file.exists():
            return None

        contract = self.load(
            dataset_name=(
                dataset_name
            )
        )

        if contract is None:
            return None

        try:
            with contract_file.open(
                "r",
                encoding="utf-8",
            ) as file:
                payload = json.load(
                    file
                )

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:
            raise DatasetError(
                "Failed to load "
                "business-key metadata."
            ) from exc

        return {
            "store_version": (
                payload[
                    "store_version"
                ]
            ),
            "dataset": (
                payload[
                    "dataset"
                ]
            ),
            "contract_fingerprint": (
                payload[
                    "contract_fingerprint"
                ]
            ),
            "created_at": (
                payload[
                    "created_at"
                ]
            ),
            "contract_version": (
                contract
                .contract_version
            ),
            "key_columns": list(
                contract.columns
            ),
            "key_column_count": len(
                contract.columns
            ),
        }