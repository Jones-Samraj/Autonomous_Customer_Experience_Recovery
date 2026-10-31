"""Text analytics: sentiment, aspect extraction, embeddings, and untrusted-text guardrails."""
from __future__ import annotations

import logging
import re
from functools import lru_cache

import numpy as np

log = logging.getLogger("cx.nlp")

ASPECT_KEYWORDS: dict[str, list[str]] = {
    "payment": ["payment", "paid", "pay ", "card", "upi", "checkout", "transaction", "deducted", "gateway", "declined", "3ds",
                "otp", "netbanking", "wallet", "charged", "debited"],
    "refund": ["refund", "money back", "reimburs", "credited", "reversal", "returned"],
    "app": ["app ", "app.", "app,", "crash", "freez", "force clos", "version", "android", "ios", "login", "screen", "hang", "update"],
    "product_quality": ["quality", "defect", "broken", "stopped working", "damaged", "faulty", "not working", "does not work",
                        "malfunction", "burning", "burnt", "cheap", "heating", "died", "stopped heating"],
    "delivery": ["deliver", "courier", "delay", "late", "parcel", "shipment", "tracking", "rider", "dispatch", "transit", "hub",
                 "promised date", "address"],
    "support": ["support", "agent", "customer care", "helpline", "ticket", "call back", "chat"],
    "pricing": ["price", "expensive", "discount", "coupon", "overpriced", "mrp", "cost"],
    "packaging": ["packag", "box", "seal", "wrap", "tampered", "crushed"],
}
ASPECT_PRIORITY = ["payment", "refund", "app", "product_quality", "delivery", "support", "pricing", "packaging"]
TICKET_CATEGORY_TO_ASPECT = {"delivery": "delivery", "payment": "payment", "app": "app", "product": "product_quality",
                             "refund": "refund", "support": "support", "billing": "pricing"}
ASPECT_LABEL = {"delivery": "Delivery Delays", "payment": "Payment Failures", "app": "Mobile App Crashes",
                "product_quality": "Product Quality", "refund": "Refund Processing Delays", "support": "Support Experience",
                "pricing": "Pricing & Discounts", "packaging": "Packaging Damage", "other": "Other"}

DOMAIN_LEXICON = {"crash": -2.6, "crashing": -2.6, "crashed": -2.6, "delayed": -2.0, "late": -1.6, "failed": -2.3, "failure": -2.3,
                  "stuck": -1.7, "defective": -2.6, "faulty": -2.4, "deducted": -2.0, "declined": -2.0, "timeout": -2.0,
                  "timed": -1.2, "pending": -1.2, "unhelpful": -2.2, "broken": -2.3, "damaged": -2.3, "disappointed": -2.4,
                  "frustrating": -2.4, "burnt": -2.0, "torn": -1.8, "tampered": -2.2, "freezes": -2.0, "hangs": -1.8}

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?)",
    r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)?\s*(rules?|instructions?|prompts?)",
    r"you\s+are\s+now\b", r"\bsystem\s*:", r"reveal\s+(your\s+)?(system\s+)?prompt", r"\b(admin|developer|root)\s+mode\b",
    r"<\s*/?\s*(tool|system|assistant|function|instruction)[^>]*>", r"```",
    r"\bexecute\b[^.]{0,40}\b(tool|command|refund|script)\b", r"delete\s+(all\s+)?(the\s+)?(logs?|records?|data)",
    r"approve\s+(a\s+)?(full\s+)?refund\s+for\s+every", r"\bact\s+as\s+(an?\s+)?(admin|system|root)\b",
    r"notify\s+all\s+customers", r"\{\{.*?\}\}",
]
_INJ = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.I | re.S)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d(?:[\s-]?\d){8}(?!\d)")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_TEXT = 1200


