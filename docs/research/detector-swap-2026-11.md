# Detector swap: Ultralytics YOLOv8 to RF-DETR

Date: 8 November 2026. Branch: `claude/rf-detr-detector`.

## Summary

- Ultralytics YOLOv8 is AGPL-3.0, which blocks a closed paid app. The detector is now RF-DETR (Apache-2.0). The decision to use RF-DETR was made before this work; this note measures whether accuracy holds.
- Chosen: RF-DETR Medium for fast mode and RF-DETR Seg Medium for precise mode, both Apache-2.0. After the 8 November threshold tuning, fast mode drops people below 0.75 confidence (it was 0.5) and ships Smart Select weights re-fitted to RF-DETR output.
- Accuracy on the 160-photo sports regression set is close to YOLOv8 but not identical. With the current Smart Select weights, exact-subject accuracy is 72.5% against 77.5% (fast) and 74.5% against 74.5% (precise). Held-out accuracy after re-fitting the weights to each detector is 73.8% against 76.9% (fast) and 79.1% against 78.3% (precise). One photo is 0.6 points, so most of these gaps are inside the noise. Those figures are at the first-pass 0.5 threshold; see "Threshold tuning" for the final ones.
- Threshold tuning recovered part of the gap. On a fixed 160-photo set, Medium at 0.75 with the re-fitted weights gets exact subject 119/160 (YOLOv8m 124), mode correct 111/160 (YOLOv8m 116, Medium at 0.5 had 106) and best-crop intruders at 4:5 and 9:16 of 9 and 14, the same as YOLOv8m. Intruders are fully back; duel and group framing is about half recovered.
- Speed on this Mac (Apple silicon, PyTorch picks MPS automatically): 35 ms per photo against 108 ms for YOLOv8m. On CPU only, RF-DETR Medium takes 306 ms against 93 ms for YOLOv8m, which matters for Windows machines without a GPU.
- Masks are not needed for accuracy. Box-only detection does as well or better on the crop-quality measures, so precise mode could be retired later (see Masks below).

## Method

