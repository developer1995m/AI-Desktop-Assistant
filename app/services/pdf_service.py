"""خواندن فایل‌های PDF و آماده‌سازی متن آن‌ها برای پرسش و پاسخ."""

from __future__ import annotations

from math import log

import re
from dataclasses import dataclass
from pathlib import Path

from app.services.pdf_retrieval import semantic_scores

try:  # نام تازه ماژول در PyMuPDF
    import pymupdf as fitz

    # روی نسخه‌های قدیمی‌تر همین بسته با نام fitz شناخته می‌شود. import دیرهنگام
    # است تا PyInstaller ماژول منسوخ‌شده fitz را در بسته قرار ندهد.
except ImportError:  # pragma: no cover - فقط برای PyMuPDF قدیمی
    import importlib

    fitz = importlib.import_module("fitz")

# متن بیشتری از سند نگه داشته می‌شود؛ چون فقط بخش‌های مرتبط به مدل می‌رود،
# سقف نگهداری متن می‌تواند سخاوتمندانه باشد.
MAX_PDF_CHARS = 120000
# برای فایل‌های بسیار سنگین فقط صفحات ابتدایی خوانده می‌شوند.
MAX_PDF_PAGES = 80

# سندی که متنش از این مقدار بیشتر باشد، به‌جای کل متن، فقط بخش‌های مرتبط فرستاده می‌شود.
MAX_CONTEXT_CHARS = 9000
# اندازه هر قطعه برای امتیازدهی و سقف تعداد قطعه‌های انتخابی در هر درخواست.
CHUNK_CHARS = 1400
CHUNK_OVERLAP = 200
MAX_CONTEXT_CHUNKS = 6
# واژه‌های کوتاه‌تر از این مقدار نادیده گرفته می‌شوند.
MIN_TERM_LEN = 3
# جداکننده قطعه‌های نامجاور در متن انتخاب‌شده.
CHUNK_SEPARATOR = "\n…\n"
# حروف و ارقام؛ باید از U+0620 شروع شود تا نقطه‌گذاری عربی (، ؛ ؟) جزو واژه نشود.
TERM_PATTERN = re.compile(r"[0-9a-z\u0620-\u06ff]+")

DOCUMENT_PROMPT = (
    "You answer questions about the PDF document the user opened. "
    "Base every answer on the document text below, quote short excerpts when useful, "
    "and answer in the language the user writes in. If the answer is not in the document, "
    "say so plainly instead of inventing details."
)
NO_TEXT_MESSAGE = "متن قابل استخراجی در این PDF پیدا نشد (احتمالاً تصویری یا اسکن‌شده است)."

NO_MATCH_NOTE = (
    "This document contains none of the words of the question, so no part of it is quoted. "
    "Say so if the question seems to be about it."
)
MULTI_DOC_PROMPT = (
    DOCUMENT_PROMPT
    + " The user has several documents open at once: use all of them, say which document an"
    " answer comes from, and point it out when one document does not cover the question."
)
# بودجه کل متن چند سند و کمینه سهم هر سند در یک درخواست.
MAX_MULTI_CONTEXT_CHARS = 14000
MIN_DOC_CONTEXT_CHARS = 1500

EXCERPT_NOTE = (
    "\nThis is a long document, so only the parts most relevant to the question are "
    "included; the excerpts may skip content and are not necessarily in document order."
)

# واژه‌های پرتکرار که ارزش جست‌وجو ندارند (فارسی و انگلیسی).
STOPWORDS = frozenset(
    """
    the and for with that this from are was were what which who how when where why does did
    about into than then they them their there you your can could should would have has had
    not but all any some more most its it's of to in on at is be as or by
    """.split()
) | frozenset(
    """
    چیست چیه کدام کدام‌یک کجا چطور چگونه چرا چه را به از که این آن است هست بود بودن شود شدن
    می نمی با برای در و یا اگر تا هم بر یک دو های هایی کرد کند کن کنم کنید دارد دارند داشت من
    ما شما او آنها همه هر بیشتر خیلی نیز فقط اما ولی روی بین بعد قبل طور خلاصه توضیح بگو بده
    درباره مورد چند چه کسی چیزی چیز لطفاً لطفا سلام ممنون
    """.split()
)


