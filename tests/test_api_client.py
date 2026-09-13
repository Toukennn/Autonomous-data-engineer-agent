import socket
import pytest
import requests
from pydantic import SecretStr

from utils.api_client import APIClient
from utils.exceptions import ExternalAPIError


@pytest.fixture
def api_client():
    """
    Create an isolated API client with small deterministic limits.
    """

    client = APIClient()

    client.timeout = 1

    client.max_response_bytes = 1_000
    client.max_total_response_bytes = 10_000

    client.max_pages = 10
    client.max_records = 100

    client.auth_token = None
    client.auth_header = "Authorization"
    client.auth_scheme = "Bearer"

    client.user_agent = (
        "autonomous-data-engineer-agent-test"
    )

    return client


# ============================================================
# URL VALIDATION
# ============================================================


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/data",
        "file:///tmp/data.json",
        "example.com/api",
        "",
    ],
)
def test_invalid_urls_are_rejected(
    api_client,
    url,
):
    with pytest.raises(
        ExternalAPIError
    ):
        api_client._validate_url(
            url
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api",
        "http://example.com/api",
    ],
)
def test_http_urls_are_allowed(
    api_client,
    url,
):
    api_client._validate_url(
        url
    )


# ============================================================
# AUTHENTICATION
# ============================================================


def test_headers_without_auth(
    api_client,
):
    headers = (
        api_client._build_headers(
            use_auth=False
        )
    )

    assert (
        headers["Accept"]
        == "application/json"
    )

    assert (
        "Authorization"
        not in headers
    )


def test_authentication_header(
    api_client,
):
    api_client.auth_token = SecretStr(
        "super-secret-token"
    )

    headers = (
        api_client._build_headers(
            use_auth=True
        )
    )

    assert (
        headers["Authorization"]
        == "Bearer super-secret-token"
    )


def test_authentication_without_token_is_rejected(
    api_client,
):
    api_client.auth_token = None

    with pytest.raises(
        ExternalAPIError
    ):
        api_client._build_headers(
            use_auth=True
        )


# ============================================================
# NESTED JSON PATHS
# ============================================================


def test_nested_json_path(
    api_client,
):
    payload = {
        "data": {
            "results": [
                {
                    "id": 1
                }
            ]
        }
    }

    result = (
        api_client._get_nested_value(
            payload,
            "data.results",
        )
    )

    assert result == [
        {
            "id": 1
        }
    ]


def test_missing_nested_path_returns_none(
    api_client,
):
    payload = {
        "data": {}
    }

    result = (
        api_client._get_nested_value(
            payload,
            "data.results",
        )
    )

    assert result is None


# ============================================================
# RECORD EXTRACTION
# ============================================================


def test_extract_records_from_results(
    api_client,
):
    payload = {
        "results": [
            {
                "id": 1
            },
            {
                "id": 2
            },
        ]
    }

    records = (
        api_client._extract_records(
            payload,
            "results",
        )
    )

    assert len(records) == 2

    assert records[0]["id"] == 1


def test_top_level_list_is_supported(
    api_client,
):
    payload = [
        {
            "id": 1
        },
        {
            "id": 2
        },
    ]

    records = (
        api_client._extract_records(
            payload,
            None,
        )
    )

    assert len(records) == 2


def test_non_object_records_are_rejected(
    api_client,
):
    payload = {
        "results": [
            "invalid",
            "records",
        ]
    }

    with pytest.raises(
        ExternalAPIError
    ):
        api_client._extract_records(
            payload,
            "results",
        )


# ============================================================
# REQUEST FAILURE HANDLING
# ============================================================


def test_timeout_becomes_external_api_error(
    api_client,
    monkeypatch,
):
    def fake_get(
        *args,
        **kwargs,
    ):
        raise requests.Timeout()

    monkeypatch.setattr(
        api_client.session,
        "get",
        fake_get,
    )

    with pytest.raises(
        ExternalAPIError,
        match="timed out",
    ):
        api_client._request_json(
            "https://example.com/api",
            {},
        )


def test_invalid_json_is_rejected(
    api_client,
    monkeypatch,
):
    class FakeResponse:
        status_code = 200
        headers = {}
        content = b"not-json"

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError(
                "Invalid JSON"
            )

    monkeypatch.setattr(
        api_client,
        "_validate_public_destination",
        lambda url: None,
    )

    monkeypatch.setattr(
        api_client.session,
        "get",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(
        ExternalAPIError,
        match="not valid JSON",
    ):
        api_client._request_json(
            "https://example.com/api",
            {},
        )

def test_large_response_is_rejected(
    api_client,
    monkeypatch,
):
    api_client.max_response_bytes = 3

    class FakeResponse:
        status_code = 200
        headers = {}
        content = b"1234"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": []
            }

    monkeypatch.setattr(
        api_client,
        "_validate_public_destination",
        lambda url: None,
    )

    monkeypatch.setattr(
        api_client.session,
        "get",
        lambda *args, **kwargs: FakeResponse(),
    )

    with pytest.raises(
        ExternalAPIError,
        match="per-page size limit",
    ):
        api_client._request_json(
            "https://example.com/api",
            {},
        )

# ============================================================
# PAGINATION
# ============================================================


def test_multiple_pages_are_combined(
    api_client,
    monkeypatch,
):
    responses = {
        "https://example.com/api": (
            {
                "results": [
                    {
                        "id": 1
                    }
                ],
                "next": (
                    "https://example.com/api?page=2"
                ),
            },
            100,
        ),
        "https://example.com/api?page=2": (
            {
                "results": [
                    {
                        "id": 2
                    }
                ],
                "next": None,
            },
            120,
        ),
    }

    def fake_request(
        url,
        headers,
    ):
        return responses[url]

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    result = (
        api_client.extract_records(
            "https://example.com/api"
        )
    )

    assert result.records == [
        {
            "id": 1
        },
        {
            "id": 2
        },
    ]

    assert (
        result.metadata["pages_fetched"]
        == 2
    )

    assert (
        result.metadata["records_extracted"]
        == 2
    )

    assert (
        result.metadata["bytes_downloaded"]
        == 220
    )


