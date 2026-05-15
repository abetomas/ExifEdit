#!/usr/bin/env zsh
# exif-sync_TagsList.zsh
# ────────────────────────────────────────────────────────────────────────────
# PERIODIC SYNC TASK
#
# Reads -TagsList (slash-delimited hierarchies) and writes / normalises:
#   a) -Subject              all node keywords, flattened
#   b) -HierarchicalSubject  pipe-delimited hierarchies
#   c) -TagsList             cleaned up (exiftool re-writes it normalised)
#
# Requirements by: A.Tomas
# Code written by: claude.ai
#
# Requires: exiftool (https://exiftool.org)
#
# Usage:
#   ./sync_tags.zsh [OPTIONS] FILE_OR_DIR ...
#
# Options:
#   -r   Recurse into sub-directories
#   -n   Dry run — show matched files and their TagsList; no writes
#   -b   Keep exiftool _original backup files
#   -v   Verbose exiftool output
#
# Examples:
#   ./sync_tags.zsh -r -n ~/Photos          # dry run
#   ./sync_tags.zsh -r ~/Photos             # live
#   ./sync_tags.zsh -r -b ~/Photos/2024     # live + backups
#
# Cron example (2 AM daily):
#   0 2 * * * /path/to/sync_tags.zsh -r /path/to/Photos >> /var/log/sync_tags.log 2>&1
# ────────────────────────────────────────────────────────────────────────────

RECURSIVE=0; DRY_RUN=0; BACKUP=0; VERBOSE=0
TARGETS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r) RECURSIVE=1 ;;
    -n) DRY_RUN=1   ;;
    -b) BACKUP=1    ;;
    -v) VERBOSE=1   ;;
    -*) print "Unknown option: $1" >&2; exit 1 ;;
    *)  TARGETS+=("$1") ;;
  esac
  shift
done

[[ ${#TARGETS[@]} -eq 0 ]] && { print "Usage: $0 [OPTIONS] FILE_OR_DIR ..." >&2; exit 1 }
command -v exiftool &>/dev/null   || { print "exiftool not found in PATH" >&2; exit 1 }

# NOTE
# IMPORTANT! exec this exiftool step to list files with no $TagsList'
# Show skipped files
# exiftool -r -if 'not defined $TagsList' \
#  -p 'Skipping (no TagsList): $filepath' "${TARGETS[@]}"
#  "${TARGETS[@]}"
# END OF NOTE


# ── shared flags ──────────────────────────────────────────────────────────────
base_args=(
  # only process files that actually have TagsList
  -if 'defined $TagsList'
  # target extensions
  -ext jpg  -ext jpeg -ext png
  -ext tif  -ext tiff
  -ext heic -ext avif
  -ext cr2  -ext cr3  -ext nef -ext arw -ext dng -ext raf -ext rw2 -ext orf
)
(( RECURSIVE )) && base_args+=(-r)
(( VERBOSE   )) && base_args+=(-v)

# ── dry run ───────────────────────────────────────────────────────────────────
if (( DRY_RUN )); then
  print "[DRY RUN] Files with TagsList:\n"
  exiftool "${base_args[@]}" \
    -p '$filename  →  TagsList: $TagsList' \
    "${TARGETS[@]}"
  exit 0
fi

# ── live run ──────────────────────────────────────────────────────────────────
# exiftool Advanced formatting — ${TAG;s/old/new/g} applies perl substitutions.
#
# Source of truth: TagsList  (e.g. "Animals/Dogs/Labrador")
#
# HierarchicalSubject ← replace every / with |
#   "Animals/Dogs/Labrador"  →  "Animals|Dogs|Labrador"
#
# Subject ← replace every / with a comma; exiftool splits and writes
#   each token as a separate Subject keyword (all nodes, flattened).
#   "Animals/Dogs/Labrador"  →  Subject: Animals  +  Dogs  +  Labrador
#
# TagsList ← copy from itself; this round-trips through exiftool,
#   normalising whitespace and removing any duplicates.

(( BACKUP )) || base_args+=(-overwrite_original)

print "Running sync…"
exiftool "${base_args[@]}" \
  '-HierarchicalSubject<${TagsList;s/\//|/g}' \
  '-Subject<${TagsList;s/\//,/g}'             \
  '-TagsList<${TagsList}'                      \
  "${TARGETS[@]}"
