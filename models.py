from datetime import date, timedelta

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    members = db.relationship('User', backref='group',
                              foreign_keys='User.group_id')

    @property
    def leader(self):
        return db.session.get(User, self.leader_id) if self.leader_id else None


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)  # legacy, = email
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)     # логин в систему
    name = db.Column(db.String(128))                                              # отображаемое имя
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_teamlead = db.Column(db.Boolean, nullable=False, default=False)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    participations = db.relationship('Participation',
                                     backref='user', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.active

    @property
    def display_name(self):
        return self.name or self.username

    @property
    def role_label(self):
        if self.is_admin:
            return 'администратор'
        if self.is_teamlead:
            return 'тимлид'
        return 'пользователь'


class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    participations = db.relationship('Participation',
                                     backref='project', cascade='all, delete-orphan')


class Participation(db.Model):
    __tablename__ = 'participations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False)
    week_start = db.Column(db.Date, nullable=False, index=True)  # понедельник недели
    kind = db.Column(db.String(8), nullable=False, default='fact')  # fact | plan
    percent = db.Column(db.Integer, nullable=False)               # 0..100
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint('user_id', 'project_id', 'week_start', 'kind',
                            name='uq_user_project_week_kind'),
    )


def current_week_start(today=None):
    """Понедельник текущей (отчётной) недели."""
    today = today or date.today()
    return today - timedelta(days=today.weekday())
