import unittest
from unittest.mock import patch

from final_ai.infrastructure.repositories import product_repository


class _FakeCursor:
    def __init__(self, *, fetchall_result=None):
        self._fetchall_result = fetchall_result or []
        self.executed = []

    def execute(self, query, params):
        self.executed.append((query, params))

    def fetchall(self):
        return self._fetchall_result

    def close(self):
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, **kwargs):
        return self._cursor

    def close(self):
        return None


class ProductRepositoryTests(unittest.TestCase):
    def test_list_products_queries_actual_review_metrics(self):
        cursor = _FakeCursor(
            fetchall_result=[
                {
                    "goods_id": "GI1",
                    "goods_name": "테스트 상품",
                    "brand_name": "브랜드",
                    "price": 10000,
                    "discount_price": 9000,
                    "rating": 4.5,
                    "review_count": 12,
                    "thumbnail_url": "https://example.com/thumb.jpg",
                    "product_url": "https://example.com/product",
                    "soldout_yn": False,
                    "pet_type": ["고양이"],
                    "category": ["사료"],
                    "subcategory": ["전연령"],
                    "popularity_score": 2.4,
                    "sentiment_avg": 0.8,
                    "repeat_rate": 0.2,
                }
            ]
        )
        connection = _FakeConnection(cursor)

        with patch.object(product_repository, "get_db_connection", return_value=connection):
            rows = product_repository.list_products(query="사료", pet_type="고양이")

        self.assertEqual(rows[0]["rating"], 4.5)
        self.assertEqual(rows[0]["review_count"], 12)
        sql, params = cursor.executed[0]
        self.assertIn("AVG(score) AS actual_rating", sql)
        self.assertIn("COUNT(review_id) AS actual_review_count", sql)
        self.assertIn("COALESCE(review_stats.actual_review_count, 0) AS review_count", sql)
        self.assertIn("review_stats.actual_rating AS rating", sql)
        self.assertIn("고양이", params)

    def test_list_gp_products_queries_actual_review_metrics(self):
        cursor = _FakeCursor(
            fetchall_result=[
                {
                    "goods_id": "GP1",
                    "goods_name": "GP 상품",
                    "pet_type": ["강아지"],
                    "category": ["간식"],
                    "subcategory": ["덴탈"],
                    "price": 5000,
                    "thumbnail_url": "https://example.com/thumb.jpg",
                    "product_url": "https://example.com/product",
                    "brand_name": "브랜드",
                    "discount_price": 4500,
                    "popularity_score": 1.2,
                    "sentiment_avg": 0.3,
                    "repeat_rate": 0.1,
                    "health_concern_tags": ["치아"],
                    "rating": 4.8,
                    "review_count": 7,
                    "main_ingredients": ["연어"],
                }
            ]
        )
        connection = _FakeConnection(cursor)

        with patch.object(product_repository, "get_db_connection", return_value=connection):
            rows = product_repository.list_gp_products(pet_type="강아지", category="간식")

        self.assertEqual(rows[0]["rating"], 4.8)
        self.assertEqual(rows[0]["review_count"], 7)
        sql, params = cursor.executed[0]
        self.assertIn("AVG(score) AS actual_rating", sql)
        self.assertIn("COUNT(review_id) AS actual_review_count", sql)
        self.assertIn("review_stats.actual_rating AS rating", sql)
        self.assertIn("강아지", params)
