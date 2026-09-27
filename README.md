# Lightroom Subject Crop

A Python tool that analyzes landscape photos, detects subjects (persons/faces), and generates XMP sidecar files with vertical crop parameters for Lightroom Classic. Available as both CLI and desktop GUI.

## Features

- **Desktop GUI** with drag & drop support
- Automatic subject detection using YOLO (persons) with face detection fallback
- Calculates optimal vertical crop centered on detected subject
- Generates Lightroom-compatible XMP sidecar files
- Supports multiple aspect ratios (4:5, 9:16, etc.)
- Batch processing for entire directories
- Preview generation with crop overlay visualization
- Preserves existing XMP metadata when updating

## Installation

```bash
# Clone or navigate to the project directory
cd ~/Projects/lightroom-subject-crop

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Lightroom Classic plugin

Crop photos without leaving Lightroom Classic: select photos, run the plugin, and the crop is applied to them in the catalog.

**Install**
1. Unzip the FramePilot build: `FramePilot-Windows` (the app and engine) or `FramePilot-macOS` (the engine only, for Apple silicon Macs). It contains `FramePilot.lrplugin` next to `framepilot-engine.exe` (Windows) or `framepilot-engine` (Mac), so keep them together.
   - **Mac:** the build isn't signed, so macOS quarantines it. Move the `FramePilot` folder where you want to keep it, then run `xattr -dr com.apple.quarantine /path/to/FramePilot` in Terminal.
2. In Lightroom Classic, open **File > Plug-in Manager**, click **Add**, and choose the `FramePilot.lrplugin` folder.
3. Choose **Library > Plug-in Extras > Check Setup...** (or **File > Plug-in Extras > FramePilot: Check Setup...**, or the button in Plug-in Manager). It finds the engine, runs it on a bundled test photo, and shows the engine's path and version with the result.

Every push to GitHub builds fresh zips: open the latest **Build FramePilot** run under the repository's **Actions** tab and download the `FramePilot-Windows` or `FramePilot-macOS` artifact.

When running from a source checkout, add `lightroom/FramePilot.lrplugin` instead. The plugin finds `engine.py` in the repository and runs it with the Python set in Plug-in Manager, else a `.venv` or `venv` next to `engine.py`, else `python` (`python3` on macOS). Lightroom on macOS doesn't see Homebrew or pyenv on its PATH, so use a venv or set the path.

**Use**
1. Select photos in the Library grid or filmstrip. A collection works well as a queue.
2. Choose **Library > Plug-in Extras > Auto-crop Selected Photos...** (or **File > Plug-in Extras** in any module).
3. Pick the aspect ratio, subject mode and framing, then click **Crop**.

**Framing**
- **Tight**, **Balanced** and **Loose** zoom in so the subject fills the crop, with a little, some or plenty of space around them. Crops never go below half the size of the largest crop that fits, so small or distant subjects don't turn into low-resolution slivers.
- **Widest** never zooms in. It keeps the full frame height and just slides the crop to the subject.

**Behavior**
- Photos are rendered with your edits, so RAW files and rotated photos work.
- If a photo is already cropped, the new crop stays inside the current crop. Reset the crop first to use the whole frame.
- The crop is locked to the chosen aspect ratio, so dragging it in the Crop tool keeps the shape.
- Each crop is a normal develop history step: undo it with **Edit > Undo** or adjust it with the Crop tool.
- To keep the original framing, create virtual copies first and crop those.
- Photos with a straightened or rotated crop (a non-zero crop angle) and videos are skipped and listed in the summary.
- After cropping, each photo is rendered again, small, and compared with the region of the original rendition the crop was meant to show. If they don't match (for example the photo's rotation was read the wrong way), the previous crop is put back and the photo is listed as "Crop didn't land where expected"; the run's log records the photo's orientation and the orientation that would have matched. Turn this off with the checkbox in the crop dialog.

**Logs**
Each run keeps its `job.json`, `result.tsv`, `engine.log` and `plugin.log` in its own folder under `%APPDATA%\FramePilot\logs` on Windows (`~/Library/Application Support/FramePilot/logs` on macOS). The last 10 runs are kept. The summary and error dialogs name the run's folder, and Plug-in Manager has a **Show Logs** button. Zip the folder to report a problem.

### Smart Select for sports

Smart Select picks the main subject the way a sports photographer would. It scores each detected person on:
- how large and in-focus they are compared with everyone else
- how close they are to the ball, and whether they're the closest player to it
- whether the frame edge cuts them off (a player half out of frame is rarely the subject)

Small, sharp background figures, blurry foreground spectators and players cut off at the frame edge lose to the player in the action.

It also decides whether the story is one player, a duel (two players contesting the ball) or a group (a celebration or huddle), and frames duels and groups together with a little more room. It then tries about 90 crops around them and picks the best: it never cuts a head or a ball in play, avoids slicing through other players, keeps hands and feet off the edges, and leaves room on the ball side. The runner-up crops are kept as alternates.

**Tune it on your own photos.** Put a mix of your multi-person sports shots in a folder, then:

```bash
# Click the main subject in each photo (s = skip, q = save and quit)
python -m src.subject_training label path/to/photos

