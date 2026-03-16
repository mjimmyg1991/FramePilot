# FramePilot Lightroom Integration — Implementation Plan

## Overview

Six improvements to make FramePilot easier to use with Lightroom Classic, ordered by implementation dependency.

---

## Feature 1: Auto-Select Current Lightroom Catalog

**Goal:** Eliminate the manual catalog-selection step by reading Lightroom's preferences to find the last-opened catalog.

### Changes

**New file: `src/catalog/lightroom_prefs.py`**
- `find_active_catalog() -> Path | None` — reads Lightroom's preferences file to get the last-opened catalog path
  - **Windows:** `%APPDATA%/Adobe/Lightroom/Preferences/Lightroom Classic CC 7 Preferences.agprefs` (or similar version-numbered files)
  - **macOS:** `~/Library/Preferences/com.adobe.LightroomClassicCC7.plist`
  - Parse the XML/plist for the `catalog_lastOpened` or `recentCatalogs` key
  - Return the most recent `.lrcat` path, validated with `Path.exists()`
  - Fallback: return `None` if prefs not found or unparseable

**Modified: `src/gui/catalog_browser.py`**
- In `_auto_detect_catalogs()` (~line 171): call `find_active_catalog()` first
- If found, pre-select it in the catalog dropdown and auto-load its folder/collection tree
- Add a visual indicator "(Active)" next to the auto-detected catalog name
- Keep existing `find_lightroom_catalogs()` as fallback list

**Modified: `src/gui/main_window.py`**
- In `_open_catalog_browser()` (~line 997): pass `active_catalog` hint to `CatalogBrowserDialog` constructor so it opens pre-loaded

### Testing
- Unit test in `tests/test_lightroom_prefs.py` for preference file parsing with mock data
- Manual: verify auto-detection on Windows/macOS with Lightroom installed

---

## Feature 2: Virtual Copies — Steer Users Toward XMP

**Goal:** Make the XMP (non-destructive) path the primary/default workflow and de-emphasize the export path. Clarify that XMP creates virtual-copy-like behavior in Lightroom without duplicating files.

### Changes

**Modified: `src/gui/main_window.py` — `LightroomDialog` class (lines 230-310)**
- Reorder and restyle the dialog:
  - **Primary button** (orange, prominent): "Apply Crops in Lightroom" with description "Non-destructive • Updates your existing catalog via XMP sidecars"
  - **Secondary button** (subtle): "Export Copies" with description "Creates new cropped JPEG files • For sharing outside Lightroom"
- Add a "Tip" label at bottom: "XMP sidecars are non-destructive — your originals stay untouched, and you can always readjust in Lightroom's Develop module."
- Rename button text from "Update in Lightroom" → "Apply Crops in Lightroom" and from "Export & Import" → "Export Copies"

**Modified: `src/gui/main_window.py` — action buttons area (~line 455)**
- Rename "→ Lightroom" button to "Apply to Lightroom" for clarity
- Keep "Write XMP" button as-is (power-user shortcut)

**Modified: `src/gui/main_window.py` — `_push_to_lightroom()` (line 1146)**
- After writing XMP files successfully, show a step-by-step instruction card instead of a plain messagebox:
  - Step 1: "Select the processed images in Lightroom"
  - Step 2: "Go to Metadata → Read Metadata from Files"
  - Step 3: "Your crops are now applied!"
- Include a "Copy steps to clipboard" button in the instruction dialog

### Testing
- Manual: launch GUI, verify dialog layout, button labels, and instruction flow

---

## Feature 3: Collection-Aware Workflow

**Goal:** After processing, offer to create/populate a Lightroom collection with the processed images so users can easily find them.

### Changes

**Modified: `src/catalog/lightroom.py`**
- Add `LightroomCatalog.create_collection(name: str) -> int` — creates a new collection in the catalog
  - **Important:** This requires write access to the catalog. Lightroom must NOT be running (it locks the DB). Add a check and clear error message.
  - Insert into `AgLibraryCollection` table
  - Return the new collection ID
