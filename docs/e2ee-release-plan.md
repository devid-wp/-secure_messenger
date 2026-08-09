# План завершения E2EE и production-релиза

Статус: release candidate preparation  
Платформа: browser-only PWA  
Криптографический runtime: OpenMLS/WASM в dedicated Worker

## 1. Определение готовности

Релиз считается готовым только при одновременном выполнении четырёх условий:

1. Содержимое сообщений, вложений и MLS state никогда не попадает на сервер
   или в постоянное browser storage в plaintext.
2. Изменение состава участников и устройств всегда приводит к корректному MLS
   Commit; отозванное устройство не читает новые эпохи.
3. Production-клиент доставляется только по HTTPS из проверенного same-origin
   build без сторонних scripts.
4. Полный автоматический и ручной release gate пройден в Chromium и Firefox.

«Полное E2EE» не означает защиту от malware, вредоносного browser extension,
скомпрометированного origin/build или участника, который уже расшифровал
сообщение. Эти ограничения должны оставаться явно указанными пользователю.

## 2. P0 — воспроизводимая среда и зависимости

### Задачи

- Зафиксировать поддерживаемые версии Python 3.12 и Node.js 20 LTS.
- Добавить `pytest` и при необходимости `pytest-asyncio` в dev requirements.
- Создать hash-pinned Python lock-файлы для production и development.
- Перевести Docker и CI с диапазонов `requirements.txt` на lock-файлы.
- Сохранить использование `npm ci`, `package-lock.json`, `Cargo.lock` и
  `cargo --locked`.
- Установить Chromium и Firefox для Playwright.
- Добавить `npm audit`, `cargo audit` и `pip-audit` в release workflow.
- Зафиксировать результаты аудита; исключения требуют срока, владельца и
  объяснения достижимости уязвимого кода.

### Gate

Чистая машина собирает одинаковый frontend/WASM и запускает весь test suite
только из файлов репозитория и зафиксированных lock-файлов.

## 3. P0 — закрытие E2EE-протокола

### MLS и сообщения

- Проверить создание DM и групп как отдельных MLS-групп.
- Проверить KeyPackage lifecycle: создание, расходование, истечение и
  пополнение.
- Покрыть add/remove/update Commit для участника и каждого устройства.
- Проверить смену epoch после добавления, отзыва и выхода участника.
- Проверить replay, duplicate, reorder, delayed old epoch, future epoch,
  повреждённый ciphertext и fork/transcript mismatch.
- При любой неоднозначной криптографической ошибке блокировать отправку до
  явного resync; не делать plaintext или non-MLS fallback.
- Подтвердить, что safety code строится из проверенных device credentials и UI
  заметно сообщает об изменении credential/device set.

### Application payload

- Сверить versioned schema текста, вложения, receipt и membership events.
- Отклонять неизвестную версию, лишние поля, неправильные типы и превышение
  лимита до изменения UI state.
- Проверить canonical encoding и отсутствие неаутентифицированных полей,
  влияющих на отображаемое содержимое.

### Gate

Все перечисленные сценарии имеют unit/integration tests, а ключевые membership
сценарии проходят browser E2E между независимыми профилями.

## 4. P0 — browser vault и восстановление

### Задачи

- Проверить создание, unlock, lock, reload и смену passphrase.
- Проверить миграцию vault v1→v2 и атомарность при сбое между записью и
  подтверждением новой записи.
- Проверить неправильную passphrase, повреждённые metadata/ciphertext/tag,
  удалённый record и частично очищенный IndexedDB.
- Убедиться, что state nonce и wrapping nonce никогда не повторяются.
- Убедиться, что lock уничтожает Worker, отклоняет pending requests и удаляет
  plaintext из React state.
- Не сохранять drafts, decrypted history, outbox, file keys или passphrase в
  localStorage, Cache Storage, logs и crash telemetry.
- Добавить понятный UX: потеря passphrase/site data означает потерю локальной
  истории; сервер не способен восстановить MLS secrets.
- Проверить восстановление аккаунта отдельно от восстановления E2EE-истории.

### Gate

