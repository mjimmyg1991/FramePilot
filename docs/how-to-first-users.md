# FramePilot: how to run it on a club shoot

For Josh and Elijah, November 2026. One page. Questions go to Matt.

FramePilot is a Lightroom Classic plug-in. You select horizontal sports photos, pick 4:5 or 9:16, and it crops each one around the action: the player on the ball, a duel, or a group. The crop is a normal Lightroom crop, so you can undo it or drag it with the Crop tool like any other.

It is an internal tool on trial. For November we want to know one thing: does it save time on a real club shoot? So every run gets one line in the field log (last section).

## Set it up once (about 10 minutes)

1. Get the `FramePilot` folder from Matt and put it in your home folder, so you have `~/FramePilot/FramePilot.lrplugin` next to `~/FramePilot/framepilot-engine`. Keep the two together.
2. In Lightroom Classic: **File > Plug-in Manager > Add**, choose `FramePilot.lrplugin`, then **Done**.
3. **Library > Plug-in Extras > Check Setup...** It runs the engine on a test photo and should say it passed. The very first run on a Mac can take a minute or two while macOS checks the engine. After that it takes a second or two.

It needs an Apple silicon Mac. If Check Setup fails, take a screenshot and send it to Matt.

## Each shoot

1. Cull and edit as normal. Crop last: FramePilot crops what you see, edits and all.
2. Select the photos you want vertical and make virtual copies: **Photo > Create Virtual Copy**. The originals stay horizontal for the website and the gallery.
3. Select only the virtual copies, then **Library > Plug-in Extras > Auto-crop Selected Photos...**
4. Pick the aspect ratio: **4:5** for feed posts, **9:16** for stories and reels. Leave Subject on **Smart Select**, Framing on **Balanced**, and keep **Check where each crop landed** ticked.
5. Click **Crop**. In testing, 11 photos took about 20 seconds, so 50 is roughly a minute and a half.
6. Go through the grid. Keep the good crops, fix the rest with the Crop tool (**R**). Count both: that count is the whole point of the trial.

Need both ratios? Make two sets of virtual copies and run each set on its own. Running 9:16 on photos already cropped to 4:5 crops inside the 4:5 crop, which is rarely what you want.

## When something looks wrong

- **"Crop didn't land where expected... the previous crop was put back"**: the plug-in caught its own mistake and undid it. Nothing is broken, but tell Matt which photo. It usually means a rotated or flipped photo.
- **A crop cuts a head or the ball**: fix it by hand and note it in the log. Five or so of those with the file names is useful feedback.
- **Logs**: File > Plug-in Manager > FramePilot > **Show Logs**. Zip the newest folder and send it to Matt. The logs contain copies of the photos, so they stay internal, especially anything with juniors in it.

## Log every run

Add one row to `docs/field-log-2026-11.md` (or send Matt the numbers and he will add it):

| Date | Shoot | Who | Ratio | Photos run | Kept as is | Fixed by hand | Minutes with FramePilot | Minutes by hand (estimate) |
|---|---|---|---|---|---|---|---|---|

For "minutes by hand", time yourself cropping 10 photos by hand once, then scale it up to the number of photos run.