- Add `LightroomCatalog.add_images_to_collection(collection_id: int, image_ids: list[int])` — inserts rows into `AgLibraryCollectionImage`
- Add `LightroomCatalog.get_image_id_by_path(file_path: Path) -> int | None` — lookup image ID from file path
- Modify `open()` to accept `readonly: bool = True` parameter — when `False`, opens without `?mode=ro`
- Add `is_catalog_locked() -> bool` — check if another process (Lightroom) has the DB locked

**New: `src/gui/collection_dialog.py`**
- `CollectionDialog(parent, image_count, catalog_path)` — small modal dialog:
  - Text field for collection name (default: "FramePilot Crops — {date}")
  - Checkbox: "Open collection in Lightroom after" (default on)
  - Warning label shown if catalog appears locked
  - "Create" and "Cancel" buttons
- Returns collection name or None

**Modified: `src/gui/main_window.py`**
- In `_push_to_lightroom()`, after successful XMP write:
  - If we know which catalog the images came from (tracked from catalog browser import), offer "Add to Lightroom Collection?"
  - Show `CollectionDialog`
  - If confirmed, open catalog in write mode, create collection, add images
  - Show success/failure message
- Track `self._source_catalog_path: Path | None` — set when images are imported via catalog browser
- Track `self._source_image_ids: dict[Path, int]` — map file paths to catalog image IDs (populated during catalog import)

**Modified: `src/gui/catalog_browser.py`**
- When importing images, also return image IDs alongside paths
- Change `on_import` callback signature: `on_import(paths: list[Path], image_ids: dict[Path, int])`

### Testing
- Unit test: `tests/test_lightroom_collection.py` — test collection creation and image addition with a mock .lrcat SQLite DB
- Manual: process images from catalog, verify collection appears in Lightroom after restart

### Risk
- Writing to the catalog while Lightroom is open will corrupt it. Must verify the lock check is robust. Show a clear warning.

---

## Feature 4: Batch "One-Click" Flow (Streamlined Wizard)

**Goal:** A single wizard that takes the user from image selection → processing → Lightroom integration in one guided flow.

### Changes

**New: `src/gui/wizard.py`**
- `LightroomWizard(parent, on_complete)` — multi-step CTkToplevel dialog

- **Step 1 — Select Images** (page 1):
  - Embed a simplified catalog browser (reuse `CatalogBrowserDialog` internals)
  - Or drag-and-drop area / folder picker
  - "Next" button (disabled until images selected)

- **Step 2 — Configure** (page 2):
  - Preset selector (shoot type dropdown from `presets.py`)
  - Aspect ratio picker (4:5, 9:16, 1:1, custom)
  - Padding slider
  - Strategy dropdown (Smart Select, Main Subject, Center Stage)
  - "Process" button

- **Step 3 — Review** (page 3):
  - Thumbnail grid of results (reuse `ThumbnailGrid` component)
  - Quick stats: "X/Y images cropped successfully"
  - Click thumbnail to see preview
  - Exclude toggle per image

- **Step 4 — Apply** (page 4):
  - Radio buttons: "Apply to Lightroom (XMP)" / "Export Copies"
  - If XMP: "Add to Collection?" checkbox with name field
  - "Apply" button
  - Progress bar during write
  - Final success screen with Lightroom instructions

- Navigation: Back/Next buttons, step indicator dots at top
- Wizard tracks state in a `WizardState` dataclass

**Modified: `src/gui/main_window.py`**
- Add "Quick Start" or "Wizard" button in the top toolbar area
- Wire to launch `LightroomWizard`
- Wizard's `on_complete` callback adds results to main window's queue for further review

### Implementation Notes
- Each step is a `CTkFrame` that gets packed/unpacked as user navigates
- Reuse existing components: `CatalogBrowserDialog` internals, `ThumbnailGrid`, `ProcessingWorker`
- The wizard is an alternative flow — the existing manual workflow remains fully functional

### Testing
- Manual: walk through wizard end-to-end
- Verify Back/Next navigation, state preservation between steps

---

## Feature 5: Folder Watch / Hot Folder Mode

**Goal:** Monitor a folder for new images and auto-process them, writing XMP sidecars automatically. Zero manual steps in FramePilot.

