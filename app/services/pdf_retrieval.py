"""بازیابی معنایی اختیاری برای متن PDF."""

from __future__ import annotations

from functools import lru_cache
from os import environ
from typing import Any

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def _load_model(model_name: str) -> Any | None:
    """مدل چندزبانه را فقط در اولین نیاز بارگذاری می‌کند."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None

    try:
        return SentenceTransformer(model_name)
    except Exception:  # noqa: BLE001 - نبود مدل نباید PDF را از کار بیندازد
        return None


def semantic_scores(chunks: list[str], question: str) -> list[float] | None:
    """امتیاز شباهت قطعه‌ها را با embedding چندزبانه برمی‌گرداند.

    مقدار `None` یعنی dependency یا مدل در دسترس نیست و caller باید fallback کند.
    """
    if not chunks or not question.strip():
        return None

    model_name = environ.get("PDF_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip()
    model = _load_model(model_name)
    if model is None:
        return None

    try:
        embeddings = model.encode(
            [question, *chunks],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        query_vector = embeddings[0]
        return [float(query_vector @ vector) for vector in embeddings[1:]]
    except Exception:  # noqa: BLE001 - retrieval واژه‌ای مسیر پشتیبان است
        return None
