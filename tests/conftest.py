import pytest

from utils.etl_tools import ETLTools


@pytest.fixture
def isolated_etl_tools(tmp_path):
    """
    Create ETLTools configured to use a temporary data directory.

    Tests must never modify the project's real data directory.
    """

    data_root = tmp_path / "data"

    data_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    tools = ETLTools()

    tools.project_root = tmp_path
    tools.data_root = data_root.resolve()

    tools.http_timeout = 1
    tools.api_max_response_bytes = 1_000_000

    return tools