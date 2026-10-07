"""Code data shipped inside the package (word lists, key tables)."""
from importlib.resources import as_file, files
from pathlib import Path


def data_path(name: str) -> Path:
    """Filesystem path of a packaged data file. The package is installed unzipped,
    so the path stays valid after the context manager exits."""
    with as_file(files("cdlbib") / "data" / name) as path:
        if not path.is_file():
            raise FileNotFoundError(f"cdlbib data file missing from the installation: {name}")
        return Path(path)
