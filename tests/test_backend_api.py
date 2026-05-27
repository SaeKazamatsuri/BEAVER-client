from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from services import backend_api


class BackendApiTests(unittest.TestCase):
    def test_build_ws_url_uses_client_websocket_route(self) -> None:
        with patch.object(
            backend_api,
            "BACKEND_CLIENT_WS_BASE_URL",
            "wss://api.example.test/client/ws",
        ):
            self.assertEqual(
                backend_api.build_ws_url("room 1"),
                "wss://api.example.test/client/ws?session=room%201",
            )

    def test_fetch_bootstrap_uses_client_bootstrap_route(self) -> None:
        response = Mock()
        response.status_code = 200
        response.reason = "OK"
        response.json.return_value = {
            "session": "demo",
            "messages": [],
        }

        with patch.object(backend_api.requests, "get", return_value=response) as get:
            session, messages = backend_api.fetch_bootstrap("demo")

        self.assertEqual(session, "demo")
        self.assertEqual(messages, [])
        get.assert_called_once()
        self.assertEqual(
            get.call_args.args[0],
            "https://api.beaver.works/api/client/bootstrap",
        )
        self.assertEqual(get.call_args.kwargs["params"], {"session": "demo"})


if __name__ == "__main__":
    unittest.main()
