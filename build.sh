#!/bin/bash

nuitka \
    --user-package-configuration-file=package-configs.yml \
    --standalone \
    --output-dir=dist \
    --output-filename=neon-player-6 \
    --remove-output \
    --python-flag=isolated \
    --plugin-enable=pyside6 \
    --include-module=bdb \
    --include-module=numpy._core._exceptions \
    --include-module=pdb \
    --include-module=unittest \
    --include-module=unittest.mock \
    --include-module=cmath \
    --include-module=http.cookies \
    --include-data-dir=./src/pupil_labs/neon_player/assets=pupil_labs/neon_player/assets \
    --macos-create-app-bundle \
    --macos-signed-app-name=com.pupil-labs.neon_player \
    --company-name="Pupil Labs" \
    --product-name="Neon Player" \
    --product-version="6.0.0.0" \
    --linux-icon=./src/pupil_labs/neon_player/assets/neon-player.svg \
    --macos-app-name="Neon Player" \
    --macos-app-icon=./src/pupil_labs/neon_player/assets/icon.icns \
    --macos-app-version=6.0 \
    --windows-icon-from-ico=./src/pupil_labs/neon_player/assets/neon-player.ico \
    src/pupil_labs/neon_player/__main__.py

if [ "$(uname)" = "Darwin" ]; then
    mv dist/__main__.app dist/neon-player-6.app
    rm -rf dist/__main__.dist
else
    mv dist/__main__.dist dist/neon-player-6
fi
