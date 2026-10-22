#!/usr/bin/env bash
# Re-download Noto Sans Sinhala via npm and copy it into assets/fonts.
set -euo pipefail
cd "$(dirname "$0")/.."
npm i --no-save @fontsource/noto-sans-sinhala
for w in 400 700 800; do
  cp node_modules/@fontsource/noto-sans-sinhala/files/noto-sans-sinhala-sinhala-$w-normal.woff2 assets/fonts/
done
cp node_modules/@fontsource/noto-sans-sinhala/LICENSE assets/fonts/NotoSansSinhala-OFL.txt
echo "fonts updated in assets/fonts"
