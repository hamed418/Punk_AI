
FROM node:20-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

ENV PORT=3220

EXPOSE 3220

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3220" ]