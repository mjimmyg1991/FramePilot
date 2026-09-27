# Phase 1 Results: Subject Selection and Crop Scoring

Follow-up to `sports-photo-composition.md`, section 7, phase 1 (no new models).

## Evaluation set

`eval/sports/subjects.json`, fetched with `python eval/fetch_sports_eval.py <folder>`:

- **Sources:** 195 multi-person sports photos from Open Images V7 validation and 23 from coco128 and Ultralytics' assets.
- **Sports:** football, rugby, AFL, basketball, volleyball, hockey, baseball, cricket, racket and combat sports.
- **Labels:** the subject, the mode, and the members of each duel or group.
- **Labelled (170):** 113 single, 39 duel, 19 group. Another 48 are skipped because the subject is unclear.
- **Scored:** 160 photos, those where YOLO finds 2+ people.
- **Caveat:** one annotator (Claude), working against YOLOv8m boxes. It's a regression check, not club football. The target set is still 100-200 photos of our own clubs.

Every number below comes from `python -m src.subject_training evaluate <folder> --cross-validate`. For duels and groups, picking any labelled member counts as a hit.

## Results

| | Before | After |
|---|---|---|
| Subject pick, all (current weights) | 150/160 | 150/160 |
| Subject pick, single photos | 92/102 | 92/102 |
| Subject pick, held-out (cross-validated training) | 150/160 | 149/160 |
| Single vs duel/group framing | 102/160 (everything single) | 116/160 |
| Duel/group members framed | 58/133 | 109/133 (95.6% precision) |

Crop problems, counted as photos affected out of 160. "Before" is the single computed crop and "after" is the best-scored candidate:

| Problem | 4:5 before | 4:5 after | 9:16 before | 9:16 after |
|---|---|---|---|---|
| Framed person's head cut | 14 | 3 | 38 | 10 |
| Ball in reach cut | 9 | 0 | 11 | 2 |
| Non-subject 20-80% visible | 36 | 9 | 38 | 15 |
| Hands or feet touching an edge | 41 | 9 | 34 | 24 |
| Head below 45% of a vertical frame | 3 | 4 | 4 | 3 |

The ranker optimises these same terms. So the table shows the hard constraints and penalties work, not that the crops look better. A true quality measure needs labelled crops: Acc@3 against one acceptable crop per photo.

## Per item

1. **Referee and crowd signals** (`kit_outlier`, `tiny`, `elevation`, `crowd_density`) were added as `SubjectWeights` features at weight 0. Training learns small weights (kit_outlier +0.10, elevation -0.20) that don't beat the current weights on held-out photos, so no weights file is saved.
   - Officials here already lose on size and edge cut-off: one miss in 160 was an umpire.
   - The subject often wears the unique kit, for example a batter among fielders or a keeper. Kit colour alone is ambiguous.
2. **Subject modes** use the brief's thresholds.
   - A sweep that tuned on half the photos and tested on the other half didn't justify changing them.
   - Main error: 24 of 102 single photos are framed as duels, mostly a batter with the catcher right behind. The two are close but not contesting anything, which no distance rule can separate.
3. **Candidate crops:** about 90 windows per aspect ratio, 1.4 ms per photo.
   - When a duel or group can't fit (common at 9:16), the lead is framed alone, and partners are kept fully in or fully out.
   - Crop weights are hand-set in `CropScoreWeights` until crops are labelled.
4. **Tenengrad** (`eval/compare_sharpness.py`) made no difference:

| Focus measure | Current weights | Cross-validated |
|---|---|---|
| Laplacian, head+torso (kept) | 150/160 | 149/160 |
| Tenengrad, head+torso | 149/160 | 149/160 |
| Tenengrad, head | 149/160 | 150/160 |
| Laplacian, head | 149/160 | 150/160 |

It's worth re-running on club photos, where long lenses make focus a stronger cue.

## Remaining misses

Of the 10 subject misses:
- 5 need pose, meaning a jump apex, a kick or a shot: skater, taekwondo kick, jump drill, squash, cricket.
- 1 is an umpire picked over the batter.
- 1 is a duplicate detection of the same person.
- 3 are close calls between two active players.
