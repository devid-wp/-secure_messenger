# Модель угроз и политика метаданных

## Защищаемые активы

- plaintext сообщений и названий групп;
- MLS epoch secrets, device private keys и local store keys;
- целостность и авторство сообщений;
- история membership и security events на устройствах;
- пароли, recovery codes и серверные session tokens;
- локальный поисковый индекс.

## Доверенные компоненты

- проверенный клиентский build и E2EE worker;
- ОС, браузер и secure random generator устройства;
- OpenMLS и выбранный crypto provider;
- Authentication Service в части привязки `user_id/device_id` к credential;
- уже проверенное устройство при добавлении нового.

Delivery Service и база сообщений **не являются доверенными для
конфиденциальности содержимого**.

## Противники

| Противник | Требуемая защита |
|---|---|
| Пассивный сетевой наблюдатель | TLS скрывает transport payload; E2EE остаётся вторым барьером |
| Активный MITM | TLS + MLS authentication; повреждение определяется |
| Утечка серверной БД | Нет plaintext, паролей, private keys и локального индекса |
| Компрометация delivery-сервера | Не раскрывает содержимое; возможны delay/drop/replay/fork/traffic analysis |
| Злоумышленник с аккаунтом | Не читает чужие чаты и не добавляет себя без membership commit |
| Украденное заблокированное устройство | Local store key защищён платформой; устройство можно отозвать |
| Украденное разблокированное устройство | Считается полной компрометацией данных этого устройства |
| XSS/supply-chain атака | CSP, отсутствие third-party script, pinned lockfile, review WASM boundary |
| Злонамеренный участник группы | Может копировать всё, что законно расшифровал |

## Что модель не скрывает

E2EE v1.0 не защищает от:

- malware, browser extension или XSS, читающих plaintext на endpoint;
- скриншота и пересылки сообщения участником;
- traffic analysis по IP, времени, размерам и частоте;
- блокировки, задержки и удаления ciphertext сервером;
- компрометации Authentication Service до ручной проверки safety code;
- данных, уже расшифрованных отозванным устройством;
- слабого пользовательского пароля для захвата аккаунта.

Fork MLS state должен обнаруживаться по transcript hash. Клиент при fork
блокирует отправку и не позволяет delivery-серверу молча выбрать другую ветку.

## Разрешённые серверу метаданные

Сервер MAY видеть только данные, необходимые для аутентификации, routing,
abuse control и ограниченного аудита:

- `user_id`, нормализованный login, verifier пароля;
- device IDs, публичные credentials, KeyPackages, status и last seen;
- chat ID, тип DM/group, membership, роли и текущую MLS epoch;
- sender device, target devices, wire format;
- время приёма, размер ciphertext, delivery/ACK state и TTL;
- IP и User-Agent в security log не дольше 30 дней;
- агрегированные метрики без message/chat/user identifiers.

## Запрещённые серверу данные

Сервер MUST NOT получать или сохранять:

- текст, тему, название группы или поисковые токены;
- preview уведомления;
- private device keys, epoch secrets, file keys;
- plaintext read receipts, typing events или drafts;
- адресную книгу устройства;
- расшифрованные вложения;
- содержимое encrypted backup;
- ключи, позволяющие восстановить E2EE историю только по паролю.

## Минимизация

- Logs содержат error code и request ID, но не ciphertext body, token или key.
- IP/User-Agent security logs удаляются через 30 дней.
- Delivery metadata удаляется вместе с envelope.
- Tombstone пользователя не хранит login дольше юридически необходимого срока.
- Размеры сообщений MAY округляться по padding policy после измерений.
- Метрики строятся на стороне сервера до удаления identifiers.

## События безопасности

Клиент обязан явно показывать:

- новое или отозванное устройство;
- изменение safety code;
- добавление/удаление участника;
- смену роли;
- невозможность проверить credential;
- resync после расхождения MLS state.

События membership передаются как MLS authenticated content. Серверный audit
не считается доказательством для клиента без криптографического подтверждения.

## Browser/PWA delivery boundary

Production PWA delivery is same-origin and HTTPS-only. The document CSP denies
everything by default, permits scripts and module Workers only from the
application origin, and grants WebAssembly compilation only through
`'wasm-unsafe-eval'`. It does not grant JavaScript `'unsafe-eval'`, inline
scripts, objects, frames, a base URL, or arbitrary network destinations.
`connect-src 'self'` confines HTTP and WebSocket transport to the deployment
origin. HSTS, `no-referrer`, nosniff, frame denial, and a restrictive
Permissions Policy are emitted by the frontend ingress.

There are no analytics, tag managers, remote fonts, third-party scripts, or
runtime CDN imports. JSX containing `dangerouslySetInnerHTML` fails lint. npm
dependencies are installed from the committed lockfile with `npm ci`; the Rust
WASM graph is fixed by `Cargo.lock`. A CSP reduces XSS probability but cannot
make a compromised same-origin build safe: build provenance and dependency
review remain part of the cryptographic trust boundary.

## Остаточные риски и последующие меры

До key transparency сервер Authentication Service теоретически способен
подменить device credential для непроверенного контакта. В v1.0 риск снижается
QR/safety verification и заметными device-change events. Key transparency —
приоритет v1.1 и требует отдельного протокола и аудита.
