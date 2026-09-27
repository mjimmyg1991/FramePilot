# Sports Photo Composition: Research Brief for FramePilot Subject Selection

**Prepared**: 27 Sep 2026
**For**: the FramePilot session redesigning the subject selection module
**Method**: three parallel research passes (photographer and editor craft, computer vision and auto-crop literature, competitor tools and implementable signals), cross-referenced. Where a claim rests on one source, it is flagged.

> Section 1 was checked against branch `claude/affectionate-hamilton-pe63i0` at 1ce46ed ("Make Smart Select sports-aware and trainable"). If the branch has moved on, trust the code.

---

## 0. TL;DR for the implementer

1. **Replace "pick the best box" with "rank people, then score candidate crops."** Detection confidence × sharpness is a detection-quality score, not an importance score. Pros choose by story: ball, face, peak action, emotion.
2. **Subject is a mode, not always a person.** There are three: single player, duel (2 players contesting the ball), group (celebration, huddle, team photo). Decide the mode first, then frame.
3. **The ball is the cheapest strong importance signal, but stock YOLO finds it poorly** (about 36% correct in one football study). Use it as a boost when found and never as a gate.
4. **Hard crop constraints matter more than placement finesse:** never cut at a joint, never cut the ball, never cut the subject's face or hands at the edge, and push intruding limbs fully out or keep them fully in.
5. **Don't hard-code rule of thirds.** Research shows it barely predicts preference. Use lead room in the direction of play and headroom, and otherwise keep visual weight balanced.
6. **Licence flag:** Ultralytics YOLOv8 (including seg and pose) is AGPL-3.0. Shipping it in a closed $49 app needs an Ultralytics Enterprise licence or a swap to Apache or MIT models. Decide this before adding more Ultralytics models.

---

## 1. Current state (branch at 1ce46ed)

**Already done (matches this research):**
- `detect_scene()` returns people and sports balls (COCO 32).
- Sharpness is measured on each person's head and torso core at a common scale.
- `subject_scoring.py`: per-person features (relative size, sharpness, confidence, centrality, side and top frame cut-off, ball proximity, closest to ball), weighted by `SubjectWeights`.
- `subject_training.py`: label, evaluate and train (softmax, L2 pull to the current weights, saves only on held-out gains) into `config/subject_weights.json`. Accuracy went from 3/10 to 8/10 on a coco128 sports subset.
- The crop sizes to subject plus padding, with `HEADROOM_SHARE` and `MIN_CROP_SCALE`.

**Gaps this research points at:**
- subject **modes** (duel, group or celebration versus single)
- **referee and crowd suppression**
- **EXIF AF point** as an intent signal
- **pose**: joint-safe crop edges, facing direction and lead room, celebration and action intensity
- **candidate-crop scoring** with edge intruders and extremity clipping (the crop is currently one computed window, not a scored set)
- team kit
- the **AGPL licence** decision
- evaluation on real club photos rather than coco128

Because trainable weights exist, the hand weights in section 6 are only a sanity check on relative importance. Add new signals as features to `SubjectWeights` and let `train` set their weights.

---

## 2. What makes a strong sports frame (craft consensus)

Confidence: **High** means 3+ independent sources agree. **Med** means 2 sources agree. **Low** means a single source or opinion.

