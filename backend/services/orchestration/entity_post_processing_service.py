"""Entity Post-Processing Layer.

Sits between raw NER output and DB storage.  Responsibilities:
  1. Normalise entity names (strip titles, articles, phrase fragments).
  2. Normalise Arabic character variants:
       - alef variations (ا / أ / إ / آ / ٱ)  → ا
       - ya / alef maqsura (ى)               → ي
       - ta marbuta (ة)                       → ه
       - tatweel (ـ)                          → removed
       - diacritics / tashkeel                → removed
  3. Filter noise (too short, starts with stopword, sentence fragments).
  4. Within-article deduplication via token-containment grouping:
       "Trump", "Donald Trump", "President Donald Trump"  →  "Donald Trump"
       (aliases = ["Trump", "President Donald Trump"])
  5. Expose arabic_normalized_key() used by cross-language unification.
  6. Return ProcessedEntity objects consumed by EntityExtractionService.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────────────────────
# Person title prefixes to strip before storing the canonical person name.
# Covers English, French transliterations, and Arabic.
# ──────────────────────────────────────────────────────────────────────────────

_PERSON_TITLE_RE = re.compile(
    r"""^(?:
        # English / Latin
        (?:former|late|ex[-\s])\s+
        |(?:president|prime\s+minister|vice\s+president|deputy\s+prime\s+minister)\s+
        |(?:secretary(?:\s+(?:of\s+state|general))?)\s+
        |(?:minister(?:\s+of\s+(?:foreign\s+affairs|defense|finance|interior))?)\s+
        |(?:foreign\s+minister|defense\s+minister|finance\s+minister|interior\s+minister)\s+
        |(?:senator|representative|governor|mayor|ambassador)\s+
        |(?:general|lt\.?\s*gen\.?|maj\.?\s*gen\.?|brig\.?\s*gen\.?|
           admiral|vice\s+adm\.?|rear\s+adm\.?|
           colonel|lt\.?\s*col\.?|major|captain|sergeant|corporal)\s+
        |(?:mr\.?|mrs\.?|ms\.?|miss|dr\.?|prof\.?|rev\.?|sr\.?|jr\.?)\s+
        |(?:king|queen|prince|princess|emir|sultan|sheikh|caliph)\s+
        |(?:chairman|ceo|cfo|cto|director|chief|head|leader|commander)\s+
        # Arabic titles
        |(?:الرئيس|رئيس\s+الوزراء|وزير|الوزير|نائب\s+الرئيس)\s+
        |(?:الأمير|الملك|الملكة|السلطان|الشيخ|الأمير)\s+
        |(?:السيد|الدكتور|الأستاذ|البروفيسور)\s+
        |(?:العميد|اللواء|الفريق|العقيد|الرائد|النقيب|المقدم)\s+
    )+""",
    re.IGNORECASE | re.VERBOSE,
)

# Leading article/conjunction prefixes to strip from ALL entity types.
_LEADING_ARTICLE_RE = re.compile(
    r"^(?:the|a|an|al-|el-)\s+",
    re.IGNORECASE,
)

# Sentence-fragment prefixes — these almost always indicate a mis-tagged span.
# We strip the prefix; if the remainder looks like a valid entity we keep it.
_FRAGMENT_PREFIX_RE = re.compile(
    r"^(?:when|after|before|during|as|if|once|while|since|although|"
    r"though|because|despite|following|amid|with|against|between|"
    r"حين|بعد|قبل|خلال|عندما|بينما|رغم)\s+",
    re.IGNORECASE,
)

# Arabic characters that need normalisation.
_ARABIC_ALEF_RE = re.compile(r"[أإآٱ]")       # hamza forms → bare alef
_ARABIC_YA_RE = re.compile(r"ى")              # alef maqsura → ya
_ARABIC_TA_MARBUTA_RE = re.compile(r"ة")      # ta marbuta → ha (for matching)
_ARABIC_TATWEEL_RE = re.compile(r"ـ")         # tatweel/kashida
# Tashkeel (diacritics + shadda + sukun range)
_ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F]")
# Hamza on waw / hamza below alef (already covered by alef RE above for alef;
# cover standalone hamza ء and hamza on ya ئ)
_ARABIC_HAMZA_RE = re.compile(r"[ءئؤ]")       # normalise to bare forms


def arabic_normalized_key(text: str) -> str:
    """Return a maximally-normalised Arabic key for cross-variant matching.

    Applies all normalisation rules so that spelling variants like
    "امريكا" / "أمريكا" / "اميركا" all map to the same key.
    Also used by EntityResolutionService for cross-language lookup.
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = _ARABIC_ALEF_RE.sub("ا", text)
    text = _ARABIC_HAMZA_RE.sub("ا", text)    # ء/ئ/ؤ → ا for matching
    text = _ARABIC_YA_RE.sub("ي", text)
    text = _ARABIC_TA_MARBUTA_RE.sub("ه", text)
    text = _ARABIC_TATWEEL_RE.sub("", text)
    text = _ARABIC_DIACRITICS_RE.sub("", text)
    return text

