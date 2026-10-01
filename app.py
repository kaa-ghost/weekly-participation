import calendar
import io
import os
from datetime import date, timedelta

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)

from models import Project, Participation, User, current_week_start, db

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')

# PostgreSQL через переменную DATABASE_URL; локально без неё — SQLite
db_url = os.environ.get('DATABASE_URL', '')
if db_url.startswith('postgres://'):  # Render выдаёт старый префикс
    db_url = 'postgresql://' + db_url[len('postgres://'):]
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Для доступа войдите в систему.'

KIND_LABELS = {'fact': 'факт', 'plan': 'план'}
MONTH_NAMES = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
               'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)

    return wrapper


def month_mondays(year, month):
    """До 4 последних понедельников месяца (недели отчёта для помесячного факта)."""
    first = date(year, month, 1)
    monday = first if first.weekday() == 0 else first + timedelta(days=7 - first.weekday())
    last = date(year, month, calendar.monthrange(year, month)[1])
    result = []
    while monday <= last:
        result.append(monday)
        monday += timedelta(days=7)
    return result[-4:] if len(result) > 4 else result


def planned_week():
    return current_week_start() + timedelta(days=7)


def selected_week():
    """Неделя, выбранная пользователем (?week=YYYY-MM-DD — любая дата недели).
    По умолчанию — текущая отчётная неделя."""
    raw = request.values.get('week', '')
    try:
        d = date.fromisoformat(raw)
        return d - timedelta(days=d.weekday())
    except ValueError:
        return current_week_start()


# ---------- Аутентификация ----------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm', '')
        if not username or not password:
            flash('Логин и пароль обязательны.', 'danger')
        elif password != confirm:
            flash('Пароли не совпадают.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Такой логин уже занят.', 'danger')
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Регистрация успешна. Войдите в систему.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash('Неверный логин или пароль.', 'danger')
        elif not user.active:
            flash('Учётная запись заблокирована.', 'danger')
        else:
            login_user(user)
            return redirect(url_for('dashboard'))
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ---------- Кабинет пользователя: факт и план ----------

@app.route('/')
@login_required
def dashboard():
    fact_week = selected_week()
    plan_week = fact_week + timedelta(days=7)
    fact_entries = (Participation.query
                    .filter_by(user_id=current_user.id, week_start=fact_week,
                               kind='fact')
                    .join(Project).order_by(Project.name).all())
    plan_entries = (Participation.query
                    .filter_by(user_id=current_user.id, week_start=plan_week,
                               kind='plan')
                    .join(Project).order_by(Project.name).all())
    projects = Project.query.filter_by(active=True).order_by(Project.name).all()
    return render_template(
        'dashboard.html',
        fact_entries=fact_entries, plan_entries=plan_entries, projects=projects,
        fact_used={e.project_id for e in fact_entries},
        plan_used={e.project_id for e in plan_entries},
        fact_remaining=sum(e.percent for e in fact_entries),
        plan_remaining=sum(e.percent for e in plan_entries),
        fact_week=fact_week, plan_week=plan_week,
        fact_week_end=fact_week + timedelta(days=6),
        plan_week_end=plan_week + timedelta(days=6),
        week=fact_week.isoformat(),
        prev_week=(fact_week - timedelta(days=7)).isoformat(),
        next_week=(fact_week + timedelta(days=7)).isoformat())


def _save_entry(user_id, project_id, percent, kind, fact_week):
    """Общая валидация и upsert записи. Возвращает (ok, message, category)."""
    week = fact_week if kind == 'fact' else fact_week + timedelta(days=7)
    project = db.session.get(Project, project_id) if project_id else None
    if project is None or not project.active:
        return False, 'Проект не найден.', 'danger'
    if percent is None or not (0 < percent <= 100):
        return False, 'Процент должен быть от 1 до 100.', 'danger'
    entry = Participation.query.filter_by(
        user_id=user_id, project_id=project.id, week_start=week, kind=kind).first()
    others = sum(e.percent for e in Participation.query.filter_by(
        user_id=user_id, week_start=week, kind=kind).all()
        if not entry or e.id != entry.id)
    if others + percent > 100:
        return False, (f'Сумма {KIND_LABELS[kind]}а по неделе не может превышать '
                       f'100% (уже занято {others}%).'), 'danger'
    if entry:
        entry.percent = percent
        action = 'Обновлено'
    else:
        db.session.add(Participation(user_id=user_id, project_id=project.id,
                                     week_start=week, kind=kind, percent=percent))
        action = 'Добавлено'
    db.session.commit()
    return True, f'{action}: {project.name} — {percent}% ({KIND_LABELS[kind]}).', 'success'


