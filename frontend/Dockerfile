ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS build
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
COPY package*.json ./
RUN npm ci --registry="$NPM_REGISTRY"
COPY . .
RUN npm run build

FROM ${NGINX_IMAGE}
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
