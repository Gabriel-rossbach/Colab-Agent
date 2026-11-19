FROM ghcr.io/cirruslabs/flutter:stable AS build
WORKDIR /app
COPY frontend/pubspec.yaml frontend/pubspec.yaml
RUN flutter pub get
COPY frontend/ .
RUN flutter pub get && flutter build web --release

FROM caddy:2-alpine
COPY --from=build /app/build/web /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
EXPOSE 80 443
