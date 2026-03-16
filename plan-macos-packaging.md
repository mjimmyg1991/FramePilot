# Plan: macOS App Packaging for FramePilot

## Goal
Make FramePilot downloadable as a `.dmg` installer for macOS (Apple Silicon).

---

## Step 1: Create macOS icon (`.icns`)
- **File:** `branding/framepilot.icns`
- Generate from existing `FramePilot Icon Mark.png` using a Python script in CI (since we can't use macOS `iconutil` cross-platform)
- On the macOS CI runner, use `sips` + `iconutil` to create the `.icns` from the PNG

## Step 2: Update PyInstaller spec for cross-platform support
- **File:** `framepilot.spec`
- Add `sys.platform` detection to:
  - Use `.icns` on macOS, `.ico` on Windows
  - Add a `BUNDLE` step (macOS only) that wraps COLLECT output into `FramePilot.app`
  - Set `bundle_identifier='com.framepilot.app'`
  - Set `info_plist` with `NSHighResolutionCapable: True`, version, min macOS version
- Remove Windows-only flags behind platform guard

## Step 3: Fix log path for macOS `.app` bundle
- **File:** `app.py`
- When frozen on macOS, write logs to `~/Library/Logs/FramePilot/` instead of next to the executable (which is inside the `.app` bundle and may not be writable)

## Step 4: Add macOS build job to GitHub Actions
- **File:** `.github/workflows/build.yml`
- Add `build-macos` job on `macos-latest` (ARM64 runner):
  1. Checkout + setup Python 3.13
  2. Install requirements + PyInstaller
  3. Download YOLO models
  4. Run tests
  5. Build with PyInstaller
  6. Install `create-dmg` via Homebrew
  7. Create `.dmg` with drag-to-Applications layout
  8. Upload `FramePilot-macOS.dmg` as artifact

## Step 5: Add GitHub Release job
- **File:** `.github/workflows/build.yml`
- Add `release` job (runs after both build jobs, only on `v*` tags)
- Downloads Windows `.zip` + macOS `.dmg` artifacts
- Creates a GitHub Release with both files attached
- You get a Releases page with download links

---

## Files Changed

| File | Action |
|------|--------|
| `framepilot.spec` | Edit — add macOS BUNDLE target + platform-aware icon |
| `app.py` | Edit — macOS-friendly log path |
| `.github/workflows/build.yml` | Edit — add macOS build + release jobs |

## What You Get
Push a tag like `v0.1.0` → GitHub builds both platforms → download `.dmg` from Releases → drag to Applications → done.

## Not Included (future)
- **Code signing / notarization** — requires $99/year Apple Developer account. Without it, users right-click → Open to bypass Gatekeeper.
- **Auto-update** — could add Sparkle framework later.
- **Intel Mac support** — builds ARM64 only (all new Macs are Apple Silicon).
