from __future__ import annotations

from collections import Counter
from time import monotonic


LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class TechnicalMetrics:
    """In-memory operational metrics with no user or message data in labels."""

    def __init__(self) -> None:
        self.started_at = monotonic()
        self.http_requests: Counter[tuple[str, str, int]] = Counter()
        self.http_latency: Counter[tuple[str, str, float]] = Counter()
        self.http_latency_count: Counter[tuple[str, str]] = Counter()
        self.http_latency_seconds: Counter[tuple[str, str]] = Counter()
        self.websocket_open_total = 0
        self.websocket_connections = 0

    def observe_http(self, method: str, route: str, status: int, seconds: float) -> None:
        labels = (method, route, status)
        self.http_requests[labels] += 1
        self.http_latency_count[(method, route)] += 1
        self.http_latency_seconds[(method, route)] += seconds
        for bucket in LATENCY_BUCKETS:
            if seconds <= bucket:
                self.http_latency[(method, route, bucket)] += 1

    def websocket_opened(self) -> None:
        self.websocket_open_total += 1
        self.websocket_connections += 1

    def websocket_closed(self) -> None:
        self.websocket_connections = max(0, self.websocket_connections - 1)

    def render_prometheus(self) -> str:
        lines = [
            "# HELP secure_messenger_uptime_seconds Process uptime in seconds.",
            "# TYPE secure_messenger_uptime_seconds gauge",
            f"secure_messenger_uptime_seconds {monotonic() - self.started_at:.3f}",
            "# HELP secure_messenger_http_requests_total Completed HTTP requests.",
            "# TYPE secure_messenger_http_requests_total counter",
        ]
        for (method, route, status), count in sorted(self.http_requests.items()):
            lines.append(
                "secure_messenger_http_requests_total"
                f'{{method="{_escape(method)}",route="{_escape(route)}",status="{status}"}} {count}'
            )
        lines.extend([
            "# HELP secure_messenger_http_request_duration_seconds_bucket HTTP request latency buckets.",
            "# TYPE secure_messenger_http_request_duration_seconds_bucket counter",
        ])
        for (method, route, bucket), count in sorted(self.http_latency.items()):
            lines.append(
                "secure_messenger_http_request_duration_seconds_bucket"
                f'{{method="{_escape(method)}",route="{_escape(route)}",le="{bucket}"}} {count}'
            )
        for (method, route), count in sorted(self.http_latency_count.items()):
            lines.append(
                "secure_messenger_http_request_duration_seconds_count"
                f'{{method="{_escape(method)}",route="{_escape(route)}"}} {count}'
            )
            lines.append(
                "secure_messenger_http_request_duration_seconds_sum"
                f'{{method="{_escape(method)}",route="{_escape(route)}"}} {self.http_latency_seconds[(method, route)]:.6f}'
            )
        lines.extend([
            "# HELP secure_messenger_websocket_connections Active authenticated WebSocket connections.",
            "# TYPE secure_messenger_websocket_connections gauge",
            f"secure_messenger_websocket_connections {self.websocket_connections}",
            "# HELP secure_messenger_websocket_open_total Accepted authenticated WebSocket connections.",
            "# TYPE secure_messenger_websocket_open_total counter",
            f"secure_messenger_websocket_open_total {self.websocket_open_total}",
        ])
        return "\n".join(lines) + "\n"
