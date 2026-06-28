# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Swimming Competition Results Scraper
# Build on Windows with: pyinstaller timescraper.spec
#
# Requirements (run once before building):
#   pip install pyinstaller customtkinter requests
#

import sys
from pathlib import Path
import customtkinter

# Locate the customtkinter assets folder so PyInstaller bundles them
CTK_PATH = Path(customtkinter.__file__).parent

block_cipher = None

a = Analysis(
    ['timescraper_010.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Bundle all customtkinter UI assets (themes, images, icons)
        (str(CTK_PATH / 'assets'), 'customtkinter/assets'),
        # Bundle config.json if it exists next to the spec file
        ('config.json', '.'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL',
        'PIL._tkinter_finder',
        'requests',
        'urllib3',
        'charset_normalizer',
        'certifi',
        'idna',
        'tkinter',
        'tkinter.filedialog',
        'concurrent.futures',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'PyQt5',
        'PyQt6',
        'wx',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SwimmingResultsScraper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Single-file executable — no installer needed
    onefile=True,
    # Hide the console window (GUI app)
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Use the bundled CustomTkinter icon
    icon='icon.ico',
)
