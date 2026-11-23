"""Bridge helper exposing legacy `trendradar` submodules without triggering heavy barrel imports."""

from pathlib import Path
import sys
import types


def _register_namespace_stub(module_name: str, package_dir: Path) -> None:
    if module_name in sys.modules:
        return
    stub = types.ModuleType(module_name)
    stub.__file__ = str(package_dir / "__init__.py")
    stub.__path__ = [str(package_dir)]
    stub.__package__ = module_name
    sys.modules[module_name] = stub


def ensure_legacy_package_on_path(legacy_root: Path) -> None:
    """Expose `trendradar` submodules while bypassing eager root/report barrel imports.

    Legacy `trendradar/__init__.py` and `trendradar/report/__init__.py` eagerly import
    `AppContext` and `html.py`, pulling `litellm`. Registering lightweight package stubs
    lets backend adapters import `crawler`, `core.frequency`, and `notification` cleanly.

    Args:
        legacy_root: Directory containing the `trendradar/` package.

    Raises:
        FileNotFoundError: When `legacy_root / "trendradar"` does not exist.
    """
    package_dir = (legacy_root / "trendradar").resolve()
    if not package_dir.is_dir():
        raise FileNotFoundError(f"Legacy trendradar package not found under: {legacy_root}")

    root_str = str(legacy_root.resolve())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    _register_namespace_stub("trendradar", package_dir)
    report_dir = package_dir / "report"
    if report_dir.is_dir():
        _register_namespace_stub("trendradar.report", report_dir)
