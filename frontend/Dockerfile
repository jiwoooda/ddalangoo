FROM ghcr.io/cirruslabs/flutter:stable AS build

WORKDIR /app

COPY pubspec.* ./
RUN flutter pub get

COPY . .

ARG API_BASE_URL=https://ddalangoo-production.up.railway.app

# Flutter asset에 .env가 등록되어 있어서 컨테이너 빌드 시에도 파일을 만들어준다.
# 실제 API URL은 --dart-define 값이 우선 적용된다.
RUN printf "API_BASE_URL=%s\nUSE_GEMINI_TTS=false\nGEMINI_API_KEY=\nOPENAI_API_KEY=\n" "${API_BASE_URL}" > .env
RUN flutter build web --release --dart-define=API_BASE_URL=${API_BASE_URL}

FROM nginx:alpine

COPY --from=build /app/build/web /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
