# Краткий план production-релиза E2EE

Статус: **release candidate**  
Платформа: browser PWA, OpenMLS/WASM в dedicated Worker

Production-ready статус разрешён только после выполнения всех P0-пунктов ниже.

## 1. Автоматический gate

- Зафиксировать Python, npm и Cargo dependencies lock-файлами.
- В CI запускать lint, typecheck, production build, все backend/frontend/WASM
  тесты, а также Playwright в Chromium и Firefox.
- Запускать `pip-audit`, `npm audit` и `cargo audit`; vulnerability допускается
  только с документированным владельцем, сроком и security approval.
- Блокировать релиз при skipped security test, изменённом lockfile или падении
  любой проверки.

## 2. E2EE и browser vault

- Покрыть DM, группы, multi-device, add/update/remove Commit, смену epoch,
  offline/reconnect, replay/reorder/fork и повреждённый ciphertext.
- При криптографической неоднозначности блокировать отправку до resync; fallback
  в plaintext запрещён.
- Проверить vault: create, lock/unlock, reload, смену passphrase, миграцию и
  повреждение IndexedDB. Lock уничтожает Worker и очищает plaintext из UI.
- Проверить encrypted attachments на малом и максимальном размере, при
  прерывании, повторе и повреждении ciphertext.

## 3. Privacy boundary и web delivery

- На копии production-подобной БД применить миграции и исключить legacy
  plaintext tables/columns.
- API schemas отклоняют лишние поля; authorization проверяется для envelopes,
  KeyPackages, uploads и downloads; действуют rate, size, quota и retention
  limits.
- Body, Authorization, cookies, ciphertext, keys и passphrases не попадают в
  backend, proxy, APM и security logs.
- Backend, PostgreSQL, Redis и object storage не доступны напрямую извне.
- Production ingress использует HTTPS/TLS 1.3, redirect с HTTP, HSTS, точный
  CORS origin и secure HttpOnly SameSite cookie с узким path.
- CSP разрешает только same-origin ресурсы и необходимый Worker/WASM; запрещены
  inline/eval scripts, analytics, CDN и mixed content. Service worker не
  кэширует API/ciphertext и не допускает downgrade старого shell.

## 4. Staging-проверка

- В Chromium и Firefox проверить два независимых профиля: регистрацию Alice и
  Bob, vault, DM, группу из трёх участников, две вкладки, offline/reconnect,
  второе устройство, отзыв устройства, повреждение vault/envelope, attachments
  и обновление PWA с предыдущего release candidate.
- Выполнить canary audit с уникальными message/group/file строками по PostgreSQL,
  Redis, object storage, логам, API/HAR, browser storage/cache и frontend build.
  Plaintext допустим только в памяти разблокированного renderer.
- Проверить migration, encrypted backup restore, rollback, storage exhaustion,
  certificate renewal, alerts и emergency release shutdown.
- Сохранить commit SHA, версии браузеров и ссылки на CI/audit artifacts.

## 5. Review и выпуск

- Независимый review покрывает OpenMLS/WASM wrapper, Worker protocol, vault,
  membership/device lifecycle, attachments, backend privacy/authorization,
  CSP/service worker и supply chain.
- Critical/high findings исправляются до релиза; medium получают решение,
  владельца и срок либо документированный accepted risk.
- Документация фиксирует реальные лимиты, поддерживаемые браузеры, metadata и
  recovery policy. UI честно показывает vault/device/crypto failures.
- После подписания release artifacts и SBOM выполнить ограниченный rollout и
  наблюдать только агрегированные метрики без payload и пользовательских ID.

## GO checklist

- [ ] Release commit/tag и lockfiles зафиксированы, рабочее дерево чистое.
- [ ] Полный CI, audits и Chromium/Firefox E2E зелёные без skip.
- [ ] Ручная staging-матрица подписана и privacy canary нигде не найден.
- [ ] HTTPS, CSP, cookies, CORS и закрытая сеть проверены.
- [ ] Migration, backup restore, rollback и incident response проверены.
- [ ] Независимый security review закрыт, документация актуальна.

Если любой пункт не выполнен, сборка остаётся release candidate, а не
production-ready E2EE messenger.