@app.route('/fact/copy', methods=['POST'])
@login_required
def copy_fact():
    """Копирование плана выбранной недели в её факт (для себя)."""
    week = selected_week()
    count, skipped = _copy_plan_to_fact(current_user.id, week)
    msg = f'Скопировано из плана в факт: {count}.'
    if skipped:
        msg += f' Пропущено: {skipped} (уже есть или превысило бы 100%).'
    flash(msg, 'info')
    return redirect(url_for('dashboard', week=week.isoformat()))


@app.route('/entries', methods=['POST'])
@login_required
def add_entry():
    week = selected_week()
    ok, msg, cat = _save_entry(current_user.id,
                               request.form.get('project_id', type=int),
                               request.form.get('percent', type=int), 'fact', week)
    flash(msg, cat)
    return redirect(url_for('dashboard', week=week.isoformat()))


@app.route('/plan', methods=['POST'])
@login_required
def add_plan():
    week = selected_week()
    ok, msg, cat = _save_entry(current_user.id,
                               request.form.get('project_id', type=int),
                               request.form.get('percent', type=int), 'plan', week)
    flash(msg, cat)
    return redirect(url_for('dashboard', week=week.isoformat()))


@app.route('/plan/copy', methods=['POST'])
@login_required
def copy_plan():
    """Копирование факта выбранной недели в план следующей (для себя)."""
    week = selected_week()
    count = _copy_fact_to_plan(current_user.id, week)
    flash(f'Скопировано записей: {count}. Уже существующие не тронуты.', 'info')
    return redirect(url_for('dashboard', week=week.isoformat()))


def _copy_fact_to_plan(user_id, fact_week):
    plan_week = fact_week + timedelta(days=7)
    facts = Participation.query.filter_by(user_id=user_id, week_start=fact_week,
                                          kind='fact').all()
    count = 0
    for f in facts:
        exists = Participation.query.filter_by(
            user_id=user_id, project_id=f.project_id,
            week_start=plan_week, kind='plan').first()
        if not exists:
            db.session.add(Participation(user_id=user_id, project_id=f.project_id,
                                         week_start=plan_week, kind='plan',
                                         percent=f.percent))
            count += 1
    db.session.commit()
    return count


def _copy_plan_to_fact(user_id, week):
    """Копирование плана текущей (отчётной) недели в её факт.

    План недели заполнялся ранее (когда она была «следующей»),
    поэтому ищем записи kind='plan' с week_start = понедельник выбранной недели.
    """
    plans = Participation.query.filter_by(user_id=user_id, week_start=week,
                                          kind='plan').all()
    count, skipped = 0, 0
    for pl in plans:
        exists = Participation.query.filter_by(
            user_id=user_id, project_id=pl.project_id,
            week_start=week, kind='fact').first()
        if exists:
            skipped += 1
            continue
        used = sum(e.percent for e in Participation.query.filter_by(
            user_id=user_id, week_start=week, kind='fact').all())
        if used + pl.percent > 100:
            skipped += 1  # превысило бы 100% — пропускаем
            continue
        db.session.add(Participation(user_id=user_id, project_id=pl.project_id,
                                     week_start=week, kind='fact',
                                     percent=pl.percent))
        count += 1
    db.session.commit()
    return count, skipped


