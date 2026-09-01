from pathlib import Path


PROJECT_ROOT = Path.cwd().resolve()


def _safe_path(path: str = ".") -> Path:
    """Resolve a path and prevent access outside the project root."""
    target = (PROJECT_ROOT / path).resolve()

    if target != PROJECT_ROOT and PROJECT_ROOT not in target.parents:
        raise ValueError("Access outside the project directory is not allowed.")

    return target


def list_files(path: str = ".", limit: int = 100) -> list:
    """List files and directories inside the project."""

    target = _safe_path(path)

    if not target.exists():
        return [{"error": f"Path does not exist: {path}"}]

    if not target.is_dir():
        return [{"error": f"Path is not a directory: {path}"}]

    items = []

    for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        items.append(
            {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "path": str(item.relative_to(PROJECT_ROOT)),
            }
        )

        if len(items) >= limit:
            break

    return items


def read_text_file(path: str, max_chars: int = 12000) -> dict:
    """Read a UTF-8 text file inside the project."""

    target = _safe_path(path)

    if not target.exists():
        return {"error": f"File does not exist: {path}"}

    if not target.is_file():
        return {"error": f"Not a file: {path}"}

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"error": "File is not a UTF-8 text file."}

    truncated = len(content) > max_chars

    return {
        "path": str(target.relative_to(PROJECT_ROOT)),
        "content": content[:max_chars],
        "truncated": truncated,
        "characters": len(content),
    }


def find_files(pattern: str, path: str = ".", limit: int = 100) -> list:
    """Find project files by filename pattern."""

    target = _safe_path(path)

    if not target.exists():
        return [{"error": f"Path does not exist: {path}"}]

    results = []

    for item in target.rglob(pattern):
        if item.is_file():
            results.append(str(item.relative_to(PROJECT_ROOT)))

        if len(results) >= limit:
            break

    return results
    