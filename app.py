import os
from datetime import timedelta

from flask import (Flask, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)

from models import Project, Participation, User, current_week_start, db

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Для доступа войдите в систему.'


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


# ---------- Кабинет пользователя ----------

@app.route('/')
@login_required
def dashboard():
    week_start = current_week_start()
    week_end = week_start + timedelta(days=6)
    entries = (Participation.query
               .filter_by(user_id=current_user.id, week_start=week_start)
               .join(Project)
               .order_by(Project.name)
               .all())
    projects = Project.query.filter_by(active=True).order_by(Project.name).all()
    used_ids = {e.project_id for e in entries}
    remaining = sum(e.percent for e in entries)
    return render_template('dashboard.html', entries=entries, projects=projects,
                           used_ids=used_ids, remaining=remaining,
                           week_start=week_start, week_end=week_end)


@app.route('/entries', methods=['POST'])
@login_required
def add_entry():
    week_start = current_week_start()
    project_id = request.form.get('project_id', type=int)
    percent = request.form.get('percent', type=int)
    project = db.session.get(Project, project_id) if project_id else None

    if project is None or not project.active:
        flash('Проект не найден.', 'danger')
    elif percent is None or not (0 < percent <= 100):
        flash('Процент должен быть от 1 до 100.', 'danger')
    else:
        exists = Participation.query.filter_by(
            user_id=current_user.id, project_id=project.id,
            week_start=week_start).first()
        if exists:
            flash('По этому проекту запись уже есть — удалите её, чтобы изменить.', 'warning')
        else:
            used = sum(e.percent for e in Participation.query.filter_by(
                user_id=current_user.id, week_start=week_start).all())
            if used + percent > 100:
                flash(f'Сумма по неделе не может превышать 100% '
                      f'(уже занято {used}%).', 'danger')
            else:
                db.session.add(Participation(user_id=current_user.id,
                                             project_id=project.id,
                                             week_start=week_start,
                                             percent=percent))
                db.session.commit()
                flash(f'Добавлено: {project.name} — {percent}%.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/entries/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    entry = db.session.get(Participation, entry_id)
    if entry is None or entry.user_id != current_user.id:
        abort(403)
    db.session.delete(entry)
    db.session.commit()
    flash('Запись удалена.', 'info')
    return redirect(url_for('dashboard'))


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
    db.create_all()
    if not User.query.filter_by(is_admin=True).first():
        admin = User(username='admin', is_admin=True)
        admin.set_password(os.environ.get('ADMIN_PASSWORD', 'admin'))
        db.session.add(admin)
        db.session.commit()
        print('Создан администратор: admin / admin (смените пароль!)')


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