@app.route('/entries/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    entry = db.session.get(Participation, entry_id)
    if entry is None or entry.user_id != current_user.id:
        abort(403)
    db.session.delete(entry)
    db.session.commit()
    flash('Запись удалена.', 'info')
    return redirect(url_for('dashboard', week=request.form.get('week', '')))


# ---------- Сводная информация ----------

@app.route('/summary')
@login_required
def summary():
    fact_week = selected_week()
    plan_week = fact_week + timedelta(days=7)
    entries = Participation.query.filter(
        Participation.week_start.in_([fact_week, plan_week])).all()
    matrix = {}
    for e in entries:
        cell = matrix.setdefault((e.user_id, e.project_id), {})
        if e.week_start == fact_week and e.kind == 'fact':
            cell['fact'] = e
        elif e.week_start == plan_week and e.kind == 'plan':
            cell['plan'] = e
    users = User.query.filter_by(active=True).order_by(User.username).all()
    projects = Project.query.filter_by(active=True).order_by(Project.name).all()
    fact_totals = {u.id: 0 for u in users}
    plan_totals = {u.id: 0 for u in users}
    for (uid, pid), cell in matrix.items():
        if 'fact' in cell:
            fact_totals[uid] = fact_totals.get(uid, 0) + cell['fact'].percent
        if 'plan' in cell:
            plan_totals[uid] = plan_totals.get(uid, 0) + cell['plan'].percent
    return render_template('summary.html', users=users, projects=projects,
                           matrix=matrix, fact_totals=fact_totals,
                           plan_totals=plan_totals, fact_week=fact_week,
                           fact_week_end=fact_week + timedelta(days=6),
                           plan_week=plan_week,
                           plan_week_end=plan_week + timedelta(days=6),
                           week=fact_week.isoformat(),
                           prev_week=(fact_week - timedelta(days=7)).isoformat(),
                           next_week=(fact_week + timedelta(days=7)).isoformat())


@app.route('/admin/fact/copy', methods=['POST'])
@admin_required
def admin_copy_fact():
    """Админ копирует план текущей недели в её факт за выбранного пользователя."""
    user = db.session.get(User, request.form.get('user_id', type=int) or 0)
    week = selected_week()
    if user is None:
        flash('Пользователь не найден.', 'danger')
    else:
        count, skipped = _copy_plan_to_fact(user.id, week)
        msg = f'{user.username}: скопировано из плана в факт — {count}.'
        if skipped:
            msg += f' Пропущено: {skipped}.'
        flash(msg, 'info')
    return redirect(url_for('summary', week=week.isoformat()))


@app.route('/admin/entries', methods=['POST'])
@admin_required
def admin_add_entry():
    """Админ вводит/меняет факт или план за любого пользователя."""
    kind = request.form.get('kind', 'fact')
    if kind not in KIND_LABELS:
        kind = 'fact'
    user = db.session.get(User, request.form.get('user_id', type=int) or 0)
    week = selected_week()
    if user is None:
        flash('Пользователь не найден.', 'danger')
    else:
        ok, msg, cat = _save_entry(user.id,
                                   request.form.get('project_id', type=int),
                                   request.form.get('percent', type=int), kind, week)
        flash(f'{user.username}: {msg}', cat)
    return redirect(url_for('summary', week=week.isoformat()))


@app.route('/admin/plan/copy', methods=['POST'])
@admin_required
def admin_copy_plan():
    """Админ копирует факт выбранной недели в план следующей за выбранного пользователя."""
    user = db.session.get(User, request.form.get('user_id', type=int) or 0)
    week = selected_week()
    if user is None:
        flash('Пользователь не найден.', 'danger')
    else:
        count = _copy_fact_to_plan(user.id, week)
        flash(f'{user.username}: скопировано записей — {count}.', 'info')
    return redirect(url_for('summary', week=week.isoformat()))


@app.route('/admin/entries/<int:entry_id>/delete', methods=['POST'])
@admin_required
def admin_delete_entry(entry_id):
    entry = db.session.get(Participation, entry_id) or abort(404)
    db.session.delete(entry)
    db.session.commit()
    flash('Запись удалена.', 'info')
    return redirect(url_for('summary', week=request.form.get('week', '')))


# ---------- Помесячный факт ----------

def _parse_month(raw):
    try:
        year, month = map(int, raw.split('-'))
        assert 1 <= month <= 12
        return year, month
    except (ValueError, AssertionError):
        today = date.today()
        return today.year, today.month


def _monthly_data(year, month):
    """Средняя занятость по факту (4 последние недели месяца, пропуски = 0)."""
    weeks = month_mondays(year, month)
    entries = (Participation.query
               .filter(Participation.kind == 'fact',
                       Participation.week_start.in_(weeks)).all())
    sums = {}
    for e in entries:
        key = (e.user_id, e.project_id)
        sums[key] = sums.get(key, 0) + e.percent
    avg = {k: round(v / 4) for k, v in sums.items()}
    users = User.query.filter_by(active=True).order_by(User.username).all()
    projects = Project.query.filter_by(active=True).order_by(Project.name).all()
    return users, projects, avg, weeks


@app.route('/monthly')
@login_required
def monthly():
    year, month = _parse_month(request.args.get('month', ''))
    users, projects, avg, weeks = _monthly_data(year, month)
    prev_month = date(year, month, 1) - timedelta(days=1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return render_template('monthly.html', users=users, projects=projects,
                           avg=avg, weeks=weeks, year=year, month=month,
                           month_name=MONTH_NAMES[month - 1],
                           ym=f'{year:04d}-{month:02d}',
                           prev_ym=f'{prev_month.year:04d}-{prev_month.month:02d}',
                           next_ym=f'{next_month.year:04d}-{next_month.month:02d}')


@app.route('/monthly/export')
@login_required
def monthly_export():
    """Выгрузка помесячного факта в XLSX (нулевые значения — пустые ячейки)."""
    import openpyxl
    year, month = _parse_month(request.args.get('month', ''))
    users, projects, avg, weeks = _monthly_data(year, month)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Факт'
    ws.append(['Пользователь'] + [p.name for p in projects])
    for u in users:
        ws.append([u.username] + [(avg.get((u.id, p.id), 0) or None)
                                  for p in projects])
    ws.append([])
    ws.append(['Методика: среднее по факту за 4 последние недели месяца: '
               + ', '.join(w.strftime('%d.%m.%Y') for w in weeks)
               + '. Отсутствие данных = 0.'])
    for col in ws.columns:  # автоширина
        width = max(len(str(c.value)) if c.value is not None else 0
                    for c in col) + 2
        ws.column_dimensions[col[0].column_letter].width = min(width, 50)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return send_file(
        bio, as_attachment=True,
        download_name=f'fact_{year:04d}_{month:02d}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------- Админка: пользователи ----------

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.username).all()
    return render_template('admin/users.html', users=users)


@app.route('/admin/users/create', methods=['GET', 'POST'])
@admin_required
def admin_user_create():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_admin = bool(request.form.get('is_admin'))
        if not username or not password:
            flash('Логин и пароль обязательны.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Такой логин уже занят.', 'danger')
        else:
            user = User(username=username, is_admin=is_admin)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash('Пользователь создан.', 'success')
            return redirect(url_for('admin_users'))
    return render_template('admin/user_form.html', user=None)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_user_edit(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if request.method == 'POST':
        new_name = request.form.get('username', '').strip()
        taken = User.query.filter(User.username == new_name,
                                  User.id != user.id).first()
        if not new_name or taken:
            flash('Логин пустой или уже занят.', 'danger')
        else:
            user.username = new_name
            user.is_admin = bool(request.form.get('is_admin'))
            user.active = bool(request.form.get('active'))
            password = request.form.get('password', '')
            if password:
                user.set_password(password)
            db.session.commit()
            flash('Пользователь обновлён.', 'success')
            return redirect(url_for('admin_users'))
    return render_template('admin/user_form.html', user=user)


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_user_delete(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash('Нельзя удалить самого себя.', 'danger')
    else:
        db.session.delete(user)
        db.session.commit()
        flash('Пользователь удалён.', 'info')
    return redirect(url_for('admin_users'))


# ---------- Админка: проекты ----------

@app.route('/admin/projects')
@admin_required
def admin_projects():
    projects = Project.query.order_by(Project.name).all()
    return render_template('admin/projects.html', projects=projects)


@app.route('/admin/projects/create', methods=['GET', 'POST'])
@admin_required
def admin_project_create():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Название обязательно.', 'danger')
        elif Project.query.filter_by(name=name).first():
            flash('Проект с таким названием уже есть.', 'danger')
        else:
            db.session.add(Project(name=name,
                                   active=bool(request.form.get('active', True))))
            db.session.commit()
            flash('Проект создан.', 'success')
            return redirect(url_for('admin_projects'))
    return render_template('admin/project_form.html', project=None)


@app.route('/admin/projects/<int:project_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_project_edit(project_id):
    project = db.session.get(Project, project_id) or abort(404)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        taken = Project.query.filter(Project.name == name,
                                     Project.id != project.id).first()
        if not name or taken:
            flash('Название пустое или уже занято.', 'danger')
        else:
            project.name = name
            project.active = bool(request.form.get('active'))
            db.session.commit()
            flash('Проект обновлён.', 'success')
            return redirect(url_for('admin_projects'))
    return render_template('admin/project_form.html', project=project)


@app.route('/admin/projects/<int:project_id>/delete', methods=['POST'])
@admin_required
def admin_project_delete(project_id):
    project = db.session.get(Project, project_id) or abort(404)
    db.session.delete(project)
    db.session.commit()
    flash('Проект удалён вместе с записями участия.', 'info')
    return redirect(url_for('admin_projects'))


# ---------- Инициализация ----------

def init_db():
    """Создаёт таблицы и администратора при старте (и под gunicorn тоже)."""
    db.create_all()
    if not User.query.filter_by(is_admin=True).first():
        admin = User(username='admin', is_admin=True)
        admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin'))
        db.session.add(admin)
        db.session.commit()
        print('Создан администратор: admin (смените пароль!)')


with app.app_context():  # выполняется и при импорте gunicorn'ом
    init_db()

if __name__ == '__main__':
    app.run(debug=True)