### Changes

**New: `src/watcher.py`**
- `FolderWatcher` class:
  - `__init__(watch_dir, output_mode, aspect_ratio, padding, strategy, on_file_processed)`
  - `start()` — begins watching in a daemon thread
  - `stop()` — stops watching
  - `is_running` property
  - Uses `watchdog` library (`watchdog.observers.Observer`, `watchdog.events.FileSystemEventHandler`)
  - On new file detected (matching `SUPPORTED_EXTENSIONS`):
    - Wait for file to be fully written (check file size stability over 1s)
    - Process with `SubjectDetector` + `CropCalculator`
    - Write XMP sidecar next to the file
    - Call `on_file_processed(result)` callback
  - Debounce: ignore duplicate events within 2s window
  - Error handling: log errors per file, continue watching

**New: `src/gui/watcher_panel.py`**
- `WatcherPanel(parent)` — CTkFrame panel added to main window sidebar or as a tab:
  - Folder path selector (browse button)
  - Settings: aspect ratio, padding, strategy (use defaults from config)
  - Start/Stop toggle button (green/red state)
  - Status indicator: "Watching..." / "Stopped"
  - Activity log: scrollable text area showing processed files
  - Counter: "X files processed"

**Modified: `src/gui/main_window.py`**
- Add "Watch Folder" tab or panel alongside the main processing area
- Instantiate `WatcherPanel`
- Wire watcher events to update the main thumbnail grid (optional: also add processed results to the main queue)

**Modified: `requirements.txt`**
- Add `watchdog` dependency

**Modified: `config/default_config.yaml`**
- Add watcher section:
  ```yaml
  watcher:
    enabled: false
    watch_dir: ""
    auto_xmp: true
    debounce_seconds: 2
  ```

**CLI support — Modified: `src/main.py`**
- Add `watch <path>` command:
  - `--aspect-ratio`, `--padding`, `--strategy` flags (same as `process`)
  - Runs `FolderWatcher` in foreground with Ctrl+C to stop
  - Uses `rich.live` for status display

### Testing
- Unit test: `tests/test_watcher.py` — test file detection, debouncing, and processing with temp directories
- Manual: drop files into watched folder, verify XMP appears

---

## Feature 6: Lightroom Classic Plugin

**Goal:** A `.lrplugin` that auto-reads XMP metadata when FramePilot writes sidecars, eliminating the manual "Read Metadata from Files" step.

### Changes

**New directory: `lrplugin/FramePilot.lrplugin/`**

**`Info.lua`** — Plugin manifest:
```lua
return {
    LrSdkVersion = 10.0,
    LrToolkitIdentifier = "com.framepilot.lightroom",
    LrPluginName = "FramePilot",
    LrPluginInfoUrl = "https://github.com/framepilot",
    LrInitPlugin = "Init.lua",
    LrShutdownPlugin = "Shutdown.lua",
    LrLibraryMenuItems = {
        { title = "Watch for FramePilot Crops", file = "WatchMenu.lua" },
        { title = "Read FramePilot Metadata", file = "ReadMenu.lua" },
    },
    VERSION = { major=1, minor=0, revision=0 },
}
```

**`Init.lua`** — Plugin initialization:
- Register a background task that periodically checks for new/modified `.xmp` files
- Look for a signal file (`.framepilot_ready`) written by FramePilot after XMP batch completion

**`WatchMenu.lua`** — Start/stop watching:
- Toggle XMP file watching on/off
- Uses `LrTasks.startAsyncTask` for background polling
- Polls every 5 seconds for `.framepilot_ready` signal file in configured directories
- When found:
  - Read the signal file (contains list of image paths)
  - Select those images in the catalog
  - Call `catalog:withWriteAccessDo()` to trigger metadata read
  - Delete the signal file
  - Show notification via `LrDialogs.message()`

**`ReadMenu.lua`** — Manual trigger:
- One-click "Read all FramePilot metadata"
- Scans catalog for images with newer XMP sidecars
- Batch-reads metadata for those images

**`Shutdown.lua`** — Cleanup:
- Stop background watcher task

