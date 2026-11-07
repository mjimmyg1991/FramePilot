"""Drop the training state from RF-DETR weight files so the bundle only carries what inference needs.

Roboflow's medium checkpoint is 405 MB, two thirds of it optimiser state. Run after the
weights are downloaded and before PyInstaller bundles them; each input gets a "-slim"
copy next to it (a new name also stops rfdetr treating it as a corrupted download):

    python slim_weights.py rf-detr-medium.pth rf-detr-seg-medium.pt
"""

import sys
from pathlib import Path

import torch

KEEP = ("model", "args")


def slim(path: Path) -> None:
    # Roboflow's own checkpoints, fetched over HTTPS with their MD5 checked by rfdetr
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    target = path.with_name(f"{path.stem}-slim{path.suffix}")
    torch.save({key: checkpoint[key] for key in KEEP if key in checkpoint}, target)
    print(f"{path.name}: {path.stat().st_size / 1e6:.0f} MB -> {target.name}: {target.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    for name in sys.argv[1:]:
        slim(Path(name))