| # | Rule | Conf. | What it means for code |
|---|------|-------|------------------------|
| R1 | Peak action is the subject: ball contact, apex of jump, the save or the shot. | High | Favour the player closest to the ball and the most extended pose. |
| R2 | The emotional peak lands just after the action (celebration, dejection) and is equally valid. | High | A celebration is its own mode: arms raised, open mouth, no ball needed. |
| R3 | Face and ball both visible is the default keeper standard. It's a soft rule, and emotion overrides it. In a header the ball must read close to the head. | High | Score face visibility and ball-in-crop. Never reject a crop outright for a missing ball. |
| R4 | Eyes and expression outrank the ball; eyes must be sharp. | High | Measure sharpness on the head region, not the whole body box. |
| R5 | Duels and 50-50 contests are a subject in their own right. | Med | Treat 2 players within touching distance of each other or the ball as one subject. |
| R6 | Lead room: leave more space in front of a moving or looking subject. In verticals keep the subject in the middle or upper band so they aren't "lost at the bottom". Centred is fine for tight celebration crops. | High | Offset the crop toward facing direction or ball side. Bias the subject's head into roughly the top 25-45% of the frame. |
| R7 | Never crop at a joint (ankle, knee, elbow, wrist, shoulder). Cut mid-shin, mid-thigh or mid-forearm instead. | High (4+) | Hard constraint on crop edges when keypoints are available. |
| R8 | Don't clip hands or feet at the edge unless it's deliberate. | Med | Penalise a subject's extremity touching a crop edge. |
| R9 | Remove clutter: other players' limbs creeping in, referee arms, ad boards and crowd behind the head. Referee arms specifically is single-source. | High / Low | Penalise partial non-subject people at crop edges. Detect and deprioritise officials. |
| R10 | Level the horizon or pitch lines first. | Med | Out of scope for selection, but a candidate feature (FramePilot already writes XMP). |
| R11 | Tighter usually means more impact, but tightness should follow the story. This is contested. | Med | Tight is the default for single and celebration. Go looser for duel, group and "context" shots. |
| R12 | A group is the subject when the story is the group: pile-ons, huddles, team photos, coin toss. | Med | Group mode requires overlapping or clustered people and a similar scale. |
| R13 | Crowd and coaches are atmosphere, rarely the primary action subject. | Med | Suppress small people at the frame edges and in the stands by default. |
| R15 | Vertical reframing is a deliberate recomposition. No wire agency (Getty, AP, Reuters) has published vertical-sport crop rules. | Gap | We are defining the standard; there is none to copy. |
| R17 | AFL marks, dunks and netball goals are isolated at the apex. Basketball puts the hoop on a thirds line (2 sources). No AFL placement rule was found. | Med / Gap | Treat a jump apex as a high "action intensity" signal. |

**Contested:** how tight to crop; whether the ball is essential (every source says "ideally" and then caveats); tight mid-motion cuts where a foot exits the frame (forum-only acceptance).

---

## 3. What the research literature says

- **Rule of thirds barely predicts preference.** In Amirshahi et al. 2014 (*Art & Perception*), computed thirds-adherence had a minor, largely insignificant correlation with aesthetic ratings. McManus et al. 2011, replicated in 2015, found people prefer crops with **balanced saliency**. One SIGGRAPH Asia 2023 poster found centred often beats thirds for portrait-style frames (single source). **Takeaway:** use lead room and headroom, not thirds snapping.
- **Crop scoring pattern: GAIC** (TPAMI 2020). Generate fewer than 100 anchor candidate crops and score each, rather than regressing one box. It is the right complexity for a desktop batch tool. VLM croppers (ProCrop 2025, CROP, Venus CVPR 2026, COMEX) are state of the art but too slow and costly per photo for this product.
- **Human-centric cropping** (bcmi, arXiv 2207.10269, ECCV 2022) scores crops using 9 partitions relative to the human box. It's a good template for where the edges should fall around a chosen person.
- **Aspect ratio as a first-class input** (arXiv 2212.14561): compute 4:5 and 9:16 as separate searches, not one crop recut.
- **Who is important:** PersonRank (arXiv 1711.01984) ranks people with a graph of interactions and includes a basketball dataset. H2V (arXiv 2101.04051) is the closest analogue: horizontal-to-vertical conversion on football-style footage, with a "Rank-SS" subject ranker using location, appearance and saliency. **H2V is worth reading in full.**
- **AutoFlip (Google MediaPipe)** uses per-object-type weights (face > person > ball > text, tunable per sport), then keeps the weighted centroid in frame. This pattern transfers directly to stills.
- **Saliency maps fail on sport:** crowds, ad boards and text pop out. Stay with person detection plus ranking rather than generic saliency.
- **Joint-aware cropping has no published method.** Keypoint-constrained crop edges would be original work, which makes it a differentiator.

