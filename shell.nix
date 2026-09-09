{ pkgs ? import <nixpkgs> {} }:

let
  pythonEnv = pkgs.python3.withPackages (ps: with ps; [
    pyqt5          # simplest Qt bindings for the UI
    yt-dlp         # YouTube (and other) download backend
  ]);
in
pkgs.mkShell {
  name = "qtytd";

  packages = [
    pythonEnv
    pkgs.ffmpeg    # muxing / post-processing for yt-dlp
    pkgs.qt5.qtbase
    pkgs.qt5.qtwayland
  ];

  # Help Qt find its platform plugins inside nix-shell
  QT_QPA_PLATFORM_PLUGIN_PATH = "${pkgs.qt5.qtbase.bin}/lib/qt-${pkgs.qt5.qtbase.version}/plugins";
  QT_PLUGIN_PATH = "${pkgs.qt5.qtbase.bin}/lib/qt-${pkgs.qt5.qtbase.version}/plugins";

  shellHook = ''
    echo "QTYTD nix-shell"
    echo "  python : $(python3 --version)"
    echo "  Qt     : PyQt5"
    echo "  ytdlp  : $(yt-dlp --version 2>/dev/null || echo bundled)"
  '';
}
