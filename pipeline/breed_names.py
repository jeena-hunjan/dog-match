"""Pure helpers that turn breed names from different sources into comparable forms.

- `clean`: tidy a raw name for display (Unicode, spaces, quotes).
- `match_key`: an aggressive normal form used only for comparing names.
- `stanford_name`: Stanford folder names ("n02099712-Labrador_retriever") to plain names.
"""

import re
import unicodedata

_SYNSET_PREFIX = re.compile(r"^n\d{8}-")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def clean(name: str) -> str:
    """NFKC (turns non-breaking spaces into spaces), straight quotes, single spaces."""
    text = unicodedata.normalize("NFKC", name).translate(_QUOTES)
    return " ".join(text.split())


def match_key(name: str) -> str:
    """Lowercase ASCII words only: 'St. Bernard' and 'Saint_Bernard' both give 'saint bernard'."""
    text = unicodedata.normalize("NFKD", clean(name).lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[_\-]", " ", text)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return " ".join("saint" if word == "st" else word for word in text.split())


def stanford_name(label: str) -> str:
    """'n02085782-Japanese_spaniel' -> 'Japanese spaniel'."""
    return clean(_SYNSET_PREFIX.sub("", label).replace("_", " "))


def stanford_alias_key(label: str) -> str:
    """'n02085782-Japanese_spaniel' -> 'Japanese_spaniel', the form used in aliases.yaml."""
    return _SYNSET_PREFIX.sub("", label)