---

## 4. Competitors (all portrait-shaped, none sport-aware)

| Product | Subject and crop logic | Gap |
|---|---|---|
| Aftershoot | "Athlete in motion" detection, Aggressive Cropping mode | Near-identical crops across a batch, no ball or celebration logic |
| Imagen AI | Crop, Portrait Crop and Headshot Crop tools with headroom rules, per-image pricing | Wedding and portrait conventions |
| Capture One (Jan 2026) | AI Crop copies a manual reference crop's subject position to the rest of the batch | Needs a human reference crop, doesn't select |
| Evoto | AI Locate, head size and face position per ratio | Portrait assumptions |
| Lightroom / Camera Raw | Select Subject plus Generative Expand. There is no autonomous "pick subject and crop" feature; the community request is still open | Manual |
| PhotoShelter | Player tagging (face + roster), "intelligent cropping" (marketing copy only) | Unverified |
| FilterPixel DeepCull for Sports | Sport-specific, but culling only | No crop |

**Positioning:** a crop selector that knows about the ball, celebrations and team kit is open ground. Joint-safe edges and a "favour our club" mode are the novel parts.

---

## 5. Signals, ranked by cost

| Signal | How | Cost | Reliability | Licence |
|---|---|---|---|---|
| Person boxes, masks, confidence | existing YOLOv8m-seg | already paid | good | **AGPL** |
| Head-region sharpness | Tenengrad (Sobel variance) on the top ~20% of the mask or bbox, instead of Laplacian on the whole box | trivial | better than Laplacian per comparative study | n/a |
| Ball | COCO class 32 in the same pass | free | **poor** on small or blurred balls (~36%, 2 sources) | AGPL |
| Ball (better) | SAHI 2×2 tiling or fine-tuned football-ball model | ~4× inference for tiling | mAP@0.5 ~0.92 in one pipeline | SAHI MIT; datasets vary |
| Player-ball distance ("possession") | nearest person centroid or feet to ball | trivial | standard in football analytics | own code |
| Referee and crowd suppression | kit-colour outlier + small scale + frame edge or stands position | cheap | standard filter step | own code |
| Team ID ("favour our club") | k-means (k=2) on torso HSV, or embeddings from the existing CLIP encoder | cheap | k-means is the baseline (2 sources) | own code |
| Pose keypoints | RTMPose (Apache-2.0, fast on CPU), MediaPipe (Apache-2.0), or YOLOv8-pose (AGPL) | moderate | good on a clear subject, weaker in crowds | see left |
| From pose: facing direction, limb extension ("action intensity"), arms raised (celebration), joint positions (crop constraint) | geometry on keypoints | trivial once pose is available | | |
| Face visible and size | existing face fallback or MediaPipe | cheap | good | Apache |
| Photographer's AF point | exiftool maker notes (Canon, Nikon, Sony) | cheap per file, but needs the exiftool binary | strongest intent signal when present; stripped by some exports; Nikon partly encrypted, Sony under-documented | exiftool free to call externally |

**The AF point is underrated for FramePilot specifically:** it works on originals with XMP sidecars, so maker notes are usually intact. The person whose box contains the AF point is almost certainly the photographer's subject. Use it as a strong boost when present, with a clean fallback when absent.

---

## 6. Proposed selection design (for the implementer to challenge)

### Step 1: Filter candidates
Drop or deprioritise people who are:
- tiny relative to the largest person (for example under 25% of max height), or
- cut by the image edge with no face visible, or
- kit-colour outliers (likely an official), or
- in the stands region, meaning above a pitch-line estimate or small and dense.

### Step 2: Choose a mode
- **Group:** 3 or more people with overlapping or clustered boxes at similar scale, **or** 2 or more with arms raised and no ball found.
- **Duel:** the top 2 by importance sit within about 1 body-width of each other, or both are within reach of the ball.
- **Single:** everything else.

