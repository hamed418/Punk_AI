FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
ENV VITE_PORT=${VITE_PORT}
EXPOSE ${VITE_PORT}

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]