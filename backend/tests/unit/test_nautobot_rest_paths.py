from __future__ import annotations

import unittest

from services.nautobot.common.rest import rest_paginate, rest_query


class RestQueryTests(unittest.TestCase):
    def test_names_with_ampersand_and_hash_are_quoted(self) -> None:
        query = rest_query(name="a&b#c d+e", limit=1)
        self.assertEqual(query, "name=a%26b%23c%20d%2Be&limit=1")


class _Api:
    def __init__(self, pages: dict[str, dict]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def rest_request(self, endpoint: str, method: str = "GET") -> dict:
        self.calls.append(endpoint)
        return self.pages[endpoint]


class RestPaginateTests(unittest.IsolatedAsyncioTestCase):
    async def test_follows_next_links(self) -> None:
        api = _Api(
            {
                "dcim/interfaces/?limit=2": {
                    "results": [{"id": 1}, {"id": 2}],
                    "next": "https://nb.example/api/dcim/interfaces/?limit=2&offset=2",
                },
                "dcim/interfaces/?limit=2&offset=2": {"results": [{"id": 3}], "next": None},
            }
        )
        results = await rest_paginate(api, "dcim/interfaces/?limit=2")
        self.assertEqual([r["id"] for r in results], [1, 2, 3])

    async def test_bounded(self) -> None:
        class Endless:
            calls = 0

            async def rest_request(self, endpoint: str, method: str = "GET") -> dict:
                self.calls += 1
                return {"results": [{}], "next": "https://nb/api/x/?offset=1"}

        api = Endless()
        results = await rest_paginate(api, "x/", max_pages=5)
        self.assertEqual(len(results), 5)
        self.assertEqual(api.calls, 5)


if __name__ == "__main__":
    unittest.main()
