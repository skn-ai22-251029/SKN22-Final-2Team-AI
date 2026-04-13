import psycopg2.extras

from final_ai.infrastructure.db.connection import get_db_connection
from final_ai.infrastructure.repositories.product_filters import build_product_filter_clauses
from final_ai.infrastructure.repositories.review_metrics_sql import (
    ACTUAL_REVIEW_METRICS_COLUMNS,
    ACTUAL_REVIEW_METRICS_JOIN,
)


def list_products(
    *,
    pet_type: str | list[str] | None = None,
    category: str | list[str] | None = None,
    subcategory: str | list[str] | None = None,
    brand: str | None = None,
    budget: int | None = None,
    query: str | None = None,
    include_soldout: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        filters = ["goods_name NOT ILIKE '%%샘플%%'"]
        params: list[object] = []

        if not include_soldout:
            filters.append("soldout_yn = FALSE")
        common_filters, common_params = build_product_filter_clauses(
            pet_type=pet_type,
            category=category,
            subcategory=subcategory,
            budget=budget,
        )
        filters.extend(common_filters)
        params.extend(common_params)
        if brand:
            filters.append("brand_name ILIKE %s")
            params.append(f"%{brand}%")
        if query:
            filters.append("(goods_name ILIKE %s OR brand_name ILIKE %s)")
            like = f"%{query}%"
            params.extend([like, like])

        sql = (
            "SELECT goods_id, goods_name, brand_name, price, discount_price, "
            f"{ACTUAL_REVIEW_METRICS_COLUMNS}, "
            "thumbnail_url, product_url, soldout_yn, pet_type, category, subcategory, "
            "popularity_score, sentiment_avg, repeat_rate "
            "FROM product "
            f"{ACTUAL_REVIEW_METRICS_JOIN} "
            "WHERE " + " AND ".join(filters) + " "
            "ORDER BY popularity_score DESC NULLS LAST, review_count DESC NULLS LAST, goods_id ASC "
            "LIMIT %s OFFSET %s"
        )
        cur.execute(sql, params + [limit, offset])
        return list(cur.fetchall())
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


def list_gp_products(
    *,
    pet_type: str | list[str] | None = None,
    category: str | list[str] | None = None,
    subcategory: str | list[str] | None = None,
    goods_name_include: str | None = None,
    goods_name_exclude: str | None = None,
    exclude_goods_ids: set[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        filters = [
            "goods_id LIKE 'GP%%'",
            "goods_name NOT ILIKE '%%샘플%%'",
        ]
        params: list[object] = []

        common_filters, common_params = build_product_filter_clauses(
            pet_type=pet_type,
            category=category,
            subcategory=subcategory,
        )
        filters.extend(common_filters)
        params.extend(common_params)

        if goods_name_include:
            filters.append("goods_name ILIKE %s")
            params.append(f"%{goods_name_include}%")
        if goods_name_exclude:
            filters.append("goods_name NOT ILIKE %s")
            params.append(f"%{goods_name_exclude}%")

        sql = (
            "SELECT goods_id, goods_name, pet_type, category, subcategory, "
            "price, thumbnail_url, product_url, brand_name, discount_price, "
            "popularity_score, sentiment_avg, repeat_rate, health_concern_tags, "
            f"{ACTUAL_REVIEW_METRICS_COLUMNS}, main_ingredients "
            "FROM product "
            f"{ACTUAL_REVIEW_METRICS_JOIN} "
            "WHERE " + " AND ".join(filters) + " "
            "ORDER BY popularity_score DESC NULLS LAST, review_count DESC NULLS LAST "
            "LIMIT %s"
        )
        cur.execute(sql, params + [limit])
        rows = list(cur.fetchall())

        if not exclude_goods_ids:
            return rows

        return [row for row in rows if row["goods_id"] not in exclude_goods_ids]
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
