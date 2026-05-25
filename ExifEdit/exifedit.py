#!/usr/bin/env python3
"""
ExifEdit  — Yet another GUI editor for EXIF/IPTC/XMP metadata in photos

Tested on MacOS/silicon on Tahoe

Requirements by	:	sudo.shebang
Code-Author		: 	Claude.ai

Requires :  exiftool       (brew install exiftool)
            PyQt6          (pip install PyQt6)
            Pillow         (pip install Pillow)
            pillow-heif    (pip install pillow-heif)   # optional – HEIC preview
Run      :  python3 exif_editor.py

License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

Acknowledgments
exiftool by Phil Harvey
Python Libraries contributions

Change Log
v-1.0.0 		:	2026-04-30 Initial version
v-1.0.1         :   2026-05-06 Accept files/folder in argv (Finder "Open With" support)
                               Right-click context menu on thumbnails (Open With, Reveal in Finder)
                               App display name + icon improvements
v-1.0.2         :   2026-05-06 Fix Dock balloon tooltip showing 'Python' instead of 'Exif Edit'
                               (NSProcessInfo.setProcessName_ + setproctitle fallback)
v-1.0.3         :   2026-05-06 Fix exiftool PATH resolution when launched as .app
                               (_find_exiftool() + EXIFTOOL constant; py2app alias + full build safe)
v-1.0.4         :   2026-05-06 Cross-platform support (Windows / Linux) for GitHub release
                               (open_with_default, reveal_in_filemanager, open_with_app helpers)
v-1.1.0         :   2026-05-08 DAM keyword tag support
                               Rename XMP:Subject → XMP-dc:Subject
                               Rename XMP:HierarchicalSubject → XMP-lr:HierarchicalSubject
                               Add XMP-digiKam:TagsList and IPTC:Keywords (keywords widget)
                               Keywords saved as multi-value exiftool args (one per keyword)
                               Dynamic "Open With" context menu via NSWorkspace (macOS)
                               parse_exif now stores XMP-ns:Tag keys alongside XMP:Tag
v-1.1.1         :   2026-05-09 Per-tag placeholder text for TagsList (slash "/") and HierarchicalSubject (pipe "|")
                               Remove IPTC:Keywords input widget (confusing due to contextual display)
                               Normalise keyword display after save: add space after comma separators
                               to match exiftool/Raw EXIF output format
v-1.1.2         :   2026-05-20 Fix GPS save: write only XMP:GPSLatitude / XMP:GPSLongitude as decimal
                               degrees — works for all formats including HEIC. Removed GPS: namespace
                               args and _gps_pending entirely. Set original_vals before setText so
                               textChanged cannot discard tags from dirty. Add Cmd+S shortcut.


"""

import sys, subprocess, json, csv, io, shutil, os, platform

# Detect OS once — used throughout for cross-platform behaviour
OS = platform.system()   # 'Darwin' | 'Windows' | 'Linux'

# v-1.0.1   2026-04-06 accept files/folder in argv()
initial_files = sys.argv[1:]  # files/folders dropped or passed in

from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget,
    QListWidgetItem, QScrollArea, QDialog,
    QDialogButtonBox, QCheckBox, QComboBox, QFileDialog,
    QMessageBox, QToolBar, QStatusBar, QGroupBox, QSpinBox,
    QAbstractItemView, QInputDialog, QCompleter, QMenu,
)
from PyQt6.QtCore import Qt, QSize, QMetaObject, Q_ARG, pyqtSlot
from PyQt6.QtGui import QPixmap, QImage, QFont, QIcon, QKeySequence, QShortcut

try:
    from PIL import Image, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HAS_HEIF = True
except ImportError:
    HAS_HEIF = False

# ── Constants ─────────────────────────────────────────────────────────────────

APP_VERSION   = "1.1.2"
APP_DATE      = "May 20, 2026"

PROFILES_FILE = Path.home() / ".exifeditor_profiles.json"
DATETIME_FMT  = "%Y:%m:%d %H:%M:%S"
THUMB_SIZE    = 160

# shared thread pool — lives for the whole process lifetime
_POOL = ThreadPoolExecutor(max_workers=4)

# ── Locate exiftool ───────────────────────────────────────────────────────────
# When launched as a .app (Automator or py2app), macOS gives a minimal PATH
# that excludes Homebrew. This helper finds exiftool regardless of launch method.
def _find_exiftool() -> str:
    # 0. Bundled inside .app (full py2app build — placed in Resources/)
    bundle_path = Path(sys.executable).parent.parent / "Resources" / "exiftool"
    if bundle_path.exists():
        return str(bundle_path)
    # 1. Already on PATH (terminal launch or venv)
    found = shutil.which("exiftool")
    if found:
        return found
    # 2. Homebrew standard locations (Apple silicon / Intel)
    for p in ["/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool"]:
        if Path(p).exists():
            return p
    # 3. Fallback — will produce a clear "not found" error at runtime
    return "exiftool"

EXIFTOOL = _find_exiftool()

# ── Cross-platform file/folder helpers ───────────────────────────────────────
def open_with_default(fp: str):
    """Open file with the OS default application."""
    if OS == "Darwin":
        subprocess.run(["open", fp])
    elif OS == "Windows":
        os.startfile(fp)
    else:
        subprocess.run(["xdg-open", fp])

def reveal_in_filemanager(fp: str):
    """Reveal file in Finder / Explorer / file manager."""
    if OS == "Darwin":
        subprocess.run(["open", "-R", fp])
    elif OS == "Windows":
        subprocess.run(["explorer", "/select,", fp])
    else:
        subprocess.run(["xdg-open", str(Path(fp).parent)])

def open_with_app(app_name: str, fp: str):
    """Open file with a named application (macOS only; falls back to default on other OS)."""
    if OS == "Darwin":
        subprocess.run(["open", "-a", app_name, fp])
    else:
        open_with_default(fp)

def get_open_with_apps(fp: str) -> list[tuple[str, str]]:
    """Return list of (display_name, bundle_id) for apps that can open fp on macOS.

    Uses NSWorkspace via pyobjc if available; falls back to a curated static list.
    Result is sorted alphabetically by display name; common photo apps floated to top.
    """
    TOP_APPS = ["Preview", "Photos", "Affinity Photo 2", "Lightroom Classic",
                "Capture One", "Pixelmator Pro", "Acorn"]
    if OS != "Darwin":
        return []
    try:
        from AppKit import NSWorkspace, NSURL
        import Foundation
        url = NSURL.fileURLWithPath_(fp)
        ws = NSWorkspace.sharedWorkspace()
        app_urls = ws.URLsForApplicationsToOpenURL_(url)
        names = []
        for app_url in app_urls:
            bundle_path = app_url.path()
            # Extract display name from CFBundleName in Info.plist
            bundle_info = Foundation.NSBundle.bundleWithPath_(bundle_path)
            name = None
            if bundle_info:
                name = (bundle_info.infoDictionary() or {}).get("CFBundleDisplayName") or \
                       (bundle_info.infoDictionary() or {}).get("CFBundleName")
            if not name:
                # Fallback: use the .app folder stem
                name = Path(bundle_path).stem
            names.append((name, bundle_path))
        # Sort: top apps first (in order), then rest alphabetically
        top = [(n, p) for app in TOP_APPS for (n, p) in names if n == app]
        rest = sorted([(n, p) for (n, p) in names if n not in TOP_APPS], key=lambda x: x[0].lower())
        return top + rest
    except Exception:
        # pyobjc not available — return a sensible static list
        static = ["Preview", "Photos", "Affinity Photo 2", "Lightroom Classic",
                  "Capture One", "Pixelmator Pro"]
        return [(name, name) for name in static]

