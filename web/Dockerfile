FROM node:22-alpine AS build
WORKDIR /repo
COPY package.json package-lock.json ./
COPY web/package.json web/
COPY mobile/package.json mobile/
COPY packages/shared packages/shared
RUN npm ci --workspace web --workspace @fm/shared --include-workspace-root
COPY web web
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm -w web run build
EXPOSE 3000
CMD ["npm", "-w", "web", "run", "start"]
