import unittest
import threading
import httpx
from scripts.nexus_tray import TrayCompanion, validate_url


class TrayTests(unittest.TestCase):
    def test_validates_local_or_https_url(self):
        self.assertEqual(validate_url("http://127.0.0.1:8000/"), "http://127.0.0.1:8000")
        with self.assertRaises(ValueError): validate_url("http://example.com")
    def test_reports_online_and_offline_states(self):
        online = TrayCompanion("https://nexus.example", httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))))
        self.assertEqual(online.status().state, "online")
        offline = TrayCompanion("https://nexus.example", httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request)))))
        self.assertEqual(offline.status().state, "offline")

    def test_refresh_loop_stops_cleanly(self):
        companion = TrayCompanion("https://nexus.example", httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))))
        stopped, updates = threading.Event(), []
        def update(status):
            updates.append(status.state)
            stopped.set()
        companion.refresh_loop(update, stopped, 0)
        self.assertEqual(updates, ["online"])