# How often Smart Select agrees with you; saves pictures of the misses
python -m src.subject_training evaluate path/to/photos --report path/to/misses

# Fit the weights to your labels
python -m src.subject_training train path/to/photos
```

`train` writes `config/subject_weights.json`, which the app, CLI and Lightroom plugin all use. It only saves when the new weights beat the current ones on photos held out from training. A few hundred labelled photos with more than one person gives a meaningful result.

A labelled regression set of 218 public sports photos lives in `eval/`; `python eval/fetch_sports_eval.py <folder>` downloads the images, and `evaluate <folder> --cross-validate` reports subject, mode and crop numbers. Current results are in `docs/research/phase1-results.md`.

### Desktop GUI

Launch the graphical interface:
```bash
# Windows
run_gui.bat

# Or directly with Python
python app.py
```

**GUI Features:**
- Drag & drop files or folders onto the queue
- Configure aspect ratio, padding, and subject selection strategy
- Live preview with crop overlay and detection bounding box
- Process files with background threading (non-blocking UI)
- Write XMP files with one click

### Command Line

Process a single image:
```bash
python -m src.main process photo.jpg
```

Process all images in a directory:
```bash
python -m src.main process ./photos
```

### Options

```
python -m src.main process <path> [OPTIONS]

Options:
  -a, --aspect-ratio TEXT   Target aspect ratio (default: 4:5)
  -p, --padding FLOAT       Padding around subject, 0.0-1.0 (default: 0.15)
  -m, --model TEXT          Detection model: yolo or face (default: yolo)
  -s, --strategy TEXT       Subject selection: largest, centered,
                            highest_confidence (default: highest_confidence)
  -o, --output-dir PATH     Output directory for XMP files
  --write-xmp / --no-write-xmp
                            Write XMP sidecar files (default: True)
  --preview                 Generate preview images with crop overlay
  -n, --dry-run             Show what would be done without writing files
  -v, --verbose             Verbose output
```

### Examples

Generate XMP files with 4:5 crop for Instagram:
```bash
python -m src.main process ./vacation_photos --aspect-ratio 4:5
```

Generate 9:16 crops for Stories/Reels with preview images:
```bash
python -m src.main process ./portraits --aspect-ratio 9:16 --preview
```

Dry run to see what would be processed:
```bash
python -m src.main process ./photos --dry-run --verbose
```

Output XMP files to a separate directory:
```bash
python -m src.main process ./photos --output-dir ./xmp_files
```

## Workflow with Lightroom Classic

1. **Export or locate your landscape photos** in a folder

2. **Run the tool** to generate XMP sidecar files:
   ```bash
   python -m src.main process ./my_photos --aspect-ratio 4:5
   ```

3. **In Lightroom Classic**:
   - Navigate to the folder containing your photos
   - Select all photos
   - Right-click → Metadata → Read Metadata from Files
   - The crop overlay will now be applied to each photo

4. **Review and adjust** any crops as needed in the Develop module

## Supported Formats

**Input Images:**
- JPEG (.jpg, .jpeg)
- PNG (.png)
- TIFF (.tif, .tiff)
- RAW formats: DNG, CR2, CR3, NEF, ARW, RAF

**Output:**
- XMP sidecar files (.xmp)
- Preview images (.jpg) when using --preview

## Detection Models

### YOLO (default)
Uses YOLOv8m for person detection. Best for full-body or partial-body shots. The model is downloaded automatically on first use.

### Face Fallback
If no person is detected, the tool falls back to OpenCV's Haar cascade face detection. Useful for close-up portraits or when YOLO misses a person.

## Configuration

Default settings can be modified in `config/default_config.yaml`.

## Development

Run tests:
```bash
pytest tests/ -v
```

## License

MIT
