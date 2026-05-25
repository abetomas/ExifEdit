#!/usr/bin/env python3
"""
rename_mtime.py — Rename files using mtime as filename,
                  and stamp EXIF DateTimeDigitized from mtime via exiftool.

New filename format: yymmdd-HHMMSSsss.ext  (sss = milliseconds)
e.g. 240715-143022123.heic

DateTimeDigitized is the same timestamp with century: YYYY:MM:DD HH:MM:SS

Requires exiftool on PATH:
    brew install exiftool

Usage:
    python3 rename_mtime.py                          # current folder, non-recursive
    python3 rename_mtime.py photo.jpg                # single file
    python3 rename_mtime.py /photos/IMG_001.heic     # single file by path
    python3 rename_mtime.py *.jpg                    # wildcard files in cwd
    python3 rename_mtime.py /photos/*.heic           # wildcard files in folder
    python3 rename_mtime.py /photos                  # folder, non-recursive
    python3 rename_mtime.py /photos -r               # folder, recursive
    python3 rename_mtime.py "/sd-card/*/"            # wildcard directories
    python3 rename_mtime.py "/sd-card/*/" -r         # wildcard dirs, recursive
    python3 rename_mtime.py /photos --ext jpg heic   # filter by extension
    python3 rename_mtime.py /photos --dry-run -v
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
from datetime import datetime


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rename files using mtime as yymmdd-HHMMSSsss.ext "
                    "and write EXIF DateTimeDigitized via exiftool.")
    parser.add_argument("target", nargs="?", default=".",
                        help="File, folder, or wildcard (default: current folder)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Recurse into subdirectories")
    parser.add_argument("--ext", nargs="+", metavar="EXT",
                        help="Only rename files with these extensions "
                             "(e.g. jpg heic png, default=all)")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="Preview renames without applying them")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show each file action (default: totals only)")
    return parser.parse_args()


def check_exiftool():
    if shutil.which("exiftool") is None:
        sys.exit(
            "Error: exiftool not found on PATH.\n"
            "  Install with:  brew install exiftool"
        )


def ext_ok(path, extensions):
    """True if file extension is in the allowed set (or no filter set)."""
    if extensions is None:
        return True
    ext = path.rsplit(".", 1)[-1].lower() if "." in os.path.basename(path) else ""
    return ext in extensions


def collect_from_dir(root, recursive, extensions):
    """
    Walk a directory and return { folder: [file_paths] }.
    Skips hidden files and directories.
    """
    folders = {}

    def scan(folder):
        folder = os.path.realpath(folder)
        files = []
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except PermissionError as e:
            print(f"[SKIP] {e}", file=sys.stderr)
            return
        subdirs = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                subdirs.append(entry.path)
            elif entry.is_file() and ext_ok(entry.path, extensions):
                files.append(entry.path)
        if files:
            folders[folder] = files
        if recursive:
            for sub in subdirs:
                scan(sub)

    scan(root)
    return folders


def resolve_targets(target, recursive, extensions):
    """
    Resolve target (file, dir, or glob) into { folder: [file_paths] }.

    Handles:
      - single file:            photo.jpg
      - single file by path:    /photos/IMG_001.heic
      - wildcard files:         *.jpg  or  /photos/*.heic
      - single directory:       /photos  or  .
      - wildcard directories:   /sd-card/*/
    """
    target = os.path.expanduser(target)

    # ── Single existing file ──────────────────────────────────────────────
    if os.path.isfile(target):
        path = os.path.realpath(target)
        if os.path.basename(path).startswith("."):
            sys.exit(f"Error: hidden files are skipped: {target}")
        if not ext_ok(path, extensions):
            sys.exit(f"Error: extension not in filter: {target}")
        return {os.path.dirname(path): [path]}

    # ── Single existing directory ─────────────────────────────────────────
    if os.path.isdir(target):
        return collect_from_dir(target, recursive, extensions)

    # ── Glob / wildcard ───────────────────────────────────────────────────
    matches = glob.glob(target)
    if not matches:
        sys.exit(f"Error: no matches for: {target}")

    folders = {}
    for match in sorted(matches):
        match = os.path.realpath(match)
        if os.path.isdir(match):
            for folder, files in collect_from_dir(match, recursive, extensions).items():
                folders.setdefault(folder, []).extend(files)
        elif os.path.isfile(match):
            if not os.path.basename(match).startswith(".") and ext_ok(match, extensions):
                folder = os.path.dirname(match)
                folders.setdefault(folder, []).append(match)

    return folders


def mtime_info(path):
    """
    Return (basename, exif_str) from a single mtime read.

    basename  — yymmdd-HHMMSSsss       (filename, century omitted)
    exif_str  — YYYY:MM:DD HH:MM:SS.mmm (DateTimeDigitized, century + ms included)
    """
    mtime = os.path.getmtime(path)
    dt = datetime.fromtimestamp(mtime)
    ms = int((mtime % 1) * 1000)
    basename = dt.strftime("%y%m%d-%H%M%S") + f"{ms:03d}"
    exif_str = dt.strftime("%Y:%m:%d %H:%M:%S") + f".{ms:03d}"
    return basename, exif_str


def write_exif_date(path, exif_str, verbose):
    """Write DateTimeDigitized via exiftool. Returns True on success."""
    cmd = [
        "exiftool",
        f"-DateTimeDigitized={exif_str}",
        "-overwrite_original",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        print(f"[EXIF ERR] {os.path.basename(path)}: {msg}", file=sys.stderr)
        return False
    # if verbose:
    #    print(f"          (EXIF DateTimeDigitized → {exif_str})")
    return True


def process_folder(folder, file_paths, dry_run, verbose):
    renamed = skipped = errors = exif_errors = 0

    for path in file_paths:
        filename = os.path.basename(path)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        base, exif_str = mtime_info(path)
        new_name = f"{base}.{ext}" if ext else base
        already_named = (filename == new_name)

        if dry_run:
            if already_named:
                if verbose:
                    print(f"[ALREADY OK] {filename}")
                skipped += 1
            else:
                if verbose:
                    print(f"[DRY]     {filename} → {new_name}")
                    # print(f"          (EXIF DateTimeDigitized would → {exif_str})")
                renamed += 1
            continue

        # ── Live mode ─────────────────────────────────────────────────────
        dst = os.path.join(folder, new_name)

        if already_named:
            if verbose:
                print(f"[ALREADY OK] {filename}")
            if not write_exif_date(path, exif_str, verbose):
                exif_errors += 1
            skipped += 1
            continue

        try:
            os.rename(path, dst)
            if verbose:
                print(f"[RENAMED] {filename} → {new_name}")
        except OSError as e:
            print(f"[ERROR]   {filename}: {e}", file=sys.stderr)
            errors += 1
            continue

        if not write_exif_date(dst, exif_str, verbose):
            exif_errors += 1

        renamed += 1

    return renamed, skipped, errors, exif_errors


def main():
    args = parse_args()
    check_exiftool()

    extensions = [e.lower().lstrip(".") for e in args.ext] if args.ext else None

    folders = resolve_targets(args.target, args.recursive, extensions)
    if not folders:
        print("No matching files found.")
        return

    print(f"Target    : {args.target}")
    print(f"Ext filter: {', '.join(extensions) if extensions else 'all'}")
    print(f"Recursive : {args.recursive}")
    print(f"Mode      : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"Verbose   : {args.verbose}")
    print()

    total_renamed = total_skipped = total_errors = total_exif_errors = 0

    for folder, file_paths in sorted(folders.items()):
        if args.verbose:
            print(f"  [{folder}]")
        renamed, skipped, errors, exif_errors = process_folder(
            folder, file_paths, args.dry_run, args.verbose)
        total_renamed     += renamed
        total_skipped     += skipped
        total_errors      += errors
        total_exif_errors += exif_errors

    print()
    print(f"Done — {total_renamed} renamed, {total_skipped} already ok, "
          f"{total_errors} errors, {total_exif_errors} EXIF errors.")


if __name__ == "__main__":
    main()