def mask_pii(text: str) -> str:
    text = _EMAIL.sub("[EMAIL]", text)
    text = _CARD.sub("[CARD]", text)
    text = _AADHAAR.sub("[ID]", text)
    return _PHONE.sub("[PHONE]", text)


def sanitize_untrusted(text: str | None) -> tuple[str, bool, str | None]:
    """Neutralise customer-provided text. Returns (clean_text, flagged, reason).

    Customer text is DATA only: instruction-like spans are removed, control characters stripped, PII masked.
    Nothing in this text can ever reach a tool call or a system prompt.
    """
    if not text:
        return "", False, None
    t = _CTRL.sub("", str(text)).strip()[:MAX_TEXT]
    flagged = bool(_INJ.search(t))
    reason = None
    if flagged:
        reason = "instruction-like content removed (possible prompt injection)"
        t = _INJ.sub("[removed: instruction-like content]", t)
    return mask_pii(t), flagged, reason


@lru_cache(maxsize=1)
def _vader():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        a = SentimentIntensityAnalyzer()
        a.lexicon.update(DOMAIN_LEXICON)
        return a
    except Exception:  # noqa: BLE001
        log.warning("vaderSentiment unavailable, using built-in lexicon scorer")
        return None


def sentiment(text: str) -> float:
    if not text:
        return 0.0
    v = _vader()
    if v is not None:
        return float(v.polarity_scores(text)["compound"])
    words = re.findall(r"[a-z']+", text.lower())
    score = sum(DOMAIN_LEXICON.get(w, 0) for w in words)
    return float(np.tanh(score / 4))


def aspect_scores(text: str) -> dict[str, int]:
    t = f" {text.lower()} "
    out = {}
    for aspect, kws in ASPECT_KEYWORDS.items():
        n = sum(1 for k in kws if k in t)
        if n:
            out[aspect] = n
    return out


def primary_aspect(text: str, fallback: str | None = None) -> tuple[str, dict[str, int]]:
    scores = aspect_scores(text)
    if not scores:
        return (fallback or "other"), scores
    best = max(scores.values())
    for a in ASPECT_PRIORITY:
        if scores.get(a) == best:
            return a, scores
    return (fallback or "other"), scores


def is_negative_voice(source_type: str, rating: float | None, sent: float | None, category: str | None) -> bool:
    if source_type == "ticket":
        return category != "inquiry"
    if rating is not None and source_type in ("review", "survey"):
        return rating <= 2
    return (sent if sent is not None else 0.0) <= -0.15


class Embedder:
    """Sentence-Transformers (MiniLM) when available, otherwise TF-IDF + truncated SVD."""

    def __init__(self, backend: str = "auto"):
        self.backend_requested = backend
        self.name = "tfidf-svd"
        self._st = None
        if backend in ("auto", "sentence-transformers"):
            try:
                from sentence_transformers import SentenceTransformer

                self._st = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
                self.name = "sentence-transformers/all-MiniLM-L6-v2"
            except Exception:  # noqa: BLE001
                if backend == "sentence-transformers":
                    log.warning("sentence-transformers requested but unavailable; using TF-IDF")

    def fit_transform(self, texts: list[str]) -> np.ndarray:
        if self._st is not None:
            return np.asarray(self._st.encode(texts, normalize_embeddings=True, show_progress_bar=False))
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import normalize

        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, stop_words="english")
        x = vec.fit_transform(texts)
        k = max(2, min(48, x.shape[0] - 1, x.shape[1] - 1))
        z = TruncatedSVD(n_components=k, random_state=7).fit_transform(x)
        return normalize(z)


def top_terms(texts: list[str], k: int = 6) -> list[str]:
    if not texts:
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer

    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", min_df=1, max_features=2000)
        x = vec.fit_transform(texts)
    except ValueError:
        return []
    scores = np.asarray(x.sum(axis=0)).ravel()
    terms = np.array(vec.get_feature_names_out())
    return [str(t) for t in terms[np.argsort(-scores)[:k]]]
