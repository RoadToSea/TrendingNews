"""Keyword rule parser and matching service."""

import logging
import re
from typing import Any, Dict, List, Tuple, Union

logger = logging.getLogger(__name__)


def _parse_word(word: str) -> Dict[str, Any]:
    """Parse a single keyword line supporting `=> alias` and `/regex/[flags]`."""
    display_name = None
    if "=>" in word:
        parts = re.split(r"\s*=>\s*", word, 1)
        word_config = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            display_name = parts[1].strip()
    else:
        word_config = word.strip()

    regex_match = re.match(r"^/(.+)/[a-z]*$", word_config)
    if regex_match:
        pattern_str = regex_match.group(1)
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            return {
                "word": pattern_str,
                "is_regex": True,
                "pattern": pattern,
                "display_name": display_name,
            }
        except re.error as exc:
            logger.warning("Invalid regex pattern '/%s/': %s", pattern_str, exc)

    return {
        "word": word_config,
        "is_regex": False,
        "pattern": None,
        "display_name": display_name,
    }


def _word_matches(word_config: Union[str, Dict[str, Any]], title_lower: str) -> bool:
    """Return True when `word_config` matches the lowercased title."""
    if isinstance(word_config, str):
        return word_config.lower() in title_lower
    if word_config.get("is_regex") and word_config.get("pattern"):
        return bool(word_config["pattern"].search(title_lower))
    return str(word_config["word"]).lower() in title_lower


def parse_keywords_text(raw_text: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse TrendRadar keyword configuration syntax from an in-memory text string.

    Args:
        raw_text: Contents following `frequency_words.txt` group syntax.

    Returns:
        Tuple[List[Dict], List[Dict], List[Dict]]: `(word_groups, filter_words, global_filters)`.
    """
    if not raw_text or not raw_text.strip():
        return [], [], []

    blocks = [block.strip() for block in re.split(r"\r?\n\s*\r?\n", raw_text) if block.strip()]
    groups: List[Dict[str, Any]] = []
    filter_words: List[Dict[str, Any]] = []
    global_filters: List[Dict[str, Any]] = []
    current_section = "WORD_GROUPS"

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if not lines:
            continue
        if lines[0].startswith("[") and lines[0].endswith("]"):
            tag = lines[0][1:-1].strip().upper()
            if tag in ("GLOBAL_FILTER", "WORD_GROUPS"):
                current_section = tag
                lines = lines[1:]

        if current_section == "GLOBAL_FILTER":
            for ln in lines:
                if not ln.startswith(("!", "+", "@")):
                    global_filters.append(_parse_word(ln))
            continue

        parsed_group = _parse_single_group(lines, filter_words)
        if parsed_group is not None:
            groups.append(parsed_group)

    return groups, filter_words, global_filters


def _parse_single_group(
    lines: List[str],
    filter_words: List[Dict[str, Any]],
) -> Dict[str, Any] | None:
    words = list(lines)
    group_alias = None
    if words and words[0].startswith("[") and words[0].endswith("]"):
        alias = words[0][1:-1].strip()
        if alias.upper() not in ("GLOBAL_FILTER", "WORD_GROUPS"):
            group_alias = alias
            words = words[1:]

    required: List[Dict[str, Any]] = []
    normal: List[Dict[str, Any]] = []
    group_excludes: List[Dict[str, Any]] = []
    max_count = 0

    for token in words:
        if token.startswith("@"):
            try:
                val = int(token[1:])
                if val > 0:
                    max_count = val
            except ValueError:
                pass
        elif token.startswith("!"):
            group_excludes.append(_parse_word(token[1:]))
        elif token.startswith("+"):
            required.append(_parse_word(token[1:]))
        else:
            normal.append(_parse_word(token))

    if not required and not normal:
        # Preserve standalone `!word` blocks as legacy group-section filters.
        filter_words.extend(group_excludes)
        return None

    key_words = normal if normal else required
    group_key = " ".join(w["word"] for w in key_words)
    display_name = group_alias or " / ".join(w.get("display_name") or w["word"] for w in (normal + required))
    return {
        "required": required,
        "normal": normal,
        "excludes": group_excludes,
        "group_key": group_key,
        "display_name": display_name,
        "max_count": max_count,
    }


def match_items_by_keyword_groups(
    items: List[Dict[str, Any]],
    raw_text: str,
) -> Tuple[List[Dict[str, Any]], int]:
    """Match normalized news/RSS items against parsed keyword groups.

    Args:
        items: List of item dicts formatted as `NewsItemDTO` dicts.
        raw_text: Keyword configuration text stored in settings.

    Returns:
        Tuple[List[Dict[str, Any]], int]: `(group_stats, total_matched_items)`.
    """
    groups, filter_words, global_filters = parse_keywords_text(raw_text)
    if not groups:
        return [], 0

    matched_buckets: List[List[Dict[str, Any]]] = [[] for _ in groups]
    matched_keys = set()

    for item in items:
        title_lower = str(item.get("title", "")).lower()
        if not title_lower:
            continue
        if any(_word_matches(gf, title_lower) for gf in global_filters):
            continue
        if any(_word_matches(fw, title_lower) for fw in filter_words):
            continue

        for idx, grp in enumerate(groups):
            if _group_matches(title_lower, grp):
                matched_buckets[idx].append(item)
                matched_keys.add((item.get("source_type"), item.get("id")))

    result_groups: List[Dict[str, Any]] = []
    for grp, bucket in zip(groups, matched_buckets):
        if not bucket:
            continue
        limit = grp["max_count"]
        trimmed = bucket[:limit] if limit > 0 else bucket
        result_groups.append(
            {
                "group_key": grp["group_key"],
                "display_name": grp["display_name"],
                "count": len(trimmed),
                "items": trimmed,
            }
        )
    result_groups.sort(key=lambda g: g["count"], reverse=True)
    return result_groups, len(matched_keys)


def _group_matches(title_lower: str, group: Dict[str, Any]) -> bool:
    for ex in group.get("excludes", []):
        if _word_matches(ex, title_lower):
            return False
    for req in group["required"]:
        if not _word_matches(req, title_lower):
            return False
    if group["normal"]:
        return any(_word_matches(nrm, title_lower) for nrm in group["normal"])
    return True
