"""
YouTube -> Smash Ultimate converter -- desktop GUI.

A deliberately lightweight, single-window PySide6 front end over :mod:`backend`.
It imports the exact same pipeline the CLI uses, so behaviour never diverges.

UX rationale
------------
The layout and interaction choices follow Shneiderman et al., *Designing the
User Interface* (6th ed.). Each numbered note below cites the principle it
implements so the design intent stays legible to future maintainers:

* **Golden Rule 1 - Consistency.** One accent colour, uniform spacing, every
  field label left-aligned in a shared column, "Convert"/"Cancel" share styling.
* **Golden Rule 2 - Universal usability.** Tooltips give novices explanations;
  the manual/auto loop toggle and remembered settings serve experts.
* **Golden Rule 3 - Informative feedback.** Live readouts for the gain slider
  and the resolved BGM id; a staged progress bar for the long conversion.
* **Golden Rule 4 - Closure.** A clear success panel ends the job with the
  output location and a one-click "Open folder".
* **Golden Rule 5 - Prevent errors.** "Convert" stays disabled until inputs are
  valid; numeric-only validators on loop times and the IP field; loop end must
  exceed start; invalid choices are simply not selectable.
* **Golden Rule 6 - Easy reversal.** "Cancel" stops cleanly at the next stage
  boundary and returns to an editable form; nothing is destroyed.
* **Golden Rule 7 - Keep users in control.** Long work runs on a worker thread
  so the UI never freezes; the user can cancel.
* **Golden Rule 8 - Reduce short-term memory load.** A searchable dropdown of
  all 1,137 tracks means users pick "Brinstar (Melee)" instead of recalling an
  internal id; the Switch IP and output folder are remembered between runs.
* **Form fill-in (8.6).** Meaningful title, brief task-framed instructions,
  labels in a consistent location (never placeholder-only), fields grouped
  meaningfully, field-specific rules shown beside the field, validation as you
  type, sensible defaults.
* **Error messages (12.8).** Failures map to specific, constructive, positively
  worded dialogs that say how to fix the problem -- never "ERROR"/"INVALID".
"""

from __future__ import annotations

import json
import os
import re
import sys
import webbrowser
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject, QSettings, QByteArray, QSize, QStringListModel, QRectF
from PySide6.QtGui import (
    QDoubleValidator, QIntValidator, QPixmap, QPainter, QIcon, QColor, QStandardItem, QStandardItemModel,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import backend
import ledger
import tooldl
from backend import ConversionConfig, ConversionError, LoopSpec, Stage


APP_NAME = "YouTube to Smash Ultimate"
APP_VERSION = "1.0.0"

# Author credit shown (as plain text, no hyperlinks) in the About dialog.
AUTHORS = "@yoavaharonofficial and @oriaharo-creator"

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
# Designed "monochrome first" (§12.6): a calm neutral body of dark ink on light
# surfaces, with ONE reserved high-intensity accent used only to draw attention
# to the primary action, focus, and live progress (§3.2.3 Intensity: "two levels
# only, with limited use of high intensity"). Semantic hues (green = success,
# amber = caution) are used *only* in feedback, applied automatically and
# consistently as a coding technique. Total functional hues stay within the
# book's "limit to ~four colors" guidance.
ACCENT = "#d7263d"      # Smash-crimson: brand + primary action / progress
ACCENT_DK = "#b51e31"   # hover/pressed
INK = "#1c1f26"         # primary text
MUTED = "#6b7280"       # secondary text / hints
SURFACE = "#ffffff"     # cards
CANVAS = "#eceef2"      # window background
BORDER = "#dfe3ea"      # hairlines
ICON_SLATE = "#5b6472"  # neutral icon glyphs (monochrome-first)
HEADER_FG = "#2b3240"   # dropdown group-header text (high contrast on tint)
HEADER_BG = "#e4e7ee"   # dropdown group-header background bar
SUCCESS = "#1f9d57"     # feedback: completed
WARNING_BG = "#fff4e0"  # feedback: caution banner
WARNING_FG = "#7a4a00"
WARNING_BD = "#ffd591"


# ---------------------------------------------------------------------------
# Inline-SVG icons (no external dependency -> bundles cleanly into the EXE).
# Stroke uses the token __C__ so a single glyph can be re-tinted on demand.
# Icons act as "marking" (§3.2.3) to speed recognition and lighten reading.
# ---------------------------------------------------------------------------

_SVG = {
    "logo": (
        '<path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" />'
        '<circle cx="18" cy="16" r="3" />'
    ),
    "link": (
        '<path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />'
        '<path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />'
    ),
    "music": '<path d="M9 18V5l12-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="18" cy="16" r="3" />',
    "sliders": (
        '<line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" />'
        '<line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" />'
        '<line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" />'
        '<line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" />'
        '<line x1="17" y1="16" x2="23" y2="16" />'
    ),
    "wifi": (
        '<path d="M5 12.55a11 11 0 0 1 14 0" /><path d="M8.5 16.1a6 6 0 0 1 7 0" />'
        '<line x1="12" y1="20" x2="12.01" y2="20" /><path d="M1.5 8.5a16 16 0 0 1 21 0" />'
    ),
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />',
    "play": '<polygon points="6 4 20 12 6 20 6 4" />',
    "x": '<line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" />',
    "check": '<polyline points="20 6 9 17 4 12" />',
    "loop": (
        '<polyline points="17 1 21 5 17 9" /><path d="M3 11V9a4 4 0 0 1 4-4h14" />'
        '<polyline points="7 23 3 19 7 15" /><path d="M21 13v2a4 4 0 0 1-4 4H3" />'
    ),
    "list": (
        '<line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" />'
        '<line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" />'
        '<line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />'
    ),
    "alert": (
        '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 '
        '3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" />'
        '<line x1="12" y1="17" x2="12.01" y2="17" />'
    ),
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />'
        '<polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />'
    ),
    "chevron-down": '<polyline points="6 9 12 15 18 9" />',
    "chevron-up": '<polyline points="18 15 12 9 6 15" />',
    "info": (
        '<circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" />'
        '<line x1="12" y1="8" x2="12.01" y2="8" />'
    ),
    "external-link": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />'
        '<polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />'
    ),
}


def _make_pixmap(key: str, size: int = 18, color: str = ICON_SLATE, stroke: float = 2.0) -> QPixmap:
    """Render an inline SVG glyph to a crisp, hi-DPI QPixmap tinted ``color``."""
    body = _SVG.get(key, "")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    dpr = 2  # render at 2x for sharpness on high-DPI displays
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    # Render into the FULL physical rect so the 24x24 viewBox fills the pixmap.
    # (Setting devicePixelRatio *before* render() shrinks the paint area and was
    # what clipped the glyphs.) DPR is applied afterwards so it still displays at
    # the requested logical size while staying crisp on hi-DPI screens.
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _icon(key: str, size: int = 18, color: str = ICON_SLATE) -> QIcon:
    return QIcon(_make_pixmap(key, size, color))


