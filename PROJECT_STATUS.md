# Project Status - Lightroom Subject Crop

**Last Updated:** January 2025
**Status:** Feature complete, pending branding/packaging

---

## What It Does

Automatically crops landscape photos to vertical formats (4:5, 9:16, etc.) by detecting subjects using AI, then exports XMP sidecar files for Lightroom or cropped JPEGs directly.

---

## Features Implemented

### Core Processing
- [x] YOLO-based person detection (yolov8m)
- [x] Face detection fallback when no person found
- [x] Smart crop calculation centered on detected subject
- [x] Configurable padding around subject
- [x] Multiple aspect ratio presets (4:5, 9:16, 2:3, 1:1, custom)
- [x] XMP sidecar file generation (Lightroom compatible)
- [x] Cropped JPEG export with quality control

### GUI Application
- [x] Modern dark theme UI (CustomTkinter)
- [x] Drag & drop file support
- [x] Live preview with draggable crop overlay
- [x] Detection bounding box visualization
- [x] Per-image crop adjustments (drag to reposition)
- [x] Flip between portrait/landscape orientation
- [x] Background processing (non-blocking UI)

### Smart Settings
- [x] Shoot type presets (Wedding, Sports, Portraits, Street, Auto-Detect)
- [x] Destination presets (Instagram, Client Gallery, Print, Web)
- [x] CLIP-based auto-detection of shoot type
- [x] Quality slider with descriptions
- [x] Consumer-friendly strategy names (Smart Select, Main Subject, Center Stage)

### Catalog Integration
- [x] Lightroom Classic catalog reader (.lrcat)
- [x] darktable library support (uses same XMP format)
- [x] Capture One catalog reader (.cocatalog)
- [x] Browse folders, collections, smart collections
- [x] Quick filters (Picked, Recent, Rated 3+)
- [x] Catalog browser dialog with image selection

### CLI
- [x] Full command-line interface via typer
- [x] Batch processing support
- [x] Dry-run mode
- [x] Preview image generation

---

## File Structure

```
lightroom-subject-crop/
├── app.py                      # GUI entry point
├── run_gui.bat                 # Windows launcher
├── run_gui.sh                  # Unix launcher
├── requirements.txt            # Dependencies
├── README.md                   # User documentation
├── CLAUDE.md                   # Project context for AI
├── PROJECT_STATUS.md           # This file
│
├── src/
│   ├── __init__.py
│   ├── main.py                 # CLI entry point
│   ├── detector.py             # YOLO + face detection
│   ├── crop_calculator.py      # Crop math
│   ├── xmp_handler.py          # XMP file read/write
│   ├── presets.py              # Shoot types, destinations, strategies
│   ├── scene_classifier.py     # CLIP-based auto-detect
│   │
│   ├── gui/
│   │   ├── __init__.py
│   │   ├── main_window.py      # Main application window
│   │   ├── preview_widget.py   # Image preview with crop overlay
│   │   ├── worker.py           # Background processing thread
│   │   └── catalog_browser.py  # Catalog import dialog
│   │
│   └── catalog/
│       ├── __init__.py
│       ├── lightroom.py        # Lightroom catalog reader
│       ├── darktable.py        # darktable library reader
│       └── capture_one.py      # Capture One catalog reader
│
├── tests/
│   └── test_crop_calculator.py # Unit tests (21 tests, all passing)
│
└── config/
    └── default_config.yaml     # Default settings
```

---

## Dependencies

```
ultralytics>=8.0.0          # YOLO detection
opencv-python>=4.8.0        # Image processing
Pillow>=10.0.0              # Image manipulation
lxml>=4.9.0                 # XMP parsing
typer>=0.9.0                # CLI framework
pyyaml>=6.0                 # Config files
rich>=13.0.0                # CLI formatting
customtkinter>=5.2.0        # Modern GUI
tkinterdnd2>=0.3.0          # Drag & drop
transformers>=4.30.0        # CLIP model
torch>=2.0.0                # PyTorch backend
pytest>=7.0.0               # Testing
```

---

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run GUI
python app.py

# Run CLI
python -m src.main process <path> --aspect-ratio 4:5

# Run tests
pytest tests/ -v
```

---

## Pending / Future Work

### Before Packaging
- [ ] Finalize app name and branding
- [ ] App icon design
- [ ] About dialog with version info
- [ ] License decision

### Packaging Options
- PyInstaller for Windows/Mac executables
- Consider Inno Setup (Windows installer) or create-dmg (Mac)
- YOLO model (~50MB) will be bundled

### Nice-to-Have Features
- [ ] Watch folder mode (auto-process new files)
- [ ] Path remapping for moved catalog files
- [ ] Batch export presets (save/load settings)
- [ ] Undo/redo for crop adjustments
- [ ] Keyboard shortcuts
- [ ] Multiple subject selection (crop each person separately)

### Potential Integrations
- Web API for mobile PWA version
- Lightroom Classic plugin (Lua SDK)
- RawTherapee .pp3 sidecar support

---

## Known Limitations

1. **Catalog import requires local files** - Cloud-synced or moved files won't resolve
2. **YOLO model download** - First run downloads ~50MB model
3. **Memory usage** - Processing many large RAW files can use significant RAM
4. **Capture One schema varies** - Different C1 versions have different database schemas

---

## Testing Notes

- All 21 unit tests passing
- Tested with landscape JPEGs, detected subjects correctly
- GUI tested on Windows, CustomTkinter renders properly
- XMP files successfully imported into Lightroom Classic

---

## Git Status

Repository initialized but commits pending user's git configuration.
All code is in working state and ready to commit.
