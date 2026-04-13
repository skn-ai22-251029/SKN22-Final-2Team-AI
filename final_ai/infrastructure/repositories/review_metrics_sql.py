ACTUAL_REVIEW_METRICS_COLUMNS = (
    "review_stats.actual_rating AS rating, "
    "COALESCE(review_stats.actual_review_count, 0) AS review_count"
)

ACTUAL_REVIEW_METRICS_JOIN = """
LEFT JOIN (
    SELECT
        product_id,
        COUNT(review_id) AS actual_review_count,
        AVG(score) AS actual_rating
    FROM review
    GROUP BY product_id
) review_stats
ON review_stats.product_id = product.goods_id
"""