KNOWN_TAGS = sorted([
    "DateTimeOriginal","DateTimeDigitized","CreateDate","ModifyDate",
    "GPSDateStamp","GPSTimeStamp",
    "XMP:GPSLatitude","XMP:GPSLongitude","XMP:GPSAltitude",
    "GPSLatitude","GPSLatitudeRef","GPSLongitude","GPSLongitudeRef",
    "GPSAltitude","GPSAltitudeRef","Orientation",
    "XMP:Title","XMP:Description",
    "XMP-dc:Subject","XMP-lr:HierarchicalSubject",
    "XMP-digiKam:TagsList","IPTC:Keywords",
    "XMP:Location","XMP:City","XMP:State","XMP:Country",
    "XMP:Creator","XMP:Rights",
    "Copyright","Artist","CopyrightNotice","Credit","Source",
    "Category","SupplementalCategories",
    "Make","Model","LensModel","ExposureTime","FNumber","ISO",
    "FocalLength","Flash","WhiteBalance","Rating","XMP:Rating",
    "ImageWidth","ImageHeight","XResolution","YResolution","ResolutionUnit",
    "FileSize","MIMEType","FileType","Software",
])

TAG_GROUPS = [
    ("📋  File Info", [
        ("FileName",        "FileName",         "readonly"),
        ("FileSize",        "FileSize",         "readonly"),
        ("MIMEType",        "MIMEType",         "readonly"),
        ("ImageWidth",      "ImageWidth",       "readonly"),
        ("ImageHeight",     "ImageHeight",      "readonly"),
        ("XResolution",     "XResolution",      "readonly"),
        ("YResolution",     "YResolution",      "readonly"),
        ("Orientation",     "Orientation",      "text"),
        ("Make",            "Make",             "text"),
        ("Model",           "Model",            "text"),
    ]),
    ("📅  Dates", [
        ("DateTimeOriginal",  "DateTimeOriginal",  "datetime"),
        ("DateTimeDigitized", "DateTimeDigitized", "datetime"),
        ("CreateDate",        "CreateDate",        "datetime"),
        ("ModifyDate",        "ModifyDate",        "datetime"),
        ("GPSDateStamp",      "GPSDateStamp",      "date"),
        ("GPSTimeStamp",      "GPSTimeStamp",      "text"),
    ]),
    ("📍  GPS", [
        ("XMP:GPSLatitude",  "XMP:GPSLatitude",  "gps"),
        ("XMP:GPSLongitude", "XMP:GPSLongitude", "gps"),
        ("GPSLatitude",      "GPSLatitude",      "readonly"),
        ("GPSLatitudeRef",   "GPSLatitudeRef",   "readonly"),
        ("GPSLongitude",     "GPSLongitude",     "readonly"),
        ("GPSLongitudeRef",  "GPSLongitudeRef",  "readonly"),
        ("GPSAltitude",      "GPSAltitude",      "text"),
        ("GPSAltitudeRef",   "GPSAltitudeRef",   "text"),
    ]),

    ("🏷  XMP Core", [
        ("XMP:Title",                   "XMP:Title",                   "text"),
        ("XMP:Description",             "XMP:Description",             "multiline"),
        ("XMP-dc:Subject",              "XMP-dc:Subject",              "keywords"),
        ("XMP-lr:HierarchicalSubject",  "XMP-lr:HierarchicalSubject",  "keywords"),
        ("XMP-digiKam:TagsList",        "XMP-digiKam:TagsList",        "keywords"),
    ]),
    ("🌍  Place", [
        ("XMP:Location", "XMP:Location", "text"),
        ("XMP:City",     "XMP:City",     "text"),
        ("XMP:State",    "XMP:State",    "text"),
        ("XMP:Country",  "XMP:Country",  "text"),
    ]),
    
    ("©  Copyright & Creator", [
        ("Copyright",       "Copyright",       "text"),
        ("Artist",          "Artist",          "text"),
        ("XMP:Creator",     "XMP:Creator",     "text"),
        ("XMP:Rights",      "XMP:Rights",      "text"),
    ]),

]

DATE_WIZARD_TAGS = ["DateTimeOriginal", "DateTimeDigitized", "CreateDate"]

# Maps internal tag keys -> the exiftool write argument prefix.
# Without these, exiftool may write to the wrong namespace or skip the tag entirely.
WRITE_TAG = {
    # EXIF dates
    "DateTimeOriginal":  "EXIF:DateTimeOriginal",
    "DateTimeDigitized": "EXIF:DateTimeDigitized",
    "CreateDate":        "EXIF:CreateDate",
    "ModifyDate":        "EXIF:ModifyDate",
    "GPSDateStamp":      "GPS:GPSDateStamp",
    "GPSTimeStamp":      "GPS:GPSTimeStamp",
    # GPS
    "GPSLatitude":       "GPS:GPSLatitude",
    "GPSLatitudeRef":    "GPS:GPSLatitudeRef",
    "GPSLongitude":      "GPS:GPSLongitude",
    "GPSLongitudeRef":   "GPS:GPSLongitudeRef",
    "GPSAltitude":       "GPS:GPSAltitude",
    "GPSAltitudeRef":    "GPS:GPSAltitudeRef",
    # IPTC — these MUST have the IPTC: prefix or exiftool writes to wrong namespace
    "Category":               "IPTC:Category",
    "SupplementalCategories": "IPTC:SupplementalCategories",
    "CopyrightNotice":        "IPTC:CopyrightNotice",
    "Credit":                 "IPTC:Credit",
    "Source":                 "IPTC:Source",
    "IPTC:Keywords":          "IPTC:Keywords",
    # XMP keyword / subject tags — full namespace required
    "XMP-dc:Subject":             "XMP-dc:Subject",
    "XMP-lr:HierarchicalSubject": "XMP-lr:HierarchicalSubject",
    "XMP-digiKam:TagsList":       "XMP-digiKam:TagsList",
    # EXIF copyright/camera
    "Copyright":   "EXIF:Copyright",
    "Artist":      "EXIF:Artist",
    "Orientation": "EXIF:Orientation",
    "Make":        "EXIF:Make",
    "Model":       "EXIF:Model",
}

def write_tag_name(tag: str) -> str:
    """Return the fully-qualified exiftool tag name for writing."""
    return WRITE_TAG.get(tag, tag)  # XMP:* tags already have their prefix

# Tags that hold lists of keywords — written as multiple -Tag=kw args to exiftool
KEYWORD_TAGS = {"XMP-dc:Subject", "XMP-lr:HierarchicalSubject",
                "XMP-digiKam:TagsList"}

# Tags not supported in HEIC/HEIF/PNG — shown greyed out for those file types
IPTC_ONLY_TAGS = {"IPTC:Keywords"}

def _keyword_args(tag: str, raw_value: str) -> list:
    """Return exiftool args for a tag value.

    For keyword tags: uses a single assignment arg (-Tag=kw1,kw2).
    -sep "," is passed globally by the caller so exiftool splits the
    comma-joined string into a proper multi-value list, replacing any
    existing values (assignment, not append — no separate clear needed).

    Accepts comma- or newline-separated input from the widget.
    """
    wname = write_tag_name(tag)
    if tag not in KEYWORD_TAGS:
        return [f"-{wname}={raw_value}"]
    # Normalise: collapse newlines to commas, strip whitespace, drop blanks
    normalised = ",".join(k.strip() for k in raw_value.replace("\n", ",").split(",") if k.strip())
    # Plain assignment replaces the existing list; -sep "," (global) splits on commas.
    return [f"-{wname}={normalised}"]

# ─────────────────────────────────────────────────────────────────────────────
# Pure functions — safe to run in thread pool
# ─────────────────────────────────────────────────────────────────────────────

def run_exiftool(*args):
    r = subprocess.run([EXIFTOOL] + list(args), capture_output=True, text=True)
    return r.stdout.strip(), r.stderr.strip()