После lock/reload plaintext отсутствует в постоянных browser stores, а
повреждение vault приводит к безопасной остановке с понятной ошибкой.

## 5. P0 — сообщения и encrypted attachments end-to-end

### Задачи

- Проверить send → persist MLS state → upload envelope → receive → decrypt →
  deduplicate → acknowledge во всех точках сбоя.
- Проверить reload сразу до и после серверного подтверждения.
- Проверить offline/reconnect без plaintext persistent outbox.
- Проверить chunked attachment encryption, уникальность AES-GCM nonce,
  аутентификацию порядка/номера chunk и целостность полного файла.
- Проверить нулевой, малый, максимальный и превышающий лимит файл.
- Проверить отмену, сетевой разрыв, повтор upload/download и повреждение одного
  chunk.
- Серверу передавать только ciphertext, `chat_id` и минимальные routing
  metadata; имя, MIME, размеры изображения, ключ, nonce и plaintext hash должны
  находиться внутри MLS payload.
- Запретить service worker кэшировать `/api/` и attachment bodies.

### Gate

Получатель восстанавливает исходный файл; storage/network/server видят только
opaque bytes. Любое повреждение обнаруживается до выдачи файла пользователю.

## 6. P0 — privacy boundary backend

### Задачи

- Применить миграции на копии production-подобной базы и проверить отсутствие
  legacy plaintext columns/tables.
- Запретить дополнительные JSON fields в envelope/upload schemas.
- Не логировать body, Authorization, cookies, ciphertext, keys и passphrases.
- Ограничить CORS точным production HTTPS origin.
- Закрыть прямой внешний доступ к backend, PostgreSQL, Redis и S3.
- Установить retention для envelopes, uploads, sessions и security logs.
- Проверить authorization каждого envelope, KeyPackage и media download.
- Добавить rate/size limits и безопасное поведение при исчерпании storage.

### Gate

Privacy sentinel test не находит plaintext в PostgreSQL, Redis, object storage,
backend/Nginx logs и API responses.

## 7. P0 — Browser/PWA delivery hardening

### Задачи

- Развернуть настоящий HTTPS ingress с TLS 1.3 и HTTP→HTTPS redirect.
- Проверить HSTS только на HTTPS и отсутствие redirect loop за proxy.
- Проверить effective CSP в браузере: same-origin scripts, без inline scripts и
  JavaScript `unsafe-eval`; только необходимый `wasm-unsafe-eval` и Worker.
- Оставить `connect-src 'self'`, `object-src/base-uri/frame-ancestors 'none'`.
- Проверить secure, HttpOnly, SameSite refresh cookie и узкий cookie path.
- Запретить analytics, tag managers, CDN scripts/fonts и support widgets.
- Проверить обновление service worker и невозможность downgrade на старый
  небезопасный cached shell.
- Хранить build artifacts и SBOM; подписывать release image по принятой
  инфраструктурной политике.

### Gate

Security headers подтверждены browser DevTools/автоматическим тестом, все
запросы same-origin HTTPS, mixed content отсутствует.

## 8. P0 — автоматический release gate

Каждый release commit должен проходить:

```powershell
git status

cd frontend
npm ci
npm audit --omit=dev
npm run lint
npm run typecheck
npm run build
npm test
npx playwright install chromium firefox
npm run test:e2e

cd src-wasm
cargo fmt --check
cargo check --locked --target wasm32-unknown-unknown
cargo audit

cd ../..
.\.venv\Scripts\python.exe -m pip install -r requirements.lock -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip_audit -r requirements.lock
.\.venv\Scripts\python.exe -m pytest
```

CI должен запускать не только выборочные privacy tests, но полный frontend,
backend, WASM и browser E2E suite. Релиз блокируется при skipped security test,
необъяснённой audit vulnerability или незакоммиченном lockfile.

## 9. P0 — ручная release-матрица

В Chromium и Firefox выполнить:

