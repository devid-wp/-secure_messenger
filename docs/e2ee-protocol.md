# ADR-0001: E2EE на базе MLS и OpenMLS

Статус: **proposed, блокирует расширение production-схемы**
Дата: **2026-07-26**

## Решение

Использовать [Messaging Layer Security, RFC 9420](https://www.rfc-editor.org/rfc/rfc9420.html)
для DM и групп. Каждый чат — отдельная MLS group, каждое устройство — MLS
client/leaf.

Библиотека-кандидат: [OpenMLS 0.8.1](https://github.com/openmls/openmls/releases/tag/openmls-v0.8.1),
собранная в локально поддерживаемый Rust/WASM wrapper. Версия и source commit
MUST быть зафиксированы в lockfile; обновление выполняется отдельным security
PR.

Начальная ciphersuite:

`MLS_128_DHKEMX25519_AES128GCM_SHA256_Ed25519`

Она поддерживается OpenMLS и использует X25519, HKDF-SHA-256, AES-128-GCM и
Ed25519. Собственные реализации primitives в JavaScript или Python запрещены.

## Почему MLS

- Один протокол покрывает DM, группы и multi-device.
- Асинхронные KeyPackages позволяют добавлять offline-устройства.
- Epoch и Commit задают однозначную границу смены membership.
- Протокол предоставляет forward secrecy и post-compromise security.
- Новый участник не получает доступ к секретам прошлых эпох.
- Delivery Service может маршрутизировать сообщения, не зная plaintext.

RFC 9420 отдельно предупреждает, что GroupID, epoch, частота, размеры и иногда
membership могут быть видимы delivery service. Поэтому E2EE не заменяет
политику метаданных из `security-model.md`.

## Почему не Signal Protocol в v1.0

[PQXDH](https://signal.org/docs/specifications/pqxdh/pqxdh.pdf),
[Double Ratchet](https://signal.org/docs/specifications/doubleratchet/doubleratchet.pdf)
и [Sesame](https://signal.org/docs/specifications/sesame/sesame.pdf) являются
сильной моделью для pairwise и multi-device messaging. Официальный
[libsignal](https://github.com/signalapp/libsignal) предоставляет Java, Swift и
TypeScript API, но текущему browser-only клиенту потребовалась бы отдельная
неофициальная browser/WASM интеграция и дополнительный group protocol.

Выбор Signal для DM и другого протокола для групп создал бы два key lifecycle,
две модели восстановления и сложный переход сообщений. Для данного продукта
это хуже единой MLS-модели.

## Ограничение OpenMLS/WASM

Upstream OpenMLS собирает `wasm32-unknown-unknown`, но README относит эту цель
к built-but-not-tested, а не к полноценно поддерживаемым платформам. Поэтому
выбор библиотеки считается окончательно принятым только после прототипа.

До прохождения gate запрещено:

- менять production schema под предполагаемый wire format;
- заявлять E2EE в UI или README;
- хранить реальные пользовательские ключи в браузере;
- писать собственный fallback crypto.

Если gate не пройден, ADR пересматривается. Предпочтительный fallback —
сменить клиентскую платформу на поддерживаемую OpenMLS, а не упрощать протокол.

## Архитектура клиента

```text
React UI
   |
   v
Message application service
   |
   +--> encrypted local repository
   |
   v
E2EE Web Worker --> OpenMLS WASM
   |
   v
Opaque envelope transport --> FastAPI delivery service
```

- Private keys и MLS state живут только в E2EE worker/local encrypted storage.
- React получает plaintext только для отображения конкретного сообщения.
- Network layer получает только serialized MLS bytes и routing metadata.
- WASM memory очищается при logout/lock настолько, насколько позволяет runtime.
- CSP запрещает third-party scripts, `eval` и непинованные remote assets.
- Service Worker не имеет постоянного доступа к plaintext message history.

## Authentication Service

1. Device генерирует Ed25519 signature key локально.
2. Сервер после аутентификации выдаёт versioned device credential, связывающую
   `user_id`, `device_id`, public key и expiry.
3. Existing device подтверждает новый credential своей подписью.
4. Клиенты валидируют credential перед добавлением KeyPackage.
5. Fingerprints всех device credentials входят в safety code пользователя.

MLS доверяет Authentication Service в привязке credential к identity. В v1.0
ручная проверка safety code обнаруживает подмену после проверки; полная защита
от злонамеренного Authentication Service требует будущего key transparency.

## Wire policy

- MLS protocol messages передаются в TLS 1.3.
- Proposal и Commit SHOULD использовать `PrivateMessage`, если RFC не требует
  другой формы.
- Application payload имеет отдельную versioned canonical encoding.
- Group name, receipts и device events шифруются как application data.
- Outer envelope не повторяет sender user name или application content type.

Application data uses this canonical versioned JSON object before MLS
encryption: `{"body":{...},"client_id":"uuid","sender_device_id":"uuid","sent_at":"ISO-8601","type":"message","version":1}`.
Supported types are `message`, `edit`, `delete`, `reaction`, `receipt`,
`attachment`, `group_metadata`, and `device_event`. Unknown versions, types,
top-level fields, malformed UUID/timestamps, mutation targets, and payloads over
64 KiB are rejected after authenticated MLS decryption and before rendering.
Canonical encoding is UTF-8 JSON with recursively lexicographically sorted
object keys, array order preserved, and no insignificant whitespace. Receivers
reject semantically equivalent JSON with different key order or whitespace.

#### Per-type body schemas

| Type | Required body fields | Optional body fields |
|---|---|---|
| `message` | `kind` ∈ {`text`,`sticker`} | text: `content` (1–16384 UTF-8 bytes); sticker: `sticker`; `reply: {target_client_id}` |
| `edit` | `target_client_id` (UUID), `content` (1–16384 UTF-8 bytes) | – |
| `delete` | `target_client_id` (UUID) | – |
| `reaction` | `target_client_id` (UUID), `emoji` (1–64 UTF-8 bytes) | – |
| `receipt` | `target_client_id` (UUID), `state` ∈ {`delivered`,`read`} | – |
| `attachment` | strict `attachment_descriptor` v1 | – |
| `group_metadata` | `name` (1–255 UTF-8 bytes) | – |
| `device_event` | `event` ∈ {`member_added`,`member_removed`,`member_left`,`device_added`,`device_removed`,`credential_changed`} | – |

The v1 attachment descriptor contains exactly `version`, `object_id`,
`algorithm`, `key`, `nonce`, `plaintext_size`, `ciphertext_size`, and `sha256`.
The key, nonce, and digest use canonical Base64 and decode to 32, 12, and 32
bytes respectively. Sizes are positive safe integers, plaintext is bounded by
the 50 MiB transport limit, and AES-GCM ciphertext size is exactly plaintext
size plus the 16-byte authentication tag.

The wire body MUST NOT carry any of these fields — they are stripped before
encryption and rejected after decryption:

```
sender, sender_login, sender_device_id, username, display_name,
reply_to, reply_preview, thread_id, parent_client_id,
attachment, file_name, mime_type, media_type, media_url, object_url,
group_name, chat_name, topic,
edited_at, deleted_at, read_at, timestamp,
id, chat_id, server_seq, status, mls_epoch,
reaction_emoji
```

`edit`, `delete`, `reaction` and `receipt` MUST reference the original
message via a UUID `target_client_id`; the receiving device MUST ignore a
mutation that targets an unknown or foreign client_id.

#### Application payload validation rules

`decodeApplicationPayload` rejects, after authenticated MLS decryption:

- non-`Uint8Array` bytes or empty payload;
- any payload whose size exceeds `MAX_APPLICATION_PAYLOAD_BYTES` (64 KiB);
- bytes that are not valid UTF-8;
- JSON parse failures;
- unknown top-level fields;
- `version` other than `1`;
- `type` not in the supported allowlist;
- `client_id` that is not a RFC 4122 variant-1 UUID;
- `sender_device_id` that is not a UUID or does not match the authenticated outer envelope sender;
- `sent_at` that is not a strict ISO-8601 timestamp;
- body fields not in the per-type schema or fields forbidden above;
- missing required body fields for the given type;
- wrong field types, per-field UTF-8 size limit violations, or unknown outbound
  fields (known local UI bookkeeping is stripped before encryption);
- `attachment_descriptor` carrying `name`, `file_name`, `mime_type`,
  `media_type`, an unknown `algorithm`, an unknown `version` or a non-UUID
  `object_id`.

`encodeApplicationPayload` rejects the same conditions in reverse — it
throws before MLS encryption if the caller did not supply a valid
`client_id` UUID, an ISO-8601 `sent_at` (or `timestamp` fallback) and the
required body fields for the inferred type. Local UI bookkeeping fields
are stripped before encryption. The UI runs this complete encoding preflight
before writing to the outbox, adding an optimistic message, clearing the
composer, or otherwise committing message state.

Only fields obtained from the authenticated MLS application payload may affect
rendered message content, kind, sender, replies, mutations, membership events,
or timestamps. Outer delivery-envelope fields are restricted to opaque event
identity and MLS epoch metadata; they cannot override rendered content. Media
download URLs are derived locally from the authenticated attachment object ID.

#### Replay, ordering and MLS errors

The client deduplicates application events by the encrypted `client_id`, then
applies edit, delete, reaction and receipt events after base messages have been
collected. This makes out-of-order mutations deterministic and prevents a
replayed ciphertext routed under another envelope id from creating a second
message. Edit/delete events are accepted only from the authenticated owner of
the original message. Unknown or revoked devices are rejected before their
wire messages are handed to the MLS runtime.

MLS failures are classified as `duplicate`, `stale_epoch`, `missing_commit`,
`corrupted_ciphertext`, `unknown_sender_device`, or `protocol_violation`.
Duplicates and stale epochs are expected no-ops. A missing Commit is retried
after the current control-envelope pass. Integrity and protocol failures are
surfaced to the UI and never rendered as ordinary messages.

#### External MLS envelope (server wire format)

The HTTP envelope that wraps an opaque MLS ciphertext is exactly:

```json
{
  "protocol_version": 1,
  "chat_id": 123,
  "content_type": "application",
  "epoch": 7,
  "payload": "<base64 MLS bytes>",
  "recipient_device_id": null
}
```

`content_type` is one of `application`, `commit`, `proposal`, `welcome`;
`payload` is the raw MLS ciphertext bytes encoded as base64; the
envelope MUST be rejected if `payload` exceeds 1 MiB or if
`content_type == "welcome"` without a `recipient_device_id`.

The envelope MUST NOT contain, and the server MUST reject with HTTP 422
when any of the following fields appear (enforced by Pydantic
`extra="forbid"` on the publish model):

```
text, content, body, sender, sender_name, sender_login,
file_name, mime_type, media_type, object_url,
reply_preview, reply_to, thread_id,
group_name, chat_name, topic,
reaction, reaction_emoji,
edited_at, deleted_at, read_at
```

The server stores `payload` as opaque bytes and never attempts to parse,
decrypt, or display its contents. `protocol_version` is pinned to `1` by a
database check constraint; future wire-format changes require a new ADR
and a new migration.

- Welcome доставляется только адресованным device IDs.
- KeyPackage одноразовый; использованный package удаляется атомарно.
- Клиент ограничивает skipped generations и максимальный скачок epoch.

## Влияние на функции

| Функция | Следствие E2EE |
|---|---|
| Группы | Add/Remove/role change требуют Proposal/Commit и новой epoch |
| Поиск | Только локальный индекс после расшифровки |
| Вложения | Отдельный file key внутри MLS application message |
| Уведомления | Push provider не получает preview |
| Backup | Только client-encrypted export с отдельным recovery secret |
| Смена устройства | Новый MLS leaf; история не появляется автоматически |
| Модерация | Сервер не анализирует содержимое; только client report с явным consent |

## Прототип и security gate

Прототип MUST доказать:

1. Create/join DM как MLS group из двух устройств.
2. Group из минимум трёх пользователей и пяти устройств.
3. Offline add через KeyPackage/Welcome.
4. Remove потерянного устройства и невозможность расшифровать новую epoch.
5. Out-of-order, duplicate и replay handling.
6. Экспорт/импорт MLS state после перезапуска браузера.
7. Отсутствие ключей и plaintext в network trace, backend logs и IndexedDB
   вне зашифрованного local store.
8. Chromium и Firefox проходят одинаковые test vectors.
9. Wrapper проходит fuzz/property tests на malformed input.
10. Независимый review Rust/WASM boundary и supply-chain lock.

## Не заявляемые гарантии

- Выбранная ciphersuite не является post-quantum.
- MLS не скрывает traffic metadata от delivery service.
- E2EE не защищает plaintext на скомпрометированном endpoint.
- OpenMLS/WASM не считается production-ready до прохождения gate.

## Первичные источники

- [RFC 9420: The Messaging Layer Security Protocol](https://www.rfc-editor.org/rfc/rfc9420.html)
- [RFC 9750: The Messaging Layer Security Architecture](https://www.rfc-editor.org/rfc/rfc9750.html)
- [OpenMLS repository](https://github.com/openmls/openmls)
- [OpenMLS 0.8.1 release](https://github.com/openmls/openmls/releases/tag/openmls-v0.8.1)
- [Signal PQXDH specification](https://signal.org/docs/specifications/pqxdh/pqxdh.pdf)
- [Signal Double Ratchet specification](https://signal.org/docs/specifications/doubleratchet/doubleratchet.pdf)
- [Signal Sesame specification](https://signal.org/docs/specifications/sesame/sesame.pdf)
- [Signal libsignal repository](https://github.com/signalapp/libsignal)