def parse_exif(stdout):
    data = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        # exiftool -s2 -G1 format: "[Group] TagName   : value"
        # Use a split limited to the FIRST colon after the tag name.
        idx = line.find(" : ")
        if idx == -1:
            tag, _, val = line.partition(":")
        else:
            tag = line[:idx]
            val = line[idx+3:]
        tag = tag.strip(); val = val.strip()
        bare = tag; xmp_key = None; xmp_full_key = None; iptc_key = None
        if tag.startswith("["):
            end = tag.find("]")
            group = tag[1:end]; bare = tag[end+1:].strip()
            if group.startswith("XMP"):
                xmp_full_key = f"{group}:{bare}"
                xmp_key = f"XMP:{bare}"
            elif group == "IPTC":
                iptc_key = f"IPTC:{bare}"

        def _store(key, v):
            # With -sep "," on read, exiftool delivers one joined line per tag.
            # Guard against the rare case where a tag appears twice anyway.
            if key in data and data[key]:
                data[key] = data[key] + ", " + v
            else:
                data[key] = v

        def _store_no_overwrite(key, v):
            """Store only if key not already populated (e.g. Composite fallback)."""
            if not data.get(key):
                data[key] = v

        _store(bare, val)
        if xmp_key:
            _store(xmp_key, val)
        if xmp_full_key:
            _store(xmp_full_key, val)
        if iptc_key:
            _store(iptc_key, val)
        if tag.startswith("["):
            end = tag.find("]")
            group = tag[1:end]
            if group == "Composite":
                # Store under Composite: key; also fill bare key as fallback
                # (some HEIC files only expose GPS via Composite group)
                _store(f"Composite:{bare}", val)
                _store_no_overwrite(bare, val)
    return data

def _normalise_keywords(val: str) -> str:
    """Ensure comma-separated keyword values always display as 'tag1, tag2, tag3'
    (comma + space) to match exiftool / Raw EXIF output."""
    return ", ".join(k.strip() for k in val.split(",") if k.strip())

def load_thumb(fp: str, size: int) -> QPixmap:
    """Runs in thread pool. Returns QPixmap (may be null on failure)."""
    if not HAS_PIL:
        return QPixmap()
    try:
        ext = Path(fp).suffix.lower()
        if ext in (".heic", ".heif") and not HAS_HEIF:
            tmp = "/tmp/_exifed_t.jpg"
            subprocess.run([EXIFTOOL, "-b", "-ThumbnailImage", "-o", tmp, fp],
                           capture_output=True)
            if not Path(tmp).exists() or Path(tmp).stat().st_size == 0:
                return QPixmap()
            img = Image.open(tmp)
        else:
            img = Image.open(fp)
        img = ImageOps.exif_transpose(img)
        img.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG")
        buf.seek(0)
        return QPixmap.fromImage(QImage.fromData(buf.read()))
    except Exception:
        return QPixmap()

def load_exif_data(fp: str) -> dict:
    """Runs in thread pool."""
    # -sep "," joins multi-value list tags (Keywords, Subject, etc.) with ","
    # so they arrive as a single comma-separated string for the keywords widget.
    stdout, _ = run_exiftool("-s2", "-G1", "-sep", ",", fp)
    data = parse_exif(stdout)
    # Normalise keyword tags to "tag1, tag2" spacing to match Raw EXIF display
    for key in KEYWORD_TAGS:
        if key in data and data[key]:
            data[key] = _normalise_keywords(data[key])
    return data

def decimal_to_dms(dec, is_lat):
    ref = ("N" if dec >= 0 else "S") if is_lat else ("E" if dec >= 0 else "W")
    dec = abs(dec)
    deg = int(dec)
    m = (dec - deg) * 60; mins = int(m)
    s = (m - mins) * 60
    return f"{deg}/1 {mins}/1 {int(s*1000)}/1000", ref

def load_profiles():
    if PROFILES_FILE.exists():
        try: return json.loads(PROFILES_FILE.read_text())
        except: pass
    return {}

