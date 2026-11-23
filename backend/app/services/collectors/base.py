"""Unified collector contract and normalized item structure."""

from dataclasses import dataclass, field
import hashlib
from typing import Dict, List, Literal, Optional, Protocol, Union


@dataclass
class CollectedItem:
    """Normalized item emitted by any hotlist, RSS, or official API collector."""

    source_type: Literal["hotlist", "rss"]
    platform_id: str
    platform_name: str
    title: str
    url: str = ""
    mobile_url: str = ""
    domain: str = ""
    rank: int = 0
    summary: str = ""
    published_at: str = ""
    author: str = ""
    guid: str = ""
    primary_metric: Optional[float] = None
    extra_metrics: Dict[str, Union[int, float, str]] = field(default_factory=dict)

    def title_hash(self) -> str:
        """Compute deterministic SHA-256 digest of whitespace-normalized title.

        Returns:
            str: Hexadecimal SHA-256 hash.
        """
        normalized = " ".join(self.title.split()).lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class CollectionResult:
    """Collector batch result containing fetched items and non-fatal error messages."""

    items: List[CollectedItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class BaseCollector(Protocol):
    """Protocol implemented by all data source collectors."""

    def collect(self) -> CollectionResult:
        """Fetch latest items from the configured upstream source.

        Returns:
            CollectionResult: Collected items and per-source error diagnostics.
        """
        ...