class PdfError(Exception):
    """خطای خواندن فایل PDF؛ متن پیام برای نمایش مستقیم به کاربر است."""


@dataclass(frozen=True)
class PdfDocument:
    """محتوای استخراج‌شده از یک فایل PDF."""

    path: Path
    name: str
    page_count: int
    pages_read: int
    text: str
    truncated: bool

    @property
    def char_count(self) -> int:
        """تعداد نویسه‌های متن استخراج‌شده."""
        return len(self.text)

    def summary(self) -> str:
        """خلاصه کوتاه سند برای نمایش در نوار بالای صفحه."""
        parts = [f"{self.page_count} صفحه", f"{self.char_count:,} نویسه"]

        if self.pages_read < self.page_count:
            parts.append(f"خوانده‌شده تا صفحه {self.pages_read}")
        if self.truncated:
            parts.append("متن کوتاه‌شده")

        return " • ".join(parts)

    def preview(self, limit: int = 4000) -> str:
        """بخش ابتدایی متن برای پیش‌نمایش در رابط کاربری."""
        if limit <= 0 or len(self.text) <= limit:
            return self.text

        return self.text[:limit].rstrip() + "\n…"

    def uses_excerpts(self, question: str | None = None, max_chars: int | None = None) -> bool:
        """آیا برای این پرسش فقط بخش‌هایی از سند (نه کل متن) به مدل فرستاده می‌شود؟"""
        budget = MAX_CONTEXT_CHARS if max_chars is None else max_chars

        return question is not None and len(self.text) > budget

    def context_for(self, question: str, max_chars: int | None = None) -> str:
        """متنی که برای پاسخ به این پرسش در اختیار مدل گذاشته می‌شود."""
        budget = MAX_CONTEXT_CHARS if max_chars is None else max_chars
        if len(self.text) <= budget:
            return self.text

        return select_relevant_chunks(self.text, question, max_chars=budget)

    def build_system_prompt(self, question: str | None = None) -> str:
        """پرامپت سیستمی سند.

        وقتی پرسش مشخص باشد و سند بلند باشد، به‌جای کل متن فقط بخش‌های مرتبط با همان
        پرسش فرستاده می‌شود تا طول درخواست و هزینه کنترل‌شده بماند.
        """
        excerpts = self.uses_excerpts(question)
        body = self.context_for(question) if excerpts and question is not None else self.text
        label = "EXCERPTS" if excerpts else "DOCUMENT"
        note = EXCERPT_NOTE if excerpts else ""

        return (
            f"{DOCUMENT_PROMPT}{note}\n\n"
            f"Document: {self.name}\n"
            f"--- BEGIN {label} ---\n{body}\n--- END {label} ---"
        )


def normalise_text(text: str) -> str:
    """فاصله‌های اضافی و خط‌های خالی تکراری را جمع می‌کند."""
    collapsed = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n").replace("\r", "\n"))
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)

    return "\n".join(line.strip() for line in collapsed.split("\n")).strip()


def _normalise_for_search(text: str) -> str:
    """متن را برای تطبیق ساده آماده می‌کند: حروف کوچک، حذف نیم‌فاصله و جمع‌کردن فاصله‌ها."""
    cleaned = text.lower()
    for invisible in ("\u200c", "\u200e", "\u200f"):
        cleaned = cleaned.replace(invisible, "")

    return re.sub(r"\s+", " ", cleaned)


def _glue(text: str) -> str:
    """فاصله‌ها را حذف می‌کند تا واژه‌های جدانوشته و چسبیده یکسان دیده شوند."""
    return text.replace(" ", "")


