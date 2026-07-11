# 로컬 MCP
cd ../AYearApart/backend/vendor/ddalangoo-langgraph/meta-mcp
npm ci
npm run build
npm run start:sse

# 백엔드
cd ../AYearApart/backend
source .venv/bin/activate
python -m uvicorn main:app --app-dir ../AYearApart/backend --host 0.0.0.0 --port 8000

# 프론트엔드 - 안드로이드 에뮬레이터
cd ../AYearApart/frontend_v2
flutter pub get
flutter run -d android

# 프론트엔드 - 크롬
cd ../AYearApart/frontend_v2
flutter pub get
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8000