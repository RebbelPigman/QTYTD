#!/usr/bin/env python3
"""QTYTD — simplest Qt YouTube downloader."""

import sys
import os
import urllib.request

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

import yt_dlp


def fmt_mb(n):
    if not n:
        return "0 Mb"
    return f"{n / (1024 * 1024):.1f} Mb"


def looks_like_url(text):
    t = text.strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def fetch_thumb(url):
    if not url:
        return b""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read()
    except Exception:
        return b""


def format_bytes(info):
    """Best-effort total size of the formats yt-dlp will download."""
    total = 0
    fmts = info.get("requested_formats")
    if fmts:
        for f in fmts:
            total += f.get("filesize") or f.get("filesize_approx") or 0
    if not total:
        total = info.get("filesize") or info.get("filesize_approx") or 0
    return int(total)


class InfoWorker(QThread):
    ready = pyqtSignal(str, bytes, int)  # title, thumb, expected bytes
    failed = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        opts = {"noprogress": True, "quiet": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                meta = ydl.extract_info(self.url, download=False)
            title = meta.get("title") or ""
            thumb = fetch_thumb(meta.get("thumbnail"))
            self.ready.emit(title, thumb, format_bytes(meta))
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, out_dir, expected):
        super().__init__()
        self.url = url
        self.out_dir = out_dir
        self.expected = expected

    def run(self):
        done_files = 0
        peak = 0

        def hook(d):
            nonlocal done_files, peak
            status = d.get("status")
            if status == "finished":
                done_files += d.get("total_bytes") or d.get("downloaded_bytes") or 0
                return
            if status != "downloading":
                return
            cur = d.get("downloaded_bytes") or 0
            part_total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = done_files + cur
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

        layout.addWidget(QLabel("YouTube link"))
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste URL here")
        self.url.textChanged.connect(self.on_url_changed)
        layout.addWidget(self.url)

        self.url_timer = QTimer(self)
        self.url_timer.setSingleShot(True)
        self.url_timer.setInterval(400)
        self.url_timer.timeout.connect(self.fetch_info)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit(self.out_dir)
        self.folder.setReadOnly(True)
        browse = QPushButton("Folder…")
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder)
        folder_row.addWidget(browse)
        layout.addLayout(folder_row)

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

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Download folder", self.out_dir)
        if path:
            self.out_dir = path
            self.folder.setText(path)

    def on_url_changed(self, _text):
        self.url_timer.start()

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


def main():
    # Do not force a style — use the system / desktop Qt theme.
    app = QApplication(sys.argv)
    win = Window()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
