"""TrendRadar Web Backend application package."""

from app.config import Settings
from app.legacy_bridge import ensure_legacy_package_on_path

# Ensure legacy `trendradar` package is importable before submodules load adapters.
ensure_legacy_package_on_path(Settings().resolved_legacy_root())
