import pytest

from utils.etl_tools import ETLTools

from utils.lineage import LineageStore

from utils.data_quality_contracts import (
    DataQualityContractStore,
)

from utils.business_keys import (
    BusinessKeyContractStore,
)

@pytest.fixture
def isolated_etl_tools(tmp_path):
    """
    Create ETLTools configured to use a temporary data directory.

    Tests must never modify the project's real data directory.
    """

    data_root = (
        tmp_path
        / "data"
    )

    data_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    tools = ETLTools()

    tools.project_root = tmp_path
    tools.data_root = (
        data_root.resolve()
    )

    # Rebind components whose paths were created
    # during ETLTools.__init__().
    tools.lineage_store = (
        LineageStore(
            tools.data_root
        )
    )

    tools.quality_contract_store = (
        DataQualityContractStore(
            tools.data_root
        )
    )

    tools.business_key_contract_store = (
        BusinessKeyContractStore(
            tools.data_root
        )
    )

    tools.http_timeout = 1
    tools.api_max_response_bytes = (
        1_000_000
    )

    return tools