_CHEVRON_CACHE: dict[str, str] = {}


def _chevron_png(key: str, color: str = ICON_SLATE) -> str:
    """Render a chevron glyph to a PNG on disk and return a QSS-friendly path.

    Qt stylesheets reference arrow images by file URL, not inline SVG, so the
    native spin-box / combo arrows are replaced with our own crisp chevrons that
    sit cleanly inside the rounded control instead of being clipped (§12.6
    legibility; fixes the "cut off" arrows).
    """
    cache_key = f"{key}:{color}"
    if cache_key in _CHEVRON_CACHE:
        return _CHEVRON_CACHE[cache_key]
    import tempfile
    pm = _make_pixmap(key, 12, color, stroke=2.4)
    out_dir = os.path.join(tempfile.gettempdir(), "yt2smash_icons")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{key}_{color.lstrip('#')}.png")
    pm.save(path, "PNG")
    qss_path = path.replace("\\", "/")
    _CHEVRON_CACHE[cache_key] = qss_path
    return qss_path


# ---------------------------------------------------------------------------
# Data: the BGM song list
# ---------------------------------------------------------------------------


def load_songlist() -> List[dict]:
    """Load the bundled BGM catalogue (resolved via the same path logic as binaries)."""
    path = backend.resource_path("data", "songlist.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# Worker: runs the pipeline off the UI thread (Golden Rule 7)
# ---------------------------------------------------------------------------


class _Cancelled(Exception):
    """Raised cooperatively at a stage boundary when the user cancels."""


class ConversionWorker(QObject):
    progress = Signal(float, str)        # overall fraction (0..1), message
    finished = Signal(object)            # backend.ConversionResult
    failed = Signal(str, str)            # (title, body) -- already user-friendly
    cancelled = Signal()

    def __init__(self, config: ConversionConfig):
        super().__init__()
        self._config = config
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        def on_progress(stage: Stage, fraction: float, message: str) -> None:
            if self._cancel:
                raise _Cancelled()
            self.progress.emit(fraction, message)

        try:
            result = backend.convert(self._config, on_progress=on_progress)
        except _Cancelled:
            self.cancelled.emit()
        except ConversionError as exc:
            # backend already phrases these specifically + constructively (12.8).
            self.failed.emit(_friendly_title(exc), str(exc))
        except Exception as exc:  # last-resort guard; keep tone non-hostile
            self.failed.emit(
                "Something unexpected happened",
                f"The conversion stopped early. Details:\n\n{exc}",
            )
        else:
            self.finished.emit(result)


def _friendly_title(exc: ConversionError) -> str:
    """Map an exception type to a short, positive dialog title (12.8.2)."""
    return {
        backend.MissingDependencyError: "A required component is missing",
        backend.DownloadFailedError: "Couldn't fetch that video",
        backend.AudioProcessingError: "Couldn't process the audio",
        backend.EncodingError: "Couldn't build the audio file",
        backend.InvalidLoopPointsError: "Check the loop points",
        backend.SwitchUploadError: "Couldn't reach your Switch",
    }.get(type(exc), "Conversion stopped")


class ToolInstallWorker(QObject):
    """Downloads any missing bundled components off the UI thread (GR7)."""

    progress = Signal(float, str)   # overall fraction (0..1), message
    finished = Signal()
    failed = Signal(str)            # already user-friendly message

    def run(self) -> None:
        def on_progress(label: str, fraction: float, message: str) -> None:
            self.progress.emit(fraction, message)

        try:
            tooldl.install_missing(on_progress)
        except tooldl.ToolDownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # network/disk surprises; stay non-hostile
            self.failed.emit(
                "The download stopped early. Check your internet connection and "
                f"try again.\n\nDetails: {exc}")
        else:
            self.finished.emit()


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------


def _hint(text: str) -> QLabel:
    """A muted, small helper line placed beside/under a field (form fill-in 8.6)."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("hint")
    return label


def _card(icon_key: str, title: str) -> tuple[QFrame, QFormLayout]:
    """A bordered 'card' grouping related fields.

    Grouping by an enclosing box with a labelled, icon-marked header implements
    the display-organisation guidance (§12.6 "design for monochrome first ...
    group related fields by a box") and consistency (Golden Rule 1).
    Returns the card frame and the QFormLayout to populate.
    """
    card = QFrame()
    card.setObjectName("card")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(14, 12, 14, 14)
    outer.setSpacing(8)

    header = QHBoxLayout()
    header.setSpacing(8)
    glyph = QLabel()
    glyph.setPixmap(_make_pixmap(icon_key, 16, ICON_SLATE))
    glyph.setFixedSize(18, 18)
    glyph.setAlignment(Qt.AlignCenter)
    label = QLabel(title)
    label.setObjectName("cardTitle")
    header.addWidget(glyph)
    header.addWidget(label)
    header.addStretch(1)
    outer.addLayout(header)

    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignLeft)      # consistent label location (8.6)
    form.setFormAlignment(Qt.AlignTop)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(7)
    form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    outer.addLayout(form)
    return card, form


_IP_RE = re.compile(r"^(\d{1,3})(\.\d{1,3}){3}$")


def _looks_like_ip(text: str) -> bool:
    text = text.strip()
    if not _IP_RE.match(text):
        return False
    return all(0 <= int(part) <= 255 for part in text.split("."))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(500)
        self._settings = QSettings("yt2smash", "converter")
        self._songs = load_songlist()
        self._worker: Optional[ConversionWorker] = None
        self._thread: Optional[QThread] = None
        self._active_config: Optional[ConversionConfig] = None
        self._active_song: Optional[dict] = None
        self._auto_install_started = False

        self._build_ui()
        self._restore_settings()
        self._run_preflight()
        self._revalidate()

    # -- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        # Scrollable body so the window stays usable on small displays
        # (universal usability, Golden Rule 2). The horizontal scrollbar is
        # disabled: cards reflow to the viewport width, so a stray horizontal
        # bar never appears across the layout (§12.6 visual cleanliness).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("scroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body = QWidget()
        body.setObjectName("body")
        root = QVBoxLayout(body)
        root.setContentsMargins(18, 16, 18, 8)
        root.setSpacing(12)

        # Non-blocking banner for missing components, now with a one-click fix
        # (caution coding, §12.6; constructive recovery, §12.8).
        root.addWidget(self._build_banner())

        root.addWidget(self._build_source_card())
        root.addWidget(self._build_audio_card())
        root.addWidget(self._build_destination_card())
        root.addWidget(self._build_output_card())
        root.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._build_footer())

        self.setStyleSheet(self._stylesheet())
        self._on_song_changed()

    # -- header / cards / footer -------------------------------------------

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(_make_pixmap("logo", 26, "#ffffff"))
        lay.addWidget(logo)

        text = QVBoxLayout()
        text.setSpacing(1)
        title = QLabel(APP_NAME)          # meaningful title (8.6)
        title.setObjectName("appTitle")
        sub = QLabel("Paste a link, pick the slot to replace, then convert.")
        sub.setObjectName("appSubtitle")
        text.addWidget(title)
        text.addWidget(sub)
        lay.addLayout(text)
        lay.addStretch(1)

        # A record of everything modded so far (reduce memory load, GR8).
        self.history_btn = QPushButton("Modded songs")
        self.history_btn.setObjectName("headerBtn")
        self.history_btn.setIcon(_icon("list", 15, "#ffffff"))
        self.history_btn.setToolTip("See every slot you've already replaced.")
        self.history_btn.clicked.connect(self._show_history)
        lay.addWidget(self.history_btn)

        # Credits / version (consistency, GR1; recognition over recall, GR8).
        self.about_btn = QPushButton("About")
        self.about_btn.setObjectName("headerBtn")
        self.about_btn.setIcon(_icon("info", 15, "#ffffff"))
        self.about_btn.setToolTip("Credits, version, and links.")
        self.about_btn.clicked.connect(self._show_about)
        lay.addWidget(self.about_btn)
        return bar

    def _build_banner(self) -> QWidget:
        """A caution banner that can install the missing components in place."""
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        self.banner.setVisible(False)
        lay = QVBoxLayout(self.banner)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        glyph = QLabel()
        glyph.setPixmap(_make_pixmap("alert", 16, WARNING_FG))
        glyph.setFixedSize(18, 18)
        glyph.setAlignment(Qt.AlignTop)
        self.banner_label = QLabel()
        self.banner_label.setObjectName("bannerText")
        self.banner_label.setWordWrap(True)
        top.addWidget(glyph)
        top.addWidget(self.banner_label, 1)
        lay.addLayout(top)

        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 100)
        self.install_progress.setTextVisible(True)
        self.install_progress.setVisible(False)
        lay.addWidget(self.install_progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.install_btn = QPushButton("  Install missing components")
        self.install_btn.setObjectName("installBtn")
        self.install_btn.setIcon(_icon("download", 15, "#ffffff"))
        self.install_btn.setToolTip(
            "Download the required tools for your system and finish setup automatically.")
        self.install_btn.clicked.connect(self._install_components)
        btn_row.addWidget(self.install_btn)
        lay.addLayout(btn_row)
        return self.banner

    def _build_source_card(self) -> QFrame:
        card, form = _card("link", "Source & target")

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.url_edit.setToolTip("Paste a full YouTube video or music link.")
        self.url_edit.textChanged.connect(self._revalidate)
        form.addRow("YouTube link", self.url_edit)

        # Searchable BGM dropdown of all slots, grouped by series (reduce memory
        # load, GR8; "organize menus by ... categories of related items", §6.4).
        # The 1,137 slots are split into bold, non-selectable series headers so
        # the list is scannable by franchise instead of being one long roll;
        # typing still filters across every track by name (§6.5 type-ahead).
        self.song_combo = QComboBox()
        self.song_combo.setEditable(True)
        self.song_combo.setInsertPolicy(QComboBox.NoInsert)
        self.song_combo.setMaxVisibleItems(18)
        self._populate_song_combo()
        self.song_combo.setToolTip(
            "Browse by series, or type part of a song name to filter all 1,137 slots.")
        self.song_combo.currentIndexChanged.connect(self._on_song_changed)
        self.song_combo.lineEdit().editingFinished.connect(self._revalidate)
        form.addRow("Replace song", self.song_combo)

        self.resolved_label = _hint("")
        form.addRow("", self.resolved_label)
        return card

    def _populate_song_combo(self) -> None:
        """Fill the combo with series-grouped items + a name-only completer.

        Series headers are inserted as bold, disabled rows (not selectable, and
        skipped by keyboard navigation). A dedicated completer model holds only
        the song display strings, so type-ahead never matches a header and the
        user lands directly on a track (§6.4 grouping, §6.5 type-ahead).
        """
        model = QStandardItemModel(self.song_combo)
        completer_strings: list[str] = []

        by_series: dict[str, list[dict]] = {}
        for song in self._songs:
            by_series.setdefault(song.get("series", "Other"), []).append(song)

        for series in sorted(by_series, key=str.lower):
            header = QStandardItem(series.upper())
            header.setFlags(Qt.NoItemFlags)              # disabled + unselectable
            header.setData("header", Qt.AccessibleDescriptionRole)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            # High-contrast group header: dark slate text on a faint tinted bar.
            # Gray-on-gray failed WCAG contrast; dark ink on a light fill is an
            # unambiguous figure/ground separation (colour theory; §12.6).
            header.setForeground(QColor(HEADER_FG))
            header.setBackground(QColor(HEADER_BG))
            model.appendRow(header)
            for song in sorted(by_series[series], key=lambda s: s["name"].lower()):
                item = QStandardItem(song["name"])
                item.setData(song, Qt.UserRole)
                item.setData(f"{song['name']}  -  {song['bgm_id']}", Qt.ToolTipRole)
                item.setForeground(QColor(INK))   # never rely on theme default text
                model.appendRow(item)
                completer_strings.append(song["name"])

        self.song_combo.setModel(model)
        self._song_model = model

        # Name-only completer (matches anywhere in the name, case-insensitive).
        self._completer_model = QStringListModel(completer_strings, self)
        completer = QCompleter(self._completer_model, self)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.activated[str].connect(self._on_completer_activated)
        self.song_combo.setCompleter(completer)

        # Default to the first real (non-header) row.
        for row in range(model.rowCount()):
            if model.item(row).data(Qt.UserRole) is not None:
                self.song_combo.setCurrentIndex(row)
                break

    def _on_completer_activated(self, name: str) -> None:
        """Map a completer pick (a bare song name) back to its combo row."""
        for row in range(self._song_model.rowCount()):
            item = self._song_model.item(row)
            song = item.data(Qt.UserRole)
            if song is not None and song["name"] == name:
                self.song_combo.setCurrentIndex(row)
                return

    def _build_audio_card(self) -> QFrame:
        card, form = _card("sliders", "Audio")

        # Volume handling. "Match game volume" runs an EBU-R128 loudness match
        # so the track sits at the same perceived level as the vanilla slot it
        # replaces (quiet sources get boosted, hot ones pulled down) -- the
        # recommended default. "Manual" exposes the old peak-normalise + boost.
        vol_row = QHBoxLayout()
        self.vol_match = QRadioButton("Match game volume")
        self.vol_manual = QRadioButton("Manual")
        self.vol_match.setChecked(True)
        self.vol_group = QButtonGroup(self)
        self.vol_group.addButton(self.vol_match)
        self.vol_group.addButton(self.vol_manual)
        self.vol_match.setToolTip(
            "Automatically level the track to match Smash's vanilla music "
            "(recommended). Quiet songs are boosted, loud ones eased down.")
        self.vol_manual.setToolTip(
            "Normalise the peak to 0 dB, then apply a fixed boost you choose.")
        vol_row.setSpacing(0)
        vol_row.addWidget(self.vol_match)
        vol_row.addSpacing(28)   # clear gap between the two choices (§12.6 spacing)
        vol_row.addWidget(self.vol_manual)
        vol_row.addStretch(1)
        form.addRow("Volume", vol_row)

        self.gain_row_widget = QWidget()
        gain_row = QHBoxLayout(self.gain_row_widget)
        gain_row.setContentsMargins(0, 0, 0, 0)
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-12.0, 12.0)
        self.gain_spin.setSingleStep(0.5)
        self.gain_spin.setValue(0.0)
        self.gain_spin.setSuffix(" dB")
        self.gain_spin.setToolTip("Extra volume applied after the track is normalised to 0 dB.")
        gain_row.addWidget(self.gain_spin)
        gain_row.addWidget(_hint("0 dB keeps the normalised level."), 1)
        form.addRow("Manual boost", self.gain_row_widget)
        self._gain_label = form.labelForField(self.gain_row_widget)
        self.gain_row_widget.setVisible(False)  # only shown in Manual mode
        if self._gain_label is not None:
            self._gain_label.setVisible(False)
        self.vol_match.toggled.connect(self._on_volume_mode)

        loop_row = QHBoxLayout()
        self.loop_manual = QRadioButton("Manual")
        self.loop_auto = QRadioButton("Whole track")
        self.loop_manual.setChecked(True)
        self.loop_group = QButtonGroup(self)
        self.loop_group.addButton(self.loop_auto)
        self.loop_group.addButton(self.loop_manual)
        self.loop_manual.setToolTip("Set exactly where the loop starts and ends (recommended).")
        self.loop_auto.setToolTip("Play the whole song, then loop back to the start.")
        # "Whole track" placed first, Manual second, with a clear gap between them.
        loop_row.setSpacing(0)
        loop_row.addWidget(self.loop_auto)
        loop_row.addSpacing(28)
        loop_row.addWidget(self.loop_manual)
        loop_row.addStretch(1)
        form.addRow("Looping", loop_row)

        self.loop_fields = QWidget()
        lf = QHBoxLayout(self.loop_fields)
        lf.setContentsMargins(0, 0, 0, 0)
        self.loop_start = QDoubleSpinBox()
        self.loop_start.setRange(0, 100000); self.loop_start.setSuffix(" s"); self.loop_start.setDecimals(2)
        self.loop_end = QDoubleSpinBox()
        self.loop_end.setRange(0, 100000); self.loop_end.setSuffix(" s"); self.loop_end.setDecimals(2)
        self.loop_end.setSpecialValueText("end of track")  # 0 => loop to end
        self.loop_start.valueChanged.connect(self._revalidate)
        self.loop_end.valueChanged.connect(self._revalidate)
        lf.addWidget(QLabel("Start"))
        lf.addWidget(self.loop_start)
        lf.addSpacing(10)
        lf.addWidget(QLabel("End"))
        lf.addWidget(self.loop_end)
        lf.addStretch(1)
        form.addRow("", self.loop_fields)
        form.addRow("", _hint("Loop end of 0 s means loop to the end of the track."))
        self.loop_manual.toggled.connect(self._on_loop_mode)
        return card

    def _build_destination_card(self) -> QFrame:
        """Where the finished file goes: save only, a local mod folder, or FTP.

        Three mutually exclusive choices presented as radio buttons, with only
        the relevant fields revealed for the active choice (§6.2 single-selection
        menus; GR5 prevent errors by not showing irrelevant inputs).
        """
        card, form = _card("folder", "Where to put it")

        self.dest_save = QRadioButton("Just save the file")
        self.dest_local = QRadioButton("Copy into a mod folder on this PC")
        self.dest_ftp = QRadioButton("Send to my Switch over Wi-Fi")
        self.dest_save.setChecked(True)
        self.dest_group = QButtonGroup(self)
        for b in (self.dest_save, self.dest_local, self.dest_ftp):
            self.dest_group.addButton(b)
            b.toggled.connect(self._on_dest_mode)
        self.dest_save.setToolTip("Write the .nus3audio to the output folder below and stop there.")
        self.dest_local.setToolTip("Also copy it straight into an ARCropolis mod folder, e.g. on a mounted SD card.")
        self.dest_ftp.setToolTip("Also upload it to your Switch (needs the ftpd FTP server running).")
        modes = QVBoxLayout()
        modes.setSpacing(4)
        modes.addWidget(self.dest_save)
        modes.addWidget(self.dest_local)
        modes.addWidget(self.dest_ftp)
        form.addRow("Destination", modes)

        # -- Local mod-folder fields (shown only for "Copy into a mod folder") --
        self.local_row = QWidget()
        lr = QFormLayout(self.local_row)
        lr.setContentsMargins(0, 2, 0, 0)
        lr.setHorizontalSpacing(14)
        lr.setVerticalSpacing(7)
        local_pick = QHBoxLayout()
        self.localdir_edit = QLineEdit()
        self.localdir_edit.setReadOnly(True)
        self.localdir_edit.setPlaceholderText("e.g. E:/ultimate/mods/MyMusicPack")
        self.localdir_edit.textChanged.connect(self._on_dest_field_changed)
        local_browse = QPushButton("Choose...")
        local_browse.setObjectName("ghost")
        local_browse.setIcon(_icon("folder", 15, ICON_SLATE))
        local_browse.clicked.connect(self._choose_local_mod_dir)
        local_pick.addWidget(self.localdir_edit, 1)
        local_pick.addWidget(local_browse)
        lr.addRow("Mod folder", local_pick)
        lr.addRow("", _hint("Pick the mod's own folder (the one inside /ultimate/mods/). "
                            "The file is placed in its stream;/sound/bgm subfolder for you."))
        self.local_preview = _hint("")
        self.local_preview.setObjectName("pathPreview")
        lr.addRow("Writes to", self.local_preview)
        self.local_row.setVisible(False)
        form.addRow("", self.local_row)

        # -- FTP fields (shown only for "Send to my Switch") -------------------
        self.ip_edit = QLineEdit()
        self.ip_edit.setPlaceholderText("192.168.1.164")
        self.ip_edit.setToolTip("Your Switch's IP address, shown in the ftpd app.")
        self.ip_edit.textChanged.connect(self._on_dest_field_changed)
        self.port_edit = QLineEdit()
        self.port_edit.setText(str(backend.DEFAULT_FTP_PORT))
        self.port_edit.setPlaceholderText(str(backend.DEFAULT_FTP_PORT))
        self.port_edit.setMaximumWidth(110)
        self.port_edit.setValidator(QIntValidator(1, 65535, self))
        self.port_edit.setToolTip("FTP port shown in the ftpd app (ftpd's default is 5000).")
        self.port_edit.textChanged.connect(self._on_dest_field_changed)
        self.modfolder_edit = QLineEdit()
        self.modfolder_edit.setPlaceholderText("HDR")
        self.modfolder_edit.setToolTip("Name of the mod folder on the SD card, under /ultimate/mods/.")
        self.modfolder_edit.textChanged.connect(self._on_dest_field_changed)
        self.path_preview = _hint("")
        self.path_preview.setObjectName("pathPreview")

        self.switch_row = QWidget()
        sr = QFormLayout(self.switch_row)
        sr.setContentsMargins(0, 2, 0, 0)
        sr.setHorizontalSpacing(14)
        sr.setVerticalSpacing(7)
        # IP + port share a row: the IP takes the space, the port sits beside it.
        addr_row = QHBoxLayout()
        addr_row.setSpacing(8)
        addr_row.addWidget(self.ip_edit, 1)
        port_lbl = QLabel("Port")
        port_lbl.setObjectName("hint")
        addr_row.addWidget(port_lbl)
        addr_row.addWidget(self.port_edit)
        sr.addRow("Switch IP", addr_row)
        sr.addRow("", _hint("Find the IP and port in your Switch's ftpd / homebrew FTP app "
                            "(ftpd's default port is 5000)."))
        sr.addRow("Mod folder", self.modfolder_edit)
        sr.addRow("", _hint("The mod's folder on the SD card, inside /ultimate/mods/."))
        sr.addRow("Sends to", self.path_preview)
        self.switch_row.setVisible(False)
        form.addRow("", self.switch_row)
        return card

    def _build_output_card(self) -> QFrame:
        card, form = _card("folder", "Output")
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        # A writable default (Downloads/Documents/home), not os.getcwd(): a frozen
        # app launched from a Start Menu shortcut inherits a non-writable cwd
        # (System32 / Program Files) on Windows. See backend.default_output_dir.
        self.out_edit.setText(backend.default_output_dir())  # sensible default (8.6)
        browse = QPushButton("Choose...")
        browse.setObjectName("ghost")
        browse.setIcon(_icon("folder", 15, ICON_SLATE))
        browse.clicked.connect(self._choose_output)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(browse)
        form.addRow("Save to", out_row)
        return card

    def _build_footer(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("footer")
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(18, 10, 18, 14)
        lay.setSpacing(10)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        self.progress.setProperty("state", "idle")
        lay.addWidget(self.progress)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("ghost")
        self.cancel_btn.setIcon(_icon("x", 15, ICON_SLATE))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        self.convert_btn = QPushButton("  Convert")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setIcon(_icon("play", 15, "#ffffff"))
        self.convert_btn.setDefault(True)
        self.convert_btn.clicked.connect(self._start)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.convert_btn)
        lay.addLayout(btn_row)
        return bar

    def _set_progress_state(self, state: str) -> None:
        """Recolour the progress bar by semantic state (consistent coding, §12.6)."""
        self.progress.setProperty("state", state)
        self.progress.style().unpolish(self.progress)
        self.progress.style().polish(self.progress)

    def _stylesheet(self) -> str:
        chev_down = _chevron_png("chevron-down", ICON_SLATE)
        chev_up = _chevron_png("chevron-up", ICON_SLATE)
        return f"""
            QWidget {{ font-family: 'Segoe UI', system-ui, sans-serif; font-size: 12px; color:{INK}; }}
            #body, #scroll {{ background: {CANVAS}; }}

            /* Header band: the single reserved high-intensity zone (§3.2.3). */
            #header {{ background: {ACCENT}; }}
            #appTitle {{ color: #ffffff; font-size: 16px; font-weight: 700; }}
            #appSubtitle {{ color: rgba(255,255,255,0.85); font-size: 11px; }}
            #headerBtn {{ background: rgba(255,255,255,0.15); color: #ffffff; border: none;
                          border-radius: 6px; padding: 7px 12px; font-weight: 600; }}
            #headerBtn:hover {{ background: rgba(255,255,255,0.28); }}

            /* Cards group related fields inside a box (§12.6 organisation). */
            #card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            #cardTitle {{ font-size: 12px; font-weight: 700; color: {INK};
                          text-transform: uppercase; letter-spacing: 0.6px; }}
            #hint {{ color: {MUTED}; font-size: 11px; }}
            #pathPreview {{ color: {INK}; font-family: 'Consolas','Menlo',monospace;
                            font-size: 11px; background: {CANVAS}; border: 1px solid {BORDER};
                            border-radius: 5px; padding: 5px 7px; }}

            QLabel {{ background: transparent; }}

            QLineEdit, QComboBox, QDoubleSpinBox {{
                padding: 6px 8px; border: 1px solid {BORDER}; border-radius: 6px;
                background: #ffffff; selection-background-color: {ACCENT};
                min-height: 20px;
            }}
            QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
            QLineEdit:read-only {{ background: {CANVAS}; color: {MUTED}; }}
            QRadioButton, QCheckBox {{ spacing: 7px; color: {INK}; }}
            /* Explicit indicator styling: a global stylesheet strips the native
               radio/checkbox glyphs, leaving solid dark blobs with no clear
               selected state. Draw our own: a white circle with a grey ring
               when off, an accent ring with a filled accent dot when on
               (§12.6 - state must be unambiguous and high-contrast). */
            QRadioButton::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; }}
            QRadioButton::indicator {{ border-radius: 9px; }}
            QCheckBox::indicator {{ border-radius: 4px; }}
            QRadioButton::indicator:unchecked, QCheckBox::indicator:unchecked {{
                border: 2px solid #aab0bd; background: #ffffff;
            }}
            QRadioButton::indicator:unchecked:hover, QCheckBox::indicator:unchecked:hover {{
                border: 2px solid {ACCENT};
            }}
            QRadioButton::indicator:checked {{
                border: 2px solid {ACCENT};
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                            stop:0 {ACCENT}, stop:0.45 {ACCENT}, stop:0.5 #ffffff, stop:1 #ffffff);
            }}
            QCheckBox::indicator:checked {{ border: 2px solid {ACCENT}; background: {ACCENT}; }}
            QRadioButton:disabled, QCheckBox:disabled {{ color: #b6bcc6; }}
            QRadioButton::indicator:disabled, QCheckBox::indicator:disabled {{
                border: 2px solid #d6dae2; background: #f2f3f6;
            }}

            /* Combo arrow: our own chevron, comfortably inside the rounded box
               (replaces the clipped native arrow, §12.6 legibility). */
            QComboBox {{ padding-right: 26px; }}
            QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
                                    width: 22px; border: none; background: transparent; }}
            QComboBox::down-arrow {{ image: url("{chev_down}"); width: 12px; height: 12px; }}

            /* The drop-down list itself: an explicit white surface with dark
               items and an accent highlight, so it never inherits a muddy
               theme-grey that washed out the series headers (§12.6 contrast). */
            QComboBox QAbstractItemView {{
                background: #ffffff; color: {INK};
                border: 1px solid {BORDER}; border-radius: 6px;
                outline: none; padding: 2px;
                selection-background-color: {ACCENT}; selection-color: #ffffff;
            }}
            QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 3px 8px; color: {INK}; }}
            QComboBox QAbstractItemView::item:selected {{ background: {ACCENT}; color: #ffffff; }}

            /* Spin-box steppers: explicit, full-height buttons with our chevrons
               so the up/down arrows are never cut off (fixes "icons cut off"). */
            QDoubleSpinBox {{ padding-right: 22px; }}
            QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
                                         width: 18px; border-left: 1px solid {BORDER};
                                         border-top-right-radius: 6px; background: {CANVAS}; }}
            QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
                                           width: 18px; border-left: 1px solid {BORDER};
                                           border-bottom-right-radius: 6px; background: {CANVAS}; }}
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background: #e3e6ec; }}
            QDoubleSpinBox::up-arrow {{ image: url("{chev_up}"); width: 10px; height: 10px; }}
            QDoubleSpinBox::down-arrow {{ image: url("{chev_down}"); width: 10px; height: 10px; }}

            /* Buttons: only the primary action carries the high-intensity accent. */
            #primary {{ background: {ACCENT}; color: #ffffff; border: none;
                        border-radius: 6px; padding: 8px 18px; font-weight: 600; }}
            #primary:hover {{ background: {ACCENT_DK}; }}
            #primary:disabled {{ background: #e7b6bc; color: #ffffff; }}
            #ghost {{ background: #ffffff; color: {INK}; border: 1px solid {BORDER};
                      border-radius: 6px; padding: 8px 14px; }}
            #ghost:hover {{ background: {CANVAS}; }}
            #ghost:disabled {{ color: #b6bcc6; border-color: #ececf0; }}

            /* Dialogs & message boxes. Applying an app-wide stylesheet strips the
               native chrome from their generic buttons and labels, which left
               flat grey-text-on-grey. Give them an explicit light surface, dark
               text, and properly contrasting buttons (§12.6 legibility). */
            QDialog, QMessageBox {{ background: {SURFACE}; }}
            QDialog QLabel, QMessageBox QLabel {{ color: {INK}; background: transparent; }}
            QMessageBox QPushButton, QDialog QPushButton {{
                background: #ffffff; color: {INK}; border: 1px solid {BORDER};
                border-radius: 6px; padding: 7px 16px; min-width: 84px; font-weight: 600;
            }}
            QMessageBox QPushButton:hover, QDialog QPushButton:hover {{ background: {CANVAS}; }}
            QMessageBox QPushButton:default, QDialog QPushButton:default {{
                background: {ACCENT}; color: #ffffff; border: none;
            }}
            QMessageBox QPushButton:default:hover, QDialog QPushButton:default:hover {{ background: {ACCENT_DK}; }}

            #banner {{ background: {WARNING_BG}; border: 1px solid {WARNING_BD};
                       border-radius: 8px; }}
            #bannerText {{ color: {WARNING_FG}; font-size: 11px; background: transparent; }}
            #installBtn {{ background: {WARNING_FG}; color: #ffffff; border: none;
                           border-radius: 6px; padding: 7px 14px; font-weight: 600; }}
            #installBtn:hover {{ background: #5e3900; }}
            #installBtn:disabled {{ background: #c9ad84; color: #ffffff; }}

            #footer {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
            QProgressBar {{ border: 1px solid {BORDER}; border-radius: 7px; text-align: center;
                            height: 20px; background: {CANVAS}; color: {INK}; font-size: 11px; }}
            QProgressBar::chunk {{ border-radius: 6px; background: {ACCENT}; }}
            QProgressBar[state="done"]::chunk {{ background: {SUCCESS}; }}
            QProgressBar[state="cancel"]::chunk {{ background: {WARNING_FG}; }}

            QListWidget#history {{ background: #ffffff; border: 1px solid {BORDER};
                                   border-radius: 8px; padding: 4px; }}
            QListWidget#history::item {{ padding: 8px 10px; border-bottom: 1px solid {BORDER};
                                         color: {INK}; }}
            QListWidget#history::item:selected {{ background: {CANVAS}; color: {INK}; }}

            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: #c7ccd6; border-radius: 5px; min-height: 24px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """

    # -- state / validation -------------------------------------------------

    def _selected_song(self) -> Optional[dict]:
        idx = self.song_combo.currentIndex()
        if 0 <= idx < self.song_combo.count():
            return self.song_combo.itemData(idx)
        return None

    def _on_song_changed(self) -> None:
        song = self._selected_song()
        if song:
            self.resolved_label.setText(
                f"Will replace <b>{song['bgm_id']}</b>  (series: {song['series']})")
        else:
            self.resolved_label.setText("")
        self._update_path_preview()
        self._revalidate()

    def _on_loop_mode(self, manual: bool) -> None:
        self.loop_fields.setVisible(manual)
        self._revalidate()

    def _on_volume_mode(self, match_checked: bool) -> None:
        # Manual boost field is only meaningful when not auto-matching.
        self.gain_row_widget.setVisible(not match_checked)
        if getattr(self, "_gain_label", None) is not None:
            self._gain_label.setVisible(not match_checked)

    def _on_dest_mode(self) -> None:
        self.local_row.setVisible(self.dest_local.isChecked())
        self.switch_row.setVisible(self.dest_ftp.isChecked())
        self._update_path_preview()
        self._revalidate()

    def _on_dest_field_changed(self) -> None:
        self._update_path_preview()
        self._revalidate()

    def _mod_folder(self) -> str:
        """Mod folder name on the SD card, defaulting to the placeholder."""
        return self.modfolder_edit.text().strip() or "HDR"

    def _ftp_port(self) -> int:
        """FTP port, falling back to ftpd's default if the field is blank/bad."""
        try:
            port = int(self.port_edit.text().strip())
        except (ValueError, AttributeError):
            return backend.DEFAULT_FTP_PORT
        return port if 1 <= port <= 65535 else backend.DEFAULT_FTP_PORT

    def _choose_local_mod_dir(self) -> None:
        start = self.localdir_edit.text().strip() or self.out_edit.text().strip() or os.getcwd()
        path = QFileDialog.getExistingDirectory(self, "Choose the mod folder", start)
        if path:
            self.localdir_edit.setText(path)

    def _update_path_preview(self) -> None:
        """Show the exact path the file will be written to for each mode (GR3)."""
        song = self._selected_song()
        # The on-SD filename ARCropolis matches keeps the full bgm_ prefix.
        fname = f"{song['bgm_id']}.nus3audio" if song else "<song>.nus3audio"
        sub = backend.ARC_STREAM_SUBPATH
        self.path_preview.setText(
            f"sd:/ultimate/mods/{self._mod_folder()}/{sub}/{fname}")
        base = self.localdir_edit.text().strip() or "<mod folder>"
        self.local_preview.setText(f"{base}/{sub}/{fname}")

    def _revalidate(self) -> None:
        """Enable Convert only when every input is valid (Golden Rule 5)."""
        problems = []
        url = self.url_edit.text().strip()
        if not url:
            problems.append("link")
        if self._selected_song() is None:
            problems.append("song")
        if self.loop_manual.isChecked():
            end = self.loop_end.value()
            if end != 0 and end <= self.loop_start.value():
                problems.append("loop")
        if self.dest_ftp.isChecked():
            if not _looks_like_ip(self.ip_edit.text()):
                problems.append("ip")
            if not self.modfolder_edit.text().strip():
                problems.append("modfolder")
        if self.dest_local.isChecked():
            if not self.localdir_edit.text().strip():
                problems.append("localdir")
        self.convert_btn.setEnabled(not problems)

    def _choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", self.out_edit.text())
        if path:
            self.out_edit.setText(path)

    def _run_preflight(self) -> None:
        problems = backend.preflight()
        if not problems:
            self.banner.setVisible(False)
            return

        self.banner.setVisible(True)
        # First time we detect missing tools, start the download automatically:
        # no button to hunt for, no files to copy or drag (GR7 keep users in
        # control with feedback; the work runs on a worker thread).
        if not self._auto_install_started:
            self._auto_install_started = True
            self.banner_label.setText(
                "Setting up the components needed to convert. "
                "This happens automatically and only once — it takes a minute.")
            self.install_btn.setVisible(False)
            self._install_components()
            return

        # If the automatic attempt didn't fully succeed, offer a one-click retry.
        self.banner_label.setText(
            "Some components still aren't ready:<br>• "
            + "<br>• ".join(problems)
            + "<br><br>This usually means the connection dropped. You can retry the "
              "automatic setup.")
        self.install_btn.setText("  Try setup again")
        self.install_btn.setVisible(True)

    # -- install missing components (§12.8 constructive recovery) -----------

    def _install_components(self) -> None:
        self.install_btn.setEnabled(False)
        self.install_progress.setValue(0)
        self.install_progress.setFormat("Starting download...")
        self.install_progress.setVisible(True)
        self.banner_label.setText("Downloading and installing components...")

        self._install_thread = QThread(self)
        self._install_worker = ToolInstallWorker()
        self._install_worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(self._install_worker.run)
        self._install_worker.progress.connect(self._on_install_progress)
        self._install_worker.finished.connect(self._on_install_finished)
        self._install_worker.failed.connect(self._on_install_failed)
        for sig in (self._install_worker.finished, self._install_worker.failed):
            sig.connect(self._install_thread.quit)
        self._install_thread.finished.connect(self._cleanup_install_thread)
        self._install_thread.start()

    def _on_install_progress(self, fraction: float, message: str) -> None:
        self.install_progress.setValue(int(fraction * 100))
        self.install_progress.setFormat(f"{message}  -  %p%")

    def _on_install_finished(self) -> None:
        self.install_progress.setVisible(False)
        remaining = backend.preflight()
        if remaining:
            # Partial success: keep the banner, report what's still missing.
            self.install_btn.setEnabled(True)
            self._run_preflight()
            QMessageBox.information(
                self, "Almost there",
                "Some components installed, but these still need attention:\n\n• "
                + "\n• ".join(remaining))
        else:
            self.banner.setVisible(False)
            QMessageBox.information(
                self, "All set",
                "All components are installed. You're ready to convert.")
        self._revalidate()

    def _on_install_failed(self, message: str) -> None:
        self.install_progress.setVisible(False)
        self.install_btn.setEnabled(True)
        self._run_preflight()
        QMessageBox.warning(self, "Couldn't finish installing components", message)

    def _cleanup_install_thread(self) -> None:
        self._install_worker = None
        self._install_thread = None

    # -- settings persistence (Golden Rule 8) -------------------------------

    def _restore_settings(self) -> None:
        ip = self._settings.value("switch_ip", "")
        if ip:
            self.ip_edit.setText(str(ip))
        mod = self._settings.value("mod_folder", "")
        if mod:
            self.modfolder_edit.setText(str(mod))
        out = self._settings.value("output_dir", "")
        if out and os.path.isdir(str(out)):
            self.out_edit.setText(str(out))
        local = self._settings.value("local_mod_dir", "")
        if local:
            self.localdir_edit.setText(str(local))

    def _save_settings(self) -> None:
        self._settings.setValue("switch_ip", self.ip_edit.text().strip())
        self._settings.setValue("mod_folder", self.modfolder_edit.text().strip())
        self._settings.setValue("output_dir", self.out_edit.text().strip())
        self._settings.setValue("local_mod_dir", self.localdir_edit.text().strip())

    # -- run / cancel -------------------------------------------------------

    def _build_config(self) -> ConversionConfig:
        song = self._selected_song()
        if self.loop_manual.isChecked():
            end = self.loop_end.value()
            loop = LoopSpec.manual_seconds(self.loop_start.value(), None if end == 0 else end)
        else:
            loop = LoopSpec.auto()
        volume_mode = backend.VOLUME_MATCH if self.vol_match.isChecked() else backend.VOLUME_MANUAL
        return ConversionConfig(
            url=self.url_edit.text().strip(),
            bgm_id=song["bgm_id"],
            output_dir=self.out_edit.text().strip() or os.getcwd(),
            volume_mode=volume_mode,
            gain_db=self.gain_spin.value(),
            loop=loop,
            ftp_ip=self.ip_edit.text().strip() if self.dest_ftp.isChecked() else None,
            ftp_port=self._ftp_port(),
            ftp_mod_name=self._mod_folder(),
            local_mod_dir=self.localdir_edit.text().strip() if self.dest_local.isChecked() else None,
        )

    # -- modded-song ledger -------------------------------------------------

    @staticmethod
    def _format_when(iso: str) -> str:
        """Human-friendly local time, e.g. 'Jun 2, 2026 6:28 PM'."""
        if not iso:
            return ""
        try:
            from datetime import datetime
            return datetime.fromisoformat(iso).strftime("%b %-d, %Y %-I:%M %p")
        except (ValueError, TypeError):
            return iso

    def _confirm_overwrite(self, config: ConversionConfig, song: Optional[dict]) -> bool:
        """If this slot is already modded, ask before clobbering it (GR5/GR6)."""
        prior = ledger.find(config.bgm_id, config.output_dir)
        if not prior:
            return True
        name = (song or {}).get("name") or prior.get("name") or ""
        box = QMessageBox(self)
        box.setIconPixmap(_make_pixmap("alert", 40, WARNING_FG))
        box.setWindowTitle("This slot is already modded")
        body = f"You've already replaced <b>{config.bgm_id}</b>"
        if name:
            body += f" ({name})"
        body += "."
        when = self._format_when(prior.get("modded_at", ""))
        if when:
            body += f"<br>Last modded {when}."
        if prior.get("filename"):
            body += f"<br>Existing file: <b>{prior['filename']}</b>."
        body += "<br><br>Converting again will overwrite it. Continue?"
        box.setText(body)
        overwrite = box.addButton("Overwrite", QMessageBox.AcceptRole)
        keep = box.addButton("Keep existing", QMessageBox.RejectRole)
        box.setDefaultButton(keep)  # default to the safe, non-destructive choice
        box.exec()
        return box.clickedButton() is overwrite

    def _record_mod(self, result) -> None:
        """Record a successful conversion to both ledgers (never raises)."""
        config = self._active_config
        if config is None:
            return
        song = self._active_song or {}
        try:
            ledger.record(ledger.ModEntry.create(
                bgm_id=config.bgm_id,
                name=song.get("name", ""),
                series=song.get("series", ""),
                internal_name=config.internal_name,
                filename=os.path.basename(result.nus3audio_path),
                mod_folder=config.ftp_mod_name,
                output_dir=config.output_dir,
                source_url=config.url,
                uploaded=bool(result.uploaded),
                loop_start=int(result.loop_start),
                loop_end=int(result.loop_end),
            ))
        except Exception:
            pass  # bookkeeping must never sink a successful conversion

    def _show_history(self) -> None:
        """A simple viewer over the global record of modded slots."""
        entries = ledger.all_entries()
        dlg = QDialog(self)
        dlg.setWindowTitle("Modded songs")
        dlg.setMinimumSize(460, 380)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)

        head = QLabel(f"{len(entries)} slot{'s' if len(entries) != 1 else ''} recorded"
                      if entries else "Nothing modded yet")
        head.setObjectName("cardTitle")
        v.addWidget(head)

        if entries:
            lst = QListWidget()
            lst.setObjectName("history")
            for e in entries:
                name = e.get("name") or e.get("bgm_id", "")
                when = self._format_when(e.get("modded_at", ""))
                suffix = "   •   sent to Switch" if e.get("uploaded") else ""
                lst.addItem(QListWidgetItem(
                    f"{name}\n{e.get('bgm_id', '')}   ·   {when}{suffix}"))
            v.addWidget(lst, 1)
            v.addWidget(_hint("Saved in each output folder as modded_songs.json, "
                              "plus a global history."))
        else:
            v.addWidget(_hint("Convert a track and it'll appear here. The record is saved to "
                              "modded_songs.json in your output folder and a global history."))
            v.addStretch(1)

        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)

        dlg.setStyleSheet(self._stylesheet())
        dlg.exec()

    def _show_about(self) -> None:
        """Credits dialog.

        Design notes (Shneiderman et al., 6th ed.):
        * **Consistency (GR1).** Reuses the app's palette and type via
          ``_stylesheet`` so the dialog reads as the same product.
        * **Two intensity levels only (§3.2.3).** Calm dark-on-light text. The
          author credit and the open-source acknowledgements are uniform,
          low-intensity lines in the same format, so nothing shouts and no line
          competes for attention. No external links.
        * **Closure (GR4).** A clear, self-contained panel with an explicit Close.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("About")
        dlg.setMinimumWidth(430)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(20, 20, 20, 18)
        v.setSpacing(12)

        # Identity: marked logo + name + version (recognition, GR8).
        ident = QHBoxLayout()
        ident.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(_make_pixmap("logo", 34, ACCENT))
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignCenter)
        ident.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        name = QLabel(APP_NAME)
        name.setObjectName("aboutTitle")
        ver = QLabel(f"Version {APP_VERSION}")
        ver.setObjectName("hint")
        titles.addWidget(name)
        titles.addWidget(ver)
        ident.addLayout(titles)
        ident.addStretch(1)
        v.addLayout(ident)

        v.addWidget(_hint("Turn a YouTube link into a Smash Ultimate music mod."))

        # Credit + acknowledgements: uniform low-intensity lines, identical
        # format, no hyperlinks.
        v.addWidget(_hint(f"Created by {AUTHORS}."))
        v.addWidget(_hint(
            "Built with yt-dlp, FFmpeg, VGAudio, nus3audio, PySide6, pydub and "
            "NumPy — each under its own license. This project is MIT-licensed."))
        v.addWidget(_hint(
            "Ships no copyrighted audio. Not affiliated with or endorsed by "
            "Nintendo. Super Smash Bros. Ultimate is a trademark of Nintendo."))

        # A single, low-key action.
        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(dlg.accept)
        actions.addWidget(close)
        v.addLayout(actions)

        dlg.setStyleSheet(self._stylesheet() + f"""
            #aboutTitle {{ font-size: 16px; font-weight: 700; color: {INK}; }}
        """)
        dlg.exec()

    def _set_running(self, running: bool) -> None:
        for w in (self.url_edit, self.song_combo, self.vol_match, self.vol_manual,
                  self.gain_spin, self.loop_manual, self.loop_auto, self.loop_fields,
                  self.dest_save, self.dest_local, self.dest_ftp,
                  self.local_row, self.switch_row):
            w.setEnabled(not running)
        self.convert_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)

    def _start(self) -> None:
        self._save_settings()
        config = self._build_config()
        song = self._selected_song()

        # Prevent errors (GR5): warn before clobbering a slot we've modded before.
        if not self._confirm_overwrite(config, song):
            return

        self._active_config = config
        self._active_song = song

        self._thread = QThread(self)
        self._worker = ConversionWorker(config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        for sig in (self._worker.finished, self._worker.failed, self._worker.cancelled):
            sig.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)

        self._set_running(True)
        self._set_progress_state("idle")
        self.progress.setValue(0)
        self.progress.setFormat("Starting...")
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.request_cancel()
            self.cancel_btn.setEnabled(False)
            self.progress.setFormat("Finishing current step, then stopping...")

    def _on_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(int(fraction * 100))
        self.progress.setFormat(f"{message}  -  %p%")

    def _on_finished(self, result) -> None:
        # Closure (Golden Rule 4): a clear, satisfying end state.
        self._set_progress_state("done")
        self.progress.setValue(100)
        self.progress.setFormat("Done")
        self._set_running(False)
        self._record_mod(result)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Conversion complete")
        body = f"Saved <b>{os.path.basename(result.nus3audio_path)}</b>."
        if result.uploaded:
            body += "<br>Sent to your Switch - it's ready in-game."
        if self._active_config and self._active_config.local_mod_dir:
            body += "<br>Copied into your mod folder."
        box.setText(body)
        open_btn = box.addButton("Open folder", QMessageBox.ActionRole)
        box.addButton("Done", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_folder(os.path.dirname(result.nus3audio_path))

    def _on_failed(self, title: str, body: str) -> None:
        self._set_progress_state("idle")
        self.progress.setValue(0)
        self.progress.setFormat("Ready")
        self._set_running(False)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(title)            # specific + constructive (12.8)
        box.setText(body)
        box.exec()

    def _on_cancelled(self) -> None:
        self._set_progress_state("cancel")
        self.progress.setValue(0)
        self.progress.setFormat("Cancelled")
        self._set_running(False)

    def _cleanup_thread(self) -> None:
        self._worker = None
        self._thread = None

    @staticmethod
    def _open_folder(path: str) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess; subprocess.Popen(["open", path])
            else:
                webbrowser.open(f"file://{path}")
        except Exception:
            pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