- Photos: the 218-photo labelled sports set in `eval/sports/subjects.json`, fetched with `eval/fetch_sports_eval.py` into a scratch folder (not committed). 160 photos have two or more people and a matching label, which is what Smart Select is scored on.
- Baseline: Ultralytics 8.x with `yolov8m.pt` (fast) and `yolov8m-seg.pt` (precise, tight boxes from masks), run from the shared venv read-only, on CPU (Ultralytics' default here; confirmed).
- RF-DETR: `rfdetr` 1.12.0 on Python 3.13 and torch 2.15, in a venv inside the worktree. Same photos, same labels, same Smart Select weights, same candidate-crop code.
- Metrics come from `python -m src.subject_training evaluate <dir> --cross-validate` (new `--precise` and `--model` options select the detector; precise mode uses `--precise`). Timing is `detect_scene` per photo after one warm-up call, measured over all 218 photos.
- The held-out rows retrain the Smart Select weights on the other folds (the evaluator's `--cross-validate`). They approximate what running `train` on each detector's output would give, because the shipped weights were fitted to YOLO's confidence and size distributions.
- The results tables below use the first-pass person threshold of 0.5 and balls at 0.25. The threshold was tuned afterwards (see "Threshold tuning"); balls stay at 0.25.
- Raw outputs were saved to the scratch folder: one text file per run from `evaluate` and one JSON per run with every detection.

## Licences

Source: [RF-DETR README](https://github.com/roboflow/rf-detr/blob/develop/README.md) and [LICENSE](https://github.com/roboflow/rf-detr/blob/develop/LICENSE), read on 8 November 2026. The LICENSE file is the plain Apache License 2.0 text and GitHub reports the repository as Apache-2.0. The README states:

> Commercially usable under Apache 2.0. The `rfdetr` package, RF-DETR Nano, Small, Medium and Large detection, every RF-DETR-Seg size (Nano through 2XLarge), and RF-DETR Keypoint are released under the Apache 2.0 license.

It also states that Atto, Femto, Pico, XL and 2XL detection ship in the optional `rfdetr[plus]` extension under the [Roboflow Platform Model License (PML 1.0)](https://github.com/roboflow/rf-detr_plus/blob/main/LICENSE), where commercial self-hosting needs an Enterprise add-on. The size table marks those five as PML 1.0 and Nano, Small, Medium, Large and Seg Nano to 2XL as Apache 2.0.

What the code does about it:

- `DETR_MODELS` in `src/detector.py` lists only Nano, Small, Medium, Large and Seg Nano, Small, Medium, Large. Anything else raises an error, and a test asserts no PML size name is present.
- `requirements.txt` pins `rfdetr` without the `plus` extra. No PML weights were downloaded at any point.
- The weights themselves are fetched from `repo.roboflow.com` by the `rfdetr` package and MD5-checked there.

### New dependencies

`pip install rfdetr` added: supervision (MIT), transformers (Apache-2.0), scipy (BSD), matplotlib (PSF-style), huggingface_hub, safetensors, tokenizers, pydantic, requests, av (BSD-3), pyDeprecate, tqdm and a few small helpers. Nothing is GPL or AGPL. Items worth knowing:

- `certifi` and `tqdm` are MPL-2.0 (file-level copyleft, fine unmodified). They are already common transitive dependencies.
- PyInstaller is GPL-2.0 with a special exception that covers the bundled output; it is a build tool, not shipped.
- `av` (PyAV) is BSD-3 but its wheel bundles a second FFmpeg with x264 and x265. It is only imported by supervision's video helpers, which FramePilot never calls, so the spec excludes it from the bundle.
- Pre-existing, not caused by this change: the `opencv-python` macOS wheel bundles a GPL-3.0 FFmpeg (libavcodec 61 built with `--enable-gpl`, libx264, libx265). The installed `~/FramePilot` build already contains `libx264` and `libx265` for that reason. Moving to `opencv-python-headless` does not change this, so it needs its own decision before a paid release (an LGPL-only OpenCV build, or a wheel without FFmpeg).
- The checkpoint files are Python pickles. They come from Roboflow over HTTPS and are MD5-checked, and `slim_weights.py` loads them only at build time.

## Results: fast mode (boxes)

All rows use the same 218 photos. "2+ people" is the number of photos where the detector finds two or more people at 0.5, which are the photos scored for subject choice.

| Metric | YOLOv8m | RF-DETR Nano | RF-DETR Small | RF-DETR Medium | RF-DETR Large |
|---|---|---|---|---|---|
| Photos with 2+ people | 160 | 160 | 156 | 160 | 159 |
| Labelled subject found (IoU 0.5), of 170 | 170 | 168 | 167 | 169 | 166 |
| People found (all photos) | 975 | 1024 | 1065 | 1064 | 1076 |
| Balls found | 164 | 158 | 157 | 155 | 160 |
| Exact subject chosen | 124/160 (77.5%) | 122/160 (76.3%) | 114/155 (73.5%) | 116/160 (72.5%) | 116/157 (73.9%) |
| Subject or duel/group member | 150/160 (93.8%) | 146/160 (91.3%) | 142/155 (91.6%) | 144/160 (90.0%) | 141/157 (89.8%) |
| Held-out exact (re-fitted weights) | 123/160 (76.9%) | 127/160 (79.4%) | 114/155 (73.5%) | 118/160 (73.8%) | 119/157 (75.8%) |
| Held-out subject or member | 149/160 (93.1%) | 150/160 (93.8%) | 143/155 (92.3%) | 147/160 (91.9%) | 144/157 (91.7%) |
| Mode correct (single vs duel/group framing) | 116/160 (72.5%) | 108/160 (67.5%) | 105/155 (67.7%) | 106/160 (66.2%) | 105/157 (66.9%) |
| Labelled members framed | 109/133 | 97/124 | 97/123 | 102/129 | 99/123 |
| Framed people who are labelled members | 109/114 | 97/103 | 97/103 | 102/109 | 99/106 |
| Time per photo, this Mac (ms) | 108 | 34 | 30 | 35 | 43 |

Crop problems, photos affected at 4:5 (first number is the single computed crop, second is the best candidate crop; lower is better):

| Problem | YOLOv8m | Nano | Small | Medium | Large |
|---|---|---|---|---|---|
| Head cut | 14 to 3 | 13 to 2 | 11 to 2 | 15 to 2 | 16 to 2 |
| Ball cut | 9 to 0 | 13 to 1 | 11 to 1 | 11 to 1 | 10 to 1 |
| Intruder | 36 to 9 | 38 to 15 | 31 to 12 | 31 to 13 | 30 to 13 |
| Extremity | 41 to 9 | 43 to 11 | 38 to 11 | 43 to 14 | 40 to 13 |
| Low head | 3 to 4 | 6 to 5 | 5 to 4 | 6 to 5 | 5 to 5 |

At 9:16 the picture is the same: head cut 38 to 10 (YOLO) against 39 to 8 (Medium), intruder 38 to 14 against 37 to 18, extremity 34 to 24 against 33 to 24.

## Results: precise mode (segmentation, tight boxes from masks)

| Metric | YOLOv8m-seg | Seg Small | Seg Medium | Seg Large | Seg Medium, boxes only |
|---|---|---|---|---|---|
| Photos with 2+ people | 158 | 159 | 157 | 156 | 157 |
| Labelled subject found, of 170 | 164 | 165 | 164 | 163 | 166 |
| People found | 932 | 1026 | 1038 | 985 | 1038 |
| Exact subject chosen | 117/157 (74.5%) | 116/156 (74.4%) | 114/153 (74.5%) | 117/153 (76.5%) | 112/154 (72.7%) |
| Subject or member | 144/157 (91.7%) | 142/156 (91.0%) | 138/153 (90.2%) | 142/153 (92.8%) | 140/154 (90.9%) |
| Held-out exact | 123/157 (78.3%) | 123/156 (78.8%) | 121/153 (79.1%) | 122/153 (79.7%) | 117/154 (76.0%) |
| Held-out subject or member | 149/157 (94.9%) | 148/156 (94.9%) | 144/153 (94.1%) | 147/153 (96.1%) | 144/154 (93.5%) |
| Mode correct | 109/157 (69.4%) | 106/156 (67.9%) | 106/153 (69.3%) | 108/153 (70.6%) | 109/154 (70.8%) |
| Time per photo, this Mac (ms) | 153 | 91 | 49 | 57 | 45 |

Precise-mode crop problems at 4:5 (single to best candidate): intruder 39 to 22 (YOLO seg), 38 to 21 (Seg Medium), 31 to 12 (Seg Medium boxes only); extremity 43 to 15, 38 to 12, 38 to 11; head cut 14 to 3, 13 to 2, 12 to 2.

## Threshold tuning (8 Nov)

Medium and Nano found about 9% more people than YOLOv8m at 0.5 (small background figures), which lowered mode correct and raised intruders. The first pass tried 0.6 and 0.7 but could not compare them, because fewer photos had two or more people at a higher threshold. This pass fixes that.

Method:

- Fixed denominator. Every configuration is scored on the same 160 photos: the ones YOLOv8m scored (two or more people at 0.5 and a matching label), listed by name in a text file and passed to `python -m src.subject_training evaluate <dir> --photos <file> --model medium --threshold 0.75`. A photo where a configuration finds only one person still counts, scored honestly (subject right only if that person is the label; mode right only if the label is single). A photo whose label matches no detection counts as a miss. A photo with no person at all would count as a miss too (none occurred at any threshold). Every figure below is out of 160.
- Detect once, filter after. Each size was run once at 0.5 and the saved detections were filtered at each higher threshold, with the face fallback re-applied if everything was filtered out. At 0.5 this reproduces the earlier Medium row exactly (116 exact, 106 mode, 13 intruders). Nano's 0.5 row differs slightly from the table above (120 exact, 106 mode, against 122 and 108) because that table scored Nano on its own 160 photos, not YOLO's.
- Sizes: Nano and Medium (fast mode, boxes). Thresholds 0.5 to 0.8 in steps of 0.05 up to 0.8 (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8). Balls stay at 0.25.
- Shipped weights are the YOLO-tuned defaults. Held-out columns re-fit the weights on the other four of five folds, including the mode and crop figures. Intruders are the best candidate crop at 4:5, or at 9:16 where stated.

Sweep, shipped (hand-set) weights unless marked held-out:

| Config | People found (218 photos) | Exact | Held-out exact | Mode correct | Held-out mode | Labelled members framed | Intruder 4:5 | Intruder 9:16 | Head cut 4:5 |
|---|---|---|---|---|---|---|---|---|---|
| YOLOv8m, 0.5 | 975 | 124 | 123 | 116 | not measured | 109/133 | 9 | 14 | 3 |
| Nano, 0.5 | 1024 | 120 | 123 | 106 | 111 | 98/125 | 15 | 19 | 2 |
| Nano, 0.55 | 949 | 118 | 121 | 106 | 111 | 98/123 | 14 | 18 | 2 |
| Nano, 0.6 | 887 | 118 | 121 | 106 | 111 | 98/123 | 13 | 17 | 2 |
| Nano, 0.65 | 821 | 118 | 121 | 107 | 113 | 98/122 | 14 | 18 | 2 |
| Nano, 0.7 | 761 | 119 | 122 | 106 | 112 | 97/120 | 12 | 17 | 2 |
| Nano, 0.75 | 694 | 120 | 123 | 104 | 109 | 95/115 | 10 | 13 | 2 |
| Nano, 0.8 | 618 | 118 | 122 | 106 | 110 | 93/113 | 9 | 12 | 2 |
| Medium, 0.5 | 1064 | 116 | 118 | 106 | 109 | 102/129 | 13 | 18 | 2 |
| Medium, 0.55 | 996 | 116 | 118 | 108 | 111 | 103/126 | 12 | 15 | 2 |
| Medium, 0.6 | 932 | 118 | 120 | 110 | 112 | 103/123 | 12 | 15 | 2 |
| Medium, 0.65 | 877 | 116 | 118 | 111 | 111 | 102/121 | 11 | 15 | 2 |
| Medium, 0.7 | 805 | 116 | 119 | 109 | 110 | 100/116 | 11 | 11 | 2 |
| **Medium, 0.75** | 757 | 116 | 119 | 109 | 110 | 99/115 | 9 | 10 | 2 |
| Medium, 0.8 | 681 | 116 | 119 | 108 | 109 | 97/112 | 7 | 11 | 2 |

With re-fitted (held-out) weights the intruder counts at 4:5 and 9:16 are: Medium 0.5 14 and 21, 0.65 13 and 19, 0.75 9 and 14, 0.8 8 and 15; Nano 0.5 14 and 20, 0.75 10 and 15, 0.8 9 and 14. YOLOv8m's are 9 and 14 with its own shipped weights. For Medium 0.75, subject or member is 142 with shipped weights and 144 held-out, against YOLOv8m's 150 and 149.

What the sweep shows:

- Intruders fall steadily as the threshold rises, because the small background figures are the ones dropped. Medium reaches YOLO's level of 9 (4:5) at 0.75 and 7 at 0.8. Nano gets there only at 0.8.
- Exact subject does not move with the threshold (Medium sits at 116 to 118 throughout). The eight regressions in "Regressions by photo" are not caused by the extra background people.
- Mode correct improves only a little: Medium peaks at 110 to 111 (0.6 to 0.65) and settles at 109 from 0.7. Nano never gets past 107. Neither reaches YOLO's 116 with the hand-set weights. The duel and group decision (`subject_modes.py`) is tuned to YOLO's detections, and I tried its one loose constant (`MIN_RELATIVE_IMPORTANCE`, 0.25 to 0.6): it does not help (111 at 0.25, 110 at 0.3, 106 or lower above that).
- The cost of a high threshold is labelled people dropped. Of the 170 labelled subjects, Medium finds 169 at 0.5, 167 at 0.6, 163 at 0.65, 160 at 0.75 and 160 at 0.8 (YOLOv8m 170). Labelled members framed fall from 102 to 99 between 0.5 and 0.75. Beyond 0.75 the intruder gain is small and the member loss continues, so the sweep stops at 0.8.
- Nano is no better than Medium on the measure that matters. At 0.75 it has 120 exact against 116, but mode correct is 104 against 109 and its held-out mode is 109 against 110. At no threshold does Nano combine a mode score near 110 with intruders near 9.

### Choice

RF-DETR Medium at a person threshold of 0.75, with re-fitted weights. Only Medium at 0.75 or above has both mode correct around 110 and intruders at YOLO's level, so Nano's speed advantage (about 1.7 times YOLO on CPU against 3 times for Medium) is not traded for here. 0.65 has one more mode-correct photo (111) but two more intruders at 4:5 (11) and four more at 9:16 (15), and with re-fitted weights its intruders are 13 and 19, so 0.75 is better on crop quality for the same mode score. Segmentation (precise) sizes were not swept and keep 0.5.

### Re-fitted weights

`python -m src.subject_training train` on the RF-DETR Medium output at 0.75 (143 photos with two or more people and a matched label) scored 91% with the code-default weights and 92% held out after re-fitting, so its own guard allowed the save. `config/subject_weights.json` now ships the fitted weights (size 1.60 to 2.23, sharpness 0.70 to 1.03, centrality 0.40 to 0.88, elevation 0.00 to -0.30, the rest within 0.15). The baseline on the training set is not the same as the 160-photo set, so use these figures instead:

| Fixed 160 photos, Medium | Exact | Subject or member | Mode correct | Members framed | Intruder 4:5 | Intruder 9:16 |
|---|---|---|---|---|---|---|
| 0.5, hand-set weights (first pass) | 116 | 144 | 106 | 102/129 | 13 | 18 |
| 0.75, hand-set weights | 116 | 142 | 109 | 99/115 | 9 | 10 |
| 0.75, re-fitted weights, held-out | 119 | 144 | 110 | 90/115 | 9 | 14 |
| 0.75, re-fitted weights as shipped (trained on these photos) | 119 | 144 | 111 | 91/115 | 9 | 14 |
| YOLOv8m, 0.5, hand-set weights | 124 | 150 | 116 | 109/133 | 9 | 14 |

The shipped row is partly in-sample because 143 of the 160 photos were used to fit the weights. The held-out row is the honest estimate of how well the same weights do on new photos. Compared with hand-set weights at the same threshold, the held-out re-fit gains three exact photos (119 against 116) and one mode photo (110 against 109), loses some labelled members (90 against 99) and has more 9:16 intruders (14 against 10). It is a modest gain at best, which is why the club-football check in the follow-ups matters.

### Did duel and group framing recover?

Partly. Mode correct went from 106 to 111 of 160 (66.2% to 69.4%; 110 held out) against YOLOv8m's 116 (72.5%), so the gap closed from ten photos to five. One photo is 0.6 points, so the remaining five-photo gap is about 3 points and is inside what a different annotator or set could move. Labelled members framed is 91/115 (79%) against 109/133 (82%) for YOLO, with 94% of framed people being labelled members (91 of 97, YOLO 109 of 114). Intruders recovered fully (9 and 14, the same as YOLOv8m). Exact subject went from 116 to 119 against 124. Nothing in the sweep or the re-fit closes the last five mode photos; that would need a re-tune of the duel and group rules on labels made from RF-DETR boxes.

The cost of 0.75: on 3 of the 218 photos nobody clears the threshold, so the engine returns "No subject detected" and leaves the photo uncropped. YOLOv8m found someone on all 218. The three are `000000000149` (best person 0.72, YOLO found 1), `000000000201` (0.64, the distant figure, YOLO found 1) and `b95e542a5ac525bc` (0.56, YOLO found 3). Only `b95e542a5ac525bc` is in the fixed 160, where it already counts as a miss; the other two are single-person photos outside it, so the table does not show them. Fixed in the next commit: when nobody reaches 0.75, the detector keeps the single most confident person above 0.5 (`FALLBACK_PERSON_THRESHOLD`). All three photos now get a person (0.72, 0.64, 0.56), and the fixed 160 score exactly as before (exact 119, mode 111, intruders 9 at 4:5 and 14 at 9:16), because only photos with nobody at 0.75 are affected.

## Timing

Measured on the same Mac, `detect_scene` per photo (including the sharpness and kit colour work), 218 photos:

| Detector | Device | ms per photo |
|---|---|---|
| YOLOv8m (box) | CPU | 108 (93 for the model call alone) |
| YOLOv8m-seg (tight) | CPU | 153 |
| RF-DETR Nano, Small, Medium, Large | MPS | 34, 30, 35, 43 |
| RF-DETR Seg Small, Medium, Large (tight) | MPS | 91 (median 57), 49, 57 |

Model call only, 30 photos, forced CPU: Nano 155 ms, Medium 306 ms, Large 472 ms, Seg Medium 759 ms. Medium on MPS is 45 ms in the same harness.

PyTorch selects MPS for RF-DETR on its own. Windows builds are CPU only, so a Windows machine will see roughly three times YOLOv8m's per-photo cost at Medium (Nano is about 1.7 times). If Windows timing proves too slow, Small or Nano can be set in `DETR_MODELS` with no accuracy penalty visible on this set.

The packaged macOS engine: 9 photos (including loading the model and starting the process) took 3.2 s in fast mode and 3.6 s in precise mode, against about 4 s on YOLOv8 in the brief. The Check Setup photo takes 2.9 s end to end after the first launch. The very first launch of a freshly built engine took 29 s while macOS checked the new binaries.

## Masks

Where masks are used, in the whole of `src`:

- `bbox_from_mask` produces the tight box in precise mode. That is the only consumer. `Detection.mask` is stored but nothing reads it afterwards.
- Sharpness is measured on a core box of the person's bounding box (`SHARPNESS_CORE`), not on mask pixels. Kit colour is a box region too. Neither needs a mask.

Do the masks help? Same detector, tight box on or off, Seg Medium:

- Exact subject 114/153 with tight boxes against 112/154 with plain boxes; held-out 121 against 117. A gain of one to two photos, inside the noise.
- Crop problems at 4:5: intruder 21 with tight boxes against 12 with plain boxes, extremity 12 against 11, head cut 2 against 2, low head 0 against 3. Tight boxes make the intruder problem worse. The same pattern appears with YOLO (intruder 22 with masks against 9 for plain boxes).

So a segmentation model is not required for accuracy. The Medium box model (no masks) matches or beats the tight-box result on crop quality and costs a third less per photo. Decision: fast mode uses RF-DETR Medium. Precise mode keeps Seg Medium for now, because "Precise mode (slower, tighter subject outline)" is an option in the Lightroom plugin dialog and in the GUI, and removing it would change the plugin and its Lua tests. The numbers argue for retiring Precise mode in a follow-up, which would also drop a 140 MB weights file from the bundle.

If Precise mode stays, Seg Large is the better pick on this set (exact 117/153, held-out member 147/153) for 8 ms more on MPS, but it is untested on CPU and I did not change the default.

## Choice

RF-DETR Medium (fast, person threshold 0.75, re-fitted weights) and Seg Medium (precise, threshold 0.5).

- Accuracy across the four Apache detection sizes is indistinguishable on 160 photos; the spread between sizes (73 to 77%) is as large as the gap to YOLO.
- Speed on MPS is the same for Nano, Small and Medium (30 to 35 ms) and only Large is slower (43 ms), so there is no speed reason to go smaller on a Mac.
- Medium has the best published COCO accuracy of the three cheap sizes (AP 54.7, against 53.0 for Small and 48.4 for Nano in the RF-DETR README), the best members-framed count here (102/129), and it is the size with a matching Seg Medium.
- Large is 20% slower and not more accurate on this set.

## Regressions by photo

With the shipped (YOLO-tuned) weights, Medium misses the labelled subject on eight photos that YOLOv8m got right and fixes two that it got wrong. New misses: `000000000149`, `000000000488`, `26557008b4fcf408`, `808b2e2e75d9de86`, `a0da01a93a6f51bf`, `c29ffd28eb6cb7e0`, `e6c55fe004472ec9`, `ebf12f432ddd2e7f`. Fixed: `bc2a5f48aa368491`, `c6335522c8e718cb`. In precise mode Seg Medium has seven new misses and five fixes.

Why:

- RF-DETR and YOLO agree on the people they both find: 910 of 975 YOLO person boxes have an RF-DETR box at IoU 0.5 or better, and the median best IoU is 0.96.
- RF-DETR finds more people, 1064 against 975 at the same 0.5 threshold, because it picks up small background figures that YOLO drops. 156 RF-DETR boxes match no YOLO box. In 58 photos RF-DETR finds more people than YOLO; in 26 it finds fewer.
- A photo such as `000000000149` has 1 person for YOLO and 4 for RF-DETR, so the same Smart Select weights now see more rivals. Weights fitted to YOLO's score and size distributions do not transfer perfectly. The held-out rows show the gap closing when the weights are re-fitted (73.8% against 76.9% in fast mode, and ahead of YOLO in precise mode), which is why re-running `python -m src.subject_training train` on the RF-DETR output is the first follow-up.
- Raising the person threshold looked unhelpful in the first pass (Medium: 0.6 gave 74.8% exact on 155 photos, 0.7 gave 75.0% on 144 photos) only because the scored set shrank with it. On a fixed 160-photo denominator it removes the intruder problem and part of the mode gap; see "Threshold tuning". It does not change which labelled subject is picked.
- Precise mode: `000000000201` (a distant figure about 2% of the frame wide) gives `no_subject` in the packaged engine. YOLOv8m-seg also returns nothing on that photo, so it is not a regression, but fast mode finds the person.

## Caveats

- The labels were made by one annotator against YOLOv8m boxes (`docs/research/phase1-results.md`), so the label matching leans towards YOLO. The 160-photo set is sports photos from Open Images and coco128, not our own clubs.
- Ball detection is similar (155 to 187 balls against 164 for YOLO) and ball-cut problems are about the same after candidate ranking (0 to 2 photos).
- The first-pass tables use the YOLO-tuned Smart Select weights. A re-fitted `config/subject_weights.json` ships from the threshold tuning; it was fitted on the same sports set it is scored on, so its held-out row is the number to trust, and a club-football set should confirm both.

## Weights and bundle size

- Roboflow's Medium checkpoint is 405 MB because it carries optimiser state. `slim_weights.py` keeps only the model and args, giving 135 MB, and detections on 25 test photos matched the original to the pixel. The build then bundles `rf-detr-medium-slim.pth` (132 MB) and `rf-detr-seg-medium-slim.pt` (140 MB). The new filename also stops `rfdetr` logging an MD5 mismatch warning for the modified file.
- A source checkout with no bundled weights lets `rfdetr` download the full files into `~/.roboflow/models`.
- Packaged macOS engine (`FRAMEPILOT_ENGINE_ONLY=1`, arm64): `_internal` is 1,055,644 KB (about 1.0 GiB), against 955,360 KB for the engine currently installed in `~/FramePilot`. The 370 MB figure in the brief does not match that installed folder, which is 933 MiB. Largest items now: torch 510 MB, the two weights files 271 MB, cv2 121 MB, transformers 47 MB, scipy 36 MB. The old build carried 105 MB of YOLO weights and 152 MB of polars (an Ultralytics dependency).
- Zipped, the new macOS engine folder is 554 MB (the CI artefact is 552 MB) against 390 MB for the engine installed today; the CI Windows zip is 665 MB. The Windows smoke test (version, a crop job on the check photo and the position check, on a CPU-only runner) finished in about 8 seconds.
- The build needed three spec changes that the old Ultralytics setup did not: scipy and transformers come out of the exclude list (RF-DETR imports both), transformers' docstring decorators read RF-DETR's source at import time so the `.py` files are bundled, and `copy_metadata` is added so `--version` can report the `rfdetr` and `opencv-python` versions. The first PyInstaller build finished without error and the frozen engine then failed at the first photo with `No module named 'scipy'`, then with `could not get source code`; a build reporting success was not enough, so the CI smoke test (which already runs a real crop job) is the guard.

## Follow-ups

1. Check the re-fitted weights and the 0.75 threshold on a club-football set (done on the sports set only). Re-tune the duel and group rules in `subject_modes.py` on labels made from RF-DETR boxes, since five mode photos remain against YOLO. Sweep the threshold for the Seg sizes, which stay at 0.5.
2. Decide on retiring Precise mode and its second weights file.
3. Decide on the OpenCV FFmpeg licence exposure noted above (pre-existing).
4. Check Windows CPU timing once CI produces a Windows build. Nano is the fallback if it is too slow, but at any threshold it gave worse mode correct than Medium, so expect to lose about five mode photos.
