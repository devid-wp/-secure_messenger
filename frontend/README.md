# Secure Messenger Frontend

React + Vite приложение для браузерного мессенджера.

## Установка

```bash
cd frontend
npm install
```

## Запуск dev-сервера

```bash
npm run dev
```

Приложение будет доступно по адресу `http://localhost:5173`

## Сборка для production

```bash
npm run build
```

## Структура

```
src/
├── main.jsx           # Entry point
├── App.jsx            # Main app component
├── App.css
├── index.css          # Global styles
└── components/
    ├── LoginForm.jsx  # Login/Register
    ├── LoginForm.css
    ├── ChatApp.jsx    # Main chat interface
    └── ChatApp.css
```

## Требования

- Node.js >= 16.x
- npm или yarn
- FastAPI бэкенд на `http://localhost:8000`
