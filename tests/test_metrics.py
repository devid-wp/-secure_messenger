import unittest

from app.core.metrics import TechnicalMetrics


class TechnicalMetricsTests(unittest.TestCase):
    def test_metrics_use_route_templates_without_payloads(self) -> None:
        metrics = TechnicalMetrics()
        metrics.observe_http(
            "POST",
            "/api/v1/chats/{chat_id}/envelopes",
            201,
            0.1,
        )
        rendered = metrics.render_prometheus()
        self.assertIn('route="/api/v1/chats/{chat_id}/envelopes"', rendered)
        self.assertNotIn("ciphertext", rendered)
        self.assertNotIn("message text", rendered)

    def test_websocket_gauge_cannot_become_negative(self) -> None:
        metrics = TechnicalMetrics()
        metrics.websocket_closed()
        metrics.websocket_opened()
        metrics.websocket_closed()
        self.assertIn("secure_messenger_websocket_connections 0", metrics.render_prometheus())
