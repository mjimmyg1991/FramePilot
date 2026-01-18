# Sample Workflow: Batch Converting Landscape Photos for Instagram

This guide walks through a typical workflow for preparing landscape photos for vertical social media formats.

## Scenario

You have 50 landscape photos from a photo walk that you want to post on Instagram (4:5 aspect ratio) and Instagram Stories (9:16). Each photo has one or more people as subjects.

## Step 1: Organize Your Photos

Create a working directory structure:
```
photo_project/
├── originals/        # Your original landscape photos
├── instagram/        # XMP files for 4:5 crops
└── stories/          # XMP files for 9:16 crops
```

## Step 2: Generate Instagram Crops (4:5)

```bash
python -m src.main process ./originals \
  --aspect-ratio 4:5 \
  --padding 0.15 \
  --preview \
  --verbose
```

This will:
- Scan all images in `./originals`
- Detect the primary subject in each photo
- Calculate a 4:5 vertical crop centered on the subject
- Write XMP sidecar files alongside the originals
- Generate preview images showing the crop overlay

## Step 3: Review Previews

Check the `*_preview.jpg` files to verify the crops look good. If any need adjustment:
- The XMP files can be manually edited
- Or re-run with different settings for specific images

## Step 4: Generate Stories Crops (9:16)

For a narrower Stories crop, output to a separate directory:

```bash
python -m src.main process ./originals \
  --aspect-ratio 9:16 \
  --output-dir ./stories \
  --preview
```

## Step 5: Import to Lightroom Classic

1. Open Lightroom Classic
2. Navigate to Library module
3. Browse to your `originals` folder
4. Select all photos (Ctrl/Cmd + A)
5. Right-click → Metadata → Read Metadata from Files
6. Switch to Develop module to see the applied crops

## Step 6: Fine-tune and Export

1. Review each crop in Develop module
2. Adjust position if needed (the crop tool will maintain aspect ratio)
3. Export with your preferred settings

## Tips

### Handling Multiple Subjects

By default, the tool selects the subject with highest detection confidence. Alternatives:

```bash
# Select the largest subject (by bounding box area)
python -m src.main process ./photos --strategy largest

# Select the most centered subject
python -m src.main process ./photos --strategy centered
```

### Adjusting Padding

The `--padding` option controls how much space to leave around the subject:

- `0.0` - Crop tightly to subject
- `0.15` - Default, 15% padding
- `0.3` - More breathing room

### Dry Run First

Always preview what will happen with `--dry-run`:

```bash
python -m src.main process ./photos --dry-run --verbose
```

### Backing Up Existing XMPs

The tool automatically creates `.xmp.bak` backups when modifying existing XMP files. To disable this, modify the call in your workflow or edit the source.

## Troubleshooting

### "No subject detected"

- Try using `--model face` for close-up portraits
- Ensure the image has clear subjects
- Lower confidence threshold in config if needed

### Crop seems off-center

- Check if multiple subjects were detected
- Try `--strategy centered` or `--strategy largest`
- Generate a preview to visualize the detection

### XMP not loading in Lightroom

- Ensure XMP filename matches: `photo.jpg` → `photo.jpg.xmp`
- Use "Read Metadata from Files" not just folder sync
- Check XMP file contains valid XML
