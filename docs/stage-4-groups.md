# Stage 4: groups

## Group profile

- `POST /api/v1/chats/groups` creates a group and its owner membership.
- `GET /api/v1/chats/groups` returns groups visible to the current user.
- `PATCH /api/v1/chats/groups/{chat_id}` updates the name, avatar, or history
  policy.
- Names are required and limited to 255 characters.
- Avatar URLs must use HTTP(S).

## Roles and permissions

| Operation | Owner | Admin | Member |
| --- | --- | --- | --- |
| Update name or avatar | Yes | Yes | No |
| Invite or add a member | Yes | Yes | No |
| Remove a regular member | Yes | Yes | No |
| Add, promote, or remove an admin | Yes | No | No |
| Change history policy | Yes | No | No |
| Transfer ownership | Yes | No | No |
| Leave the group | After transfer | Yes | Yes |

There is exactly one owner in the API model. The owner cannot be removed and
cannot leave until ownership has been transferred to another current member.

Endpoints:

- `POST /api/v1/chats/groups/{chat_id}/members`
- `DELETE /api/v1/chats/groups/{chat_id}/members/{login}`
- `DELETE /api/v1/chats/groups/{chat_id}/leave`
- `POST /api/v1/chats/groups/{chat_id}/owner`

## Invitations

- `POST /api/v1/chats/groups/{chat_id}/invitations` creates an invitation.
- `GET /api/v1/chats/groups/invitations/pending` lists incoming invitations.
- `POST /api/v1/chats/groups/invitations/{id}/accept` accepts one.
- Invitations are addressed to one user, expire after seven days, and never add
  the user without explicit acceptance.
- A repeated pending invitation for the same group and user is reused.

## System messages

Membership changes, ownership transfers, profile changes, and history-policy
changes create immutable messages with `kind: "system"`. They share the normal
per-chat `server_seq`, appear in history, and are delivered through realtime
events. Clients cannot edit or delete them.

## History access

Groups support two policies:

- `since_join` (default): a new member sees messages beginning with the server
  sequence captured when their membership was created.
- `all`: every current member may read the complete group history.

Only the owner can change this policy. Sequence-based boundaries avoid clock
precision and timezone errors.

## Migrations

- `20260729_10` adds group avatars.
- `20260729_11` adds expiring invitations.
- `20260729_12` adds history boundaries, history policy, and system-message
  kinds.

User blocking applies to direct messages. It does not silently disrupt
communication among the remaining members of a shared group.
