#!/usr/bin/env python3
"""Download the books CSV dataset from Google Drive."""

import os
import sys
from pathlib import Path

GDRIVE_FILE_ID = "13wJwUikFpuZNyqIQYvgaAmOzQde4eGzz"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "books.csv"


def download():
    output_path = Path(os.environ.get("BOOKS_CSV_PATH", str(DEFAULT_OUTPUT)))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        print(f"Dataset already exists at {output_path}")
        return

    try:
        import gdown
    except ImportError:
        print("gdown not installed. Install with: pip install gdown")
        print("Then re-run this script.")
        _print_manual_instructions(output_path)
        sys.exit(1)

    url = f"https://drive.google.com/uc?id={GDRIVE_FILE_ID}"
    print(f"Downloading dataset to {output_path} ...")

    try:
        gdown.download(url, str(output_path), quiet=False)
        if output_path.exists() and output_path.stat().st_size > 0:
            print(f"Download complete: {output_path} ({output_path.stat().st_size:,} bytes)")
        else:
            raise RuntimeError("Download produced empty file")
    except Exception as e:
        print(f"Download failed: {e}")
        _print_manual_instructions(output_path)
        sys.exit(1)


def _print_manual_instructions(output_path: Path):
    print("\n--- Manual Download Instructions ---")
    print(f"1. Open: https://drive.google.com/file/d/{GDRIVE_FILE_ID}/view?usp=drive_link")
    print("2. Click the download button (arrow icon)")
    print(f"3. Save the file as: {output_path}")
    print("------------------------------------\n")


if __name__ == "__main__":
    download()
