"""Unicode tokenization for candidate similarity. This is not a language parser.

Tokens keep letters and numbers from any script ``\\w`` recognizes. Punctuation
alone is not a token, so two punctuation-only excerpts are not a match.
"""

from __future__ import annotations

import re

TOKENIZER_VERSION = "unicode-regex-v1"

# Numbers, including decimals, percentages, and a leading currency sign, are
# kept whole. Remaining tokens are Unicode letters and digits without "_".
_TOKEN = re.compile(
    r"[$€£¥]\s*[0-9]+(?:[.,][0-9]+)*(?:%|٪)?|[0-9]+(?:[.,][0-9]+)*(?:%|٪)?|[^\W_]+",
    re.UNICODE,
)


def tokenize(text: str) -> tuple[str, ...]:
    """Return lowercase tokens in appearance order. The same text always matches."""
    return tuple(match.group(0).casefold() for match in _TOKEN.finditer(text))


def token_set(text: str) -> frozenset[str]:
    return frozenset(tokenize(text))