1. Регистрация Alice и Bob в независимых browser profiles.
2. Создание vault, lock/unlock и reload.
3. DM в обе стороны и группа минимум из трёх участников.
4. Две вкладки одного профиля и конкурентная отправка.
5. Offline send/reconnect и reload в критических точках.
6. Добавление второго устройства и проверка welcome/epoch.
7. Отзыв online- и offline-устройства; попытка прочитать новую эпоху.
8. Повреждение IndexedDB vault record и MLS envelope.
9. Малый и максимально разрешённый файл; повреждение ciphertext.
10. Обновление PWA/service worker с предыдущего release candidate.
11. Очистка site data и проверка UX необратимой потери локальных ключей.

Для каждого запуска сохранить версию браузера, commit SHA, результат и ссылку
на артефакты CI.

## 10. P0 — canary privacy audit

- Использовать уникальные строки для message, group name, attachment name и
  attachment body.
- Сохранить HAR/network trace без расшифрованных response bodies.
- Искать canary в PostgreSQL dump, Redis dump, object storage, container logs,
  reverse-proxy logs, browser IndexedDB/localStorage/Cache Storage и собранном
  frontend artifact.
- Отдельно проверить error paths: неправильный payload, 500 response,
  interrupted upload и corrupted vault.
- Любое обнаружение plaintext вне памяти разблокированного renderer является
  release blocker.

## 11. P0 — независимый security review

Перед публичным production-релизом отдать на review:

- Rust/OpenMLS wrapper и сериализацию provider state;
- JS↔Worker protocol и передачу vault key material;
- vault KDF/AEAD/nonces/migration;
- membership/device lifecycle и fork handling;
- attachment cryptography;
- backend authorization/privacy boundary;
- CSP, service worker и supply chain.

Все critical/high findings исправляются до релиза. Medium findings получают
решение, владельца и срок; принятый риск документируется в security model.

## 12. P1 — production operations

- Подготовить staging, идентичный production по topology и headers.
- Автоматизировать миграции с backup и проверенным rollback-планом.
- Настроить encrypted backups PostgreSQL/object storage; они содержат только
  ciphertext и не заменяют browser vault recovery.
- Настроить health checks, alerts, storage quotas и certificate renewal.
- Не отправлять payload/ciphertext в APM. Метрики должны быть агрегированными и
  не содержать chat/user/message identifiers.
- Подготовить incident response: компрометация origin/build, утечка БД,
  отозванное устройство, повреждённый release artifact.
- Подготовить key/session rotation и процедуру экстренного отключения release.

## 13. P1 — документация и UX перед публикацией

- Синхронизировать `product-v1.md` с реализованными attachments и фактическими
  лимитами.
- Зафиксировать точные поддерживаемые версии Chromium и Firefox после матрицы.
- Опубликовать security model, recovery limitations и metadata policy.
- Добавить пользователю инструкции экспорта/восстановления, если encrypted
  export действительно реализован; иначе явно указать его отсутствие.
- Показать в UI состояние vault, device verification, device changes и
  криптографические ошибки без ложного обещания доставки/защиты.

## 14. Go/no-go checklist

Решение **GO** возможно только если:

- [ ] рабочее дерево чистое, release commit/tag зафиксирован;
- [ ] dependency locks и audits зелёные;
- [ ] lint, typecheck, build, unit, integration и pytest зелёные;
- [ ] Chromium и Firefox E2E зелёные;
- [ ] ручная матрица подписана ответственным;
- [ ] privacy canary нигде не найден;
- [ ] production HTTPS/CSP/cookies проверены;
- [ ] database migrations и backup restore проверены на staging;
- [ ] независимый security review закрыт;
- [ ] документация соответствует фактическому поведению;
- [ ] rollback и incident response готовы.

При невыполнении любого P0 gate результат называется pre-release/release
candidate, а не production-ready E2EE messenger.

## 15. Рекомендуемая последовательность работ

1. Dependencies и полный CI.
2. Дополнение protocol/vault negative tests.
3. Cross-browser Playwright suite.
4. Staging HTTPS deployment.
5. Ручная матрица и privacy canary audit.
6. Независимый security review и исправления.
7. Production rehearsal: migration, backup restore, rollback.
8. Документация, release tag, ограниченный rollout.
9. Наблюдение за rollout без сбора чувствительных данных.

