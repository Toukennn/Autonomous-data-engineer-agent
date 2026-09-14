import hashlib
import json
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path

from models.data_quality import (
    DataQualityContract,
)
from utils.data_layers import (
    DataLayer,
    validate_dataset_name,
)
from utils.exceptions import (
    DatasetError,
)


def quality_contract_fingerprint(
    contract: DataQualityContract,
) -> str:
    """
    Return a stable SHA-256 fingerprint for
    one validated data-quality contract.
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


class DataQualityContractStore:
    """
    Persistent deterministic store for
    dataset-specific quality contracts.
    """

    STORE_VERSION = 1

    def __init__(
        self,
        data_root: Path,
    ):
        self.data_root = (
            data_root.resolve()
        )

        self.contracts_root = (
            self.data_root
            / "_contracts"
        ).resolve()

        try:
            self.contracts_root.relative_to(
                self.data_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Quality-contract directory "
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
        layer: DataLayer,
        dataset_name: str,
    ) -> Path:
        """
        Resolve a quality-contract path from
        application-controlled layer and
        validated logical dataset name.
        """

        validated_name = (
            validate_dataset_name(
                dataset_name
            )
        )

        layer_directory = (
            self.contracts_root
            / layer.value
        ).resolve()

        contract_file = (
            layer_directory
            / f"{validated_name}.json"
        ).resolve()

        try:
            contract_file.relative_to(
                self.contracts_root
            )

        except ValueError as exc:
            raise DatasetError(
                "Quality-contract path escaped "
                "the contract directory."
            ) from exc

        return contract_file

    def _save_atomic(
        self,
        *,
        payload: dict,
        contract_file: Path,
    ) -> None:
        """
        Atomically persist a quality contract.
        """

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
                "data-quality contract."
            ) from exc

    def save(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
        contract: DataQualityContract,
    ) -> str:
        """
        Persist one validated quality contract.

        Returns its deterministic fingerprint.
        """

        contract_file = (
            self._resolve_contract_file(
                layer=layer,
                dataset_name=(
                    dataset_name
                ),
            )
        )

        fingerprint = (
            quality_contract_fingerprint(
                contract
            )
        )

        payload = {
            "store_version": (
                self.STORE_VERSION
            ),
            "layer": layer.value,
            "dataset": (
                validate_dataset_name(
                    dataset_name
                )
            ),
            "contract_fingerprint": (
                fingerprint
            ),
            "updated_at": (
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
        layer: DataLayer,
        dataset_name: str,
    ) -> DataQualityContract | None:
        """
        Load and validate one persisted quality
        contract.

        Returns None when no contract exists.
        """

        contract_file = (
            self._resolve_contract_file(
                layer=layer,
                dataset_name=(
                    dataset_name
                ),
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
                "data-quality contract."
            ) from exc

        if not isinstance(
            payload,
            dict,
        ):
            raise DatasetError(
                "Quality-contract document "
                "must be a JSON object."
            )

        if (
            payload.get(
                "store_version"
            )
            != self.STORE_VERSION
        ):
            raise DatasetError(
                "Unsupported quality-contract "
                "store version."
            )

        expected_dataset = (
            validate_dataset_name(
                dataset_name
            )
        )

        if (
            payload.get("layer")
            != layer.value
        ):
            raise DatasetError(
                "Quality-contract layer "
                "binding does not match "
                "the requested layer."
            )

        if (
            payload.get("dataset")
            != expected_dataset
        ):
            raise DatasetError(
                "Quality-contract dataset "
                "binding does not match "
                "the requested dataset."
            )

        raw_contract = payload.get(
            "contract"
        )

        if not isinstance(
            raw_contract,
            dict,
        ):
            raise DatasetError(
                "Quality-contract payload "
                "is missing or invalid."
            )

        try:
            contract = (
                DataQualityContract
                .model_validate(
                    raw_contract
                )
            )

        except Exception as exc:
            raise DatasetError(
                "Persisted data-quality "
                "contract is invalid."
            ) from exc

        actual_fingerprint = (
            quality_contract_fingerprint(
                contract
            )
        )

        stored_fingerprint = (
            payload.get(
                "contract_fingerprint"
            )
        )

        if (
            stored_fingerprint
            != actual_fingerprint
        ):
            raise DatasetError(
                "Persisted data-quality "
                "contract fingerprint "
                "does not match its content."
            )

        return contract

    def get_metadata(
        self,
        *,
        layer: DataLayer,
        dataset_name: str,
    ) -> dict | None:
        """
        Return safe persisted contract metadata
        without changing the contract.
        """

        contract_file = (
            self._resolve_contract_file(
                layer=layer,
                dataset_name=(
                    dataset_name
                ),
            )
        )

        if not contract_file.exists():
            return None

        # load() performs all integrity checks.
        contract = self.load(
            layer=layer,
            dataset_name=dataset_name,
        )

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
                "quality-contract metadata."
            ) from exc

        return {
            "store_version": (
                payload[
                    "store_version"
                ]
            ),
            "layer": payload["layer"],
            "dataset": (
                payload["dataset"]
            ),
            "contract_fingerprint": (
                payload[
                    "contract_fingerprint"
                ]
            ),
            "updated_at": (
                payload["updated_at"]
            ),
            "contract_name": (
                contract.name
            ),
            "contract_version": (
                contract
                .contract_version
            ),
            "rule_count": len(
                contract.rules
            ),
        }