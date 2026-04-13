import re

from final_ai.infrastructure.db.connection import get_db_connection
from final_ai.infrastructure.embedding.fastembed_client import embed_query
from final_ai.infrastructure.observability import get_logger
from final_ai.infrastructure.repositories.product_filters import build_product_filter_clauses
from final_ai.infrastructure.repositories.review_metrics_sql import (
    ACTUAL_REVIEW_METRICS_COLUMNS,
    ACTUAL_REVIEW_METRICS_JOIN,
)

logger = get_logger(__name__)

_PET_SPECIES_KR = {
    "dog": "강아지",
    "cat": "고양이",
    "강아지": "강아지",
    "고양이": "고양이",
}

_SEARCH_STOPWORDS = {
    "추천",
    "추천해줘",
    "추천해주세요",
    "추천해",
    "알려줘",
    "알려주세요",
    "좋은",
    "좋아요",
    "우리",
    "아이",
    "반려동물",
    "반려견",
    "반려묘",
}

_TOKEN_SUFFIXES = (
    "추천해주세요",
    "추천해줘",
    "알려주세요",
    "알려줘",
    "입니다",
    "이에요",
    "예요",
    "에요",
    "으로",
    "에서",
    "한테",
    "용",
    "에",
    "의",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "과",
    "와",
    "도",
    "로",
)


def normalize_pet_species(species: str | list[str] | None) -> str | None:
    if not species:
        return None
    
    # 리스트인 경우 첫 번째 요소 사용
    if isinstance(species, list):
        if not species:
            return None
        species = species[0]
        
    val = str(species).strip().lower()
    return _PET_SPECIES_KR.get(val) or _PET_SPECIES_KR.get(str(species).strip())