# Stopwords that should not appear as the first token of a valid entity.
_LEADING_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "this", "that", "it", "he", "she", "they", "we",
    "who", "which", "what", "where", "when", "how", "why",
    "also", "just", "said", "says", "would", "could", "should",
    "may", "might", "will", "has", "have", "had", "been",
    "was", "were", "are", "but", "not", "all", "any", "some",
    "after", "before", "during", "about", "into", "over", "under",
    # Arabic
    "في", "من", "إلى", "على", "عن", "هذا", "هذه", "ذلك", "تلك",
    "التي", "الذي", "الذين", "أن", "إن", "كان", "كانت",
    "قال", "قالت", "بعد", "قبل", "خلال", "حتى", "منذ", "لكن",
})

# Generic standalone words that are never meaningful entities on their own.
_GENERIC_SINGLES: frozenset[str] = frozenset({
    "government", "army", "military", "police", "ministry", "officials",
    "state", "country", "region", "city", "capital", "official",
    "president", "minister", "king", "prince", "general", "commander",
    "spokesman", "spokesperson", "source", "sources", "report", "reports",
    "الحكومة", "الجيش", "الشرطة", "الوزارة", "المسؤولين",
    "الدولة", "المنطقة", "المدينة", "العاصمة", "الرئيس", "الوزير",
})

# Minimum character length for a processed entity name.
_MIN_LEN = 3

# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ProcessedEntity:
    """A cleaned, deduplicated entity ready for DB storage."""

    display_name: str          # Cleaned name (proper case, titles stripped)
    canonical_name: str        # Will be resolved further by EntityResolutionService
    entity_type: str
    mention_count: int
    context_snippet: str
    aliases: list[str] = field(default_factory=list)


