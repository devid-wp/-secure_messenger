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
encryption: `{"version":1,"type":"message","client_id":"uuid","sent_at":"ISO-8601","body":{...}}`.
Supported types are `message`, `edit`, `delete`, `reaction`, `receipt`,
`attachment`, `group_metadata`, and `device_event`. Unknown versions, types,
top-level fields, malformed UUID/timestamps, mutation targets, and payloads over
64 KiB are rejected after authenticated MLS decryption and before rendering.
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
