import unittest

import httpx

from backend.app.integrations.web_research import WebResearchAdapter


class WebResearchTests(unittest.TestCase):
    def test_search_returns_bounded_structured_https_results(self):
        def handler(_):
            return httpx.Response(200, json={
                "Heading": "NEXUS",
                "AbstractText": "A structured result.",
                "AbstractURL": "https://example.com/nexus",
                "AbstractSource": "Example",
                "RelatedTopics": [{"Text": "Unsafe", "FirstURL": "http://example.com"}],
            })

        adapter = WebResearchAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
        result = adapter.search("NEXUS", 99)

        self.assertEqual(result["provider"], "duckduckgo")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://example.com/nexus")

    def test_news_parses_rss_without_fetching_article_pages(self):
        rss = b"""<rss><channel><item><title>Headline</title><link>https://news.example/story</link><description>Summary</description><source>Example News</source><pubDate>Tue, 28 Aug 2026 12:00:00 GMT</pubDate></item></channel></rss>"""
        adapter = WebResearchAdapter(httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=rss))))
        result = adapter.news("AI updates")

        self.assertEqual(result["provider"], "google_news_rss")
        self.assertEqual(result["results"][0]["source"], "Example News")
        self.assertTrue(result["results"][0]["published_at"].endswith("+00:00"))

    def test_rejects_short_or_overlong_queries(self):
        adapter = WebResearchAdapter(httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))))
        with self.assertRaises(ValueError):
            adapter.search("x")
        with self.assertRaises(ValueError):
            adapter.news("x" * 201)


if __name__ == "__main__":
    unittest.main()
