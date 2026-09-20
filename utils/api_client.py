import ipaddress
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import (
    parse_qsl,
    urlencode,
    urljoin,
    urlparse,
)

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

        self.max_redirects = (
            settings.api_max_redirects
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

    @staticmethod
    def _origin(
        url: str,
    ) -> tuple[str, str, int]:
        """
        Return a normalized URL origin:
        scheme, hostname, port.
        """

        parsed = urlparse(
            url
        )

        hostname = (
            parsed.hostname or ""
        ).lower()

        if parsed.port is not None:
            port = parsed.port

        elif parsed.scheme == "https":
            port = 443

        else:
            port = 80

        return (
            parsed.scheme.lower(),
            hostname,
            port,
        )


    @staticmethod
    def _is_unsafe_ip(
        address: ipaddress.IPv4Address
        | ipaddress.IPv6Address,
    ) -> bool:
        """
        Reject non-public network destinations.
        """

        return (
            not address.is_global
            or address.is_multicast
            or address.is_unspecified
            or address.is_loopback
            or address.is_link_local
        )


    def _validate_public_destination(
        self,
        url: str,
    ) -> None:
        """
        Prevent API ingestion from reaching local/private networks.
        """

        parsed = urlparse(
            url
        )

        hostname = parsed.hostname

        if not hostname:
            raise ExternalAPIError(
                "API URL does not contain a valid hostname."
            )

        normalized_hostname = (
            hostname.lower()
        )

        if (
            normalized_hostname == "localhost"
            or normalized_hostname.endswith(
                ".localhost"
            )
        ):
            raise ExternalAPIError(
                "Localhost API destinations are not allowed."
            )

        # --------------------------------------------------------
        # Literal IP address
        # --------------------------------------------------------

        try:
            literal_ip = ipaddress.ip_address(
                normalized_hostname
            )

        except ValueError:
            literal_ip = None

        if literal_ip is not None:

            if self._is_unsafe_ip(
                literal_ip
            ):
                raise ExternalAPIError(
                    "Private or local network API "
                    "destinations are not allowed."
                )

            return

        # --------------------------------------------------------
        # DNS hostname
        # --------------------------------------------------------

        try:
            resolved = socket.getaddrinfo(
                normalized_hostname,
                parsed.port
                or (
                    443
                    if parsed.scheme == "https"
                    else 80
                ),
                type=socket.SOCK_STREAM,
            )

        except socket.gaierror as exc:
            raise ExternalAPIError(
                "API hostname could not be resolved."
            ) from exc

        addresses = set()

        for result in resolved:

            raw_address = (
                result[4][0]
                .split("%", 1)[0]
            )

            addresses.add(
                ipaddress.ip_address(
                    raw_address
                )
            )

        if not addresses:
            raise ExternalAPIError(
                "API hostname did not resolve "
                "to an IP address."
            )

        for address in addresses:

            if self._is_unsafe_ip(
                address
            ):
                raise ExternalAPIError(
                    "API hostname resolves to a private "
                    "or local network destination."
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

    @staticmethod
    def _add_query_parameter(
        url: str,
        name: str,
        value: str | int | float,
    ) -> str:
        """
        Add or replace one query parameter in a URL.

        Existing query parameters are preserved.
        """

        if not name.strip():
            raise ExternalAPIError(
                "Incremental API parameter name cannot be empty."
            )

        parsed = urlparse(
            url
        )

        query_parameters = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        # Remove an existing copy of the same parameter.
        query_parameters = [
            (
                parameter_name,
                parameter_value,
            )
            for (
                parameter_name,
                parameter_value,
            )
            in query_parameters
            if parameter_name != name
        ]

        query_parameters.append(
            (
                name,
                str(value),
            )
        )

        query = urlencode(
            query_parameters
        )

        return parsed._replace(
            query=query
        ).geturl()


    def _calculate_next_watermark(
        self,
        records: list[dict[str, Any]],
        watermark_field: str,
        previous_watermark: (
            str
            | int
            | float
            | None
        ),
    ) -> str | int | float | None:
        """
        Calculate the highest watermark contained in extracted records.

        Supported watermark types:

        - integers
        - floats
        - strings

        String watermarks should use a naturally sortable format,
        such as ISO-8601 timestamps.
        """

        # No new records means the checkpoint must not move.
        if not records:
            return previous_watermark

        values: list[
            str
            | int
            | float
        ] = []

        for record in records:

            value = self._get_nested_value(
                record,
                watermark_field,
            )

            # Every incremental record must have the watermark.
            # Ignoring missing values could permanently skip records.
            if value is None:
                raise ExternalAPIError(
                    "Incremental record does not contain "
                    f"watermark field '{watermark_field}'."
                )

            if isinstance(
                value,
                bool,
            ):
                raise ExternalAPIError(
                    "Boolean values cannot be used "
                    "as incremental watermarks."
                )

            if not isinstance(
                value,
                (
                    str,
                    int,
                    float,
                ),
            ):
                raise ExternalAPIError(
                    "Incremental watermark values must be "
                    "strings or numbers."
                )

            values.append(
                value
            )

        numeric_values = all(
            isinstance(
                value,
                (
                    int,
                    float,
                ),
            )
            and not isinstance(
                value,
                bool,
            )
            for value in values
        )

        string_values = all(
            isinstance(
                value,
                str,
            )
            for value in values
        )

        if not (
            numeric_values
            or string_values
        ):
            raise ExternalAPIError(
                "Incremental watermark values must "
                "have a consistent type."
            )

        next_watermark = max(
            values
        )

        # ------------------------------------------------------------
        # Prevent checkpoint regression
        # ------------------------------------------------------------

        if previous_watermark is not None:

            previous_is_numeric = (
                isinstance(
                    previous_watermark,
                    (
                        int,
                        float,
                    ),
                )
                and not isinstance(
                    previous_watermark,
                    bool,
                )
            )

            previous_is_string = isinstance(
                previous_watermark,
                str,
            )

            if (
                numeric_values
                and not previous_is_numeric
            ):
                raise ExternalAPIError(
                    "Previous incremental watermark type "
                    "does not match extracted records."
                )

            if (
                string_values
                and not previous_is_string
            ):
                raise ExternalAPIError(
                    "Previous incremental watermark type "
                    "does not match extracted records."
                )

            if (
                next_watermark
                < previous_watermark
            ):
                raise ExternalAPIError(
                    "Incremental watermark moved backwards."
                )

        return next_watermark

    # ============================================================
    # REQUEST
    # ============================================================

    def _request_json(
        self,
        url: str,
        headers: dict[str, str],
    ) -> tuple[Any, int]:

        current_url = url

        original_origin = (
            self._origin(
                url
            )
        )

        authenticated = (
            self.auth_header
            in headers
        )

        for redirect_count in range(
            self.max_redirects + 1
        ):

            self._validate_url(
                current_url
            )

            self._validate_public_destination(
                current_url
            )

            try:
                response = self.session.get(
                    current_url,
                    headers=headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )

            except requests.Timeout as exc:
                raise ExternalAPIError(
                    "API request timed out."
                ) from exc

            except requests.RequestException as exc:
                raise ExternalAPIError(
                    f"API request failed: {exc}"
                ) from exc

            # ----------------------------------------------------
            # SAFE REDIRECT HANDLING
            # ----------------------------------------------------

            if response.status_code in {
                301,
                302,
                303,
                307,
                308,
            }:

                location = (
                    response.headers.get(
                        "Location"
                    )
                )

                if not location:
                    raise ExternalAPIError(
                        "API returned a redirect "
                        "without a Location header."
                    )

                if (
                    redirect_count
                    >= self.max_redirects
                ):
                    raise ExternalAPIError(
                        "API exceeded the configured "
                        "redirect limit."
                    )

                redirected_url = urljoin(
                    current_url,
                    location,
                )

                self._validate_url(
                    redirected_url
                )

                if (
                    authenticated
                    and self._origin(
                        redirected_url
                    )
                    != original_origin
                ):
                    raise ExternalAPIError(
                        "Authenticated API requests "
                        "cannot redirect to another origin."
                    )

                current_url = (
                    redirected_url
                )

                continue

            # ----------------------------------------------------
            # HTTP STATUS
            # ----------------------------------------------------

            try:
                response.raise_for_status()

            except requests.RequestException as exc:
                raise ExternalAPIError(
                    f"API request failed: {exc}"
                ) from exc

            # ----------------------------------------------------
            # RESPONSE SIZE
            # ----------------------------------------------------

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

            # ----------------------------------------------------
            # JSON
            # ----------------------------------------------------

            try:
                payload = (
                    response.json()
                )

            except ValueError as exc:
                raise ExternalAPIError(
                    "API response is not valid JSON."
                ) from exc

            return (
                payload,
                body_size,
            )

        raise ExternalAPIError(
            "API exceeded the configured redirect limit."
        )

    def discover_records_path(
        self,
        url: str,
        *,
        max_depth: int = 4,
    ) -> str | None:
        """
        Inspect one public JSON response for a collection
        of record objects using the normal API safeguards.

        None selects a top-level list or a single object.
        """
        headers = self._build_headers(
            use_auth=False
        )
        payload, _ = self._request_json(
            url,
            headers,
        )

        if isinstance(payload, list):
            if not payload:
                raise ExternalAPIError(
                    "API returned an empty record collection."
                )
            if not all(
                isinstance(record, dict)
                for record in payload
            ):
                raise ExternalAPIError(
                    "Top-level API records must be JSON objects."
                )
            return None

        if not isinstance(payload, dict):
            raise ExternalAPIError(
                "API must return a JSON object or "
                "a list of JSON objects."
            )

        candidates: list[str] = []

        def walk(
            value: Any,
            path: str,
            depth: int,
        ) -> None:
            if depth > max_depth:
                return

            if isinstance(value, list):
                if value and all(
                    isinstance(record, dict)
                    for record in value
                ):
                    candidates.append(path)
                return

            if isinstance(value, dict):
                for key, nested_value in value.items():
                    nested_path = (
                        f"{path}.{key}"
                        if path
                        else key
                    )
                    walk(
                        nested_value,
                        nested_path,
                        depth + 1,
                    )

        walk(payload, "", 0)

        # The extractor treats a plain JSON object as one record.
        if not candidates:
            return None

        preferred_names = [
            "results",
            "data",
            "items",
            "records",
            "rows",
            "entries",
        ]

        def candidate_score(path: str) -> tuple[int, int, str]:
            final_name = path.split(".")[-1].lower()
            try:
                priority = preferred_names.index(final_name)
            except ValueError:
                priority = len(preferred_names)
            return (
                priority,
                path.count("."),
                path,
            )

        candidates.sort(key=candidate_score)

        if len(candidates) > 1:
            first_score = candidate_score(candidates[0])[:2]
            second_score = candidate_score(candidates[1])[:2]
            if first_score == second_score:
                raise ExternalAPIError(
                    "API contains multiple possible "
                    "record collections and cannot be "
                    "resolved safely."
                )

        return candidates[0]

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
        watermark_param: str | None = None,
        watermark_field: str | None = None,
        watermark_value: (
            str
            | int
            | float
            | None
        ) = None,
    ) -> APIExtractionResult:
        """
        Extract records from one or more API pages.

        Features:
        - optional pagination
        - configurable record path
        - configurable next-page path
        - optional authentication
        - HTTPS enforcement for authenticated requests
        - same-origin protection for authenticated pagination
        - pagination-loop detection
        - page-count limit
        - record-count limit
        - total download-size limit
        - extraction metadata

        The default paths support APIs such as PokéAPI:

            {
                "results": [...],
                "next": "https://..."
            }
        """

        # ========================================================
        # INITIAL URL VALIDATION
        # ========================================================

        self._validate_url(
            url
        )

        # ========================================================
        # INCREMENTAL INGESTION VALIDATION
        # ========================================================

        incremental_enabled = any(
            value is not None
            for value in (
                watermark_param,
                watermark_field,
                watermark_value,
            )
        )

        if incremental_enabled:

            if (
                watermark_param is None
                or not watermark_param.strip()
            ):
                raise ExternalAPIError(
                    "Incremental extraction requires "
                    "a watermark parameter."
                )

            if (
                watermark_field is None
                or not watermark_field.strip()
            ):
                raise ExternalAPIError(
                    "Incremental extraction requires "
                    "a watermark field."
                )

        # Authenticated API traffic must never use plain HTTP.
        if (
            use_auth
            and urlparse(url).scheme.lower()
            != "https"
        ):
            raise ExternalAPIError(
                "Authenticated API extraction requires HTTPS."
            )

        initial_origin = (
            self._origin(
                url
            )
        )

        # ========================================================
        # EXTRACTION START
        # ========================================================

        started_at = datetime.now(
            timezone.utc
        )

        headers = self._build_headers(
            use_auth=use_auth
        )

        # ========================================================
        # BUILD INITIAL REQUEST URL
        # ========================================================

        initial_request_url = url

        if (
            incremental_enabled
            and watermark_value is not None
        ):
            initial_request_url = (
                self._add_query_parameter(
                    url=url,
                    name=watermark_param,
                    value=watermark_value,
                )
            )

        current_url = initial_request_url

        visited_urls: set[str] = set()

        all_records: list[
            dict[str, Any]
        ] = []

        pages_fetched = 0
        bytes_downloaded = 0

        # ========================================================
        # PAGINATION LOOP
        # ========================================================

        while current_url:

            # ----------------------------------------------------
            # Detect pagination cycles
            # ----------------------------------------------------

            if current_url in visited_urls:
                raise ExternalAPIError(
                    "Pagination loop detected."
                )

            # ----------------------------------------------------
            # Enforce maximum page count
            # ----------------------------------------------------

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

            # ----------------------------------------------------
            # Fetch one page
            # ----------------------------------------------------

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

            # ----------------------------------------------------
            # Total download-size protection
            # ----------------------------------------------------

            if (
                bytes_downloaded
                > self.max_total_response_bytes
            ):
                raise ExternalAPIError(
                    "API extraction exceeded the configured "
                    "total download-size limit."
                )

            # ----------------------------------------------------
            # Extract records
            # ----------------------------------------------------

            records = self._extract_records(
                payload,
                records_path,
            )

            all_records.extend(
                records
            )

            # ----------------------------------------------------
            # Record-count protection
            # ----------------------------------------------------

            if (
                len(all_records)
                > self.max_records
            ):
                raise ExternalAPIError(
                    "API extraction exceeded the configured "
                    f"maximum of {self.max_records} records."
                )

            # ----------------------------------------------------
            # Stop after first page if pagination is disabled
            # ----------------------------------------------------

            if not paginate:
                break

            # ----------------------------------------------------
            # Resolve next-page URL
            # ----------------------------------------------------

            next_url = (
                self._get_nested_value(
                    payload,
                    next_path,
                )
            )

            # No next page means extraction is complete.
            if not next_url:
                break

            if not isinstance(
                next_url,
                str,
            ):
                raise ExternalAPIError(
                    "Pagination next value must be a URL string."
                )

            resolved_next_url = urljoin(
                current_url,
                next_url,
            )

            self._validate_url(
                resolved_next_url
            )

            # ----------------------------------------------------
            # Protect authenticated pagination
            # ----------------------------------------------------
            #
            # Without this check, an API could return:
            #
            #     "next": "https://evil.example/page2"
            #
            # and our Authorization header could otherwise be sent
            # to that new host.
            # ----------------------------------------------------

            if (
                use_auth
                and self._origin(
                    resolved_next_url
                )
                != initial_origin
            ):
                raise ExternalAPIError(
                    "Authenticated pagination cannot "
                    "continue to another origin."
                )

            current_url = (
                resolved_next_url
            )

        # ========================================================
        # EXTRACTION COMPLETE
        # ========================================================

        completed_at = datetime.now(
            timezone.utc
        )

        initial_request_url = url

        next_watermark = None

        if incremental_enabled:
            next_watermark = (
                self._calculate_next_watermark(
                    records=all_records,
                    watermark_field=watermark_field,
                    previous_watermark=watermark_value,
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
            "records_path": (
                records_path
            ),
            "next_path": (
                next_path
            ),
            "authenticated": (
                use_auth
            ),
            "started_at": (
                started_at.isoformat()
            ),
            "completed_at": (
                completed_at.isoformat()
            ),
            "incremental_enabled": (
                incremental_enabled
            ),
            "watermark_param": (
                watermark_param
            ),
            "watermark_field": (
                watermark_field
            ),
            "previous_watermark": (
                watermark_value
            ),
            "next_watermark": (
                next_watermark
            ),
        }

        return APIExtractionResult(
            records=all_records,
            metadata=metadata,
        )