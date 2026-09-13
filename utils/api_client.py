from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import get_runtime_settings
from utils.exceptions import ExternalAPIError


@dataclass(frozen=True)
class APIExtractionResult:
    """
    Records and metadata produced by one API extraction run.
    """

    records: list[dict[str, Any]]
    metadata: dict[str, Any]


class APIClient:
    """
    Resilient HTTP client for API ingestion.

    Responsibilities:

    - HTTP requests
    - retries
    - exponential backoff
    - rate-limit handling
    - pagination
    - response-size limits
    - optional authentication
    - extraction metadata
    """

    RETRYABLE_STATUS_CODES = (
        429,
        500,
        502,
        503,
        504,
    )

    def __init__(self):
        settings = get_runtime_settings()

        self.timeout = (
            settings.http_timeout_seconds
        )

        self.max_response_bytes = (
            settings.api_max_response_bytes
        )

        self.max_total_response_bytes = (
            settings.api_max_total_response_bytes
        )

        self.max_pages = (
            settings.api_max_pages
        )

        self.max_records = (
            settings.api_max_records
        )

        self.auth_token = (
            settings.api_auth_token
        )

        self.auth_header = (
            settings.api_auth_header
        )

        self.auth_scheme = (
            settings.api_auth_scheme
        )

        self.user_agent = (
            settings.api_user_agent
        )

        retry_strategy = Retry(
            total=settings.api_retry_total,
            connect=settings.api_retry_total,
            read=settings.api_retry_total,
            status=settings.api_retry_total,
            backoff_factor=(
                settings.api_retry_backoff_seconds
            ),
            status_forcelist=(
                self.RETRYABLE_STATUS_CODES
            ),
            allowed_methods=frozenset(
                {"GET"}
            ),
            respect_retry_after_header=True,
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry_strategy
        )

        self.session = requests.Session()

        self.session.mount(
            "https://",
            adapter,
        )

        self.session.mount(
            "http://",
            adapter,
        )

    # ============================================================
    # URL VALIDATION
    # ============================================================

    @staticmethod
    def _validate_url(
        url: str,
    ) -> None:
        """
        Basic URL validation.

        More advanced private-network / SSRF protection will be
        added separately.
        """

        parsed = urlparse(
            url
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            raise ExternalAPIError(
                "Only HTTP and HTTPS API URLs are allowed."
            )

        if not parsed.netloc:
            raise ExternalAPIError(
                "API URL must contain a valid hostname."
            )

    # ============================================================
    # HEADERS / AUTH
    # ============================================================

    def _build_headers(
        self,
        use_auth: bool,
    ) -> dict[str, str]:

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        if not use_auth:
            return headers

        if self.auth_token is None:
            raise ExternalAPIError(
                "Authenticated API extraction was requested "
                "but API_AUTH_TOKEN is not configured."
            )

        token = (
            self.auth_token
            .get_secret_value()
        )

        if self.auth_scheme:
            value = (
                f"{self.auth_scheme} {token}"
            )

        else:
            value = token

        headers[
            self.auth_header
        ] = value

        return headers

    # ============================================================
    # NESTED JSON PATH
    # ============================================================

    @staticmethod
    def _get_nested_value(
        payload: Any,
        path: str | None,
    ) -> Any:
        """
        Resolve simple dotted JSON paths such as:

        data.results
        pagination.next
        """

        if path is None or path == "":
            return payload

        current = payload

        for key in path.split("."):

            if not isinstance(
                current,
                dict,
            ):
                return None

            current = current.get(
                key
            )

            if current is None:
                return None

        return current

    # ============================================================
    # REQUEST
    # ============================================================

    def _request_json(
        self,
        url: str,
        headers: dict[str, str],
    ) -> tuple[Any, int]:

        self._validate_url(
            url
        )

        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
            )

            response.raise_for_status()

        except requests.Timeout as exc:
            raise ExternalAPIError(
                "API request timed out."
            ) from exc

        except requests.RequestException as exc:
            raise ExternalAPIError(
                f"API request failed: {exc}"
            ) from exc

        content_length = (
            response.headers.get(
                "Content-Length"
            )
        )

        if content_length:

            try:
                declared_size = int(
                    content_length
                )

            except ValueError:
                declared_size = None

            if (
                declared_size is not None
                and declared_size
                > self.max_response_bytes
            ):
                raise ExternalAPIError(
                    "API response exceeded the configured "
                    "per-page size limit."
                )

        body_size = len(
            response.content
        )

        if (
            body_size
            > self.max_response_bytes
        ):
            raise ExternalAPIError(
                "API response exceeded the configured "
                "per-page size limit."
            )

        try:
            payload = response.json()

        except ValueError as exc:
            raise ExternalAPIError(
                "API response is not valid JSON."
            ) from exc

        return (
            payload,
            body_size,
        )

    # ============================================================
    # RECORD EXTRACTION
    # ============================================================

    def _extract_records(
        self,
        payload: Any,
        records_path: str | None,
    ) -> list[dict[str, Any]]:

        if isinstance(
            payload,
            list,
        ):
            records = payload

        elif isinstance(
            payload,
            dict,
        ):

            extracted = (
                self._get_nested_value(
                    payload,
                    records_path,
                )
            )

            # Preserve the old behavior for APIs that return
            # one object rather than a results list.
            if extracted is None:
                records = [
                    payload
                ]

            elif isinstance(
                extracted,
                list,
            ):
                records = extracted

            elif isinstance(
                extracted,
                dict,
            ):
                records = [
                    extracted
                ]

            else:
                raise ExternalAPIError(
                    "The configured records path does not "
                    "contain an object or list of objects."
                )

        else:
            raise ExternalAPIError(
                "API returned an unsupported JSON structure."
            )

        invalid_records = [
            record
            for record in records
            if not isinstance(
                record,
                dict,
            )
        ]

        if invalid_records:
            raise ExternalAPIError(
                "API records must be JSON objects."
            )

        return records

    # ============================================================
    # PAGINATED EXTRACTION
    # ============================================================

    def extract_records(
        self,
        url: str,
        *,
        paginate: bool = True,
        records_path: str | None = "results",
        next_path: str | None = "next",
        use_auth: bool = False,
    ) -> APIExtractionResult:
        """
        Extract records from one or more API pages.

        The default paths support APIs such as PokéAPI:

            {
                "results": [...],
                "next": "https://..."
            }
        """

        started_at = (
            datetime.now(
                timezone.utc
            )
        )

        headers = (
            self._build_headers(
                use_auth=use_auth
            )
        )

        current_url = url

        visited_urls: set[str] = set()

        all_records: list[
            dict[str, Any]
        ] = []

        pages_fetched = 0
        bytes_downloaded = 0

        while current_url:

            if current_url in visited_urls:
                raise ExternalAPIError(
                    "Pagination loop detected."
                )

            if (
                pages_fetched
                >= self.max_pages
            ):
                raise ExternalAPIError(
                    "API pagination exceeded the configured "
                    f"maximum of {self.max_pages} pages."
                )

            visited_urls.add(
                current_url
            )

            payload, page_bytes = (
                self._request_json(
                    current_url,
                    headers,
                )
            )

            pages_fetched += 1

            bytes_downloaded += (
                page_bytes
            )

            if (
                bytes_downloaded
                > self.max_total_response_bytes
            ):
                raise ExternalAPIError(
                    "API extraction exceeded the configured "
                    "total download-size limit."
                )

            records = (
                self._extract_records(
                    payload,
                    records_path,
                )
            )

            all_records.extend(
                records
            )

            if (
                len(all_records)
                > self.max_records
            ):
                raise ExternalAPIError(
                    "API extraction exceeded the configured "
                    f"maximum of {self.max_records} records."
                )

            if not paginate:
                break

            next_url = (
                self._get_nested_value(
                    payload,
                    next_path,
                )
            )

            if not next_url:
                break

            if not isinstance(
                next_url,
                str,
            ):
                raise ExternalAPIError(
                    "Pagination next value must be a URL string."
                )

            current_url = urljoin(
                current_url,
                next_url,
            )

        completed_at = (
            datetime.now(
                timezone.utc
            )
        )

        metadata = {
            "source_url": url,
            "pages_fetched": pages_fetched,
            "records_extracted": len(
                all_records
            ),
            "bytes_downloaded": (
                bytes_downloaded
            ),
            "pagination_enabled": (
                paginate
            ),
            "records_path": records_path,
            "next_path": next_path,
            "authenticated": use_auth,
            "started_at": (
                started_at.isoformat()
            ),
            "completed_at": (
                completed_at.isoformat()
            ),
        }

        return APIExtractionResult(
            records=all_records,
            metadata=metadata,
        )