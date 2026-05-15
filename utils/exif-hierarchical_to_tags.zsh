#!/usr/bin/env zsh
# exif-hierarchical_to_tags.zsh
# ────────────────────────────────────────────────────────────────────────────
# MIGRATION TASK (run once)
#
# Reads -HierarchicalSubject (pipe-delimited) and writes:
#   a) -TagsList  slash-delimited hierarchies  (Animals/Dogs/Labrador)
#   b) -Subject   flattened keywords — all nodes, one per pipe segment
#                 (Animals, Dogs, Labrador)
#
# Requirements by: A.Tomas
# Code written by: claude.ai
#
# Requires: exiftool (https://exiftool.org)
#
# Usage:
#   ./migrate_hierarchical_to_tags.zsh [OPTIONS] FILE_OR_DIR ...
#
# Options:
#   -r   Recurse into sub-directories
#   -n   Dry run — show matched files and their HierarchicalSubject; no writes
#   -b   Keep exiftool _original backup files
#   -v   Verbose exiftool output
#
# Examples:
#   ./migrate_hierarchical_to_tags.zsh -r -n ~/Photos      # dry run
#   ./migrate_hierarchical_to_tags.zsh -r ~/Photos          # live
#   ./migrate_hierarchical_to_tags.zsh -r -b ~/Photos       # live + backups
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
# IMPORTANT! exec this exiftool step to list files with no $HierarchicalSubject'
# Show skipped files
# exiftool -r -if 'not defined $HierarchicalSubject' \
#  -p 'Skipping (no HierarchicalSubject): $filepath' "${TARGETS[@]}"
#  "${TARGETS[@]}"
# END OF NOTE

# ── shared flags ──────────────────────────────────────────────────────────────
base_args=(
  # only process files that actually have HierarchicalSubject
  -if 'defined $HierarchicalSubject'
  # target extensions (add/remove as needed)
  -ext jpg  -ext jpeg -ext png
  -ext tif  -ext tiff
  -ext heic -ext avif
  -ext cr2  -ext cr3  -ext nef -ext arw -ext dng -ext raf -ext rw2 -ext orf
)
(( RECURSIVE )) && base_args+=(-r)
(( VERBOSE   )) && base_args+=(-v)

# ── dry run: just show what would be touched ──────────────────────────────────
if (( DRY_RUN )); then
  print "[DRY RUN] Files with HierarchicalSubject:\n"
  exiftool "${base_args[@]}" \
    -p '$filename  →  HierarchicalSubject: $HierarchicalSubject' \
    "${TARGETS[@]}"
  exit 0
fi

# ── live run ──────────────────────────────────────────────────────────────────
# exiftool Advanced formatting — the ${TAG;s/old/new/g} syntax applies a
# perl substitution to the tag value before writing.
#
# TagsList ← replace every | with /
#   "Animals|Dogs|Labrador"  →  "Animals/Dogs/Labrador"
#
# Subject  ← replace every | with a comma; exiftool then splits on the
#   separator and writes each token as a separate Subject keyword,
#   giving us all hierarchy nodes flattened.
#   "Animals|Dogs|Labrador"  →  Subject: Animals  +  Dogs  +  Labrador

(( BACKUP )) || base_args+=(-overwrite_original)

print "Running migration…"
exiftool "${base_args[@]}" \
  '-TagsList<${HierarchicalSubject;s/\|/\//g}' \
  '-Subject<${HierarchicalSubject;s/\|/,/g}' \
  "${TARGETS[@]}"
