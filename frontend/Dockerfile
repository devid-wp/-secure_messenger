FROM rust:1.88-alpine AS wasm

RUN apk add --no-cache musl-dev && rustup target add wasm32-unknown-unknown
RUN cargo install wasm-bindgen-cli --version 0.2.126 --locked
WORKDIR /wasm
COPY src-wasm ./
RUN cargo build --locked --release --target wasm32-unknown-unknown \
    && mkdir -p /wasm-generated \
    && wasm-bindgen target/wasm32-unknown-unknown/release/secure_messenger_mls_wasm.wasm \
       --target web --out-dir /wasm-generated --out-name mls

FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
COPY --from=wasm /wasm-generated ./src/crypto/wasm-generated
ENV VITE_API_URL=""
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
