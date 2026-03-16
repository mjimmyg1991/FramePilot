# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for FramePilot (Windows + macOS)."""

import os
import sys
from pathlib import Path

block_cipher = None
is_macos = sys.platform == 'darwin'

# Get paths to required packages
import customtkinter
import cv2

customtkinter_path = Path(customtkinter.__path__[0])
cv2_path = Path(cv2.__file__).parent

# OpenCV haar cascades path
haarcascades_path = Path(cv2.data.haarcascades)

# Project root
project_root = Path(SPECPATH)

# Platform-specific icon
if is_macos:
    icon_file = str(project_root / 'branding' / 'framepilot.icns')
else:
    icon_file = str(project_root / 'branding' / 'framepilot.ico')

a = Analysis(
    ['app.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # CustomTkinter assets (themes, etc.)
        (str(customtkinter_path), 'customtkinter'),
        # Branding assets
        (str(project_root / 'branding'), 'branding'),
        # Config files
        (str(project_root / 'config'), 'config'),
        # OpenCV haar cascades for face detection
        (str(haarcascades_path), 'cv2/data'),
        # YOLO model files
        (str(project_root / 'yolov8m.pt'), '.'),
        (str(project_root / 'yolov8m-seg.pt'), '.'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        # Ultralytics/YOLO dependencies
        'ultralytics',
        'ultralytics.nn',
        'ultralytics.nn.tasks',
        'ultralytics.utils',
        'ultralytics.utils.callbacks',
        'ultralytics.engine',
        'ultralytics.engine.model',
        'ultralytics.engine.predictor',
        'ultralytics.engine.results',
        'ultralytics.models',
        'ultralytics.models.yolo',
        'ultralytics.models.yolo.detect',
        'ultralytics.data',
        # PyTorch
        'torch',
        'torchvision',
        # OpenCV
        'cv2',
        # Other dependencies
        'lxml',
        'lxml.etree',
        'yaml',
        'rich',
        'typer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary large packages
        'matplotlib',
        'notebook',
        'jupyter',
        'IPython',
        'scipy',
        'pandas',
        # Exclude transformers/CLIP (optional feature, very large)
        'transformers',
        'tokenizers',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FramePilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window - GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FramePilot',
)

# macOS: wrap into .app bundle
if is_macos:
    app = BUNDLE(
        coll,
        name='FramePilot.app',
        icon=icon_file,
        bundle_identifier='com.framepilot.app',
        info_plist={
            'CFBundleDisplayName': 'FramePilot',
            'CFBundleShortVersionString': '0.1.0',
            'CFBundleVersion': '0.1.0',
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '12.0',
            'NSHumanReadableCopyright': 'Copyright © 2026 FramePilot',
        },
    )
