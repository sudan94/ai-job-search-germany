"""OpenAI wrapper, plus the embedding backend for the prefilter.

Two rules the rest of the code depends on:

* `available` is False when no key is configured, and every caller checks it
  instead of crashing.  The pipeline then does everything that does not need a
  model (fetch, normalize, dedup, store, heuristic language signal) and records
  why the rest was skipped.
* `json_chat` always returns a validated Pydantic object or raises - callers
  never see half-parsed model output.

Embeddings use the same key: `text-embedding-3-small` when one is set, and a
built-in lexical backend when it is not, so the similarity prefilter still
ranks jobs on a machine with no credentials at all.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

#: Roughly 3k tokens of JD is plenty for scoring; keeps cost and latency down.
MAX_JD_CHARS = 12_000

#: Retried: transient transport and capacity failures. A 400 is a bug in our
#: request and must surface immediately rather than being retried three times.
RETRYABLE = (RateLimitError, InternalServerError, APIConnectionError, APITimeoutError)


class LLMUnavailable(RuntimeError):
    pass


class LLMRefused(RuntimeError):
    """The model declined the request.

    Recorded against the one job and skipped; it never aborts a run.
    """


def _client_kwargs() -> dict:
    """Arguments for every OpenAI client we build.

    `base_url` is always explicit.  Left out, the SDK falls back to the
    OPENAI_BASE_URL environment variable, and `.env` ships that key blank - an
    empty base URL makes every request relative and surfaces as the useless
    message "Connection error."
    """
    return {
        "api_key": settings.openai_api_key,
        "base_url": settings.openai_base_url_effective,
        "timeout": 120.0,
    }


def truncate(text: str, limit: int = MAX_JD_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[...truncated]"


class LLMClient:
    """Chat completions: schema-validated JSON for the pipeline."""

    def __init__(self) -> None:
        self._client = None
        self.model = settings.chat_model

    @property
    def available(self) -> bool:
        return settings.llm_enabled

    def _ensure(self):
        if not self.available:
            raise LLMUnavailable(
                "OPENAI_API_KEY is not set - scoring and language judgment are disabled."
            )
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(**_client_kwargs())
        return self._client

    @staticmethod
    def _messages(system: str, user: str) -> list[dict]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(RETRYABLE),
        reraise=True,
    )
    def json_chat(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> T:
        """Structured output. The SDK derives the JSON schema from the model class,
        so the response is schema-valid rather than coaxed out of prose."""
        client = self._ensure()
        response = client.chat.completions.parse(
            model=self.model,
            messages=self._messages(system, user),
            response_format=schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        message = response.choices[0].message

        if getattr(message, "refusal", None):
            raise LLMRefused(f"The model declined this request: {message.refusal}")

        if message.parsed is not None:
            return message.parsed

        # Structured outputs guarantee valid JSON; parse it ourselves if the SDK
        # did not populate .parsed.
        raw = message.content or ""
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:
            logger.warning("Model returned unusable JSON: %s | payload=%s", exc, raw[:500])
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(RETRYABLE),
        reraise=True,
    )
    def text_chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.6,
        max_tokens: int | None = None,
    ) -> str:
        client = self._ensure()
        response = client.chat.completions.create(
            model=self.model,
            messages=self._messages(system, user),
            temperature=temperature,
            max_tokens=max_tokens,
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMRefused(f"The model declined this request: {message.refusal}")
        return (message.content or "").strip()


# ------------------------------------------------------------------ embeddings


class EmbeddingBackend:
    """Turns text into vectors for the similarity prefilter."""

    name = "none"
    label = "None"

    @property
    def model_tag(self) -> str:
        """Stored with the CV so a run can tell whether vectors are comparable."""
        return f"{self.name}:none"

    def available(self) -> bool:
        return False

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class OpenAIBackend(EmbeddingBackend):
    """`text-embedding-3-small` - fractions of a cent per posting."""

    name = "openai"
    label = "OpenAI embeddings"

    def __init__(self) -> None:
        self._client = None

    @property
    def model_tag(self) -> str:
        return f"{self.name}:{settings.embedding_model}"

    def available(self) -> bool:
        return bool(settings.openai_api_key)

    def _ensure(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(**_client_kwargs())
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(RETRYABLE),
        reraise=True,
    )
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure()
        cleaned = [truncate(t, 8_000) or " " for t in texts]
        response = client.embeddings.create(model=settings.embedding_model, input=cleaned)
        return [item.embedding for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_TOKEN_RE = re.compile(r"[a-zäöüß0-9\+#\.]{2,}", re.IGNORECASE)

#: Words carrying no signal about whether a job matches a CV.
_STOPWORDS = {
    "and", "the", "for", "with", "you", "your", "our", "are", "will", "have", "has",
    "that", "this", "from", "not", "als", "auf", "aus", "bei", "das", "dem",
    "den", "der", "des", "die", "ein", "eine", "einen", "für", "ist", "mit", "nicht",
    "sich", "sie", "und", "von", "wir", "zum", "zur", "über", "sind", "auch", "wie",
    "job", "jobs", "work", "working", "team", "teams", "role", "position", "company",
    "gmbh", "www", "http", "https", "com", "de",
}

#: Hashing-trick width. Large enough that unrelated terms rarely collide.
_LEXICAL_DIM = 1024


class LexicalBackend(EmbeddingBackend):
    """Keyless fallback: hashed bag-of-words with sub-linear term weighting.

    Not semantic - it will not connect "Golang" to "backend" the way a real
    embedding does. Its only job is the cheap end of the prefilter: pushing
    obviously unrelated postings (sales, nursing, logistics) below the ones
    that share vocabulary with the CV, so the model's budget goes to plausible
    matches. Runs offline, costs nothing, and is deterministic.
    """

    name = "lexical"
    label = "Built-in lexical (no key)"

    @property
    def model_tag(self) -> str:
        return f"{self.name}:builtin"

    def available(self) -> bool:
        return True

    @staticmethod
    def _vector(text: str) -> list[float]:
        counts: dict[int, float] = {}
        for token in _TOKEN_RE.findall((text or "").lower()):
            if token in _STOPWORDS or len(token) < 3:
                continue
            bucket = (
                int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big")
                % _LEXICAL_DIM
            )
            counts[bucket] = counts.get(bucket, 0.0) + 1.0

        vector = [0.0] * _LEXICAL_DIM
        for bucket, count in counts.items():
            # Sub-linear scaling: a JD repeating "Python" 20 times should not
            # outweigh one that also mentions Docker, Postgres and FastAPI.
            vector[bucket] = 1.0 + math.log(count)

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def get_embedder() -> EmbeddingBackend:
    """OpenAI when a key is configured, otherwise the keyless lexical backend."""
    openai_backend = OpenAIBackend()
    if openai_backend.available():
        return openai_backend
    return LexicalBackend()


llm = LLMClient()
embedder = get_embedder()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
