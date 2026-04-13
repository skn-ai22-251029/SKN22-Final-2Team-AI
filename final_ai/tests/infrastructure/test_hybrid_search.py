import unittest
from unittest.mock import patch

from final_ai.infrastructure.search import hybrid_search
from final_ai.infrastructure.search.hybrid_search import normalize_pet_species


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self.description = [
            ("goods_id",),
            ("goods_name",),
            ("pet_type",),
            ("category",),
            ("subcategory",),
            ("price",),
            ("thumbnail_url",),
            ("product_url",),
            ("brand_name",),
            ("discount_price",),
            ("popularity_score",),
            ("sentiment_avg",),
            ("repeat_rate",),
            ("health_concern_tags",),
            ("rating",),
            ("review_count",),
            ("main_ingredients",),
        ]
        self._results = [
            [
                (
                    "GI1",
                    "테스트 상품",
                    ["고양이"],
                    ["사료"],
                    ["전연령"],
                    10000,
                    "https://example.com/thumb.jpg",
                    "https://example.com/product",
                    "브랜드",
                    9000,
                    1.5,
                    0.3,
                    0.2,
                    ["소화"],
                    4.7,
                    15,
                    ["연어"],
                )
            ],
            [],
        ]

    def execute(self, query, params):
        self.executed.append((query, params))

    def fetchall(self):
        return self._results.pop(0)

    def close(self):
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        return None


class HybridSearchTests(unittest.TestCase):
    def test_normalize_pet_species_maps_known_values(self):
        self.assertEqual(normalize_pet_species("dog"), "강아지")
        self.assertEqual(normalize_pet_species("cat"), "고양이")
        self.assertEqual(normalize_pet_species("강아지"), "강아지")
        self.assertIsNone(normalize_pet_species("hamster"))

    def test_hybrid_search_queries_actual_review_metrics(self):
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)

        with (
            patch.object(hybrid_search, "embed_query", return_value=[0.1, 0.2]),
            patch.object(hybrid_search, "get_db_connection", return_value=connection),
        ):
            rows = hybrid_search.hybrid_search_pg("고양이 사료", pet_type="고양이", top_k=5)

        self.assertEqual(rows[0]["rating"], 4.7)
        self.assertEqual(rows[0]["review_count"], 15)
        self.assertEqual(rows[0]["goods_id"], "GI1")
        executed_sql = "\n".join(query for query, _ in cursor.executed)
        self.assertIn("AVG(score) AS actual_rating", executed_sql)
        self.assertIn("COUNT(review_id) AS actual_review_count", executed_sql)
        self.assertIn("review_stats.actual_rating AS rating", executed_sql)