### Step 3: Score each person's importance (weights are starting guesses, tune on a labelled set)
```
importance =
    0.30 * ball_proximity        # 1 at the ball, decaying with distance in body-heights; 0 if no ball found
  + 0.20 * af_point_hit          # 1 if the EXIF AF point falls inside the box; weight redistributes if no EXIF
  + 0.15 * relative_scale        # height / max person height
  + 0.15 * head_sharpness_rel    # Tenengrad on the head region / max
  + 0.10 * face_visible          # 0..1
  + 0.10 * action_intensity      # limb extension / airborne / arms raised (pose; 0 if no pose)
  × team_bias                    # 1.0 default; e.g. 1.3 for "our club" kit when that mode is on
```
Missing signals redistribute their weight rather than scoring 0, so the current behaviour is the no-extras fallback.

### Step 4: Generate and score candidate crops (GAIC-style)
For each target aspect separately, generate about 50-100 windows at several scales (tight, medium, loose) and offsets that contain the subject core (head plus torso, plus the ball if found and within reach). Then score each window:

**Hard rejects:**
- subject face or head cut
- ball cut when the ball is within reach of the subject
- more than about 10% of the subject's mask outside the window (unless the window is a deliberate tight crop)

**Penalties:**
- an edge within about 3-5% of window height of a subject joint keypoint (ankle, knee, hip, wrist, elbow, shoulder)
- subject hand or foot touching an edge
- a non-subject person partly inside, with the penalty scaled by visible fraction (fully in or fully out is fine)
- subject head below the upper ~45% (verticals)
- lead room on the wrong side: facing or ball side has less space than the back side

**Rewards:**
- subject scale matching the mode's target: tight for single and celebration, medium for duel, loose for group
- balanced visual weight (subject centroid plus ball near the horizontal centre band, per the balanced-saliency finding)

Return the top window, with the next 2 kept as alternates for the GUI (cheap variety, and it fixes the complaint that Aftershoot gives every photo the same crop).

### Step 5: Fallbacks
- no people found: keep the current face fallback, then a centre crop
- no pose: skip the joint and facing terms; approximate lead room from the ball side
- no ball: importance runs on the remaining terms

---

## 7. Phasing (shortest useful path first)

Already on the branch: ball as a boost, possession distance, core sharpness, frame cut-off, trainable weights.

1. **No new models:** referee and crowd filtering, mode selection (single, duel, group), GAIC-style candidate-window scoring with the edge-intruder, extremity and headroom terms, and lead room from the ball side. Optionally try Tenengrad against the current core sharpness and keep it only if `evaluate` improves.
2. **EXIF AF point** via exiftool when the binary is present, added as a feature so `train` can weight it.
3. **Pose** (pick the model *after* the licence decision): joint-safe edges, facing direction, celebration detection, action intensity.
4. **Team kit clustering** for a "favour our club" toggle.
5. **Better ball detection** (SAHI or fine-tune), only if the labelled set shows ball misses are the main error.