def save_profiles(p):
    PROFILES_FILE.write_text(json.dumps(p, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# Dialogs
# ─────────────────────────────────────────────────────────────────────────────

class DateWizardDialog(QDialog):
    def __init__(self, n_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📅 Date Wizard")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>Stamp date/time on {n_files} file(s)</b><br>"
            "Ideal for scanner batches without embedded dates.<br>"
            "Writes DateTimeOriginal, DateTimeDigitized and CreateDate."))
        now = datetime.now()
        grid = QGridLayout()
        self._spins = {}
        for col, (lbl, key, lo, hi, val) in enumerate([
            ("Year","Y",1900,2100,now.year), ("Month","M",1,12,now.month),
            ("Day","D",1,31,now.day),        ("Hour","h",0,23,now.hour),
            ("Min","m",0,59,now.minute),     ("Sec","s",0,59,0)]):
            grid.addWidget(QLabel(lbl), 0, col, Qt.AlignmentFlag.AlignCenter)
            sb = QSpinBox(); sb.setRange(lo, hi); sb.setValue(val)
            sb.setFixedWidth(72); sb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._spins[key] = sb; grid.addWidget(sb, 1, col)
        layout.addLayout(grid)
        layout.addWidget(QLabel("Write to:"))
        self._checks = {}
        row = QHBoxLayout()
        for t in DATE_WIZARD_TAGS:
            cb = QCheckBox(t); cb.setChecked(True)
            self._checks[t] = cb; row.addWidget(cb)
        layout.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_values(self):
        s = self._spins
        dt = datetime(s["Y"].value(), s["M"].value(), s["D"].value(),
                      s["h"].value(), s["m"].value(), s["s"].value())
        return dt.strftime(DATETIME_FMT), [t for t, cb in self._checks.items() if cb.isChecked()]


class ProfilesDialog(QDialog):
    def __init__(self, profiles, current_tags, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⭐ Profiles")
        self.setMinimumSize(500, 460)
        self.profiles = profiles; self.current_tags = current_tags
        self._chosen_name = None; self._chosen_tags = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Metadata Profiles</b> — save tag sets as named presets"))
        self.lb = QListWidget()
        self.lb.currentRowChanged.connect(self._preview)
        layout.addWidget(self.lb)
        bf = QHBoxLayout()
        for lbl, slot, style in [
            ("Apply to files",    self._apply,  "background:#30d158;color:#000;"),
            ("Save current as…",  self._save,   "background:#0a84ff;color:#000;"),
            ("Delete",            self._delete, "")]:
            b = QPushButton(lbl)
            if style: b.setStyleSheet(style)
            b.clicked.connect(slot); bf.addWidget(b)
        layout.addLayout(bf)
        layout.addWidget(QLabel("Profile contents:"))
        self.prev = QTextEdit(); self.prev.setReadOnly(True)
        self.prev.setFont(QFont("Menlo", 10)); self.prev.setFixedHeight(160)
        layout.addWidget(self.prev)
        self._refresh()

    def _refresh(self):
        self.lb.clear()
        for n in sorted(self.profiles): self.lb.addItem(n)

    def _preview(self, row):
        if row < 0: return
        name = self.lb.item(row).text()
        self.prev.setPlainText("\n".join(
            f"  {k}: {v}" for k, v in sorted(self.profiles.get(name, {}).items())))

    def _save(self):
        readonly_tags = {"FileName","FileSize","MIMEType","ImageWidth","ImageHeight",
                         "XResolution","YResolution","GPSLatitude","GPSLatitudeRef",
                         "GPSLongitude","GPSLongitudeRef"}
        snap = {k: v for k, v in self.current_tags.items() if v and k not in readonly_tags}
            
        if not snap:
            QMessageBox.information(self, "Nothing to save", "Fill tags first."); return
        name, ok = QInputDialog.getText(self, "Save Profile",
                                        "Profile name (e.g. 'Family Canada 1970s'):")
        if ok and name:
            self.profiles[name] = snap; save_profiles(self.profiles); self._refresh()

    def _apply(self):
        row = self.lb.currentRow()
        if row < 0:
            QMessageBox.information(self, "No selection", "Click a profile first."); return
        self._chosen_name = self.lb.item(row).text()
        self._chosen_tags = self.profiles[self._chosen_name]
        self.accept()

    def _delete(self):
        row = self.lb.currentRow()
        if row < 0: return
        name = self.lb.item(row).text()
        if QMessageBox.question(self, "Delete", f"Delete '{name}'?") == QMessageBox.StandardButton.Yes:
            del self.profiles[name]; save_profiles(self.profiles)
            self._refresh(); self.prev.clear()


class AddTagDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add / Edit Tag"); self.setMinimumWidth(400)
        layout = QFormLayout(self)
        self.tag_cb = QComboBox(); self.tag_cb.setEditable(True)
        self.tag_cb.addItems(KNOWN_TAGS); self.tag_cb.setCurrentText("")
        c = QCompleter(KNOWN_TAGS)
        c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        c.setFilterMode(Qt.MatchFlag.MatchContains)
        self.tag_cb.setCompleter(c)
        layout.addRow("Tag:", self.tag_cb)
        self.val_edit = QLineEdit(); self.val_edit.setPlaceholderText("Value")
        layout.addRow("Value:", self.val_edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self):
        return self.tag_cb.currentText().strip(), self.val_edit.text().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

class ExifEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ExifEditor"); self.resize(1400, 900)
        self.files = []; self.selected_files = []
        self.current_file = None
        self.tag_widgets = {}; self.original_vals = {}; self.dirty = set()
        self.profiles = load_profiles()
        self._item_map = {}   # filepath -> QListWidgetItem (grid)
        self._extra_form = None

        self._check_exiftool()
        self._build_ui()
        self._apply_style()

    def _check_exiftool(self):
        try: subprocess.run([EXIFTOOL, "-ver"], capture_output=True, check=True)
        except FileNotFoundError:
            QMessageBox.critical(self, "exiftool not found", "brew install exiftool")
            sys.exit(1)

    def _apply_style(self):
        self.setStyleSheet("""
        QMainWindow,QWidget{background:#1c1c1e;color:#f2f2f7;font-size:12px;}
        QToolBar{background:#2c2c2e;border:none;spacing:3px;padding:4px 6px;}
        QStatusBar{background:#2c2c2e;color:#8e8e93;}
        QPushButton{background:#3a3a3c;color:#f2f2f7;border:1px solid #48484a;
          border-radius:6px;padding:5px 12px;}
        QPushButton:hover{background:#48484a;}
        QPushButton:pressed{background:#2c2c2e;}
        
        QLineEdit,QTextEdit,QComboBox,QSpinBox{
          background:#2c2c2e;color:#f2f2f7;border:1px solid #3a3a3c;
          border-radius:4px;padding:4px 8px;font-family:Menlo,monospace;font-size:11px;}
        QLineEdit{qproperty-alignment:AlignLeft;}
          
          
        QLineEdit:focus,QTextEdit:focus{border:1px solid #0a84ff;}
        QLineEdit[readOnly="true"]{background:#242426;color:#8e8e93;}
        QListWidget{background:#2c2c2e;border:1px solid #3a3a3c;}
        QListWidget::item:selected{background:#0a84ff;color:#fff;}
        QListWidget::item:hover{background:#3a3a3c;}
        QGroupBox{border:1px solid #3a3a3c;border-radius:6px;
          margin-top:10px;padding-top:4px;font-weight:bold;color:#8e8e93;}
        QGroupBox::title{subcontrol-origin:margin;left:10px;}
        QScrollArea{border:none;}
        QSplitter::handle{background:#3a3a3c;}
        QCheckBox{color:#f2f2f7;spacing:6px;}
        QDialog{background:#1c1c1e;}
        QComboBox QAbstractItemView{background:#2c2c2e;color:#f2f2f7;}
        """)

    def _build_ui(self):
        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)

        def tbtn(label, slot, bg=""):
            b = QPushButton(label); b.clicked.connect(slot)
            s = "border-radius:6px;padding:5px 12px;"
            if bg: s += f"background:{bg};color:#000;"
            b.setStyleSheet(s); tb.addWidget(b)

        tbtn("Open Files",     self._open_files,    "#0a84ff")
        tbtn("Open Folder",    self._open_folder)
        tb.addSeparator()
        tbtn("Save Changes",   self._save_changes,  "#30d158")
        tbtn("Batch Apply",    self._batch_apply,   "#ff9f0a")
        tbtn("Copy Tags →",    self._copy_tags)
        tb.addSeparator()
        tbtn("📅 Date Wizard", self._date_wizard)
        tbtn("⭐ Profiles",    self._profiles_menu)
        tbtn("➕ Add Tag",     self._add_tag_dialog)
        tb.addSeparator()
        tbtn("↩ Revert",       self._revert)
        tbtn("🗑 Delete Tag",  self._delete_tag)
        tbtn("📋 Raw EXIF",    self._show_raw)
        tbtn("Export CSV",     self._export_csv)
        tb.addSeparator()
        tbtn("ℹ About",        self._show_about)

        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready — open files to begin")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # ── Left pane ────────────────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(6,6,6,6); ll.setSpacing(4)

        hdr = QHBoxLayout()
        self.file_count_lbl = QLabel("No files")
        self.file_count_lbl.setStyleSheet("color:#8e8e93;font-size:11px;")
        hdr.addWidget(self.file_count_lbl); hdr.addStretch()
        cb = QPushButton("Clear"); cb.setFixedHeight(22)
        cb.clicked.connect(self._clear_files); hdr.addWidget(cb)
        ll.addLayout(hdr)

        self.view_btn = QPushButton("☰ List view")
        self.view_btn.setCheckable(True)
        self.view_btn.clicked.connect(self._toggle_view)
        ll.addWidget(self.view_btn)

        self.file_grid = QListWidget()
        self.file_grid.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self.file_grid.setGridSize(QSize(THUMB_SIZE+16, THUMB_SIZE+44))
        self.file_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.file_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.file_grid.setMovement(QListWidget.Movement.Static)
        self.file_grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_grid.setWordWrap(True); self.file_grid.setSpacing(4)
        self.file_grid.itemSelectionChanged.connect(self._on_sel_changed)
        self.file_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_grid.customContextMenuRequested.connect(self._grid_context_menu)
        ll.addWidget(self.file_grid)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.itemSelectionChanged.connect(self._on_sel_changed)
        self.file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._grid_context_menu)
        self.file_list.hide()
        ll.addWidget(self.file_list)

        sel_hint = QLabel("Shift-click: range  ·  ⌘-click: non-contiguous")
        sel_hint.setStyleSheet("font-size:9px;color:#636366;padding:2px 4px;")
        ll.addWidget(sel_hint)

        splitter.addWidget(left)

        # ── Right pane ───────────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(10,8,10,8); rl.setSpacing(4)

        self.fname_lbl = QLabel("Select a file to edit")
        self.fname_lbl.setStyleSheet("font-size:15px;font-weight:bold;")
        rl.addWidget(self.fname_lbl)

        self.fpath_lbl = QLabel("")
        self.fpath_lbl.setStyleSheet("font-size:10px;color:#8e8e93;font-family:Menlo,monospace;")
        self.fpath_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rl.addWidget(self.fpath_lbl)

        gps_row = QHBoxLayout()
        gps_row.addWidget(QLabel("📍 GPS paste:"))
        self.gps_edit = QLineEdit()
        self.gps_edit.setPlaceholderText("Paste from Google Maps:  22.596431, 59.434489  → Enter")
        self.gps_edit.returnPressed.connect(self._apply_gps)
        gps_row.addWidget(self.gps_edit)
        gb = QPushButton("Apply GPS"); gb.clicked.connect(self._apply_gps)
        gps_row.addWidget(gb)
        rl.addLayout(gps_row)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.editor_widget = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_widget)
        self.editor_layout.setSpacing(6)
        self.editor_layout.addStretch()
        scroll.setWidget(self.editor_widget)
        rl.addWidget(scroll)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 1100])

        # ── Keyboard shortcuts ───────────────────────────────────────────────
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self._save_changes)

    # ── thumbnail / list context menu ─────────────────────────────────────────
    def _grid_context_menu(self, pos):
        """Right-click context menu on thumbnail/list items."""
        active = self._active_list()
        item = active.itemAt(pos)
        if not item:
            return
        fp = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        if OS == "Darwin":
            apps = get_open_with_apps(fp)
            if apps:
                open_with_sub = menu.addMenu("Open With")
                for display_name, bundle_path in apps:
                    # bundle_path is either a full .app path or a plain name (static fallback)
                    if bundle_path.endswith(".app") or "/" in bundle_path:
                        open_with_sub.addAction(
                            display_name,
                            lambda f=fp, p=bundle_path: subprocess.run(["open", "-a", p, f]))
                    else:
                        open_with_sub.addAction(
                            display_name,
                            lambda f=fp, n=display_name: open_with_app(n, f))
                open_with_sub.addSeparator()
                open_with_sub.addAction("Other…",
                    lambda f=fp: subprocess.run(["open", "-a", "", f]) or open_with_default(f))
            else:
                menu.addAction("Open with Default App",
                               lambda f=fp: open_with_default(f))
        else:
            menu.addAction("Open with Default App",
                           lambda f=fp: open_with_default(f))
        menu.addSeparator()
        fm_label = "Reveal in Finder" if OS == "Darwin" else "Reveal in File Manager"
        menu.addAction(fm_label, lambda f=fp: reveal_in_filemanager(f))
        menu.exec(active.viewport().mapToGlobal(pos))

    # ── view toggle ───────────────────────────────────────────────────────────
    def _toggle_view(self, checked):
        if checked:
            self.view_btn.setText("🖼 Thumbnail view")
            self.file_grid.hide(); self.file_list.show()
        else:
            self.view_btn.setText("☰ List view")
            self.file_list.hide(); self.file_grid.show()

    def _active_list(self):
        return self.file_list if self.file_list.isVisible() else self.file_grid

    # ── file loading ──────────────────────────────────────────────────────────
    def _open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files", "",
            "Media (*.jpg *.jpeg *.heic *.heif *.png *.tiff *.tif "
            "*.raw *.cr2 *.nef *.arw *.dng *.mp4 *.mov *.pdf);;All (*.*)")
        if paths: self._load_files(paths)

    def _open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if not folder: return
        exts = {".jpg",".jpeg",".heic",".heif",".png",".tiff",".tif",
                ".raw",".cr2",".nef",".arw",".dng",".mp4",".mov",".pdf"}
        paths = sorted(str(p) for p in Path(folder).rglob("*")
                       if p.suffix.lower() in exts)
        if paths: self._load_files(paths)
        else: QMessageBox.information(self, "No files", "No supported files found.")

    def _load_files(self, paths):
        self.files = paths
        self.file_grid.clear(); self.file_list.clear(); self._item_map.clear()
        for path in paths:
            name = Path(path).name
            gi = QListWidgetItem(QIcon(), name)
            gi.setData(Qt.ItemDataRole.UserRole, path)
            gi.setToolTip(path)
            gi.setSizeHint(QSize(THUMB_SIZE+16, THUMB_SIZE+44))
            self.file_grid.addItem(gi)
            li = QListWidgetItem(name)
            li.setData(Qt.ItemDataRole.UserRole, path)
            self.file_list.addItem(li)
            self._item_map[path] = gi

        n = len(paths)
        self.file_count_lbl.setText(f"{n} file{'s' if n!=1 else ''}")
        self.status_bar.showMessage(f"Loaded {n} file(s) — loading thumbnails…")

        # Submit thumbnail jobs to thread pool; callback posts result to main thread
        for path in paths:
            future = _POOL.submit(load_thumb, path, THUMB_SIZE)
            future.add_done_callback(
                lambda f, p=path: self._post_thumb(p, f.result()))

        if paths:
            self.file_grid.setCurrentRow(0)
            self.file_list.setCurrentRow(0)
            self._load_exif(paths[0])

    @pyqtSlot()
    def _post_thumb(self, fp: str, px: QPixmap):
        """Called from thread pool — marshal back to main thread via invokeMethod."""
        # We can't touch Qt widgets from a worker thread, so use a queued call.
        QMetaObject.invokeMethod(
            self, "_recv_thumb",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, fp),
            Q_ARG(QPixmap, px),
        )

    @pyqtSlot(str, QPixmap)
    def _recv_thumb(self, fp: str, px: QPixmap):
        """Runs on main thread — safe to update widgets."""
        item = self._item_map.get(fp)
        if item and not px.isNull():
            item.setIcon(QIcon(px))

    def _clear_files(self):
        self.files.clear(); self.file_grid.clear(); self.file_list.clear()
        self._item_map.clear(); self.current_file = None
        self.file_count_lbl.setText("No files")
        self.fname_lbl.setText("Select a file to edit"); self.fpath_lbl.setText("")
        self._clear_editor(); self.status_bar.showMessage("Ready")

    def _on_sel_changed(self):
        items = self._active_list().selectedItems()
        self.selected_files = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        if not items: return
        fp = items[0].data(Qt.ItemDataRole.UserRole)
        # Only reload EXIF when the primary (first-clicked) file actually changes.
        # If the user is shift/cmd-clicking to build a multi-selection, the first
        # item stays the same and we leave the editor untouched.
        if fp != self.current_file:
            self._load_exif(fp)

    # ── EXIF load ─────────────────────────────────────────────────────────────
    def _load_exif(self, fp):
        if self.dirty and self.current_file:
            r = QMessageBox.question(self, "Unsaved changes",
                                     "Discard changes and switch files?")
            if r != QMessageBox.StandardButton.Yes: return
        self.current_file = fp
        self.fname_lbl.setText(Path(fp).name)
        self.fpath_lbl.setText(fp)
        self.status_bar.showMessage(f"Loading {Path(fp).name}…")
        future = _POOL.submit(load_exif_data, fp)
        future.add_done_callback(
            lambda f: QMetaObject.invokeMethod(
                self, "_recv_exif",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(object, f.result()),
            )
        )

    @pyqtSlot(object)
    def _recv_exif(self, data: dict):
        self._build_editor(data)
        self.status_bar.showMessage(
            f"{Path(self.current_file).name} — {len(data)} tags loaded")

    # ── editor form ───────────────────────────────────────────────────────────
    def _clear_editor(self):
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.tag_widgets.clear(); self.original_vals.clear(); self.dirty.clear()

    def _build_editor(self, tag_data):
        self._clear_editor()

        # Detect formats that don't support IPTC tags (HEIC, HEIF, PNG)
        ext = Path(self.current_file).suffix.lower() if self.current_file else ""
        iptc_unsupported = ext in (".heic", ".heif", ".png")

        for group_name, fields in TAG_GROUPS:
            box = QGroupBox(group_name)
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            form.setSpacing(6)
            form.setContentsMargins(8, 4, 8, 8)
            for tag, display, kind in fields:
                value = tag_data.get(tag, "")
                # Set original_vals BEFORE _make_field so textChanged during
                # widget construction doesn't falsely mark tags as dirty.
                self.original_vals[tag] = value
                container = self._make_field(tag, value, kind)

                # Disable IPTC-only tags for unsupported file formats
                unsupported = iptc_unsupported and tag in IPTC_ONLY_TAGS
                if unsupported:
                    container.setEnabled(False)
                    container.setToolTip(
                        f"IPTC tags are not supported in {ext.upper()} files.\n"
                        f"Use XMP-dc:Subject instead.")
                    container.setStyleSheet("QTextEdit { background: #1a1a1c; color: #48484a; }")

                lbl = QLabel(display if not unsupported else f"{display}  ⚠ not supported in {ext.upper()}")
                lbl.setStyleSheet(
                    "font-family:Menlo,monospace;font-size:10px;"
                    + ("color:#48484a;" if unsupported else "color:#8e8e93;")
                    + "min-width:220px;")
                form.addRow(lbl, container)
                # Register the actual input widget
                if isinstance(container, (QLineEdit, QTextEdit)):
                    self.tag_widgets[tag] = container
                else:
                    le = container.findChild(QLineEdit)
                    self.tag_widgets[tag] = le if le else container
            self.editor_layout.addWidget(box)

        self._extra_box = QGroupBox("➕  Extra / Custom Tags")
        self._extra_form = QFormLayout(self._extra_box)
        self._extra_form.setSpacing(5)
        self.editor_layout.addWidget(self._extra_box)
        self.editor_layout.addStretch()
        # Clear any dirty flags that may have been set during widget construction
        self.dirty.clear()
        self._upd_status()

    def _make_field(self, tag, value, kind):
        if kind == "readonly":
            w = QLineEdit(value); w.setReadOnly(True)
            w.setMinimumHeight(28)
            w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            from PyQt6.QtWidgets import QSizePolicy as _SP
            w.setSizePolicy(_SP.Policy.Expanding, _SP.Policy.Fixed)
            return w

        if kind == "multiline":
            w = QTextEdit(); w.setPlainText(value); w.setFixedHeight(80)
            from PyQt6.QtWidgets import QSizePolicy as _SP
            w.setSizePolicy(_SP.Policy.Expanding, _SP.Policy.Fixed)
            w.textChanged.connect(lambda t=tag, ww=w: self._dirty_text(t, ww))
            return w

        if kind == "keywords":
            # Keywords: one keyword per line (exiftool accepts comma-sep or multi-value)
            # Display: join list values with newline; save: pass each line as separate -Tag= arg
            if tag == "XMP-digiKam:TagsList":
                w = QTextEdit(); w.setPlainText(value); w.setFixedHeight(72)
                w.setPlaceholderText('Comma-separated structured tag tree using slash "/" :  One/Two/Three,  ParentTag/ChildTag')
            elif tag == "XMP-lr:HierarchicalSubject":
                w = QTextEdit(); w.setPlainText(value); w.setFixedHeight(72)
                w.setPlaceholderText('Comma-separated structured tag tree using pipe "|" :  One|Two|Three,  ParentTag|ChildTag')
            else:
                w = QTextEdit(); w.setPlainText(value); w.setFixedHeight(72)
                w.setPlaceholderText("Comma-separated: Nature, Travel, Birds")
            from PyQt6.QtWidgets import QSizePolicy as _SP
            w.setSizePolicy(_SP.Policy.Expanding, _SP.Policy.Fixed)
            w.textChanged.connect(lambda t=tag, ww=w: self._dirty_text(t, ww))
            return w

        from PyQt6.QtWidgets import QSizePolicy as _SP
        container = QWidget()
        hl = QHBoxLayout(container); hl.setContentsMargins(0,0,0,0); hl.setSpacing(4)
        w = QLineEdit(value)
        w.setMinimumHeight(28)
        w.setSizePolicy(_SP.Policy.Expanding, _SP.Policy.Fixed)
        w.setSizePolicy(_SP.Policy.Expanding, _SP.Policy.Fixed)
        w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if kind == "gps":
            w.setPlaceholderText("decimal degrees  (use GPS paste bar above)")
        w.textChanged.connect(lambda v, t=tag: self._dirty_line(t, v))
        hl.addWidget(w)
        if kind in ("datetime", "date"):
            btn = QPushButton("📅"); btn.setFixedWidth(32); btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, t=tag, ww=w, k=kind: self._date_pick(t, ww, k))
            hl.addWidget(btn)
        return container

    def _dirty_line(self, tag, value):
        if value != self.original_vals.get(tag, ""): self.dirty.add(tag)
        else: self.dirty.discard(tag)
        self._upd_status()

    def _dirty_text(self, tag, w):
        v = w.toPlainText()
        if v != self.original_vals.get(tag, ""): self.dirty.add(tag)
        else: self.dirty.discard(tag)
        self._upd_status()

    def _upd_status(self):
        n = len(self.dirty)
        self.status_bar.showMessage(
            f"{n} unsaved change{'s' if n!=1 else ''} — click Save Changes"
            if n else "No unsaved changes")

    def _get_val(self, tag):
        w = self.tag_widgets.get(tag)
        if w is None: return ""
        if isinstance(w, QTextEdit): return w.toPlainText()
        if isinstance(w, QLineEdit): return w.text()
        return ""

    def _set_val(self, tag, value):
        w = self.tag_widgets.get(tag)
        if w is None: return
        if isinstance(w, QTextEdit): w.setPlainText(value)
        elif isinstance(w, QLineEdit): w.setText(value)

    # ── GPS paste ─────────────────────────────────────────────────────────────
    def _apply_gps(self):
        text = self.gps_edit.text().strip()
        if not text: return
        try:
            parts = [p.strip() for p in text.split(",")]
            lat, lon = float(parts[0]), float(parts[1])
        except Exception:
            QMessageBox.warning(self, "Invalid GPS",
                "Expected:  lat, lon  e.g. 22.596431, 59.434489"); return

        # Write only XMP decimal tags — works for all formats including HEIC.
        # Set original_vals BEFORE setText so textChanged doesn't discard from dirty.
        self.original_vals["XMP:GPSLatitude"]  = ""
        self.original_vals["XMP:GPSLongitude"] = ""
        self._set_val("XMP:GPSLatitude",  f"{lat:.14f}")
        self._set_val("XMP:GPSLongitude", f"{lon:.14f}")
        self.dirty.update({"XMP:GPSLatitude", "XMP:GPSLongitude"})

        # Update the readonly DMS display fields (cosmetic only, never written)
        lat_dms, lat_ref = decimal_to_dms(lat, True)
        lon_dms, lon_ref = decimal_to_dms(lon, False)
        for t, v in [("GPSLatitude", lat_dms), ("GPSLatitudeRef", lat_ref),
                     ("GPSLongitude", lon_dms), ("GPSLongitudeRef", lon_ref)]:
            w = self.tag_widgets.get(t)
            if isinstance(w, QLineEdit):
                w.setText(v)

        self.gps_edit.clear()
        self._upd_status()
        self.status_bar.showMessage(f"GPS set: {lat:.6f}, {lon:.6f}")

    # ── date picker ───────────────────────────────────────────────────────────
    def _date_pick(self, tag, widget, kind):
        dlg = DateWizardDialog(1, self)
        dlg.setWindowTitle(f"Set date — {tag}")
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dt_str, _ = dlg.get_values()
            new_val = dt_str if kind == "datetime" else dt_str[:10].replace("-", ":")
            widget.setText(new_val)
            # Explicitly mark dirty in case textChanged didn't fire
            if new_val != self.original_vals.get(tag, ""):
                self.dirty.add(tag)
                self._upd_status()

    # ── save / revert ─────────────────────────────────────────────────────────
    def _save_changes(self):
        if not self.current_file:
            QMessageBox.information(self, "Nothing to save", "Open a file first."); return
        if not self.dirty:
            QMessageBox.information(self, "No changes", "No edits to save."); return

        ext = Path(self.current_file).suffix.lower()
        iptc_unsupported = ext in (".heic", ".heif", ".png")
        args = []
        for t in self.dirty:
            if iptc_unsupported and t in IPTC_ONLY_TAGS:
                continue
            raw = self._get_val(t)
            args.extend(_keyword_args(t, raw))

        args = ["-sep", ",", "-d", DATETIME_FMT] + args
        args += ["-overwrite_original", self.current_file]
        stdout, stderr = run_exiftool(*args)

        import re as _re
        success = bool(_re.search(r"\d+\s+image\s+files?\s+updated", stdout.lower()))
        if success:
            for t in list(self.dirty):
                raw = self._get_val(t)
                if t in KEYWORD_TAGS:
                    raw = ", ".join(
                        k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()
                    )
                    self._set_val(t, raw)
                self.original_vals[t] = raw
            self.dirty.clear()
            self.status_bar.showMessage(f"✓ Saved to {Path(self.current_file).name}")
            self._load_exif(self.current_file)
        else:
            full_cmd = " ".join(args)
            msg = stderr or stdout or "exiftool returned no output"
            QMessageBox.critical(self, "Save failed",
                f"exiftool said:\n{msg}\n\nFull command:\nexiftool {full_cmd}")
    def _revert(self):
        if not self.dirty: return
        if QMessageBox.question(self, "Revert", "Discard all unsaved changes?") == QMessageBox.StandardButton.Yes:
            for t, v in self.original_vals.items(): self._set_val(t, v)
            self.dirty.clear(); self.status_bar.showMessage("Reverted")

    # ── delete tag ────────────────────────────────────────────────────────────
    def _delete_tag(self):
        if not self.current_file: return
        tag, ok = QInputDialog.getText(self, "Delete Tag",
                                       "Tag name to delete (e.g. GPSLatitude):")
        if not ok or not tag: return
        targets = self.selected_files or [self.current_file]
        if QMessageBox.question(self, "Confirm",
                f"Delete '{tag}' from {len(targets)} file(s)?") == QMessageBox.StandardButton.Yes:
            run_exiftool(f"-{tag}=", "-overwrite_original", *targets)
            self.status_bar.showMessage(f"Deleted '{tag}' from {len(targets)} file(s)")
            self._load_exif(self.current_file)

    # ── batch apply ───────────────────────────────────────────────────────────
    def _batch_apply(self):
        if not self.current_file: return
        others = [f for f in self.selected_files if f != self.current_file]
        if not others:
            QMessageBox.information(self, "Batch Apply",
                "⌘-click / shift-click multiple files, edit the first, then Batch Apply."); return

        # Snapshot GPS and all tag values NOW before any save/reload can wipe them
        gps = dict(getattr(self, "_gps_pending", {}))
        tag_snapshot = {}
        for _, fields in TAG_GROUPS:
            for tag, _, kind in fields:
                if kind == "readonly": continue
                # Priority: GPS pending > widget current value > original loaded value
                val = (gps.get(tag)
                       or self._get_val(tag)
                       or self.original_vals.get(tag, ""))
                if val:
                    tag_snapshot[tag] = val
        # Extra/custom tags
        for tag, w in self.tag_widgets.items():
            if tag not in {t for _, fields in TAG_GROUPS for t, _, _ in fields}:
                val = self._get_val(tag) or self.original_vals.get(tag, "")
                if val:
                    tag_snapshot[tag] = val

        # Save pending changes to the source file (without triggering async reload)
        if self.dirty:
            r = QMessageBox.question(self, "Unsaved changes",
                "Save changes to the source file before applying to others?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel: return
            if r == QMessageBox.StandardButton.Yes:
                save_args = [f"-{write_tag_name(t)}={gps.get(t) or self._get_val(t)}"
                             for t in self.dirty]
                save_args = ["-d", DATETIME_FMT] + save_args + ["-overwrite_original", self.current_file]
                stdout, stderr = run_exiftool(*save_args)
                if stdout or not stderr:
                    self.original_vals.update({t: self._get_val(t) for t in self.dirty})
                    self.dirty.clear()
                    self._gps_pending = {}
                    self.status_bar.showMessage(f"✓ Saved {Path(self.current_file).name}")
                else:
                    QMessageBox.critical(self, "Save failed", stderr or stdout)
                    return
                # No _load_exif here — we keep the editor state intact

        # Always include the source file in targets
        targets = [self.current_file] + others

        dlg = QDialog(self); dlg.setWindowTitle("Batch Apply"); dlg.setMinimumWidth(520)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"Choose tags to apply to {len(targets)} file(s)\n"
            f"(includes source: {Path(self.current_file).name}):"))

        checks = {}   # tag -> QCheckBox (populated below, before _toggle_all is used)
        group_checks = {}  # group name -> list of tag checkboxes

        # Select All / Deselect All
        sel_all_btn = QPushButton("✓ Select All")
        sel_all_btn.setCheckable(True)
        def _toggle_all(checked):
            sel_all_btn.setText("✗ Deselect All" if checked else "✓ Select All")
            for cb in checks.values(): cb.setChecked(checked)
        sel_all_btn.clicked.connect(_toggle_all)
        layout.addWidget(sel_all_btn)

        scroll = QScrollArea(); inner = QWidget(); vl = QVBoxLayout(inner)
        vl.setSpacing(2)

        for gname, fields in TAG_GROUPS:
            group_tag_cbs = []  # tag checkboxes in this group that appear in snapshot

            # Collect which tags will appear for this group
            visible = [(tag, display) for tag, display, kind in fields
                       if kind != "readonly" and tag in tag_snapshot]
            if not visible:
                continue

            # Group header row: label + "Select group" checkbox
            hrow = QWidget(); hl = QHBoxLayout(hrow); hl.setContentsMargins(0,4,0,0)
            grp_lbl = QLabel(gname)
            grp_lbl.setStyleSheet("font-weight:bold;color:#8e8e93;")
            grp_cb = QCheckBox("all")
            grp_cb.setStyleSheet("color:#8e8e93;font-size:10px;")
            hl.addWidget(grp_lbl); hl.addStretch(); hl.addWidget(grp_cb)
            vl.addWidget(hrow)

            for tag, display in visible:
                val = tag_snapshot[tag]
                cb = QCheckBox(f"    {display}  ·  {val[:55]}")
                checks[tag] = cb
                group_tag_cbs.append(cb)
                vl.addWidget(cb)

            group_checks[gname] = group_tag_cbs

            # Wire group checkbox to toggle its children
            def _make_grp_toggle(tag_cbs, gcb):
                def _toggle(checked):
                    gcb.blockSignals(True)
                    for c in tag_cbs: c.setChecked(checked)
                    gcb.blockSignals(False)
                return _toggle
            grp_cb.clicked.connect(_make_grp_toggle(group_tag_cbs, grp_cb))

        # Extra/custom tags (no group)
        extras = [(tag, val) for tag, val in tag_snapshot.items()
                  if tag not in {t for _, fields in TAG_GROUPS for t, _, _ in fields}]
        if extras:
            hrow = QWidget(); hl = QHBoxLayout(hrow); hl.setContentsMargins(0,4,0,0)
            grp_lbl = QLabel("➕  Extra / Custom Tags")
            grp_lbl.setStyleSheet("font-weight:bold;color:#8e8e93;")
            grp_cb = QCheckBox("all")
            grp_cb.setStyleSheet("color:#8e8e93;font-size:10px;")
            hl.addWidget(grp_lbl); hl.addStretch(); hl.addWidget(grp_cb)
            vl.addWidget(hrow)
            extra_cbs = []
            for tag, val in extras:
                cb = QCheckBox(f"    {tag}  ·  {val[:55]}")
                checks[tag] = cb; extra_cbs.append(cb); vl.addWidget(cb)
            grp_cb.clicked.connect(_make_grp_toggle(extra_cbs, grp_cb))

        scroll.setWidget(inner); scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        sel = [t for t, cb in checks.items() if cb.isChecked()]
        if not sel: return

        # Write selected tags (using snapshotted values) to all targets
        write_args = [f"-{write_tag_name(t)}={tag_snapshot[t]}" for t in sel]
        write_args = ["-d", DATETIME_FMT] + write_args + ["-overwrite_original"] + targets
        stdout, stderr = run_exiftool(*write_args)
        if stdout or not stderr:
            self.status_bar.showMessage(
                f"✓ Applied {len(sel)} tag(s) to {len(targets)} file(s)")
        else:
            msg = stderr or stdout or "exiftool returned no output"
            QMessageBox.critical(self, "Batch Apply failed", f"exiftool said:\n{msg}")

    # ── copy tags ─────────────────────────────────────────────────────────────
    def _copy_tags(self):
        if not self.current_file: return
        targets = [f for f in self.selected_files if f != self.current_file]
        if not targets:
            QMessageBox.information(self, "Copy Tags", "⌘-click multiple files first."); return
        if QMessageBox.question(self, "Copy Tags",
                f"Copy all tags from:\n  {Path(self.current_file).name}\n"
                f"→ {len(targets)} file(s)?") == QMessageBox.StandardButton.Yes:
            run_exiftool("-TagsFromFile", self.current_file,
                         "-all:all", "-overwrite_original", *targets)
            self.status_bar.showMessage(f"✓ Tags copied to {len(targets)} file(s)")

    # ── date wizard ───────────────────────────────────────────────────────────
    def _date_wizard(self):
        targets = self.selected_files or ([self.current_file] if self.current_file else [])
        if not targets:
            QMessageBox.information(self, "Date Wizard", "Open files first."); return
        dlg = DateWizardDialog(len(targets), self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        dt_str, tags = dlg.get_values()
        if not tags: return
        args = ["-d", DATETIME_FMT] + [f"-{write_tag_name(t)}={dt_str}" for t in tags] + ["-overwrite_original"] + targets
        run_exiftool(*args)
        for t in tags: self._set_val(t, dt_str); self.original_vals[t] = dt_str
        self.dirty -= set(tags)
        self.status_bar.showMessage(f"✓ Date wizard: {dt_str} → {len(targets)} file(s)")

    # ── profiles ──────────────────────────────────────────────────────────────
    def _profiles_menu(self):
        current = {tag: self._get_val(tag) for tag in self.tag_widgets}
        dlg = ProfilesDialog(self.profiles, current, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg._chosen_tags:
            self._apply_profile(dlg._chosen_name, dlg._chosen_tags)

    def _apply_profile(self, name, tags):
        targets = self.selected_files or ([self.current_file] if self.current_file else [])
        if not targets: return
        readonly_tags = {"FileName","FileSize","MIMEType","ImageWidth","ImageHeight",
                         "XResolution","YResolution","GPSLatitude","GPSLatitudeRef",
                         "GPSLongitude","GPSLongitudeRef"}
        writable = {t: v for t, v in tags.items() if t not in readonly_tags}
        if not writable:
            QMessageBox.information(self, "Nothing to apply",
                "Profile contains no writable tags."); return
        args = [f"-{write_tag_name(t)}={v}" for t, v in writable.items()] + ["-overwrite_original"] + targets

        stdout, stderr = run_exiftool(*args)
        if "updated" not in stdout.lower() and "image" not in stdout.lower():
            QMessageBox.critical(self, "Save failed",
                f"exiftool output:\n{stdout}\n{stderr}"); return
        for t, v in writable.items():
            self.original_vals[t] = v
        for t, v in writable.items():
            self._set_val(t, v)
        self.dirty.clear()
        self.status_bar.showMessage(f"✓ Profile '{name}' applied to {len(targets)} file(s)")

      
    # ── add custom tag ────────────────────────────────────────────────────────
    def _add_tag_dialog(self):
        dlg = AddTagDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        tag, value = dlg.values()
        if not tag or self._extra_form is None: return
        lbl = QLabel(tag)
        lbl.setStyleSheet(
            "font-family:Menlo,monospace;font-size:10px;color:#8e8e93;min-width:220px;")
        w = QLineEdit(value)
        w.textChanged.connect(lambda v, t=tag: self._dirty_line(t, v))
        self._extra_form.addRow(lbl, w)
        self.tag_widgets[tag] = w; self.original_vals[tag] = ""
        if value: self.dirty.add(tag); self._upd_status()

    # ── about ─────────────────────────────────────────────────────────────────
    def _show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("About Exif Edit")
        dlg.setFixedSize(340, 280)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(10)

        title = QLabel("Exif Edit")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:28px;font-weight:bold;color:#f2f2f7;")
        layout.addWidget(title)

        subtitle = QLabel("EXIF / IPTC / XMP Metadata Editor")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size:11px;color:#8e8e93;")
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        version = QLabel(f"Version  {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("font-size:13px;color:#f2f2f7;font-family:Menlo,monospace;")
        layout.addWidget(version)

        date = QLabel(f"{APP_DATE}")
        date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        date.setStyleSheet("font-size:11px;color:#8e8e93;font-family:Menlo,monospace;")
        layout.addWidget(date)

        layout.addSpacing(8)

        credit = QLabel("Powered by exiftool · Phil Harvey")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credit.setStyleSheet("font-size:10px;color:#636366;")
        layout.addWidget(credit)

        layout.addStretch()

        btn = QPushButton("OK")
        btn.setFixedWidth(80)
        btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch(); btn_row.addWidget(btn); btn_row.addStretch()
        layout.addLayout(btn_row)

        dlg.exec()

    # ── raw / csv ─────────────────────────────────────────────────────────────
    def _show_raw(self):
        if not self.current_file: return
        stdout, _ = run_exiftool("-s", "-G", self.current_file)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Raw EXIF — {Path(self.current_file).name}")
        dlg.resize(700, 600)
        layout = QVBoxLayout(dlg)
        te = QTextEdit(); te.setReadOnly(True); te.setFont(QFont("Menlo", 10))
        te.setPlainText(stdout); layout.addWidget(te); dlg.exec()

    def _export_csv(self):
        if not self.current_file: return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV",
            Path(self.current_file).stem + "_exif.csv", "CSV (*.csv)")
        if not path: return
        stdout, _ = run_exiftool("-s", "-G", self.current_file)
        rows = []
        for line in stdout.splitlines():
            # format: [Group] TagName : Value
            idx = line.find(" : ")
            if idx == -1: continue
            tag = line[:idx].strip(); val = line[idx+3:].strip()
            rows.append((tag, val))
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([("Tag","Value")] + rows)
        self.status_bar.showMessage(f"Exported {len(rows)} tags → {path}")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import traceback
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("Exif Edit")
        app.setApplicationDisplayName("Exif Edit")

        # Override the process name shown in the macOS menu bar (requires pyobjc)
        try:
            from AppKit import NSBundle
            info = NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = "Exif Edit"
        except ImportError:
            pass

        # Set Dock / window icon — update this path to your .icns file
        _icon_path = Path(__file__).parent / "exifedit.icns"
        if _icon_path.exists():
            app.setWindowIcon(QIcon(str(_icon_path)))

        win = ExifEditor()
        win.show()

        # Load any files/folders passed as arguments (e.g. from Finder "Open With")
        if initial_files:
            _exts = {".jpg", ".jpeg", ".heic", ".heif", ".png", ".tiff", ".tif",
                     ".raw", ".cr2", ".nef", ".arw", ".dng", ".mp4", ".mov", ".pdf"}
            _paths = []
            for arg in initial_files:
                p = Path(arg)
                if p.is_dir():
                    _paths += sorted(str(f) for f in p.rglob("*")
                                     if f.suffix.lower() in _exts)
                elif p.is_file() and p.suffix.lower() in _exts:
                    _paths.append(str(p))
            if _paths:
                win._load_files(_paths)

        sys.exit(app.exec())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
