"""Small observability report writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def write_observability_report(payload: Mapping[str, Any], output_dir: str | Path) -> dict[str, str]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "observability_status.json"
    html_path = directory / "observability_status.html"
    data = {**dict(payload), "execution_attempted": False}
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    html_path.write_text(
        "<html><body><h1>Observability Status</h1><pre>"
        + json.dumps(data, indent=2, sort_keys=True)
        + "</pre></body></html>",
        encoding="utf-8",
    )
    return {"json": str(json_path), "html": str(html_path)}

