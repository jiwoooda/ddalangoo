FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app

COPY . .

ARG API_BASE_URL=https://ddalangoo-production.up.railway.app
ARG USE_GEMINI_TTS=true

# Railway의 build context가 repo root 또는 frontend 중 어느 쪽이어도 동작하게 한다.
RUN set -eux; \
    if [ -f pubspec.yaml ]; then \
      FLUTTER_PROJECT_DIR="/app"; \
    elif [ -f frontend/pubspec.yaml ]; then \
      FLUTTER_PROJECT_DIR="/app/frontend"; \
    else \
      echo "Flutter pubspec.yaml을 찾지 못했습니다."; \
      find /app -maxdepth 4 -type f | sort | sed -n '1,120p'; \
      exit 1; \
    fi; \
    cd "$FLUTTER_PROJECT_DIR"; \
    test -f .env || printf "API_BASE_URL=\nUSE_OPENAI_REALTIME_VOICE=false\nUSE_GEMINI_TTS=false\n" > .env; \
    flutter pub get; \
    flutter build web --release --no-wasm-dry-run --dart-define=API_BASE_URL=${API_BASE_URL} --dart-define=USE_GEMINI_TTS=${USE_GEMINI_TTS}; \
    mkdir -p /app/build_output; \
    cp -R build/web/. /app/build_output/

FROM nginx:alpine

COPY --from=build /app/build_output /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
