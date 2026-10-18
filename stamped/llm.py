"""Gemini (google-genai) calls: query extraction and a short grounded summary.

Both functions degrade gracefully: on any failure they return None and the
caller falls back to deterministic behaviour.
"""
import logging
import os

from pydantic import BaseModel, Field

log = logging.getLogger("stamped.llm")
DEFAULT_MODEL = "gemini-3.8-flash"


class Query(BaseModel):
    companies: list[str] = Field(description="Company names the user asked about, as written, deduplicated.")
    role: str = Field(description="Target job role normalised to a standard title, e.g. 'Software Engineer'. Empty string if none given.")
    location: str = Field(default="", description="City/state/region if mentioned, else empty string.")


_EXTRACT_PROMPT = (
    "You extract structured data from a message sent by an international student asking about "
    "H-1B visa sponsorship. Return the companies mentioned, the target job role (normalised to a "
    "common title, expanding abbreviations like SWE -> Software Engineer, DS -> Data Scientist), and "
    "the location if given. Do not invent companies. If none are named, return an empty list."
)


def _client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    from google import genai
    from google.genai import types
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=20_000)), types


def _model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def extract_query(text: str) -> Query | None:
    try:
        c = _client()
        if c is None:
            log.warning("GEMINI_API_KEY not set; using fallback extraction")
            return None
        client, types = c
        resp = client.models.generate_content(
            model=_model(),
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=_EXTRACT_PROMPT,
                response_mime_type="application/json",
                response_schema=Query,
                temperature=0,
            ),
        )
        if isinstance(resp.parsed, Query):
            return resp.parsed
        return Query.model_validate_json(resp.text)
    except Exception as e:  # network, quota, bad JSON, ...
        log.warning("Gemini extraction failed: %s", e)
        return None


def summarize(user_text: str, facts: str) -> str | None:
    """Two-sentence takeaway grounded ONLY in the computed facts."""
    try:
        c = _client()
        if c is None:
            return None
        client, types = c
        resp = client.models.generate_content(
            model=_model(),
            contents=f"User asked: {user_text}\n\nFacts (the only source of truth):\n{facts}",
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Write a 2-sentence, plain-language takeaway for an international student. "
                    "Use ONLY the facts given. Do not add numbers, companies or claims. Do not promise "
                    "sponsorship: past filings do not guarantee future sponsorship."
                ),
                temperature=0.3,
            ),
        )
        return (resp.text or "").strip() or None
    except Exception as e:
        log.warning("Gemini summary failed: %s", e)
        return None
