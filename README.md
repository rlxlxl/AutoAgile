# AutoAgile — двусторонняя синхронизация YouGile ↔ GitHub / GitLab

AutoAgile связывает задачи в **YouGile** с репозиторием на **GitHub** или **GitLab** и
поддерживает их в согласованном состоянии: по новым задачам создаются ветки и
Pull Request / Merge Request, а состояние чек-листов синхронизируется между YouGile и
PR/MR в обе стороны в реальном времени

Хостинг выбирается одной переменной `GIT_PROVIDER` (`github` или `gitlab`) — весь
остальной код общий. Реализации провайдеров лежат в `app/providers/github` 
`app/providers/gitlab` за единым интерфейсом `GitProvider`

---

## Содержание

1. [Назначение](#назначение)
2. [Состав системы](#состав-системы)
3. [Настройка файла .env](#настройка-файла-env)
4. [Запуск](#запуск)
5. [Настройка вебхуков](#настройка-вебхуков)
6. [Принцип работы](#принцип-работы)
7. [Устранение неполадок](#устранение-неполадок)
8. [Структура репозитория](#структура-репозитория)
9. [Требования](#требования)

---

## Назначение

Каждая новая задача в YouGile порождает в репозитории две сущности:

- **Ветку** вида `feature/<короткий-id>-<название>`;
- **Pull Request / Merge Request** (из ветки в `dev`) с чек-листом задачи в теле.

Далее состояние чек-листа синхронизируется автоматически:

- отметка пункта в **PR/MR** отражается в **YouGile**;
- отметка пункта в **YouGile** отражается в **PR/MR**.

Синхронизация выполняется вживую через вебхуки в обоих направлениях.

---

## Состав системы

Система состоит из трёх компонентов:

| Компонент | Команда запуска | Назначение |
| --- | --- | --- |
| Поллер | `python -m app.cli.main` | Периодически опрашивает колонку YouGile и создаёт ветку для каждой новой задачи. |
| Вебхук-сервер | `uvicorn app.webhooks.server:app --host 0.0.0.0 --port 8000` | Принимает вебхуки от GitHub/GitLab и YouGile и синхронизирует чек-листы в реальном времени. |
| CI (GitHub Actions / GitLab CI) | выполняется в CI | При пуше в ветку `feature/**` запускает тесты и создаёт PR/MR с чек-листом из YouGile. |

---

## Настройка файла .env

В корне проекта расположен файл `.env` (шаблон — `.env.example`). Требуется заполнить
следующие значения:

```bash
# --- Выбор хостинга ---
GIT_PROVIDER=github                            # github | gitlab

# --- YouGile ---
YOUGILE_BEARER_TOKEN=токен_из_YouGile        # Настройки -> API -> создать ключ
YOUGILE_PROJECT_ID=id_проекта
YOUGILE_BOARD_ID=id_доски
YOUGILE_COLUMN_ID=id_колонки                  # колонка, за которой ведётся наблюдение
YOUGILE_POLL_INTERVAL=10                      # период опроса в секундах

# --- GitHub (если GIT_PROVIDER=github) ---
GITHUB_TOKEN=ghp_личный_токен                 # Personal Access Token со scope "repo"
GITHUB_REPO=owner/repo                         # например: rlxlxl/AutoAgile
GITHUB_WEBHOOK_SECRET=произвольная_строка     # та же строка указывается в настройках вебхука GitHub

# --- GitLab (если GIT_PROVIDER=gitlab) ---
GITLAB_TOKEN=glpat_личный_токен               # Personal/Project Access Token со scope "api"
GITLAB_URL=http://localhost:8929               # адрес self-hosted GitLab
GITLAB_PROJECT_ID=42                           # числовой ID проекта или "group%2Fproject"
GITLAB_WEBHOOK_TOKEN=произвольная_строка      # та же строка в поле Secret token вебхука GitLab

# --- Секрет вебхуков YouGile ---
YOUGILE_WEBHOOK_SECRET=                        # должно оставаться пустым (см. примечание)
```

> Активен только один провайдер за раз — тот, что указан в `GIT_PROVIDER`. Заполнять
> нужно лишь блок соответствующего хостинга.

> **Примечание о `YOUGILE_WEBHOOK_SECRET`.** YouGile не подписывает свои вебхуки.
> Если задать это значение, сервер будет отклонять все запросы от YouGile с ответом
> `{"skipped":"invalid_signature"}`, и обратная синхронизация работать не будет.
> Поле необходимо оставлять пустым.

> **Примечание о применении настроек.** Значения считываются один раз при запуске.
> После изменения `.env` необходимо перезапустить поллер и вебхук-сервер.

### Получение значений YouGile

- **Токен:** YouGile → Настройки → раздел API.
- **project / board / column ID:** при первом запуске `python -m app.cli.main` открывается
  интерактивное меню выбора проекта, доски и колонки, которое сохраняет эти
  идентификаторы в `.env`. Альтернативно — через API:
  `GET https://ru.yougile.com/api-v2/tasks?columnId=<id>` (поле `id` у объектов).

---

## Запуск

### 1. Установка зависимостей

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Заполнение `.env`

См. раздел [Настройка файла .env](#настройка-файла-env).

### 3. Запуск вебхук-сервера (терминал №1)

```bash
source venv/bin/activate
uvicorn app.webhooks.server:app --host 0.0.0.0 --port 8000
```

Проверка: обращение к `http://localhost:8000/health` должно возвращать
`{"status":"ok", ...}`.

### 4. Запуск поллера (терминал №2)

```bash
source venv/bin/activate
python -m app.cli.main
```

### 5. Публикация сервера в интернет (терминал №3)

GitHub и YouGile должны иметь возможность обращаться к серверу, поэтому требуется
публичный HTTPS-адрес. Наиболее простой способ — ngrok:

```bash
ngrok http 8000
```

ngrok выдаёт адрес вида `https://xxxx.ngrok-free.dev` — далее он обозначается как `<host>`.

> При перезапуске ngrok публичный адрес меняется, и его необходимо повторно указать
> в вебхуках GitHub и YouGile (см. следующий раздел).

---

## Настройка вебхуков

### GitHub

Репозиторий → **Settings → Webhooks → Add webhook**:

- **Payload URL:** `https://<host>/webhook/github` (обратите внимание: `webhook`, без `s`)
- **Content type:** `application/json`
- **Secret:** значение `GITHUB_WEBHOOK_SECRET`
- **Which events:** «Let me select individual events» → отметить **Pull requests**
- Сохранить.

### GitLab

Проект → **Settings → Webhooks → Add new webhook**:

- **URL:** `https://<host>/webhook/gitlab`
- **Secret token:** значение `GITLAB_WEBHOOK_TOKEN`
- **Trigger:** отметить **Merge request events**
- Сохранить.

> **Локальный GitLab и приватная сеть.** По умолчанию GitLab блокирует вебхуки на
> localhost / приватные адреса. Если вебхук-сервер и ngrok крутятся локально, включите
> **Admin → Settings → Network → Outbound requests → «Allow requests to the local network
> from webhooks and integrations»**.
>
> **Токен для CI.** `CI_JOB_TOKEN` не может создавать Merge Request. Заведите Project
> Access Token (Settings → Access Tokens, роль Developer+, scope `api`) и положите его в
> **Settings → CI/CD → Variables** как `GITLAB_TOKEN`.

### YouGile

Подписка создаётся одним запросом (подставьте токен и `<host>`):

```bash
curl -X POST https://ru.yougile.com/api-v2/webhooks \
  -H "Authorization: Bearer ТОКЕН_YOUGILE" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://<host>/webhook/yougile","event":"task-updated"}'
```

> Адрес `/webhook/yougile` указывается без `s`. Ошибочный вариант `/webhooks/...`
> приводит к ответам `404`.

Просмотр существующих подписок:

```bash
curl -s -H "Authorization: Bearer ТОКЕН_YOUGILE" https://ru.yougile.com/api-v2/webhooks
```

---

## Принцип работы

### Связывание Pull Request и задачи

Pull Request связывается с задачей YouGile по **имени ветки** `feature/<короткий-id>-...`,
где `<короткий-id>` — часть идентификатора задачи до первого дефиса. Ветку создаёт
поллер, поэтому связывание выполняется автоматически и не требует ручных действий.

> Рекомендуется называть задачи в YouGile кратко и латиницей — из названия
> формируется имя ветки. Пример: `fix_frontend` вместо «Почините фронт».

### Сопоставление пунктов чек-листа

В GitHub чек-лист представлен строками Markdown (`- [ ]` / `- [x]`), а в YouGile — массивом
объектов. Пункты сопоставляются по тексту без учёта регистра и лишних пробелов.

### Направление GitHub → YouGile

```mermaid
flowchart LR
  A["Изменение тела PR (галочка)"] -->|"вебхук pull_request.edited"| B["POST /webhook/github"]
  B --> C["find_task_for_branch(head.ref)"]
  C --> D["GET /api-v2/tasks/{id}"]
  D --> E["PATCH /api-v2/tasks/{id} (checklists)"]
```

### Направление YouGile → GitHub

```mermaid
flowchart LR
  A["Изменение задачи в YouGile"] -->|"вебхук task-updated"| B["POST /webhook/yougile"]
  B --> C["поиск открытого PR по ветке feature/<короткий-id>-"]
  C --> D["GET /repos/owner/repo/pulls/{n}"]
  D --> E["изменение - [ ] / - [x] в теле"]
  E --> F["PATCH /repos/owner/repo/pulls/{n}"]
```

### Защита от зацикливания

Без защиты системы обновляли бы друг друга бесконечно: изменение в GitHub вызывает
изменение в YouGile, которое снова инициирует вебхук в GitHub. Для предотвращения этого
используется механизм «echo guard» (`app/sync_guard.py`): после записи в систему сервер
запоминает хеш результирующего состояния чек-листа и однократно игнорирует вебхук,
порождённый этой же записью.

---

## Устранение неполадок

| Симптом | Причина и решение |
| --- | --- |
| `/health` недоступен через ngrok | Не запущен `uvicorn`. Проверьте `http://localhost:8000/health`. |
| В логах `404 Not Found` на `/webhooks/...` | Лишняя `s` в адресе вебхука. Корректно: `/webhook/github` и `/webhook/yougile`. |
| Ответ `{"skipped":"invalid_signature"}` от `/webhook/yougile` | Значение `YOUGILE_WEBHOOK_SECRET` не пустое. Очистите его в `.env` и перезапустите сервер. |
| Изменения в `.env` не применяются | Настройки считываются при старте. Перезапустите поллер и `uvicorn`. |
| Ответ `{"skipped":"task_not_found"}` | Задача по имени ветки не найдена (неверный `YOUGILE_BOARD_ID`/`YOUGILE_COLUMN_ID` или задача в другой колонке). |
| Ответ `{"skipped":"pr_not_found"}` | Для задачи ещё не создан открытый Pull Request (CI не отработал). Это ожидаемо до создания PR. |
| После перезапуска ngrok синхронизация прекратилась | Изменился публичный адрес. Обновите URL в вебхуках GitHub и YouGile. |

Диагностика: панель ngrok `http://127.0.0.1:4040` отображает все входящие запросы и ответы
сервера, что позволяет определить причину пропуска синхронизации.

---

## Структура репозитория

```
app/
  core/                # провайдеро-независимая логика
    api.py             # клиент YouGile API (get_task, update_task, create_task)
    checklist.py       # конвертация Markdown <-> чек-лист YouGile, поиск задачи по ветке
    checklist_sync.py  # сопоставление чек-листов и вычисление хешей состояний
    sync_guard.py      # защита от зацикливания (echo guard)
    config.py          # чтение настроек из .env / yougile.env / окружения
    git_service.py     # создание и пуш веток
    poller.py          # опрос YouGile и создание веток
    models.py          # датаклассы
  providers/           # адаптеры хостинга за единым интерфейсом
    base.py            # GitProvider (ABC) + PullRequest/WebhookEvent + get_provider()
    github/client.py   # GitHubProvider (Pull Requests, подпись X-Hub-Signature-256)
    gitlab/client.py   # GitLabProvider (Merge Requests, токен X-Gitlab-Token)
  webhooks/
    server.py          # FastAPI: /webhook/scm, /webhook/github, /webhook/gitlab, /webhook/yougile, /health
  cli/
    main.py            # точка входа поллера
    menu.py            # интерактивный выбор проекта/доски/колонки
    create_pr.py       # создание PR/MR с чек-листом (запускается в CI)
.github/workflows/
  ci.yml               # тесты и создание PR при пуше в feature/** (GIT_PROVIDER=github)
.gitlab-ci.yml         # тесты и создание MR при пуше в feature/** (GIT_PROVIDER=gitlab)
.env                   # локальные настройки (в .gitignore, в репозиторий не попадает)
.env.example           # шаблон настроек
```

---

## Требования

- Python 3.10+ (используется синтаксис `str | None`)
- Токен YouGile и токен выбранного хостинга (GitHub **или** GitLab)
- ngrok или иной способ предоставить серверу публичный HTTPS-адрес
