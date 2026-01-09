#!/bin/bash

set -e

VERSION=$(uv run python -c "from importlib.metadata import version; print(version('pupil_labs.neon_player'))")
VERSION_SIMPLE=$(echo "$VERSION" | awk -F. '{print $1"."$2"."$3}' | grep -Eo '^[0-9\.]*')

echo "Build $VERSION ($VERSION_SIMPLE)"

uv run pyside6-uic src/pupil_labs/neon_player/assets/splash.ui \
    -o src/pupil_labs/neon_player/ui/splash.py

UV_PATH=$(uv run python -c "import uv; print(uv.find_uv_bin())")

uv run -m nuitka src/pupil_labs/neon_player \
    --assume-yes-for-downloads \
    --user-package-configuration-file=package-configs.yml \
    --standalone \
    --output-dir=dist \
    --output-filename=neon-player \
    --remove-output \
    --python-flag=isolated \
    --include-data-dir=./src/pupil_labs/neon_player/assets=pupil_labs/neon_player/assets \
    --include-data-files="$UV_PATH"=uv \
    --nofollow-import-to=uv \
    --macos-create-app-bundle \
    --macos-signed-app-name=com.pupil-labs.neon_player \
    --company-name="Pupil Labs" \
    --product-name="Neon Player" \
    --product-version="$VERSION_SIMPLE.0" \
    --linux-icon=./src/pupil_labs/neon_player/assets/neon-player.svg \
    --macos-app-name="Neon Player" \
    --macos-app-icon=./src/pupil_labs/neon_player/assets/icon.icns \
    --macos-app-version="$VERSION_SIMPLE" \
    --windows-icon-from-ico=./src/pupil_labs/neon_player/assets/neon-player.ico \
    --plugin-enable=pyside6 \
    --include-module=bdb \
    --include-module=numpy._core._exceptions \
    --include-module=pdb \
    --include-module=unittest \
    --include-module=unittest.mock \
    --include-module=http.cookies \
    --include-module=PySide6.QtOpenGL \
    --include-package-data=qt_property_widgets \
    --include-package=plistlib \
    --include-package=google.protobuf \
    --include-module=ctypes.util \
    --include-module=cmath \
    --include-module=zoneinfo

cp -r deployment/* dist/
cd dist

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    sed -i "s/{{VERSION}}/$VERSION/g" linux/DEBIAN/control
    sed -i "s/{{VERSION}}/$VERSION/g" linux/usr/share/applications/neon-player.desktop
    mkdir -p ./linux/opt
    mv neon_player.dist ./linux/opt/neon-player
    dpkg-deb --build linux ./neon-player-$VERSION.deb

elif [[ "$OSTYPE" == "darwin"* ]]; then
    mkdir dmg
    ln -s /Applications dmg/Applications
    mv neon_player.app "dmg/Neon Player.app"
    hdiutil create -fs HFS+J -volname "Install Neon Player $VERSION" -srcfolder dmg -ov -format UDZO "neon-player-$VERSION.dmg"

elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    sed -i "s/{{VERSION}}/$VERSION/g" windows/neon-player.iss
    "/c/Program Files (x86)/Inno Setup 6/iscc.exe" windows/neon-player.iss
fi
