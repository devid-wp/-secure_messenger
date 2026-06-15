# Secure Messenger

Защищённый мессенджер на FastAPI + React.

## Стек

- **Backend:** FastAPI, SQLite, PBKDF2-HMAC-SHA256 (100 000 итераций) для хеширования паролей
- **Frontend:** React 18, Vite

## Структура

```
app/                 FastAPI-бэкенд
  auth.py            модуль регистрации/проверки пользователя
  crypto.py          PBKDF2 + secure_compare
  database.py        обёртка над SQLite
  main.py            HTTP + WebSocket API
  schema.sql         схема БД
frontend/            React-приложение
  src/components/    LoginForm, ChatApp
```

## Запуск

### 1. Установить зависимости бэкенда

```bash
pip install -r requirements.txt
```

### 2. Запустить бэкенд

```bash
cd app
python main.py
```

API поднимется на `http://localhost:8000`.

### 3. Запустить фронтенд (в другом терминале)

```bash
cd frontend
npm install
npm run dev
```

UI откроется на `http://localhost:5173`.
