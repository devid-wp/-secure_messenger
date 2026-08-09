# Спецификация Secure Messenger

Статус: **draft для утверждения**

Версия набора документов: **1.0-draft.1**
Дата фиксации: **2026-07-26**

Эти документы задают границы продукта и модель безопасности. Текущая схема
хранит сообщения только как opaque MLS envelopes; прежнее plaintext-хранилище
удалено миграцией `20260805_20`.

## Нормативные документы

1. [Состав версии 1.0](product-v1.md)
2. [Доменная модель](domain-model.md)
3. [Жизненный цикл сообщения](message-lifecycle.md)
4. [Модель угроз и политика метаданных](security-model.md)
5. [Потеря пароля, устройства и восстановление](recovery.md)
6. [ADR-0001: E2EE на базе MLS и OpenMLS](e2ee-protocol.md)
7. [ADR-0002: Vault KDF и lockout semantics](adr-0002-kdf-and-lockout.md)
8. [Политика backup/recovery локального vault](local-vault-backup-recovery.md)
9. [Stage 5 implementation status](stage-5-progress.md)
10. [Stage 6: stickers and encrypted media](stage-6-stickers-media.md)
11. [PWA E2EE runtime](pwa-e2ee.md)
12. [Backend opaque-storage boundary](backend-opaque-storage.md)
13. [Stage 3: рабочие личные сообщения](stage-3-direct-messages.md)
14. [Stage 4: группы](stage-4-groups.md)
15. [Фундамент backend и миграций](foundation.md)
16. [Production deployment](production-deploy.md)
17. [Browser compatibility](browser-compatibility.md)

Слова **MUST**, **MUST NOT**, **SHOULD** и **MAY** обозначают обязательное,
запрещённое, рекомендуемое и необязательное поведение.

## Зафиксированные решения

- Криптографическим endpoint является устройство, а не учётная запись.
- Каждый DM и каждый групповой чат является отдельной MLS-группой.
- Сервер маршрутизирует ciphertext, но не получает ключи и plaintext.
- Поиск выполняется только локально по расшифрованному индексу.
- Потеря пароля не должна давать серверу способ расшифровать историю.
- Потеря всех устройств означает потерю старой истории в v1.0.
- Облачная резервная копия, звонки и key transparency не входят в v1.0;
  вложения передаются только как client-side encrypted blobs.
- Расширение production-БД заблокировано до утверждения этих документов и
  прохождения E2EE-прототипа из ADR-0001.

## Порядок изменения

Изменение состава v1.0 или криптографической модели оформляется отдельным ADR.
Изменение, которое заставляет сервер видеть новый вид plaintext или
метаданных, требует обновления `security-model.md` и отдельного security review.
