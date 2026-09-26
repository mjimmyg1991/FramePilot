# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for FramePilot."""

import os
import sys
from pathlib import Path

block_cipher = None

# Get paths to required packages
import customtkinter
import cv2

customtkinter_path = Path(customtkinter.__path__[0])
cv2_path = Path(cv2.__file__).parent

# OpenCV haar cascades path
haarcascades_path = Path(cv2.data.haarcascades)

# Project root
project_root = Path(SPECPATH)

DETECTION_HIDDEN_IMPORTS = [
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
]

EXCLUDED_MODULES = [
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
]

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
        *DETECTION_HIDDEN_IMPORTS,
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
    excludes=EXCLUDED_MODULES,
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
    icon=str(project_root / 'branding' / 'framepilot.ico'),
)

# Headless engine for the Lightroom Classic plugin. A console exe so the plugin
# can wait for it to finish; it shares the GUI's bundled models and libraries.
engine = Analysis(
    ['engine.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=DETECTION_HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDED_MODULES,
    cipher=block_cipher,
    noarchive=False,
)

engine_pyz = PYZ(engine.pure, engine.zipped_data, cipher=block_cipher)

engine_exe = EXE(
    engine_pyz,
    engine.scripts,
    [],
    exclude_binaries=True,
    name='framepilot-engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=str(project_root / 'branding' / 'framepilot.ico'),
)

coll = COLLECT(
    exe,
    engine_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    engine.binaries,
    engine.zipfiles,
    engine.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FramePilot',
)
