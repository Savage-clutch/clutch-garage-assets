"""Mirror every visible Garage file into this repo. Runs hourly from .github/workflows/sync.yml.

The Garage (garage.clutch.ca) is the source of truth. garage-external publishes /manifest.json: every file a visitor
can see on the Garage, its original download link and a fingerprint that changes only when the file changes. This
script downloads new and changed files, deletes ones that were removed or hidden, and rewrites INDEX.md.
Standard library only.
"""

import json
import re
import pathlib
import sys
import urllib.parse
import urllib.request

SOURCE = "https://garage-external.vercel.app/manifest.json"
BRAND = "https://garage-external.vercel.app/brand.md"
RAW = "https://raw.githubusercontent.com/Savage-clutch/clutch-garage-assets/main"
ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / ".garage-state.json"
MAX_BYTES = 95 * 1024 * 1024  # GitHub refuses files over 100 MB
FOLDERS = {"logos": "Logos", "fonts": "Fonts (Poppins; Circular is licensed and not mirrored)",
           "colours": "Colour files", "icons": "2D icons", "clutch-moments": "Clutch Moments",
           "media-kit": "Clutch Media Kit (photos and video)"}


def fetch(url: str, timeout: int = 300):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "clutch-garage-assets-sync"}),
                                  timeout=timeout)


def write_index(files: list[dict]) -> None:
    lines = ["# Clutch Garage assets: index", "",
             "Every file below is a mirror of garage.clutch.ca, checked hourly. See the commit history for when "
             "each change arrived.",
             f"Raw download link pattern: {RAW}/<path>", ""]
    for folder, title in FOLDERS.items():
        group = [f for f in files if f["path"].startswith(folder + "/")]
        if not group:
            continue
        lines += [f"## {title}", ""]
        for f in sorted(group, key=lambda f: f["path"].lower()):
            label = f.get("title") or f["path"].split("/", 1)[1]
            extra = f" ({f['collection']})" if f.get("collection") else ""
            lines.append(f"- {label}{extra}: {RAW}/{urllib.parse.quote(f['path'])}")
        lines.append("")
    (ROOT / "INDEX.md").write_text("\n".join(lines))


def write_brand() -> None:
    """BRAND.md: the full brand guide, for any AI that can open GitHub links but not garage-external."""
    with fetch(BRAND, 180) as r:
        text = r.read().decode("utf-8")
    if "# Part 1: Writing Clutch copy" not in text:  # never replace a good copy with an error page
        raise ValueError("brand.md looked incomplete")
    text = re.sub(r" Generated \d{4}-\d\d-\d\d \d\d:\d\d UTC\.", "", text)
    head = ("<!-- Mirror of https://garage-external.vercel.app/brand.md (live from garage.clutch.ca), refreshed "
            "hourly. Prefer the live link when you can open it. -->\n\n")
    (ROOT / "BRAND.md").write_text(head + text)


def main() -> int:
    with fetch(SOURCE, 180) as r:
        manifest = json.load(r)
    files = manifest["files"]
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if len(files) < 0.5 * len(state):  # a broken manifest must never wipe the mirror
        print(f"Manifest has {len(files)} files but the mirror has {len(state)}. Refusing to sync.")
        return 1

    want = {f["path"]: f for f in files}
    added = removed = 0
    failed = []
    for path, f in want.items():
        target = ROOT / path
        if state.get(path) == f["fingerprint"] and target.exists():
            continue
        try:
            with fetch(f["url"]) as r:
                data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                print(f"skip (over 95 MB): {path}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            state[path] = f["fingerprint"]
            added += 1
        except Exception as e:  # keep going; report at the end
            failed.append(f"{path}: {e}")

    for path in [p for p in state if p not in want]:
        (ROOT / path).unlink(missing_ok=True)
        del state[path]
        removed += 1
    for d in sorted((p for p in ROOT.glob("*/**") if p.is_dir()), reverse=True):
        if d.name != ".git" and ".git" not in d.parts and not any(d.iterdir()):
            d.rmdir()

    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    write_index([f for f in files if f["path"] in state])
    try:
        write_brand()
    except Exception as e:
        failed.append(f"BRAND.md: {e}")
    print(f"{len(state)} files mirrored: {added} added or updated, {removed} removed, {len(failed)} failed")
    for line in failed:
        print("  failed:", line)
    return 1 if failed and not (added or removed) else 0


if __name__ == "__main__":
    sys.exit(main())
