"""Pure address normalization shared by DVF and DPE cleaning steps.

`normalize_address` turns a free-form French postal address into a
canonical uppercase, accent-free, whitespace-collapsed string with common
street-type abbreviations expanded, so DVF and DPE addresses can be
compared with plain string equality during the DVF x DPE join.

Design choices (documented per CLAUDE.md — no silent assumptions):
- Output convention is UPPERCASE, matching the typical French postal
  convention (La Poste normalized address format) and the DVF/DPE source
  data, which are themselves mostly uppercase.
- Accents are stripped via Unicode NFKD decomposition (e.g. "É" -> "E",
  "Ç" -> "C"). Ligatures that do not decompose under NFKD (e.g. "Œ", "Æ")
  are NOT split into "OE"/"AE" — they are rare in postal addresses and are
  left as-is rather than guessed at silently.
- Only abbreviations that are unambiguous street-type/qualifier tokens are
  expanded. Each abbreviation is matched as a whole token (with an
  optional trailing period) so it never matches inside an already-spelled
  word (e.g. "AV" does not match inside "AVENUE", "ST" does not match
  inside "SAINT"). This also makes the function idempotent.
- Hyphens and apostrophes are left untouched (they matter for commune
  names such as "SAINT-JEAN-DE-LUZ" and "D'ARCANGUES"); only curly
  apostrophes ("'") are normalized to the straight ASCII apostrophe (').
- Whitespace (including tabs/newlines) is collapsed to single spaces and
  the result is stripped.
"""

import re
import unicodedata

# Common French postal abbreviations -> expanded form.
# Not exhaustive, but covers the abbreviations most likely to appear in
# DVF/DPE source addresses. Extend here if a join-rate audit surfaces a
# recurring unmatched abbreviation — this is the single place to add one.
_ABBREVIATIONS: dict[str, str] = {
    "R": "RUE",
    "AV": "AVENUE",
    "AVE": "AVENUE",
    "BD": "BOULEVARD",
    "BLVD": "BOULEVARD",
    "PL": "PLACE",
    "STE": "SAINTE",
    "ST": "SAINT",
    "CHE": "CHEMIN",
    "CHEM": "CHEMIN",
    "RTE": "ROUTE",
    "ALL": "ALLEE",
    "SQ": "SQUARE",
    "IMP": "IMPASSE",
    "RES": "RESIDENCE",
    "LOT": "LOTISSEMENT",
    "FG": "FAUBOURG",
    "FBG": "FAUBOURG",
    "CRS": "COURS",
    "PAS": "PASSAGE",
    "GAL": "GENERAL",
    "QU": "QUAI",
    "PTE": "PORTE",
    "ESP": "ESPLANADE",
    "HAM": "HAMEAU",
}

# Longest abbreviations first so, in principle, no shorter pattern could
# ever pre-empt a longer one (in practice \b already prevents overlap —
# see module docstring — this is defense in depth).
_ABBREVIATION_PATTERNS = [
    (re.compile(rf"\b{re.escape(abbr)}\b\.?"), full)
    for abbr, full in sorted(_ABBREVIATIONS.items(), key=lambda kv: -len(kv[0]))
]

_WHITESPACE_RE = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_address(address: str) -> str:
    """Normalize a French postal address for cross-source comparison.

    Pure function: no I/O, no network, no randomness. See module
    docstring for the exact normalization rules and their rationale.
    """
    if not address:
        return ""

    text = unicodedata.normalize("NFKC", address)
    text = text.replace("’", "'")  # curly apostrophe -> straight
    text = text.upper()
    text = _strip_accents(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    for pattern, full in _ABBREVIATION_PATTERNS:
        text = pattern.sub(full, text)

    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text