def search_terms(question: str) -> list[str]:
    """واژه‌های معنادار پرسش را برای امتیازدهی قطعه‌ها بیرون می‌کشد."""
    normalised = _normalise_for_search(question)
    terms: list[str] = []

    for word in TERM_PATTERN.findall(normalised):
        if len(word) < MIN_TERM_LEN or word in STOPWORDS or word in terms:
            continue
        terms.append(word)

    return terms


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    """متن را به قطعه‌های همپوشان می‌شکند تا بتوان بخش‌های مرتبط را جدا کرد."""
    size = CHUNK_CHARS if size is None else size
    overlap = CHUNK_OVERLAP if overlap is None else overlap

    if size <= 0:
        raise ValueError("اندازه قطعه باید مثبت باشد.")

    overlap = max(0, min(overlap, size // 2))
    step = size - overlap
    chunks: list[str] = []

    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break

    return chunks


def _spread_indexes(count: int, limit: int) -> list[int]:
    """برای پرسش‌های کلی (مثل «خلاصه کن») قطعه‌هایی از سراسر سند انتخاب می‌کند."""
    if count <= limit:
        return list(range(count))
    if limit <= 1:
        return [0]

    return sorted({round(position * (count - 1) / (limit - 1)) for position in range(limit)})


def _join_within_budget(chunks: list[str], indexes: list[int], max_chars: int) -> str:
    """قطعه‌های انتخابی را به‌هم می‌چسباند و بودجه نویسه را رعایت می‌کند."""
    kept: list[str] = []

    for index in indexes:
        candidate = CHUNK_SEPARATOR.join(kept + [chunks[index]])
        if kept and len(candidate) > max_chars:
            continue
        kept.append(chunks[index])

    return CHUNK_SEPARATOR.join(kept)


def select_relevant_chunks(
    text: str,
    question: str,
    max_chars: int | None = None,
    max_chunks: int | None = None,
) -> str:
    """بخش‌هایی از سند را که به پرسش مربوط‌اند انتخاب می‌کند.

    امتیاز هر قطعه شمارش واژه‌های پرسش است، اما هر واژه با کمیابی‌اش در سند وزن
    می‌گیرد (IDF هموار) تا واژه‌های همه‌جا حاضر، انتخاب را بلاتکلیف نکنند. ترتیب
    نهایی همان ترتیب اصلی سند است تا پاسخ مدل به هم نریزد. اگر هیچ واژه‌ای پیدا
    نشود (پرسش کلی مثل «خلاصه کن») نمونه‌هایی از سراسر سند برگردانده می‌شود.
    """
    max_chars = MAX_CONTEXT_CHARS if max_chars is None else max_chars
    max_chunks = MAX_CONTEXT_CHUNKS if max_chunks is None else max_chunks

    if not text or max_chars <= 0 or max_chunks <= 0:
        return ""

    chunks = chunk_text(text)
    if not chunks:
        return ""
    if len(chunks) <= max_chunks and len(text) <= max_chars:
        return text

    terms = search_terms(question)

    # وزن هر واژه بر پایه کمیابی خودش در همین سند (IDF هموار): واژه‌ای که فقط
    # در بخش کوچکی از سند می‌آید نشانه بهتری است تا واژه‌ای که همه‌جا تکرار
    # می‌شود (مثل نام سند یا سرستون جدول) که قبلاً همه قطعه‌ها را هم‌امتیاز می‌کرد.
    # فرمول: log(N/df) + 1 — واژه‌ای که همه‌جا هست وزن خنثی ۱ می‌گیرد، نه صفر.
    normalised_chunks = [_normalise_for_search(chunk) for chunk in chunks]
    glued_chunks = [_glue(chunk) for chunk in normalised_chunks]

    weights = {
        term: log(len(chunks) / max(1, sum(
            1
            for normalised, glued in zip(normalised_chunks, glued_chunks)
            if term in normalised or term in glued
        ))) + 1.0
        for term in terms
    }

    # نسخه «چسبیده» بدون فاصله هم بررسی می‌شود تا تفاوت نیم‌فاصله با فاصله
    # («می‌شود» در برابر «می شود») تطبیق را از دست ندهد.
    scores = [
        (
            sum(
                count * weights[term]
                for term in terms
                if (count := normalised.count(term) + glued.count(term))
            ),
            index,
        )
        for index, (normalised, glued) in enumerate(zip(normalised_chunks, glued_chunks))
    ]

    chosen = sorted(
        index
        for score, index in sorted(scores, key=lambda item: (-item[0], item[1]))
        if score > 0
    )[:max_chunks]

    if not chosen:
        semantic = semantic_scores(chunks, question)
        if semantic is not None:
            chosen = [
                index
                for index, _score in sorted(
                    enumerate(semantic), key=lambda item: (-item[1], item[0])
                )[:max_chunks]
            ]
            chosen.sort()

        if not chosen:
            chosen = _spread_indexes(len(chunks), max_chunks)

    return _join_within_budget(chunks, chosen, max_chars)


def _multi_document_budget(count: int) -> int:
    """سهم هر سند از بودجه کل متن وقتی چند سند همزمان باز است."""
    return max(MIN_DOC_CONTEXT_CHARS, MAX_MULTI_CONTEXT_CHARS // max(1, count))


def has_matching_chunk(text: str, question: str) -> bool:
    """آیا هر کدام از واژه‌های معنادار پرسش در این متن پیدا می‌شود؟"""
    terms = search_terms(question)
    if not terms:
        return False

    normalised = _normalise_for_search(text)
    glued = _glue(normalised)

    return any(term in normalised or term in glued for term in terms)


def _document_plan(
    documents: list[PdfDocument], question: str | None
) -> list[tuple[str, str]]:
    """نقشه ارسال هر سند: فهرست (برچسب، متن).

    تنها منبع حقیقت است؛ هم ساخت پرامپت و هم گزارش «گزیده فرستاده می‌شود» از همین
    استفاده می‌کنند تا هیچ‌وقت از هم جدا نشوند. وقتی چند سند باز است و پرسش مشخصی
    پرسیده شده، سندی که هیچ واژه مرتبطی ندارد خالی رها می‌شود (فقط یادداشت می‌گیرد) تا
    متن بی‌ربط بودجه را نخورد.
    """
    if question is None:
        return [("DOCUMENT", document.text) for document in documents]

    if len(documents) == 1:
        document = documents[0]
        if document.uses_excerpts(question):
            return [("EXCERPTS", document.context_for(question))]

        return [("DOCUMENT", document.text)]

    budget = _multi_document_budget(len(documents))
    matched = [has_matching_chunk(document.text, question) for document in documents]
    # اگر هیچ سندی مرتبط نبود، پرسش کلی است و نمونه‌های سراسر همه سندها می‌آید.
    filter_unrelated = any(matched)
    plan: list[tuple[str, str]] = []

    for document, is_match in zip(documents, matched):
        if filter_unrelated and not is_match:
            plan.append(("DOCUMENT", NO_MATCH_NOTE))
            continue

        if document.uses_excerpts(question, max_chars=budget):
            plan.append(("EXCERPTS", document.context_for(question, max_chars=budget)))
        else:
            plan.append(("DOCUMENT", document.text))

    return plan


def local_search_answer(documents: list[PdfDocument], question: str) -> str:
    """با استفاده از متن محلی PDF یک پاسخ کوتاه و مرتبط از سندهای باز می‌سازد.

    این تابع همان‌طور که نامش می‌گوید برای حالت آفلاین یا شکست مدل طراحی شده است:
    به‌جای شکست کامل، بهترین بخش‌های مرتبط را از متن استخراج‌شده پیدا می‌کند و یک
    پاسخ کوتاه ولی عملی به کاربر می‌دهد.
    """
    if not documents:
        return "هیچ فایل PDF باز نیست تا از متن آن جستجو شود."

    clean_question = (question or "").strip()
    if not clean_question:
        return "برای جستجوی محلی، یک سؤال وارد نشده است."

    answers: list[str] = []
    for document in documents:
        excerpt = select_relevant_chunks(document.text, clean_question, max_chars=1200)
        if not excerpt.strip():
            continue
        if not has_matching_chunk(document.text, clean_question):
            continue

        snippet = " ".join(excerpt.split())
        if len(snippet) > 220:
            snippet = snippet[:220].rstrip() + "…"

        answers.append(f"در «{document.name}»: {snippet}")

    if not answers:
        return "در متن PDFهای باز، هیچ بخش مرتبطی با این سؤال پیدا نشد."

    return " ".join(answers[:2])


def documents_use_excerpts(documents: list[PdfDocument], question: str) -> bool:
    """آیا در این پرسش حداقل یک سند فقط به‌صورت گزیده فرستاده می‌شود؟"""
    open_documents = [document for document in documents if document is not None]
    if not open_documents:
        return False

    return any(kind == "EXCERPTS" for kind, _ in _document_plan(open_documents, question))


def documents_system_prompt(
    documents: list[PdfDocument], question: str | None = None
) -> str:
    """پرامپت سیستمی برای یک یا چند سند باز.

    با یک سند رفتار همان `PdfDocument.build_system_prompt` است. با چند سند، هر سند
    نشانه‌دار و جدا می‌آید و بودجه متن بین آن‌ها تقسیم می‌شود تا طول درخواست کنترل‌شده
    بماند.
    """
    open_documents = [document for document in documents if document is not None]
    if not open_documents:
        raise ValueError("برای ساخت پرامپت حداقل یک سند لازم است.")
    if len(open_documents) == 1:
        return open_documents[0].build_system_prompt(question=question)

    blocks: list[str] = []

    for index, (kind, body) in enumerate(_document_plan(open_documents, question), start=1):
        document = open_documents[index - 1]
        blocks.append(
            f"--- BEGIN {kind} {index}: {document.name} ---\n"
            f"{body}\n"
            f"--- END {kind} {index}: {document.name} ---"
        )

    return f"{MULTI_DOC_PROMPT}\n\n" + "\n\n".join(blocks)


def load_pdf(path: str | Path) -> PdfDocument:
    """فایل PDF را باز می‌کند و متن صفحات آن را برمی‌گرداند.

    خطاهای قابل پیش‌بینی (فایل نبود، فرمت نامعتبر، رمزدار بودن و نبود متن) با
    `PdfError` گزارش می‌شوند تا رابط کاربری بتواند پیام روشن نشان دهد.
    """
    pdf_path = Path(path)

    if not pdf_path.exists():
        raise PdfError(f"فایل پیدا نشد: {pdf_path.name}")
    if not pdf_path.is_file():
        raise PdfError("مسیر داده‌شده یک فایل نیست.")

    try:
        document = fitz.open(pdf_path)
    except Exception as error:  # noqa: BLE001 - پیام PyMuPDF ممکن است هر نوعی باشد
        raise PdfError(f"این فایل به‌عنوان PDF باز نشد: {error}") from error

    try:
        if document.needs_pass:
            raise PdfError("این PDF رمز دارد؛ نسخه بدون رمز را باز کنید.")

        page_count = document.page_count
        pages_read = min(page_count, MAX_PDF_PAGES)
        page_texts = [
            normalise_text(document.load_page(index).get_text("text"))
            for index in range(pages_read)
        ]
    finally:
        document.close()

    text = normalise_text("\n\n".join(page_text for page_text in page_texts if page_text))

    if not text:
        raise PdfError(NO_TEXT_MESSAGE)

    truncated = len(text) > MAX_PDF_CHARS
    if truncated:
        text = text[:MAX_PDF_CHARS].rstrip() + "\n…"

    return PdfDocument(
        path=pdf_path,
        name=pdf_path.name,
        page_count=page_count,
        pages_read=pages_read,
        text=text,
        truncated=truncated,
    )
