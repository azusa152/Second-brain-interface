import time
import uuid
from collections.abc import Callable
from typing import Any

from structlog.contextvars import bind_contextvars, clear_contextvars

from backend.logging_config import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_access_logger = get_logger("backend.access")


class RequestIDMiddleware:
    """Attach request_id to structlog contextvars and response headers."""

    def __init__(self, app: Callable[..., Any], header_name: str = REQUEST_ID_HEADER) -> None:
        self.app = app
        self.header_name = header_name
        self._header_name_bytes = header_name.lower().encode("latin-1")

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope.get("headers", []), self._header_name_bytes)
        scope["request_id"] = request_id
        clear_contextvars()
        bind_contextvars(request_id=request_id)

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(key.lower() == self._header_name_bytes for key, _ in headers):
                    headers.append((self._header_name_bytes, request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            clear_contextvars()

    @staticmethod
    def _resolve_request_id(headers: list[tuple[bytes, bytes]], header_name: bytes) -> str:
        for key, value in headers:
            if key.lower() != header_name:
                continue
            request_id = value.decode("latin-1", errors="ignore").strip()
            if request_id:
                return request_id
        return str(uuid.uuid4())


class AccessLogMiddleware:
    """Log one structured access event per HTTP request."""

    def __init__(
        self,
        app: Callable[..., Any],
        skip_paths: set[str] | None = None,
    ) -> None:
        self.app = app
        self.skip_paths = skip_paths or {"/health"}

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in self.skip_paths:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        request_id = scope.get("request_id")
        client = scope.get("client")
        client_ip = client[0] if isinstance(client, tuple) and client else None
        status_code = 500
        started_at = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            _access_logger.exception(
                "http_request_failed",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                client_ip=client_ip,
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            _access_logger.info(
                "http_request",
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                client_ip=client_ip,
            )
