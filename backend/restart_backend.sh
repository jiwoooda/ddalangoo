#!/usr/bin/env bash
set -u

# backend 디렉터리 기준으로 실행되도록 스크립트 자신의 위치로 이동한다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

PORT=8000
HOST="0.0.0.0"
BACKEND_MODE="${BACKEND_MODE:-detached}"
CHECK_URL="http://127.0.0.1:${PORT}/docs"
LOG_DIR="logs"
LOG_FILE="${LOG_DIR}/uvicorn_8000.log"
PID_FILE="${LOG_DIR}/uvicorn_8000.pid"

mkdir -p "$LOG_DIR"

echo "[restart] stopping processes listening on port ${PORT}"
EXISTING_PIDS="$(lsof -tiTCP:${PORT} -sTCP:LISTEN || true)"
if [ -n "$EXISTING_PIDS" ]; then
  echo "$EXISTING_PIDS" | xargs kill
  sleep 1

  # 정상 종료가 늦는 경우에만 8000 리스너를 한 번 더 정리한다.
  REMAINING_PIDS="$(lsof -tiTCP:${PORT} -sTCP:LISTEN || true)"
  if [ -n "$REMAINING_PIDS" ]; then
    echo "$REMAINING_PIDS" | xargs kill -9
  fi
else
  echo "[restart] no existing process on port ${PORT}"
fi

if [ "$BACKEND_MODE" = "foreground" ]; then
  echo "[restart] starting uvicorn in foreground on port ${PORT}"
  echo "[restart] foreground mode keeps the server attached to this terminal"
  exec .venv/bin/uvicorn main:app --host "$HOST" --port "$PORT" --lifespan off
fi

if [ "$BACKEND_MODE" != "detached" ]; then
  echo "[restart] unsupported BACKEND_MODE=${BACKEND_MODE}. Use detached or foreground."
  exit 1
fi

echo "[restart] starting uvicorn in detached mode on port ${PORT}"
nohup .venv/bin/uvicorn main:app --host "$HOST" --port "$PORT" --lifespan off > "$LOG_FILE" 2>&1 &
SERVER_PID="$!"
echo "$SERVER_PID" > "$PID_FILE"
echo "[restart] pid=${SERVER_PID}"
echo "[restart] log=${LOG_FILE}"

# FastAPI 문서 엔드포인트가 응답하면 서버가 실제로 준비된 것으로 본다.
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fs --max-time 1 "$CHECK_URL" > /dev/null; then
    echo "[restart] ready url=${CHECK_URL}"
    exit 0
  fi
  sleep 0.5
done

echo "[restart] server did not become ready quickly"
echo "[restart] recent log:"
tail -n 40 "$LOG_FILE"
exit 1
