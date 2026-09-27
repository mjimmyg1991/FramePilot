#!/usr/bin/env python3
"""Download the photos for the labelled sports evaluation set.

The labels in eval/sports/subjects.json cover 195 multi-person sports photos
from the Open Images V7 validation split (CC BY 2.0, via Flickr) and 23 from
Ultralytics' coco128 sample and bundled assets. Images aren't stored in git;
this script fetches them next to a copy of the labels so the folder can be
passed straight to the evaluate and train commands:

    python eval/fetch_sports_eval.py /tmp/sports-eval
    python -m src.subject_training evaluate /tmp/sports-eval --cross-validate
"""

import io
import shutil
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


LABELS = Path(__file__).parent / "sports" / "subjects.json"
OPEN_IMAGES_URL = "https://open-images-dataset.s3.amazonaws.com/validation/{name}"
COCO128_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip"
PACKAGE_ASSETS = ("bus.jpg", "zidane.jpg")


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _fetch_open_images(names: list[str], target: Path) -> int:
    def fetch(name: str) -> bool:
        path = target / name
        if path.exists():
            return True
        try:
            path.write_bytes(_download(OPEN_IMAGES_URL.format(name=name)))
            return True
        except OSError as e:
            print(f"  failed: {name} ({e})", file=sys.stderr)
            return False

    with ThreadPoolExecutor(8) as pool:
        return sum(pool.map(fetch, names))


def _fetch_coco128(names: list[str], target: Path) -> int:
    missing = [n for n in names if not (target / n).exists()]
    if missing:
        archive = zipfile.ZipFile(io.BytesIO(_download(COCO128_URL)))
        members = {Path(m).name: m for m in archive.namelist() if m.endswith(".jpg")}
        for name in missing:
            if name in members:
                (target / name).write_bytes(archive.read(members[name]))
    return sum((target / n).exists() for n in names)


def _copy_package_assets(names: list[str], target: Path) -> int:
    try:
        import ultralytics
    except ImportError:
        print("  ultralytics not installed; skipping bus.jpg and zidane.jpg", file=sys.stderr)
        return 0
    assets = Path(ultralytics.__file__).parent / "assets"
    for name in names:
        if (assets / name).exists():
            shutil.copy2(assets / name, target / name)
    return sum((target / n).exists() for n in names)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    import json

    target = Path(argv[0])
    target.mkdir(parents=True, exist_ok=True)
    names = sorted(json.loads(LABELS.read_text(encoding="utf-8"))["labels"])
    package = [n for n in names if n in PACKAGE_ASSETS]
    coco = [n for n in names if n.startswith("000000")]
    open_images = [n for n in names if n not in package and n not in coco]

    found = _fetch_open_images(open_images, target)
    found += _fetch_coco128(coco, target)
    found += _copy_package_assets(package, target)
    shutil.copy2(LABELS, target / LABELS.name)
    print(f"{found}/{len(names)} photos in {target}")
    return 0 if found == len(names) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