class EntityPostProcessor:
    """Apply normalization, noise-filtering, and within-batch deduplication."""

    # ── Public API ────────────────────────────────────────────────────────────

    def process(
        self, raw_entities: list[tuple[str, str, int, str]]
    ) -> list[ProcessedEntity]:
        """
        Transform raw NER output into cleaned, deduplicated entities.

        Args:
            raw_entities: list of (name, entity_type, mention_count, snippet)

        Returns:
            Deduplicated list of ProcessedEntity objects.
        """
        # Step 1 — normalise and filter each raw entity.
        candidates: list[tuple[str, str, int, str, str]] = []  # (display, norm, type, count, snippet)
        for raw_name, entity_type, count, snippet in raw_entities:
            display = self.normalize_name(raw_name, entity_type)
            if display is None:
                continue
            norm = self._to_normalized_key(display)
            candidates.append((display, norm, entity_type, count, snippet))

        # Step 2 — exact-key merging (same normalized form after title-stripping).
        candidates = self._merge_exact_duplicates(candidates)

        # Step 3 — within-batch token-containment grouping (PERSON only for now).
        result = self._group_by_token_containment(candidates, raw_entities)

        return result

    def normalize_name(self, name: str, entity_type: str) -> str | None:
        """
        Return a cleaned display name, or None if the name should be rejected.

        Processing order:
          1. Unicode normalisation + whitespace collapse.
          2. Arabic character normalisation.
          3. Strip person titles (PERSON type only).
          4. Strip leading articles ("The X" → "X").
          5. Strip fragment prefixes ("When X" → "X").
          6. Noise gate (too short, starts with stopword, generic single word).
          7. Proper-case the result.
        """
        # 1. Unicode
        name = unicodedata.normalize("NFKC", name)
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            return None

        # 2. Arabic normalisation
        name = self._normalize_arabic(name)

        # 3. Person title stripping
        if entity_type == "person":
            name = self._strip_person_titles(name)

        # 4. Leading article
        name = _LEADING_ARTICLE_RE.sub("", name).strip()

        # 5. Fragment prefix — strip the prefix word and keep the rest,
        #    but only if the remainder still looks like a named entity.
        fragment_match = _FRAGMENT_PREFIX_RE.match(name)
        if fragment_match:
            remainder = name[fragment_match.end():].strip()
            # Keep remainder only if it starts with a capital letter (Latin)
            # or an Arabic letter, signalling a proper noun.
            if remainder and (remainder[0].isupper() or "\u0600" <= remainder[0] <= "\u06FF"):
                name = remainder
            else:
                return None  # discard: can't recover a proper noun

        # 6. Noise gate
        if self._is_noise(name, entity_type):
            return None

        # 7. Proper-case
        name = self._canonical_case(name, entity_type)
        return name

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_arabic(name: str) -> str:
        """Normalise Arabic character variants for display storage.

        Note: ta marbuta (ة) is kept as-is for display; it is only collapsed
        to 'ه' in arabic_normalized_key() used for matching/deduplication.
        """
        name = _ARABIC_ALEF_RE.sub("ا", name)
        name = _ARABIC_HAMZA_RE.sub("ا", name)
        name = _ARABIC_YA_RE.sub("ي", name)
        name = _ARABIC_TATWEEL_RE.sub("", name)
        name = _ARABIC_DIACRITICS_RE.sub("", name)
        return name

    @staticmethod
    def _strip_person_titles(name: str) -> str:
        """Strip leading honorific/role titles from a person name."""
        stripped = _PERSON_TITLE_RE.sub("", name).strip()
        # If stripping removed everything, return original to let noise gate handle it.
        return stripped if stripped else name

    @staticmethod
    def _is_noise(name: str, entity_type: str) -> bool:
        """Return True if the name should be rejected."""
        if len(name) <= 2:
            return True

        first_token = name.split()[0].lower().rstrip(".,;:")
        if first_token in _LEADING_STOPWORDS:
            return True

        # All-digit or mostly-digit names (dates, codes)
        if re.sub(r"[\s\-/]", "", name).isdigit():
            return True

        # Single generic common noun
        if name.lower() in _GENERIC_SINGLES:
            return True

        # Very short single-token that is a common word (lowercase = not a proper noun)
        tokens = name.split()
        if len(tokens) == 1 and len(name) < 5 and name.islower():
            return True

        return False

    @staticmethod
    def _canonical_case(name: str, entity_type: str) -> str:
        """Apply consistent capitalisation rules."""
        # If the name is already mixed-case (e.g. "NATO", "UN", "FBI"), preserve it.
        if name.isupper() and len(name) <= 6:
            return name  # Keep acronyms as-is

        # Check if it looks like an Arabic string (majority Arabic chars).
        arabic_chars = sum(1 for c in name if "\u0600" <= c <= "\u06FF")
        if arabic_chars > len(name) * 0.3:
            return name  # Don't alter Arabic case

        # For Latin names: title case, but preserve all-caps acronyms within.
        parts = name.split()
        cased = []
        for part in parts:
            if part.isupper() and len(part) <= 4:
                cased.append(part)  # preserve acronym
            else:
                cased.append(part.capitalize())
        return " ".join(cased)

    @staticmethod
    def _to_normalized_key(display: str) -> str:
        """Lower-case, unicode-normalised key for comparison."""
        return unicodedata.normalize("NFKC", display).strip().lower()

    @staticmethod
    def _merge_exact_duplicates(
        candidates: list[tuple[str, str, int, str, str]],
    ) -> list[tuple[str, str, int, str, str]]:
        """
        Merge candidates that share the same (norm_key, entity_type) after
        title-stripping.  Keeps the first-seen display_name; sums counts.
        """
        seen: dict[tuple[str, str], int] = {}       # (norm, type) → index
        merged: list[list] = []

        for display, norm, etype, count, snippet in candidates:
            key = (norm, etype)
            if key in seen:
                idx = seen[key]
                merged[idx][3] += count  # accumulate mention count
                # Keep longer/richer snippet
                if len(snippet) > len(merged[idx][4]):
                    merged[idx][4] = snippet
            else:
                seen[key] = len(merged)
                merged.append([display, norm, etype, count, snippet])

        return [tuple(m) for m in merged]  # type: ignore[return-value]

    def _group_by_token_containment(
        self,
        candidates: list[tuple[str, str, int, str, str]],
        raw_entities: list[tuple[str, str, int, str]],
    ) -> list[ProcessedEntity]:
        """
        For PERSON entities: if one entity's tokens are a strict subset of
        another's (same type), merge the shorter into the longer.

        Example:
            "Trump" (tokens={trump}) ⊆ "Donald Trump" (tokens={donald,trump})
            → canonical="Donald Trump", alias="Trump"

        For ORG/LOC: only merge if norm keys are identical (handled already).
        """
        # Build a lookup of raw names so we can record original aliases.
        raw_name_map: dict[tuple[str, str], str] = {
            (self._to_normalized_key(n), t): n
            for n, t, _, _ in raw_entities
        }

        # Separate PERSON from others for targeted grouping.
        persons = [c for c in candidates if c[2] == "person"]
        others = [c for c in candidates if c[2] != "person"]

        grouped_persons = self._token_containment_group(persons, raw_name_map)
        other_results = [
            ProcessedEntity(
                display_name=c[0],
                canonical_name=self._to_normalized_key(c[0]),
                entity_type=c[2],
                mention_count=c[3],
                context_snippet=c[4],
                aliases=[],
            )
            for c in others
        ]

        return grouped_persons + other_results

    def _token_containment_group(
        self,
        persons: list[tuple[str, str, int, str, str]],
        raw_name_map: dict[tuple[str, str], str],
    ) -> list[ProcessedEntity]:
        """
        Group PERSON entities by token containment.
        Canonical = entity with the most tokens (longest name).
        Shorter-token entities become aliases of the canonical.
        """
        if not persons:
            return []

        # Sort descending by token count so the longest name comes first.
        persons_sorted = sorted(
            persons, key=lambda c: len(c[1].split()), reverse=True
        )

        # Union-Find for grouping.
        parent: dict[int, int] = {i: i for i in range(len(persons_sorted))}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                # Always make the larger-index (longer name) the root... wait,
                # we sorted descending, so index 0 = longest.  We always keep
                # the smaller index (longer name) as root.
                parent[max(px, py)] = min(px, py)

        tokens_list = [set(c[1].split()) for c in persons_sorted]

        for i in range(len(persons_sorted)):
            for j in range(i + 1, len(persons_sorted)):
                # j has fewer or equal tokens (sorted descending).
                tokens_j = tokens_list[j]
                tokens_i = tokens_list[i]
                # Containment: all tokens of j are in i.
                if tokens_j and tokens_j <= tokens_i:
                    union(i, j)

        # Build groups.
        groups: dict[int, list[int]] = {}
        for idx in range(len(persons_sorted)):
            root = find(idx)
            groups.setdefault(root, []).append(idx)

        results: list[ProcessedEntity] = []
        for root, members in groups.items():
            # The root is always the longest (canonical) entity.
            canonical = persons_sorted[root]
            can_display, can_norm, can_type, can_count, can_snippet = canonical

            # Gather aliases from shorter members.
            aliases: list[str] = []
            total_count = can_count
            for m in members:
                if m == root:
                    continue
                member = persons_sorted[m]
                mem_display, mem_norm, _, mem_count, mem_snippet = member
                total_count += mem_count
                if mem_display.lower() != can_display.lower():
                    aliases.append(mem_display)
                # Also capture original raw name as alias.
                raw_orig = raw_name_map.get((mem_norm, can_type), "")
                if raw_orig and raw_orig.lower() != can_display.lower() and raw_orig not in aliases:
                    aliases.append(raw_orig)
                # Use richer snippet.
                if len(mem_snippet) > len(can_snippet):
                    can_snippet = mem_snippet

            # Capture original raw name of the canonical as alias if it differs.
            raw_canonical = raw_name_map.get((can_norm, can_type), "")
            if raw_canonical and raw_canonical.lower() != can_display.lower():
                aliases.insert(0, raw_canonical)

            results.append(
                ProcessedEntity(
                    display_name=can_display,
                    canonical_name=can_norm,
                    entity_type=can_type,
                    mention_count=total_count,
                    context_snippet=can_snippet,
                    aliases=sorted(set(aliases)),
                )
            )

        return results
