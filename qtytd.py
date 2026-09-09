#!/usr/bin/env python3
"""QTYTD — simplest Qt YouTube downloader."""

# --- stdlib ---
import sys
import os
import urllib.request

# --- Qt widgets used by the window ---
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
)
from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap

# --- download backend ---
import yt_dlp


# Turn a byte count into "12.3 Mb" for the label above the bar.
def fmt_mb(n):
    if not n:
        return "0 Mb"
    return f"{n / (1024 * 1024):.1f} Mb"


# Only fetch metadata when the field looks like an http(s) URL.
def looks_like_url(text):
    t = text.strip().lower()
    return t.startswith("http://") or t.startswith("https://")


# Download thumbnail image bytes from the URL yt-dlp reports.
def fetch_thumb(url):
    if not url:
        return b""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read()
    except Exception:
        return b""


# Best-effort total size of the formats yt-dlp will actually download
# (video + audio when they are separate streams).
def format_bytes(info):
    total = 0
    fmts = info.get("requested_formats")
    if fmts:
        for f in fmts:
            total += f.get("filesize") or f.get("filesize_approx") or 0
    if not total:
        total = info.get("filesize") or info.get("filesize_approx") or 0
    return int(total)


# Background thread: resolve title, thumbnail, and expected size after paste.
class InfoWorker(QThread):
    ready = pyqtSignal(str, bytes, int)  # title, thumb bytes, expected size
    failed = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        # skip_download: metadata only, no file written
        opts = {"noprogress": True, "quiet": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                meta = ydl.extract_info(self.url, download=False)
            title = meta.get("title") or ""
            thumb = fetch_thumb(meta.get("thumbnail"))
            self.ready.emit(title, thumb, format_bytes(meta))
        except Exception as exc:
            self.failed.emit(str(exc))


# Background thread: download the video and report accumulated progress.
class DownloadWorker(QThread):
    progress = pyqtSignal(int, int)  # bytes done, bytes total
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, out_dir, expected):
        super().__init__()
        self.url = url
        self.out_dir = out_dir
        self.expected = expected  # size from InfoWorker, if known

    def run(self):
        # yt-dlp often downloads video then audio; add those parts together
        # so the bar does not jump back to 0 between streams.
        done_files = 0
        peak = 0

        def hook(d):
            nonlocal done_files, peak
            status = d.get("status")
            # A stream finished: lock in its size and wait for the next one.
            if status == "finished":
                done_files += d.get("total_bytes") or d.get("downloaded_bytes") or 0
                return
            if status != "downloading":
                return
            cur = d.get("downloaded_bytes") or 0
            part_total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = done_files + cur
            # Never let the displayed amount go backwards.
            if done < peak:
                done = peak
            else:
                peak = done
            total = self.expected
            if not total:
                total = done_files + part_total
            if total < done:
                total = done
            self.progress.emit(int(done), int(total))

        # Save as "<title>.<ext>" in the chosen folder.
        opts = {
            "outtmpl": os.path.join(self.out_dir, "%(title)s.%(ext)s"),
            "noprogress": True,
            "progress_hooks": [hook],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.url])
            self.finished.emit("Download finished.")
        except Exception as exc:
            self.failed.emit(str(exc))


# Main window: link, folder, preview, progress, download.
class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QTYTD")
        self.setMinimumWidth(520)
        self.out_dir = os.path.expanduser("~/Downloads")
        self.worker = None
        self.info_worker = None
        self.expected = 0
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)

        # Thumbnail + title row (filled after a URL is pasted).
        media = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(160, 90)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background: palette(mid);")
        self.title = QLabel("Title")
        self.title.setWordWrap(True)
        media.addWidget(self.thumb)
        media.addWidget(self.title, 1)
        layout.addLayout(media)

        # URL field; typing/pasting starts a short debounce timer.
        layout.addWidget(QLabel("YouTube link"))
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste URL here")
        self.url.textChanged.connect(self.on_url_changed)
        layout.addWidget(self.url)

        # Wait 400ms after the last edit so we do not query on every keystroke.
        self.url_timer = QTimer(self)
        self.url_timer.setSingleShot(True)
        self.url_timer.setInterval(400)
        self.url_timer.timeout.connect(self.fetch_info)

        # Output folder path + browse button.
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(self.out_dir)
        self.folder.setReadOnly(True)
        browse = QPushButton("Folder…")
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

        # "xx Mb / xx Mb" sits directly above the bar.
        self.size_label = QLabel("0 Mb / 0 Mb")
        self.size_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.size_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        self.go = QPushButton("Download")
        self.go.clicked.connect(self.start_download)
        layout.addWidget(self.go)

        self.status = QLabel("")
        layout.addWidget(self.status)

    # System folder picker; keep the chosen path.
    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Download folder", self.out_dir)
        if path:
            self.out_dir = path
            self.folder.setText(path)

    # Restart the debounce timer on every change to the URL field.
    def on_url_changed(self, _text):
        self.url_timer.start()

    # After debounce: start InfoWorker if the text is a URL.
    def fetch_info(self):
        url = self.url.text().strip()
        if not looks_like_url(url):
            return
        if self.info_worker and self.info_worker.isRunning():
            self.info_worker.terminate()
        self.status.setText("Loading info…")
        self.info_worker = InfoWorker(url)
        self.info_worker.ready.connect(self.on_info)
        self.info_worker.failed.connect(self.on_info_err)
        self.info_worker.start()

    # Apply title, thumb, and expected size from InfoWorker.
    def on_info(self, title, thumb_bytes, expected):
        self.title.setText(title or "Untitled")
        self.expected = expected
        if expected:
            self.size_label.setText(f"0 Mb / {fmt_mb(expected)}")
        if thumb_bytes:
            pix = QPixmap()
            pix.loadFromData(thumb_bytes)
            self.thumb.setPixmap(
                pix.scaled(self.thumb.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.thumb.clear()
        self.status.setText("")

    def on_info_err(self, msg):
        self.status.setText("Could not load video info.")

    # Validate inputs, then start DownloadWorker.
    def start_download(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.warning(self, "QTYTD", "Paste a YouTube link first.")
            return
        if not os.path.isdir(self.out_dir):
            QMessageBox.warning(self, "QTYTD", "Choose a valid folder.")
            return

        self.go.setEnabled(False)
        self.bar.setValue(0)
        self.size_label.setText(f"0 Mb / {fmt_mb(self.expected)}")
        self.status.setText("Downloading…")
        self.worker = DownloadWorker(url, self.out_dir, self.expected)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_ok)
        self.worker.failed.connect(self.on_err)
        self.worker.start()

    # Update Mb label and bar from the worker hook.
    def on_progress(self, done, total):
        self.size_label.setText(f"{fmt_mb(done)} / {fmt_mb(total)}")
        if total > 0:
            self.bar.setValue(min(100, int(done * 100 / total)))

    def on_ok(self, msg):
        self.go.setEnabled(True)
        self.bar.setValue(100)
        if self.expected:
            self.size_label.setText(f"{fmt_mb(self.expected)} / {fmt_mb(self.expected)}")
        self.status.setText(msg)

    def on_err(self, msg):
        self.go.setEnabled(True)
        self.status.setText("Failed.")
        QMessageBox.critical(self, "QTYTD", msg)


# App entry: no style override so the desktop Qt theme is used.
def main():
    app = QApplication(sys.argv)
    win = Window()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
