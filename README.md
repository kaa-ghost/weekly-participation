# Учёт занятости по проектам

Web-приложение: пользователи за неделю распределяют 100% своей занятости по проектам.
Администратор управляет пользователями и проектами (CRUD).

## Стек
Python 3.11+, Flask 3, Flask-SQLAlchemy (SQLite), Flask-Login, Bootstrap 5 (CDN).

## Запуск

    python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python app.py

При первом запуске создаётся БД `instance/app.db` и администратор:
**логин `admin`, пароль `admin`** (пароль можно задать через переменную окружения
`ADMIN_PASSWORD` перед первым запуском).

## Роли и сценарии

- **Регистрация** — открытая (`/register`), новый пользователь не админ.
- **Пользователь** (`/`) — видит текущую неделю (понедельник–воскресенье), выбирает
  проект, указывает % занятости, может добавить запись по другому проекту.
  Сумма по неделе не может превысить 100%. Свои записи можно удалять.
- **Админ** — разделы «Пользователи» и «Проекты»: создание, редактирование
  (в т.ч. сброс пароля, блокировка, роль), удаление.

## Структура

- `app.py` — маршруты и инициализация
- `models.py` — модели User, Project, Participation
- `templates/` — шаблоны (Jinja2 + Bootstrap)

## Деплой на тестовый хостинг

### Вариант A: Render (бесплатно, публичный URL)

1. Загрузите папку проекта в репозиторий GitHub.
2. На https://render.com → *New → Web Service* → подключите репозиторий
   (Render подхватит `render.yaml` автоматически).
3. После деплоя откройте выданный URL `https://<имя>.onrender.com`,
   войдите как `admin` / пароль из `ADMIN_PASSWORD`.

### Вариант B: PythonAnywhere (бесплатный тариф)

1. Загрузите архив проекта через *Files*.
2. В консоли: `pip install -r requirements.txt`.
3. *Web* → *Add a new web app* → *Manual configuration* → Python 3.10+.
4. В WSGI-файле укажите путь к `app.py` (объект `app`).
5. Перезагрузите приложение.

### Вариант C: Kimi «构建应用» (kimi.com/build)

Откройте страницу https://www.kimi.com/build, опишите задачу
(можно вставить ТЗ из этого чата) — Kimi сгенерирует и опубликует
приложение со своей облачной БД и логином, даст ссылку вида
`abc.ok.kimi.link`. Готовый Flask-код туда не импортируется,
сайт будет пересобран на стеке Kimi.

## Версия с PostgreSQL

Эта версия использует PostgreSQL при заданной переменной окружения `DATABASE_URL`
(без неё локально работает SQLite, удобно для разработки).

### Render (база создаётся автоматически)

1. Удалите старый веб-сервис (данные в нём всё равно эфемерные) и создайте
   **новый** Web Service из этого репозитория — Render по `render.yaml`
   поднимет и приложение, и базу `weekly-db`, и свяжет их.
2. Либо вручную: *New → PostgreSQL* → скопируйте *Internal Database URL* →
   в веб-сервисе *Environment* добавьте `DATABASE_URL` со этим значением
   → *Manual Deploy*.

### Локально с Docker

    docker run --name weekly-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=weekly -p 5432:5432 -d postgres:16
    export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/weekly
    python app.py

Теперь данные (пользователи, проекты, записи) сохраняются между деплоями.

### Docker (приложение + PostgreSQL одной командой)

    docker compose up --build

Приложение будет на http://localhost:8000 (admin / admin123).
База в именованном томе `pgdata` — данные сохраняются между перезапусками.

Только образ приложения (без compose):

    docker build -t weekly-app .
    docker run -p 8000:8000 -e SECRET_KEY=secret -e ADMIN_PASSWORD=admin123 \
      -e DATABASE_URL=postgresql://user:pass@host:5432/weekly weekly-app

Образ не содержит БД — PostgreSQL подключается через DATABASE_URL.
