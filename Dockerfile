FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app

# Railway 프론트 서비스의 build context는 frontend 디렉터리다.
# 따라서 Dockerfile이 repo root에 있더라도 COPY 경로는 frontend 내부 기준으로 쓴다.
COPY pubspec.* ./
RUN flutter pub get

COPY . .

# Railway/GitHub에는 .env를 올리지 않아도 Flutter asset 번들링이 실패하지 않게 한다.
RUN test -f .env || printf "API_BASE_URL=\nUSE_OPENAI_REALTIME_VOICE=false\nUSE_GEMINI_TTS=false\n" > .env

ARG API_BASE_URL=https://ddalangoo-production.up.railway.app

RUN flutter build web --release --no-wasm-dry-run --dart-define=API_BASE_URL=${API_BASE_URL}

FROM nginx:alpine

COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
