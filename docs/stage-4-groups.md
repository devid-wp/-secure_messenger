# Stage 4: группы

## Профиль группы

- `POST /api/v1/chats/groups` создаёт группу и owner membership;
- `GET /api/v1/chats/groups` возвращает группы текущего пользователя;
- `PATCH /api/v1/chats/groups/{chat_id}` меняет название или avatar URL;
- название обязательно и ограничено 255 символами;
- avatar URL должен использовать HTTP(S). Бинарная загрузка аватаров будет
  частью отдельного безопасного media storage.

## Участники и роли

- `POST /api/v1/chats/groups/{chat_id}/members` добавляет участника;
- `DELETE /api/v1/chats/groups/{chat_id}/members/{login}` удаляет участника;
- owner может добавлять и удалять admin/member;
- admin может управлять только обычными member;
- owner нельзя удалить этой операцией;
- состав и роли возвращаются в `members` и `member_roles`.

## Приглашения

- `POST /api/v1/chats/groups/{chat_id}/invitations` создаёт приглашение;
- `GET /api/v1/chats/groups/invitations/pending` показывает входящие;
- `POST /api/v1/chats/groups/invitations/{id}/accept` принимает приглашение;
- приглашение адресное, действует 7 дней и не добавляет пользователя без accept;
- повторный pending invite для той же группы и пользователя переиспользуется.

## Миграции

- `20260729_10` добавляет `chats.avatar_url`;
- `20260729_11` добавляет адресные приглашения с состоянием и сроком действия.

Блокировка пользователей запрещает личные сообщения, но не останавливает
общение остальных участников общей группы.
