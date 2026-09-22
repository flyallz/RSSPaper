#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
output_root="${1:-$repo_root/dist}"
app="$output_root/教育技术期刊雷达.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$output_root/module-cache"
cp "$repo_root/src/macos/Info.plist" "$app/Contents/Info.plist"
cp "$repo_root/src/macos/AppIcon.icns" "$app/Contents/Resources/AppIcon.icns"
cp "$repo_root/data/edtech-radar.opml" "$app/Contents/Resources/edtech-radar.opml"
printf 'APPL????' > "$app/Contents/PkgInfo"
swiftc -parse-as-library -O -module-cache-path "$output_root/module-cache" \
  -framework AppKit -framework SwiftUI -framework Security \
  "$repo_root/src/macos/main.swift" -o "$app/Contents/MacOS/EdTechRadar"
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"
ditto -c -k --keepParent "$app" "$output_root/教育技术期刊雷达-Mac.zip"
echo "Built $output_root/教育技术期刊雷达-Mac.zip"