**Modified: `src/xmp_handler.py`**
- Add `write_signal_file(image_paths: list[Path], signal_dir: Path)`:
  - After a batch XMP write, create `.framepilot_ready` file listing processed image paths
  - The Lightroom plugin watches for this file

**Modified: `src/gui/main_window.py`**
- After XMP write in `_push_to_lightroom()`:
  - Also write the signal file via `write_signal_file()`
  - Update instruction dialog: "If the FramePilot plugin is installed, crops will be applied automatically. Otherwise: Metadata → Read Metadata from Files"

**New: `src/gui/plugin_installer.py`**
- `install_lightroom_plugin()` function:
  - Copy `FramePilot.lrplugin/` folder to Lightroom's plugin directory
  - **Windows:** `%APPDATA%/Adobe/Lightroom/Modules/`
  - **macOS:** `~/Library/Application Support/Adobe/Lightroom/Modules/`
  - Or instruct user to add via File → Plug-in Manager → Add
- `PluginInstallerDialog` — small dialog with:
  - "Install Plugin" button (auto-install)
  - "Manual Install" button (opens plugin folder location)
  - Status: installed/not installed

**Modified: `src/gui/main_window.py`**
- Add "Install Plugin" option in a Help/Settings menu or in the Lightroom dialog

### Testing
- Manual: install plugin in Lightroom, process images in FramePilot, verify crops auto-apply
- Test signal file write/read in `tests/test_signal_file.py`

### Notes
- Lightroom SDK uses Lua. The plugin is pure Lua — no Python dependency inside Lightroom.
- The signal file approach avoids IPC complexity. It's a simple coordination mechanism.
- Plugin should gracefully handle: signal file missing, images not in catalog, Lightroom busy.

---

## Implementation Order

```
1. Auto-Select Catalog      (standalone, no dependencies)
2. Virtual Copies / UX      (standalone, UI-only changes)
3. Collection-Aware          (depends on catalog reader changes)
4. One-Click Wizard          (depends on 1, 2, 3 for full flow)
5. Folder Watch              (standalone, new module)
6. Lightroom Plugin          (depends on signal file from XMP handler)
```

Features 1, 2, and 5 can be implemented in parallel.
Feature 3 builds on the catalog reader.
Feature 4 ties everything together.
Feature 6 is independent but most useful after the others are in place.

---

## New Files Summary

| File | Purpose |
|------|---------|
| `src/catalog/lightroom_prefs.py` | Read Lightroom preferences for active catalog |
| `src/gui/collection_dialog.py` | Collection creation dialog |
| `src/gui/wizard.py` | One-click Lightroom wizard |
| `src/watcher.py` | Folder watch engine |
| `src/gui/watcher_panel.py` | Watch folder UI panel |
| `lrplugin/FramePilot.lrplugin/Info.lua` | Plugin manifest |
| `lrplugin/FramePilot.lrplugin/Init.lua` | Plugin init |
| `lrplugin/FramePilot.lrplugin/WatchMenu.lua` | Watch for signal files |
| `lrplugin/FramePilot.lrplugin/ReadMenu.lua` | Manual metadata read |
| `lrplugin/FramePilot.lrplugin/Shutdown.lua` | Cleanup |
| `src/gui/plugin_installer.py` | Plugin installer UI |
| `tests/test_lightroom_prefs.py` | Prefs parsing tests |
| `tests/test_lightroom_collection.py` | Collection write tests |
| `tests/test_watcher.py` | Folder watcher tests |
| `tests/test_signal_file.py` | Signal file tests |

## Modified Files Summary

| File | Changes |
|------|---------|
| `src/gui/main_window.py` | Wizard button, watcher panel, collection flow, plugin installer, updated LightroomDialog, signal file writing |
| `src/gui/catalog_browser.py` | Auto-select active catalog, return image IDs |
| `src/catalog/lightroom.py` | Collection write methods, write-mode open, lock check |
| `src/xmp_handler.py` | Signal file writing |
| `src/main.py` | `watch` CLI command |
| `config/default_config.yaml` | Watcher config section |
| `requirements.txt` | Add `watchdog` |
| `CLAUDE.md` | Update architecture docs |