**Evaluation:** use the existing `subject_training label` and `evaluate` commands on 100-200 of our own club photos (Royals, Gully, Redbacks, juniors). For each, record the correct subject, the mode, and one acceptable 4:5 crop. Measure subject-pick accuracy, then crop IoU and Acc@3 (is an acceptable crop in the top 3). Keep this as the regression check for every weight change.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| AGPL exposure in a paid closed app (Ultralytics own licence page + GitHub issue #19390) | Buy an Ultralytics Enterprise licence, or migrate to RF-DETR or YOLOX (Apache-2.0) for detection and RTMPose or MediaPipe (Apache-2.0) for pose |
| Ball detector misses make the ranking worse than today | Ball is a boost only, never a gate; check against the labelled set |
| Weights overfit to football | Keep per-shoot-type weight tables in `presets.py` (sports, wedding, portrait already exist) |
| Pose slows batch runs on CPU | Run pose only on the top 3 candidates and inside the candidate crops, not the full frame |
| 2026 arXiv IDs cited from a research pass (ProCrop 2505.22490, CROP 2605.12545, COMEX 2608.07570, DensFiLM 2607.25465) | Verify before citing anywhere public; none of the recommendations depend on them |

---

## Sources

**Craft**
- [Aftershoot: sports photo editing tips](https://aftershoot.com/blog/sports-photo-editing-tips/)
- [Digital Photography School: football/soccer](https://digital-photography-school.com/tips-for-photographing-football-soccer/)
- [Digital Camera World: soccer like a pro](https://www.digitalcameraworld.com/uk/tutorials/how-to-photograph-soccer-like-a-pro)
- [Jeff Vogan: action shots](https://www.jeffvoganphotography.com/Blog/Mastering-Action-Shots-Essential-Tips-for-Sports-Photography)
- [TTL Sports: composition](https://www.ttlsports.com/composition-techniques-for-sport-photography)
- [PetaPixel: Blair Bunting on tension and motion](https://petapixel.com/2022/10/21/capturing-tension-and-motion-in-commercial-sports-photography/)
- [SLR Lounge: AFL with Michael Wilson](https://www.slrlounge.com/capturing-incredible-football-photos-afl-michael-wilson/)
- [ClickCommunity: avoiding limb chops](https://www.theclickcommunity.com/blog/how-best-crop-photos-avoiding-limb-chops-great-compositions/)
- [Tuts+: when to crop limbs](https://photography.tutsplus.com/tutorials/what-we-expect-to-see-when-to-crop-limbs-in-a-portrait--cms-22349)
- [LensVid: crop for impact](https://lensvid.com/post-processing/sports-photography-tip-crop-for-impact/)
- [Sports in Frame: cropping](https://www.sportsinframe.com/cropping/)
- [PetaPixel: basketball hoop walkthrough](https://petapixel.com/2009/07/14/basketball-hoop-walkthrough/)
- [Wikipedia: Headroom (photographic framing)](https://en.wikipedia.org/wiki/Headroom_(photographic_framing))

**Research**
- [GAIC, TPAMI 2020](https://github.com/HuiZeng/Grid-Anchor-based-Image-Cropping) (arXiv 1909.08989)
- [Human-centric image cropping, ECCV 2022](https://github.com/bcmi/Human-Centric-Image-Cropping) (arXiv 2207.10269)
- [Experience-based direct crop generation](https://arxiv.org/abs/2212.14561)
- [PersonRank](https://arxiv.org/abs/1711.01984)
- [H2V horizontal-to-vertical](https://arxiv.org/abs/2101.04051)
- [AutoFlip docs](https://mediapipe.readthedocs.io/en/latest/solutions/autoflip.html)
- [Amirshahi et al. 2014, rule of thirds](https://pdfs.semanticscholar.org/c060/3b5133ff5c534e0e504af36b9422c47a65f9.pdf)
- [Balanced saliency preference (Frontiers 2015)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4707557/)
- [Rule-of-thirds or centred? SIGGRAPH Asia 2023](https://dl.acm.org/doi/10.1145/3610542.3626121)
- [CrowdFix](https://arxiv.org/abs/1910.02618)

**Tools, signals, licence**
- [Ultralytics licence](https://www.ultralytics.com/license), [issue #19390](https://github.com/ultralytics/ultralytics/issues/19390)
- [Roboflow: tracking the ball](https://blog.roboflow.com/tracking-ball-sports/), [small objects / SAHI](https://blog.roboflow.com/detect-small-objects/)
- [Roboflow: pose model comparison](https://blog.roboflow.com/best-pose-estimation-models/)
- [ExifTool](https://exiftool.org/)
- [Aftershoot sports](https://aftershoot.com/sports-photography), [Imagen crop tool](https://imagen-ai.com/tools/219-photo-crop), [FilterPixel DeepCull Sports](https://filterpixel.com/deepcull-sports), [Capture One](https://www.captureone.com)