def test_relative_next_url_is_supported(
    api_client,
    monkeypatch,
):
    visited = []

    def fake_request(
        url,
        headers,
    ):
        visited.append(
            url
        )

        if len(visited) == 1:
            return (
                {
                    "results": [
                        {
                            "id": 1
                        }
                    ],
                    "next": "/api?page=2",
                },
                10,
            )

        return (
            {
                "results": [
                    {
                        "id": 2
                    }
                ],
                "next": None,
            },
            10,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    api_client.extract_records(
        "https://example.com/api"
    )

    assert visited == [
        "https://example.com/api",
        "https://example.com/api?page=2",
    ]


def test_pagination_can_be_disabled(
    api_client,
    monkeypatch,
):
    calls = 0

    def fake_request(
        url,
        headers,
    ):
        nonlocal calls

        calls += 1

        return (
            {
                "results": [
                    {
                        "id": 1
                    }
                ],
                "next": (
                    "https://example.com/page2"
                ),
            },
            10,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    result = (
        api_client.extract_records(
            "https://example.com/api",
            paginate=False,
        )
    )

    assert calls == 1

    assert len(
        result.records
    ) == 1


def test_pagination_loop_is_rejected(
    api_client,
    monkeypatch,
):
    def fake_request(
        url,
        headers,
    ):
        return (
            {
                "results": [
                    {
                        "id": 1
                    }
                ],
                "next": (
                    "https://example.com/api"
                ),
            },
            10,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    with pytest.raises(
        ExternalAPIError,
        match="Pagination loop",
    ):
        api_client.extract_records(
            "https://example.com/api"
        )


# ============================================================
# SAFETY LIMITS
# ============================================================


def test_max_pages_is_enforced(
    api_client,
    monkeypatch,
):
    api_client.max_pages = 1

    def fake_request(
        url,
        headers,
    ):
        return (
            {
                "results": [
                    {
                        "id": 1
                    }
                ],
                "next": (
                    "https://example.com/page2"
                ),
            },
            10,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    with pytest.raises(
        ExternalAPIError,
        match="maximum of 1 pages",
    ):
        api_client.extract_records(
            "https://example.com/api"
        )


def test_max_records_is_enforced(
    api_client,
    monkeypatch,
):
    api_client.max_records = 1

    def fake_request(
        url,
        headers,
    ):
        return (
            {
                "results": [
                    {
                        "id": 1
                    },
                    {
                        "id": 2
                    },
                ],
                "next": None,
            },
            10,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    with pytest.raises(
        ExternalAPIError,
        match="maximum of 1 records",
    ):
        api_client.extract_records(
            "https://example.com/api"
        )


def test_total_download_size_is_enforced(
    api_client,
    monkeypatch,
):
    api_client.max_total_response_bytes = 5

    def fake_request(
        url,
        headers,
    ):
        return (
            {
                "results": [],
                "next": None,
            },
            6,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    with pytest.raises(
        ExternalAPIError,
        match="total download-size limit",
    ):
        api_client.extract_records(
            "https://example.com/api"
        )


# ============================================================
# RETRY CONFIGURATION
# ============================================================


def test_retry_policy_is_configured(
    api_client,
):
    adapter = (
        api_client.session.get_adapter(
            "https://"
        )
    )

    retries = adapter.max_retries

    assert (
        429
        in retries.status_forcelist
    )

    assert (
        500
        in retries.status_forcelist
    )

    assert (
        "GET"
        in retries.allowed_methods
    )

    assert (
        retries.respect_retry_after_header
        is True
    )

def test_loopback_ip_is_rejected(
    api_client,
):
    with pytest.raises(
        ExternalAPIError
    ):
        api_client._validate_public_destination(
            "http://127.0.0.1/api"
        )


def test_private_ip_is_rejected(
    api_client,
):
    with pytest.raises(
        ExternalAPIError
    ):
        api_client._validate_public_destination(
            "http://192.168.1.10/api"
        )


def test_localhost_is_rejected(
    api_client,
):
    with pytest.raises(
        ExternalAPIError
    ):
        api_client._validate_public_destination(
            "http://localhost/api"
        )


def test_hostname_resolving_to_private_ip_is_rejected(
    api_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "utils.api_client.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (
                    "10.0.0.5",
                    443,
                ),
            )
        ],
    )

    with pytest.raises(
        ExternalAPIError
    ):
        api_client._validate_public_destination(
            "https://example.com/api"
        )


def test_authenticated_http_is_rejected(
    api_client,
):
    api_client.auth_token = SecretStr(
        "secret"
    )

    with pytest.raises(
        ExternalAPIError,
        match="requires HTTPS",
    ):
        api_client.extract_records(
            "http://example.com/api",
            use_auth=True,
        )


def test_authenticated_cross_origin_pagination_is_rejected(
    api_client,
    monkeypatch,
):
    api_client.auth_token = SecretStr(
        "secret"
    )

    def fake_request(
        url,
        headers,
    ):
        return (
            {
                "results": [
                    {
                        "id": 1
                    }
                ],
                "next": (
                    "https://evil.example/page2"
                ),
            },
            10,
        )

    monkeypatch.setattr(
        api_client,
        "_request_json",
        fake_request,
    )

    with pytest.raises(
        ExternalAPIError,
        match="another origin",
    ):
        api_client.extract_records(
            "https://example.com/api",
            use_auth=True,
        )