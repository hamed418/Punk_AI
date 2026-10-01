# FROM node:20-alpine

# WORKDIR /app

# COPY package*.json ./
# RUN npm install

# COPY . .
# ENV VITE_PORT=${VITE_PORT}
# EXPOSE ${VITE_PORT}

# CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM node:20-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

ENV PORT=3000

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p" ]