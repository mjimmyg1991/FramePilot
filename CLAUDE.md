# FramePilot - AI Agent Context

> Python desktop application for auto-cropping landscape photos to vertical formats using AI subject detection. Generates XMP sidecars for Lightroom Classic or exports cropped JPEGs directly.
>
> **Brand:** "Smart crops. Zero effort." - See `BRAND.md` and `branding/` folder for brand guidelines and assets.

---

## Quick Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run GUI application
python app.py

# Run CLI
python -m src.main process <path> --aspect-ratio 4:5 --padding 0.15

# Run tests (293 tests)
pytest tests/ -v

# Run single test file
pytest tests/test_crop_calculator.py -v

# Dry run (no files written)
python -m src.main process <path> --dry-run

# Lightroom Classic plugin engine (normally run by the plugin)
python engine.py <job.json> <result.tsv>
python engine.py --verify <verify.json> <verify.tsv>   # crop position self-check
python engine.py --version

# Smart Select: label your photos, measure accuracy, fit weights
python -m src.subject_training label <photo_folder>
python -m src.subject_training evaluate <photo_folder> --report <misses_dir>
python -m src.subject_training train <photo_folder>

# Sports regression set: fetch photos, then evaluate (add --cross-validate for held-out numbers)
python eval/fetch_sports_eval.py /tmp/sports-eval
python -m src.subject_training evaluate /tmp/sports-eval --cross-validate
```

---

## Architecture

```
lightroom-subject-crop/
├── app.py                          # GUI entry point
├── engine.py                       # Headless engine entry for the LrC plugin
├── requirements.txt                # Dependencies
├── config/default_config.yaml      # Default settings
├── config/subject_weights.json     # Trained Smart Select weights (optional; code defaults otherwise)
│
├── src/
│   ├── main.py                     # CLI entry (typer)
│   ├── detector.py                 # YOLOv8m-seg + face detection
│   ├── crop_calculator.py          # Crop math & subject selection
│   ├── subject_scoring.py          # Sports-aware Smart Select features + weights
│   ├── subject_modes.py            # Single / duel / group decision
│   ├── crop_candidates.py          # GAIC-style candidate crops, hard rejects, scoring
│   ├── subject_training.py         # Label/evaluate/train CLI for subject weights
│   ├── xmp_handler.py              # XMP sidecar read/write
│   ├── presets.py                  # Shoot types, destinations, strategies
│   ├── scene_classifier.py         # CLIP-based auto-detect
│   ├── lrc_bridge.py               # LrC plugin job processing + orientation mapping
│   ├── lrc_verify.py               # LrC crop position self-check (NCC vs pre-crop rendition)
│   ├── engine_info.py              # Engine --version report (+ config/build_info.json from CI)
│   │
│   ├── gui/
│   │   ├── main_window.py          # Main CustomTkinter window
│   │   ├── preview_widget.py       # Canvas preview with crop overlay + zoom
│   │   ├── thumbnail_grid.py       # Batch preview thumbnail grid
│   │   ├── worker.py               # Background processing thread
│   │   └── catalog_browser.py      # Catalog import dialog
│   │
│   └── catalog/
│       ├── lightroom.py            # Lightroom .lrcat reader
│       ├── darktable.py            # darktable library.db reader
│       └── capture_one.py          # Capture One .cocatalog reader
│
├── eval/
│   ├── sports/subjects.json        # 218 labelled sports photos (subject, mode, members)
│   ├── fetch_sports_eval.py        # Downloads the images (not in git)
│   └── compare_sharpness.py        # Focus-measure comparison on a labelled folder
│
├── docs/research/                  # Composition brief + phase 1 results
│
├── lightroom/
│   └── FramePilot.lrplugin/        # Lightroom Classic plugin (Lua 5.1)
│       ├── Info.lua                # Plugin manifest + menu items
│       ├── FramePilotAutoCrop.lua  # Dialog, render, run engine, apply crops, position check
│       ├── FramePilotCheckSetup.lua # Check Setup: engine path/version + bundled test photo
│       ├── FramePilotEngine.lua    # Engine lookup/execution, per-run log folders
│       ├── FramePilotCore.lua      # Pure helpers (JSON, results, commands, log pruning)
│       ├── check-photo.jpg         # Test photo for Check Setup (ultralytics bus.jpg, 640px)
│       └── PluginInfoProvider.lua  # Plug-in Manager engine settings, Check Setup, Show Logs
│
└── tests/
    ├── test_crop_calculator.py     # Crop math tests
    ├── test_lrc_bridge.py          # Engine + orientation mapping tests
    ├── test_subject_scoring.py     # Smart Select features + sports scenarios
    ├── test_subject_training.py    # Label matching, weight fitting, evaluate reports
    ├── test_subject_modes.py       # Single/duel/group + mode framing
    ├── test_crop_candidates.py     # Candidate windows, rejects, terms, fallbacks
    ├── test_lrc_plugin.py          # Plugin Lua tests (lupa, fake LrC SDK)
    ├── test_lrc_verify.py          # Position self-check against simulated LrC renders
    ├── lr_simulation.py            # Simulated LrC render: develop crop + orientation
    ├── test_engine_info.py         # Engine --version / command line
    └── test_workflows.py           # CI triggers and Windows zip
