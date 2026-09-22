#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
output_root="${1:-$repo_root/dist}"
mkdir -p "$output_root/module-cache"
swiftc -parse-as-library -D RADAR_TEST -module-cache-path "$output_root/module-cache" \
  -framework AppKit -framework SwiftUI -framework Security \
  "$repo_root/src/macos/main.swift" "$repo_root/src/macos/translation_test.swift" \
  -o "$output_root/translation_test"
"$output_root/translation_test"