def _extract_search_terms(query: str, *extra_terms: str | None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add_token(raw: str):
        token = raw.strip()
        if not token or token in _SEARCH_STOPWORDS:
            return
        if token not in seen:
            seen.add(token)
            terms.append(token)

    for source in (query, *extra_terms):
        if not source:
            continue
        for raw in re.findall(r"[0-9A-Za-z가-힣/]+", str(source)):
            for piece in (piece for piece in raw.split("/") if piece):
                add_token(piece)
                for suffix in _TOKEN_SUFFIXES:
                    if len(piece) <= len(suffix) + 1:
                        continue
                    if piece.endswith(suffix):
                        trimmed = piece[: -len(suffix)].strip()
                        if len(trimmed) >= 2:
                            add_token(trimmed)
    return terms


def hybrid_search_pg(
    query: str,
    top_k: int = 20,
    pet_type: str | list[str] | None = None,
    category: str | list[str] | None = None,
    subcategory: str | list[str] | None = None,
    health_concerns: str | list[str] | None = None,
    brand: str | None = None,
    exclude_brands: str | list[str] | None = None,
    exclude_categories: str | list[str] | None = None,
    exclude_subcategories: str | list[str] | None = None,
    exclude_health_concerns: str | list[str] | None = None,
    exclude_goods_ids: str | list[str] | None = None,
    budget: int | None = None,
    allowed_goods_ids: list[str] | None = None,
) -> list[dict]:
    query_vec = embed_query(query)
    pet_type_kr = normalize_pet_species(pet_type) or pet_type
    rrf_k = 60

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        vec_sql = """
            SELECT goods_id, goods_name, pet_type, category, subcategory,
                   price, thumbnail_url, product_url, brand_name, discount_price,
                   popularity_score, sentiment_avg, repeat_rate, health_concern_tags,
                   """ + ACTUAL_REVIEW_METRICS_COLUMNS + """, main_ingredients
            FROM product
            """ + ACTUAL_REVIEW_METRICS_JOIN + """
            WHERE 1=1 {filters}
            ORDER BY embedding <=> %s::vector
            LIMIT 100
        """
        keyword_sql = """
            SELECT goods_id, goods_name, pet_type, category, subcategory,
                   price, thumbnail_url, product_url, brand_name, discount_price,
                   popularity_score, sentiment_avg, repeat_rate, health_concern_tags,
                   """ + ACTUAL_REVIEW_METRICS_COLUMNS + """, main_ingredients
            FROM product
            """ + ACTUAL_REVIEW_METRICS_JOIN + """
            WHERE search_vector @@ plainto_tsquery('simple', %s) {filters}
            ORDER BY ts_rank(search_vector, plainto_tsquery('simple', %s)) DESC
            LIMIT 100
        """

        filter_parts = [
            "AND goods_name NOT ILIKE '%%샘플%%'",
            "AND goods_id NOT LIKE 'GP%%'",
        ]
        common_filters, filter_params_shared = build_product_filter_clauses(
            pet_type=pet_type_kr,
            category=category,
            subcategory=subcategory,
            health_concerns=health_concerns,
            brand=brand,
            exclude_brands=exclude_brands,
            exclude_categories=exclude_categories,
            exclude_subcategories=exclude_subcategories,
            exclude_health_concerns=exclude_health_concerns,
            exclude_goods_ids=exclude_goods_ids,
            budget=budget,
            allowed_goods_ids=allowed_goods_ids,
        )
        filter_parts.extend(f"AND {clause}" for clause in common_filters)

        filter_str = " ".join(filter_parts)

        cols = []
        vec_rows = []
        if query_vec is not None:
            cur.execute(vec_sql.format(filters=filter_str), filter_params_shared + [query_vec])
            cols = [description[0] for description in cur.description]
            vec_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        cur.execute(keyword_sql.format(filters=filter_str), [query] + filter_params_shared + [query])
        keyword_cols = [description[0] for description in cur.description]
        if not cols:
            cols = keyword_cols
        keyword_rows = [dict(zip(keyword_cols, row)) for row in cur.fetchall()]

        if not vec_rows and not keyword_rows:
            loose_terms = _extract_search_terms(query, category, subcategory)
            if loose_terms:
                score_parts = []
                score_params = []
                where_parts = []
                where_params = []

                for term in loose_terms:
                    like = f"%{term}%"
                    score_parts.append(
                        "("
                        "CASE WHEN goods_name ILIKE %s THEN 5 ELSE 0 END + "
                        "CASE WHEN brand_name ILIKE %s THEN 2 ELSE 0 END + "
                        "CASE WHEN COALESCE(array_to_string(category, ' '), '') ILIKE %s THEN 3 ELSE 0 END + "
                        "CASE WHEN COALESCE(array_to_string(subcategory, ' '), '') ILIKE %s THEN 4 ELSE 0 END + "
                        "CASE WHEN COALESCE(array_to_string(health_concern_tags, ' '), '') ILIKE %s THEN 4 ELSE 0 END"
                        ")"
                    )
                    score_params.extend([like, like, like, like, like])
                    where_parts.append(
                        "("
                        "goods_name ILIKE %s OR "
                        "brand_name ILIKE %s OR "
                        "COALESCE(array_to_string(category, ' '), '') ILIKE %s OR "
                        "COALESCE(array_to_string(subcategory, ' '), '') ILIKE %s OR "
                        "COALESCE(array_to_string(health_concern_tags, ' '), '') ILIKE %s"
                        ")"
                    )
                    where_params.extend([like, like, like, like, like])

                loose_sql = f"""
                    SELECT goods_id, goods_name, pet_type, category, subcategory,
                           price, thumbnail_url, product_url, brand_name, discount_price,
                           popularity_score, sentiment_avg, repeat_rate, health_concern_tags,
                           {ACTUAL_REVIEW_METRICS_COLUMNS}, main_ingredients,
                           ({' + '.join(score_parts)}) AS loose_score
                    FROM product
                    {ACTUAL_REVIEW_METRICS_JOIN}
                    WHERE 1=1 {filter_str}
                      AND ({' OR '.join(where_parts)})
                    ORDER BY loose_score DESC,
                             popularity_score DESC NULLS LAST,
                             review_count DESC NULLS LAST,
                             price ASC
                    LIMIT 100
                """
                cur.execute(loose_sql, score_params + filter_params_shared + where_params)
                loose_cols = [description[0] for description in cur.description]
                keyword_rows = [dict(zip(loose_cols, row)) for row in cur.fetchall()]
                if keyword_rows:
                    logger.info(
                        "loose fallback search matched %s rows for query=%r terms=%s",
                        len(keyword_rows),
                        query,
                        loose_terms,
                    )

        scores: dict[str, float] = {}
        rows_by_id: dict[str, dict] = {}

        # 1. 벡터 검색 순위 반영 (RRF)
        for rank, row in enumerate(vec_rows):
            goods_id = row["goods_id"]
            scores[goods_id] = scores.get(goods_id, 0) + 1 / (rrf_k + rank + 1)
            rows_by_id[goods_id] = row

        # 2. 키워드 검색 순위 반영 (RRF)
        for rank, row in enumerate(keyword_rows):
            goods_id = row["goods_id"]
            scores[goods_id] = scores.get(goods_id, 0) + 1 / (rrf_k + rank + 1)
            rows_by_id[goods_id] = row

        # 최종 _score 산출 및 정렬
        sorted_ids = sorted(scores, key=lambda goods_id: scores[goods_id], reverse=True)
        results = []
        for goods_id in sorted_ids[:top_k]:
            row = rows_by_id[goods_id]
            row["_score"] = scores[goods_id]
            results.append(row)

        return results
    except Exception:
        logger.exception("hybrid_search_pg failed")
        return []
    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()
