# ADR-0002: Vault KDF and lockout semantics

Status: **proposed, locks Stage 3 follow-up**

Дата: **2026-08-07**

## Решение

Browser vault v2 продолжает использовать **PBKDF2-HMAC-SHA-256** через
WebCrypto как key-encryption KDF для DEK. Argon2id в проверенном
WASM-пакете остаётся предпочтительным KDF на будущее; переход
зафиксирован как отдельный ADR, требующий security review и browser/CI
gate.

Lockout истории продолжает опираться на уничтожение Worker’а:
WebAssembly linear memory освобождается при `Worker.terminate()`, и
plaintext MLS state выгружается из JS-кучи как только ссылки на
`WasmMlsClient` и `state_ciphertext` обнуляются. DEK создаётся
extractable внутри Worker scope, чтобы `changePassphrase` мог
пере-обернуть DEK без перешифрования state; raw bytes живут только в
worker и обнуляются сразу после wrap/unwrap.

## Почему PBKDF2, а не Argon2id (пока)

RFC 9106 рекомендует Argon2id как modern memory-hard KDF. На v1.0
browser-only клиента есть две причины остаться на PBKDF2:

1. **Supply-chain доверие.** Argon2id требует отдельный WASM-блоб.
   Доступные пакеты (`argon2-browser`, `hash-wasm`) распространяют
   предкомпилированный WASM, чья криптографическая корректность не
   покрыта нашим security review. Самописная реализация Argon2 в
   JavaScript явно запрещена ADR-0001.
2. **Браузерный gate.** Sandbox для разработки не имеет Chromium и
   Vite-сборки с WASM-блобом. Тестирование «нормально проходит
   browser/CI gate» требует production build под актуальным Edge и
   Chrome, что сейчас не доступно в этой итерации.

PBKDF2-HMAC-SHA-256 при 600 000 итерациях — это одобренный NIST SP
800-132 fallback и OWASP Password Storage Cheat Sheet рекомендация для
2024 года. Он остаётся приемлемым до тех пор, пока Argon2id не пройдёт
browser/CI gate.

## Параметры PBKDF2 в v2

| Параметр | Значение |
|---|---|
| Алгоритм | PBKDF2-HMAC-SHA-256 |
| Итерации | 600 000 |
| Salt | 16 случайных байт на каждую запись |
| Output | 256-битный AES-GCM key wrapping key |
| Длина пароля | ≥ 10 символов (валидация в `passphraseKey`) |

Изменение cost-фактора в будущем — операция над каждой записью
индивидуально: `kdf.parameters.iterations` хранится per record, так что
старая запись переразворачивается со старыми параметрами, а новая
запись использует новые. Двух-iteration сосуществование допускается.

## Условия для перехода на Argon2id

Переход регистрируется отдельным ADR, который будет принят только когда:

- выбран конкретный WASM-пакет (предпочтительно `hash-wasm` или
  audited форк `argon2-browser`), его source коммит зафиксирован в
  lockfile;
- блоб загружается в Chromium и Firefox dev-сборке без падений;
- WASM-блоб прошёл fuzz/property тесты против RFC 9106 reference vectors;
- production Vite-сборка укладывается в 2 MiB JS budget;
- security review подтверждает, что wrapper не leak’ает параметры в
  plaintext logs.

В этом случае v2 record получает новое значение `kdf.name`, например
`Argon2id-v1`, и параллельная миграция паролей проводится через
`changePassphrase`.

## Операции vault

`mlsRuntimeBridge` экспортирует:

| Метод | Назначение |
|---|---|
| `createVault(deviceId, passphrase)` | Создаёт новый v2 record. Отказывается, если запись уже есть. |
| `unlockVault(deviceId, passphrase)` | Разворачивает DEK, готовит Worker к шифрованию. |
| `lockMlsRuntime()` | Уничтожает Worker, отклоняет pending запросы, обнуляет ссылки. |
| `changePassphrase(deviceId, old, new)` | Пере-оборачивает DEK под новый passphrase и salt без перешифрования state. |
| `hasVault(deviceId)` | Возвращает boolean: существует ли v2 запись для устройства. |
| `getVaultStatus(deviceId)` | Возвращает `{exists, version, locked, migrationRequired}`. |

`lockMlsRuntime()` — единственная команда, которая реально уничтожает
криптографическое состояние runtime’а. После неё:

1. Все pending-запросы в bridge `pending` Map получают rejection с
   текстом `vault is locked`.
2. `worker.terminate()` вызывается — Worker и его WASM linear memory
   освобождаются немедленно.
3. JS-ссылка `worker = null` сбрасывается, чтобы следующий вызов
   пересоздал Worker.
4. `client`, `activeDek`, `activeDeviceId` внутри Worker сбрасываются
   до того, как `terminate()` снимет процесс.

После lock:

- `mlsRuntimeAvailable()` возвращает `true` только если новый Worker
  пересоздан и `vaultStatus` подтвердил `exists && !locked`.
- `encryptAndPublish` / `decryptEnvelope` бросают `Sending is disabled:
  this runtime has no MLS vault`, потому что worker handler’ы
  `encrypt` / `process` падают на precondition `if (!activeDek) throw
  'Browser vault is locked'`.
- UI `ChatApp` не показывает composer и помечает кнопку «Send»
  disabled.

## Гарантии после блокировки

- **Plaintext не остаётся в IndexedDB.** `state_ciphertext` всегда
  AES-256-GCM шифруется DEK’ом; DEK живёт только в Worker’е до lock.
  После lock DEK handle остаётся у сборщика мусора как только
  `activeDek = null` в Worker’е.
- **Plaintext не остаётся в localStorage.** `readOutbox` и
  `writeOutbox` в `ChatApp.jsx` — это deliberate no-ops, которые
  компилируются в `[].filter` / пустой write. Драфты и outbox живут
  только в React `useRef`, который теряется при размонтировании.
- **WebAssembly memory освобождается** через `worker.terminate()`.
  Альтернативная явная команда `client.destroy()` для `WasmMlsClient`
  остаётся TODO до тех пор, пока upstream OpenMLS WASM binding не
  предоставит безопасный wipe API.

## Связь с другими ADR

- ADR-0001: E2EE на базе MLS и OpenMLS — определяет v1 vault как
  fallback migration source.
- ADR-0002: настоящий документ.

## Зафиксированные решения

- Vault v2 использует PBKDF2-HMAC-SHA-256 до тех пор, пока Argon2id не
  пройдёт browser/CI gate.
- Lock уничтожает Worker; никакого «мягкого» lock не предусмотрено.
- `changePassphrase` — это re-wrap, а не re-encryption: DEK остаётся,
  меняется только обёртка.
- Plaintext MLS state никогда не покидает Worker и никогда не
  сохраняется в IndexedDB / localStorage.