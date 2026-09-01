import unittest
from backend.app.intent_routing import preview_intent_route

class IntentRoutingTests(unittest.TestCase):
    def test_preview_explains_read_only_and_approval_routes(self):
        self.assertEqual(preview_intent_route("search current news")["intent"], "research")
        result = preview_intent_route("email a contact")
        self.assertTrue(result["approval_required"])
        self.assertEqual(result["risk_level"], "safe_write")
    def test_preview_is_bounded(self):
        with self.assertRaises(ValueError): preview_intent_route("")
