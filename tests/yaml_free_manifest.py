"""Read the top-level list fields of plugin.yaml without a YAML dependency."""

from pathlib import Path


def read(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith((" ", "-")) and line.rstrip().endswith(":"):
            current = line.rstrip()[:-1]
            out[current] = []
        elif current and line.startswith("  - "):
            out[current].append(line[4:].strip())
        elif line and not line.startswith(" "):
            current = None
    return out
