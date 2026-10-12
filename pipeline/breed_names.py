"""Pure helpers that turn breed names from different sources into comparable forms.

- `clean`: tidy a raw name for display (Unicode, spaces, quotes).
- `match_key`: an aggressive normal form used only for comparing names.
- `akc_display_name`: AKC plurals ("Retrievers (Labrador)") to "Labrador Retriever".
- `stanford_name`: Stanford folder names ("n02099712-Labrador_retriever") to plain names.
"""

import re
import unicodedata
from collections.abc import Collection, Mapping

_SYNSET_PREFIX = re.compile(r"^n\d{8}-")
_INVERTED = re.compile(r"(?P<group>.+?) \((?P<kind>.+)\)")
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


def _singular_last_word(name: str, keep_words: Collection[str]) -> str:
    *head, last = name.split(" ")
    if last.endswith("s") and not last.endswith("ss") and last not in keep_words:
        last = last[:-1]
    return " ".join([*head, last])


def akc_display_name(
    raw: str, overrides: Mapping[str, str], keep_words: Collection[str] = ()
) -> str:
    """Singular display name for an AKC breed.

    `overrides` handles irregular plurals (Kuvaszok -> Kuvasz) and is keyed by the cleaned
    raw name. Otherwise the last word loses its final "s" unless it is in `keep_words`
    (e.g. Maltese, Pyrenees), and "Group (Kind)" is turned round to "Kind Group".
    """
    name = clean(raw)
    if name in overrides:
        return overrides[name]
    inverted = _INVERTED.fullmatch(name)
    if inverted:
        return f"{inverted['kind']} {_singular_last_word(inverted['group'], keep_words)}"
    return _singular_last_word(name, keep_words)
