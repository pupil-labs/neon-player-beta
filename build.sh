#!/bin/bash

nuitka \
  --standalone \
  --output-dir=dist \
  --output-filename=neon-player-6 \
  --plugin-enable=pyside6 \
  --include-module=bdb \
  --include-module=numpy._core._exceptions \
  --include-module=pdb \
  --include-module=unittest \
  --python-flag=isolated \
  --company-name="Pupil Labs" \
  --product-name="Neon Player" \
  --product-version="6.0.0.0" \
  --include-data-dir=./src/pupil_labs/neon_player/assets=pupil_labs/neon_player/assets \
  --macos-create-app-bundle \
  src/pupil_labs/neon_player/__main__.py
