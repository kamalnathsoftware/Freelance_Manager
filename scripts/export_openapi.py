"""Write backend/openapi.json so `npm -w @fm/shared run generate` can produce typed clients."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))
from app.main import app  # noqa: E402

out = pathlib.Path(__file__).resolve().parents[1] / "backend" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"wrote {out}")