```

### Key Data Flow

1. **Detection**: `detector.py` → `detect_scene()` returns people (tight bboxes from masks in precise mode) and sports balls (COCO class 32); sharpness is measured on each person's core (head/torso)
2. **Subject Selection**: `crop_calculator.frame_subject()` → `SubjectChoice`. Smart Select (`highest_confidence`) scores people with `subject_scoring.py` (weighted features: size, sharpness, confidence, centrality, side/top cut-off, ball proximity/holder, plus referee/crowd signals `kit_outlier`, `tiny`, `elevation`, `crowd_density` at weight 0 until trained), then `subject_modes.choose_subject()` decides single / duel / group. Weights come from `config/subject_weights.json` if present, else `SubjectWeights` defaults. New person-level signals go in `SubjectWeights` so `train` can weight them
3. **Crop Calculation**: `crop_candidates.rank_crops()` generates ~90 windows around the subject (base window from `calculate_crop_for_subject`: subject/union + padding, +0.10 duel, +0.20 group, never below `MIN_CROP_SCALE`), hard-rejects cut heads and cut reachable balls (falls back to the lead alone if a duel/group can't fit), scores the rest with `CropScoreWeights` (hand-set until crops are labelled) and returns the top 3
4. **Output**: `xmp_handler.py` → writes XMP sidecar OR `worker.py` → exports cropped JPEG (`ProcessingResult.alternate_crops` holds the runners-up)

### Lightroom Classic Plugin Flow

1. **Plugin** (`lightroom/FramePilot.lrplugin`) renders selected photos to 2048px JPEGs via `LrExportSession` (edits applied, orientation baked in)
2. Writes `job.json` (rendition path, develop `orientation`, current crop) and runs the engine via `LrTasks.execute`
3. **Engine** (`engine.py` → `src/lrc_bridge.py`) detects subjects, computes the crop inside the current crop, and maps it to develop coordinates (unrotated stored pixels)
4. Writes tab-separated results; plugin applies them with `photo:applyDevelopSettings` inside `catalog:withWriteAccessDo`
5. **Position self-check**: re-renders each cropped photo at 512px and runs `engine --verify`, which compares it (NCC) with the expected region of the pre-crop rendition under every orientation. A mismatch restores the previous crop and logs the orientation used and the best-matching one
6. **Logs**: each run's job/result/engine.log/plugin.log/verify files go to `%APPDATA%\FramePilot\logs\<timestamp>-<kind>` (last 10 kept); renditions stay in temp
- **CI**: `tests.yml` (pytest on Linux) and `build.yml` run on every push and PR; `workflow_dispatch` is not available to sessions. `build.yml` makes `FramePilot-Windows` (app + engine) and `FramePilot-macOS` (engine only, arm64, `FRAMEPILOT_ENGINE_ONLY=1`); both smoke-test the frozen engine
- **Engine lookup**: Plug-in Manager setting → `framepilot-engine(.exe)` next to the plugin folder → `../engine.py` in a source checkout
- **Skipped**: videos and photos with a non-zero `CropAngle` (rotated crops aren't axis-aligned)
- **Lua 5.1 only** (Lightroom's embedded Lua): no `goto`, no integer division

### GUI Architecture

- **CustomTkinter** for modern dark theme
- **Threaded processing** via `worker.py` (non-blocking UI)
- **Callbacks** for progress: `on_progress`, `on_file_complete`, `on_complete`

---

## Style Guide (Must Follow)

### Python Version & Typing
- **Python 3.11+** required (uses `int | None` union syntax)
- **Type hints on all function signatures**
- Use `from __future__ import annotations` is NOT used; use native syntax

### Naming Conventions
- **Classes**: PascalCase (`SubjectDetector`, `CropRegion`)
- **Functions/methods**: snake_case (`calculate_vertical_crop`)
- **Constants**: UPPER_SNAKE_CASE (`SUPPORTED_EXTENSIONS`, `PERSON_CLASS_ID`)
- **Private members**: single underscore prefix (`self._yolo_model`)

### Data Structures
- **Prefer `@dataclass`** for data containers (`Detection`, `CropRegion`, `ProcessingResult`)
- **Use `Enum`** for fixed choices (`SubjectStrategy`)
- **Normalized coordinates** (0-1 range) for all bbox/crop values

### Documentation
- **Module docstrings**: Brief description of purpose
- **Class docstrings**: One-line description
- **Method docstrings**: Args/Returns for public methods only
- **No inline comments** unless logic is non-obvious

### GUI Patterns
- **CustomTkinter widgets** (CTkButton, CTkFrame, etc.)
- **Dark theme**: `ctk.set_appearance_mode("dark")`
- **Callback pattern**: Pass `on_X` callables, use `self.after()` for thread-safe UI updates
- **Grid/pack layouts**: Use grid for main structure, pack for internal widget arrangement

### Error Handling
- **Let exceptions propagate** in core logic
- **Catch and display** in GUI layer via `messagebox`
- **Graceful degradation**: Missing optional features (CLIP, drag-drop) shouldn't crash

### Testing
- **pytest** for test runner
- **Class-based test organization** (`TestCropRegion`, `TestSelectPrimarySubject`)
- **pytest.approx()** for float comparisons
- **Descriptive test names**: `test_width_height`, `test_centered_strategy`

---

## Proactive Protocols

### Before Making Changes
1. **Read existing code first** - understand current patterns before modifying
2. **Run tests before and after** - `pytest tests/ -v` must pass
3. **Test GUI manually** - `python app.py` should launch without errors

### When Optimizing or Refactoring
1. **Always verify the build passes before presenting changes**
2. Run `pytest tests/ -v` and confirm all tests pass
3. Launch GUI with `python app.py` to verify no import/runtime errors
4. Check for any new linter warnings

### Background Task Handling
- **Use `threading.Thread(daemon=True)`** for background work
- **Update UI via `self.after(0, callback)`** - never modify widgets from threads
- **Provide progress callbacks** with signature `(current: int, total: int)`
- **Support cancellation** via flag checking in loops

### Adding New Features
1. Create module in appropriate location (`src/`, `src/gui/`, `src/catalog/`)
2. Add dataclasses for new data types
3. Write tests if adding core logic
4. Update this CLAUDE.md if architecture changes

### Catalog Integration Notes
- **Catalogs are SQLite databases** - always open read-only (`?mode=ro`)
- **File paths may be stale** - check `path.exists()` before using
- **Cloud-synced catalogs** won't have local files

---

## Dependencies

| Package | Purpose |
|---------|---------|
| ultralytics | YOLOv8 segmentation (yolov8m-seg.pt) |
| opencv-python | Image processing, face detection fallback |
| Pillow | Image manipulation, JPEG export |
| lxml | XMP parsing and generation |
| typer | CLI framework |
| customtkinter | Modern GUI widgets |
| tkinterdnd2 | Drag & drop support (optional) |
| transformers + torch | CLIP for scene classification (optional) |

---

## Current State (V2)

- **V2 Feature complete** - All planned features implemented
- **293 tests passing** - Crop logic, subject scoring/modes/training, candidate crops, LrC engine and plugin Lua covered
- **Sports regression set**: `eval/` (see `docs/research/phase1-results.md` for current numbers)
- **Pending**: Branding decisions, app name, packaging
- See `PROJECT_STATUS.md` for detailed feature list

### V2 New Features

| Feature | Description |
|---------|-------------|
| **Segmentation Detection** | Uses YOLOv8m-seg for tighter bounding boxes derived from pixel-accurate masks |
| **Batch Preview Grid** | Scrollable thumbnail grid showing cropped previews for quick review |
| **Zoom Controls** | Mouse wheel zoom, +/- buttons, Fit/100% buttons, middle-mouse pan |
| **Detection Dataclass** | Now includes `mask` (segmentation) and `original_bbox` fields |

### Detection Model

- **Model**: `yolov8m-seg.pt` (segmentation variant, ~50MB)
- **Tight Bbox**: Derived from segmentation mask pixels via `bbox_from_mask()`
- **Fallback**: Original YOLO bbox if mask processing fails
- **Face Detection**: OpenCV Haar cascade as backup when no persons detected

---

## Consumer-Friendly Mappings

| Technical Term | User-Facing Name |
|----------------|------------------|
| `highest_confidence` | Smart Select |
| `largest` | Main Subject |
| `centered` | Center Stage |
| `jpeg_quality: 85` | Instagram / Social |
| `jpeg_quality: 92` | Client Gallery |
| `jpeg_quality: 100` | Print / Magazine |
