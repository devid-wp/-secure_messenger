# Доменная модель

## Основной принцип

`User` отвечает за учётную запись и права, `Device` — за криптографическую
идентичность. Один пользователь может быть представлен несколькими MLS leaves.
Серверная модель membership по пользователям и криптографическая membership по
устройствам связаны, но не взаимозаменяемы.

Будущие идентификаторы MUST быть случайными UUIDv4 или 128-битными opaque ID.
Последовательные целые идентификаторы из текущей схемы являются переходными.

## User

Учётная запись человека.

| Поле | Назначение | Видит сервер |
|---|---|---|
| `user_id` | Стабильный opaque ID | Да |
| `login_normalized` | Уникальный логин для входа | Да |
| `password_verifier` | Argon2id verifier с уникальной солью | Да |
| `account_status` | `active`, `locked`, `deleted` | Да |
| `created_at` | Время создания | Да |
| `recovery_code_hashes` | Одноразовые коды восстановления аккаунта | Да, только hash |

`User` не содержит message keys, MLS state или приватный identity key.

## Device

Отдельная установка клиента и единственный криптографический endpoint.

| Поле | Назначение | Где хранится |
|---|---|---|
| `device_id` | Случайный стабильный ID | Сервер и клиент |
| `user_id` | Владелец | Сервер |
| `credential` | Публичная MLS credential | Сервер и клиенты |
| `signature_public_key` | Публичный Ed25519 key | Сервер и клиенты |
| `key_packages` | Одноразовые MLS KeyPackages | Сервер до использования |
| `device_label` | Пользовательская подпись устройства | E2EE между своими устройствами |
| `status` | `pending`, `active`, `revoked` | Сервер |
| `created_at`, `last_seen_at` | Аудит и управление | Сервер |
| signature private key | Подпись MLS сообщений | Только устройство |
| MLS group state | Epoch secrets и ratchet state | Только устройство |
| local store key | Шифрование локальной БД | Только устройство |

Удалённое устройство никогда не возвращается в `active`: повторная установка
создаёт новый `device_id` и новые ключи.

## Chat

Логический чат и единица E2EE. Каждый `Chat` соответствует одной MLS group.

| Поле | Назначение | Видит сервер |
|---|---|---|
| `chat_id` | Opaque routing ID | Да |
| `mls_group_id` | Случайный MLS GroupID | Да |
| `type` | `dm` или `group` | Да |
| `current_epoch` | Контроль порядка MLS commits | Да |
| `encrypted_metadata` | Название, avatar reference, настройки | Только ciphertext |
| `created_at` | Время создания | Да |
| `state` | `active`, `tombstoned` | Да |

Один DM для одной пары пользователей SHOULD переиспользоваться. Повторное
создание после identity reset MAY создать новый `chat_id`, чтобы не смешивать
разные криптографические контексты.

## Participant

Серверная запись допуска пользователя и его устройств к чату.

| Поле | Назначение | Видит сервер |
|---|---|---|
| `chat_id`, `user_id` | Membership | Да |
| `role` | `owner`, `admin`, `member` | Да |
| `membership_state` | `invited`, `active`, `removed`, `left` | Да |
| `joined_epoch`, `removed_epoch` | Граница доступа | Да |
| `joined_at`, `removed_at` | Аудит | Да |

Криптографический состав хранится отдельно как `ChatDevice`: одна запись на
активное устройство участника с MLS leaf index и credential fingerprint.
Пользователь считается способным читать новые сообщения, если хотя бы одно его
активное устройство включено в актуальную эпоху.

## Message

Сервер хранит envelope, а не содержимое сообщения.

| Поле | Назначение | Видит сервер |
|---|---|---|
| `message_id` | Случайный idempotency/routing ID | Да |
| `chat_id` | Адрес доставки | Да |
| `sender_device_id` | Проверка membership и rate limit | Да |
| `mls_epoch` | Маршрутизация и защита от stale send | Да |
| `wire_format` | `application`, `proposal`, `commit`, `welcome` | Да |
| `ciphertext` | MLS message bytes | Да, не расшифровывает |
| `ciphertext_size` | Ограничение ресурса | Да |
| `accepted_at`, `expires_at` | Очередь и retention | Да |

Внутри encrypted application payload находятся:

- `schema_version`;
- `client_message_id`;
- `kind` (`text`, `receipt`, `chat_metadata`, `device_event`);
- `sender_user_id`;
- текст или control payload;
- client timestamp;
- reply/edit поля только в будущих версиях.

Plaintext payload MUST NOT дублироваться во внешнем envelope.

## Delivery

`Delivery` связывает одно сообщение и одно устройство-получатель.

- состояния: `queued`, `fetched`, `acked`, `expired`;
- сервер удаляет ciphertext после ACK всех целевых устройств либо по TTL;
- `fetched` не означает `read`;
- read receipt является отдельным E2EE application message;
- повторная доставка одного `message_id` допустима, клиент обязан дедуплицировать.

## Инварианты

1. Активный `ChatDevice` обязан принадлежать активному `Participant`.
2. Application message принимается только от устройства в текущем MLS epoch.
3. Удалённый device не может публиковать KeyPackage и отправлять сообщения.
4. Новый участник не получает epoch secrets до своей эпохи.
5. Удалённый участник не получает ciphertext новых эпох.
6. Смена membership завершается MLS Commit до новых application messages.
7. Серверная membership и подтверждённая MLS membership должны сходиться;
   расхождение блокирует отправку и требует resync.
8. Серверная роль не является достаточным разрешением: клиент проверяет
   подписанного инициатора Commit по E2EE-копии role state.
