"""Regenerate data/icons/placeholder.png (1x1 transparent PNG).

The PNG itself is binary and is not committed via the API push path;
this script recreates it byte-for-byte from base64.
Usage:  python tools/make_placeholder_icon.py
"""
import base64
import pathlib

B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

def main() -> None:
    out = pathlib.Path(__file__).resolve().parent.parent / "data" / "icons" / "placeholder.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(B64))
    print(f"wrote {out} ({out.stat().st_size} bytes)")

if __name__ == "__main__":
    main()
