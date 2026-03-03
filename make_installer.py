#!/usr/bin/env python3
"""
make_installer.py — Regenerate install.py after any code change.

Run from the restaurant-iq-bot/ directory:
    python make_installer.py

This script encodes all source files as base64 and writes a new install.py
that Windows users can run to bootstrap the bot from a single file.
"""

import base64
import os

# Files to embed in the installer (relative to this script's directory)
SOURCE_FILES = [
    "config.py",
    "database.py",
    "transcriber.py",
    "analyzer.py",
    "report_generator.py",
    "bot.py",
    ".env.example",
    "requirements.txt",
    "setup_windows.bat",
]

INSTALLER_HEADER = '''#!/usr/bin/env python3
"""
Restaurant-IQ Bot — Windows One-Click Installer
------------------------------------------------
Run this file on Windows to extract all bot source files and set up your environment.

Requirements:
  - Python 3.11+ installed (https://python.org)
  - Ollama installed (https://ollama.ai)

Usage:
  1. Save this file somewhere (e.g. Desktop)
  2. Double-click it, or run: python install.py
  3. Follow the prompts to enter your Telegram bot token
"""

import base64
import os
import subprocess
import sys

FILES = {
'''

INSTALLER_FOOTER = '''}

SETUP_BAT = "setup_windows.bat"


def extract_files():
    print("Extracting Restaurant-IQ Bot files...")
    for filename, encoded in FILES.items():
        content = base64.b64decode(encoded)
        with open(filename, "wb") as f:
            f.write(content)
        print(f"  ✓ {filename}")
    print()


def run_setup():
    if not os.path.exists(SETUP_BAT):
        print(f"ERROR: {SETUP_BAT} not found after extraction.")
        sys.exit(1)
    subprocess.call(["cmd", "/c", SETUP_BAT])


if __name__ == "__main__":
    extract_files()
    run_setup()
'''


def encode_file(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    missing = [f for f in SOURCE_FILES if not os.path.exists(f)]
    if missing:
        print(f"ERROR: Missing files: {missing}")
        raise SystemExit(1)

    lines = [INSTALLER_HEADER]
    for filename in SOURCE_FILES:
        encoded = encode_file(filename)
        lines.append(f'    "{filename}": (')
        # Split long base64 strings across multiple lines for readability
        chunk_size = 80
        chunks = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]
        for chunk in chunks:
            lines.append(f'        "{chunk}"')
        lines.append("    ),")

    lines.append(INSTALLER_FOOTER)

    output_path = os.path.join(script_dir, "install.py")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    size_kb = os.path.getsize(output_path) // 1024
    print(f"install.py regenerated ({size_kb} KB) — {len(SOURCE_FILES)} files embedded.")


if __name__ == "__main__":
    main()
