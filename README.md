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
1. Unzip the FramePilot Windows build. It contains `FramePilot.lrplugin` next to `framepilot-engine.exe`, so keep them together.
2. In Lightroom Classic, open **File > Plug-in Manager**, click **Add**, and choose the `FramePilot.lrplugin` folder.

When running from a source checkout, add `lightroom/FramePilot.lrplugin` instead. The plugin finds `engine.py` in the repository, and runs it with `python` (`python3` on macOS) unless you set another interpreter in Plug-in Manager.

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
