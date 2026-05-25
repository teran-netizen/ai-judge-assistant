# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install
COPY . .
ARG VITE_YANDEX_CLIENT_ID
ARG VITE_VK_CLIENT_ID
ARG VITE_API_URL
ARG VITE_DEV_ACCESS
ENV VITE_YANDEX_CLIENT_ID=$VITE_YANDEX_CLIENT_ID
ENV VITE_VK_CLIENT_ID=$VITE_VK_CLIENT_ID
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_DEV_ACCESS=$VITE_DEV_ACCESS
RUN npm run build && sed -i "s/BUILD_TS/$(date +%s)/g" dist/sw.js

# Serve stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh
EXPOSE 80 443
ENTRYPOINT ["/docker-entrypoint.sh"]
