FROM node:22-alpine AS build
WORKDIR /src
ARG VITE_AVATURN_URL=https://dressme.avaturn.dev/
ARG VITE_AVATURN_EXPORT_ORIGINS=
ENV VITE_AVATURN_URL=$VITE_AVATURN_URL
ENV VITE_AVATURN_EXPORT_ORIGINS=$VITE_AVATURN_EXPORT_ORIGINS
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
