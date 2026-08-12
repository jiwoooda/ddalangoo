#!/usr/bin/env bash
set -euo pipefail

# repo 루트 기준으로 backend 재시작, Flutter APK 빌드, 실기기 설치를 한 번에 수행한다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DEVICE_SERIAL="${DEVICE_SERIAL:-R3CX60FLNCA}"
ADB_BIN="${ADB_BIN:-/Users/seeun/Library/Android/sdk/platform-tools/adb}"
FRONTEND_DIR="${SCRIPT_DIR}/frontend_v3"
APK_PATH="${FRONTEND_DIR}/build/app/outputs/flutter-apk/app-debug.apk"
PACKAGE_NAME="com.ddalangoo.ddalangoo"

echo "[all] restart backend on port 8000"
"${SCRIPT_DIR}/backend/restart_backend.sh"

echo "[all] check android device serial=${DEVICE_SERIAL}"
"$ADB_BIN" -s "$DEVICE_SERIAL" get-state > /dev/null

echo "[all] build Flutter debug APK"
cd "$FRONTEND_DIR"
flutter build apk --debug

echo "[all] install APK package=${PACKAGE_NAME}"
"$ADB_BIN" -s "$DEVICE_SERIAL" install -r -d "$APK_PATH"

echo "[all] verify installed package"
"$ADB_BIN" -s "$DEVICE_SERIAL" shell pm path "$PACKAGE_NAME"

echo "[all] done"
