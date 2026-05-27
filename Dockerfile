FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app

# 프론트만 먼저 복사해서 Docker layer cache가 pubspec 변경 기준으로 동작하게 한다.
COPY frontend/pubspec.* ./
RUN flutter pub get

COPY frontend/ ./

# Railway/GitHub에는 .env를 올리지 않아도 Flutter asset 번들링이 실패하지 않게 한다.
RUN test -f .env || printf "API_BASE_URL=\nUSE_OPENAI_REALTIME_VOICE=false\nUSE_GEMINI_TTS=false\n" > .env

ARG API_BASE_URL=https://ddalangoo-production.up.railway.app

RUN flutter build web --release --no-wasm-dry-run --dart-define=API_BASE_URL=${API_BASE_URL}

FROM nginx:alpine

COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
