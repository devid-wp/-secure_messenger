# Жизненный цикл сообщения

## Состояния

```text
local_draft
    |
    v
encrypting --> local_failed
    |
    v
local_queued --retry--> submitting
    |                     |
    |                     +--> rejected
    |                     |
    |                     v
    +-----------------> accepted
                           |
                           v
                  queued_per_device
                     /           \
                    v             v
                 fetched       expired
                    |
                    v
                 acked
```

`read` не является серверным состоянием сообщения. Это локальное состояние
получателя; при включённой функции оно отправляется как новое E2EE-сообщение.

## Отправка

1. Клиент создаёт случайный `client_message_id`.
2. Plaintext валидируется и сохраняется в зашифрованной локальной БД.
3. E2EE worker проверяет актуальную MLS epoch и membership.
4. Payload шифруется OpenMLS. UI и backend не получают ключ сообщения.
5. Клиент отправляет envelope с `message_id`, `chat_id`, `sender_device_id`,
   `mls_epoch`, `wire_format` и `ciphertext`.
6. Сервер атомарно проверяет membership, epoch, размер и idempotency.
7. После durable write сервер отвечает `accepted`.
8. Для каждого устройства-получателя создаётся `Delivery`.

Повтор запроса с тем же `message_id` MUST возвращать прежний результат и не
создавать второе логическое сообщение.

## Получение

1. Устройство получает envelope через WebSocket либо выполняет catch-up.
2. Проверяет chat, epoch, replay window и допустимый размер.
3. Передаёт bytes в E2EE worker.
4. При успешной аутентификации/расшифровке сохраняет plaintext в локальной
   зашифрованной БД и отправляет ACK.
5. Повреждённый или неаутентичный ciphertext не отображается; клиент отправляет
   минимальную ошибку синхронизации без plaintext и ключевого материала.

## Ordering, replay и offline

- Network arrival order не считается message order.
- MLS generation и client sequence обрабатываются криптографической библиотекой.
- Серверный `accepted_at` используется только как стабильный UI fallback.
- Клиент хранит ограниченное число skipped keys согласно политике библиотеки.
- Epoch слишком далеко впереди вызывает запрос resync, а не неограниченное
  продвижение ratchet.
- Replay уже принятого MLS message отбрасывается.
- Offline sender может шифровать только при наличии актуального локального
  состояния; после membership change stale send будет отклонён.

## Изменение membership

Proposal/Commit/Welcome являются сообщениями протокола, а не application
plaintext. Сервер сериализует их в том же журнале чата.

1. Авторизованное устройство создаёт proposal.
2. Commit переводит чат в новую epoch.
3. Сервер принимает ровно один Commit для пары `(chat_id, current_epoch)`
   атомарной compare-and-swap операцией и блокирует application messages
   старой epoch.
4. Welcome доставляется только новым устройствам.
5. После Remove удалённое устройство не получает новые envelopes.

Если два устройства создали конкурирующие commits, проигравшая ветка не
применяется автоматически. Клиенты сверяют `confirmed_transcript_hash`,
останавливают отправку при fork и выполняют контролируемый resync. Delivery
server не имеет права выбирать ветку незаметно для клиентов.

## Удаление и retention

- «Удалить у меня» удаляет локальный plaintext и локальный индекс.
- Remote delete не поддерживается в v1.0.
- Сервер удаляет envelope после ACK всех устройств либо через 30 дней.
- Сервисные security events хранятся до 90 дней без ciphertext содержимого.
- Удаление на сервере не может стереть копии, уже полученные устройствами.
- Криптографическое стирание локальных данных требует удаления local store key.

## Ошибки

| Ошибка | Поведение |
|---|---|
| Нет сети | Оставить `local_queued`, повторять с backoff |
| Duplicate ID | Вернуть исходный ACK |
| Stale epoch | Обновить MLS state и зашифровать заново с новым `message_id` |
| Sender removed | Не повторять; показать постоянную ошибку |
| Invalid ciphertext | Не отображать, записать безопасный код ошибки |
| Local key unavailable | Заблокировать E2EE storage; не запрашивать plaintext у сервера |
