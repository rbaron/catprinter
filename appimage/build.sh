#!/bin/sh
# Builds dist/CatPrinter-<version>-x86_64.AppImage.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build/appimage"
APPDIR="$BUILD/AppDir"
APP_ID=io.github.catprinter.Gui
APPIMAGETOOL_VERSION=1.9.1
TOOL="$BUILD/tools/appimagetool-$APPIMAGETOOL_VERSION-x86_64.AppImage"
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage"
VERSION="$(cd "$ROOT" && python3 -c 'import catprinter_gui; print(catprinter_gui.VERSION)')"
OUTPUT="$ROOT/dist/CatPrinter-$VERSION-x86_64.AppImage"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/share/catprinter" "$BUILD/tools" "$ROOT/dist"

# App code. img.py needs OpenCV and is only used by the command line tool.
for pkg in catprinter catprinter_gui; do
    cp -r "$ROOT/$pkg" "$APPDIR/usr/share/catprinter/"
done
find "$APPDIR" -name __pycache__ -prune -exec rm -rf {} +
rm -f "$APPDIR/usr/share/catprinter/catprinter/img.py"

python3 -m pip install --quiet --no-compile \
    --target "$APPDIR/usr/share/catprinter/vendor" -r "$ROOT/appimage/requirements.txt"
rm -rf "$APPDIR/usr/share/catprinter/vendor/bin"
if find "$APPDIR/usr/share/catprinter/vendor" -name '*.so' | grep -q .; then
    echo "Error: bundled dependencies must be pure Python" >&2
    exit 1
fi

cp "$ROOT/appimage/AppRun" "$APPDIR/AppRun"
cp "$ROOT/catprinter_gui/data/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
ln -sf "$APP_ID.svg" "$APPDIR/.DirIcon"
mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$APPDIR/usr/share/applications"
cp "$ROOT/catprinter_gui/data/$APP_ID.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
cat > "$APPDIR/$APP_ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Impresora térmica
Comment=Imprime imágenes, PDF, documentos y texto en tu impresora térmica
Exec=catprinter %F
Icon=$APP_ID
Terminal=false
Categories=Graphics;Utility;
DESKTOP
cp "$APPDIR/$APP_ID.desktop" "$APPDIR/usr/share/applications/"

if [ ! -x "$TOOL" ]; then
    echo "Downloading appimagetool $APPIMAGETOOL_VERSION..."
    curl -fL -o "$TOOL" "$TOOL_URL"
    chmod +x "$TOOL"
fi
# Build next to the output and rename, so a running copy is not overwritten.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUTPUT.tmp"
mv -f "$OUTPUT.tmp" "$OUTPUT"
echo "Built $OUTPUT"
