import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User
from app.demo import DEMO_ACCOUNTS
from sqlalchemy import inspect, text
from seed_demo import seed_database

app = create_app()


def auto_setup_enabled():
    return os.environ.get('AUTO_SETUP_DATABASE', '').lower() in {'1', 'true', 'yes', 'on'}


def setup_database_schema():
    # Keep this opt-in on Vercel. Running database DDL during every serverless
    # cold start makes even static assets wait on the database connection.
    with app.app_context():
        try:
            db.create_all()
            print("Database tables ensured")

            inspector = inspect(db.engine)
            user_columns = {column['name'] for column in inspector.get_columns('users')}

            with db.engine.connect() as conn:
                if 'is_approved' not in user_columns:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_approved BOOLEAN DEFAULT FALSE"))
                if db.engine.dialect.name == 'postgresql' and 'password_hash' in user_columns:
                    conn.execute(text("ALTER TABLE users ALTER COLUMN password_hash TYPE VARCHAR(255)"))
                conn.execute(text("UPDATE users SET is_approved = TRUE WHERE is_approved IS NULL"))
                conn.commit()
                print("Database schema patched")
        except Exception as e:
            print(f"Database setup warning: {e}")


def ensure_demo_data():
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            table_names = set(inspector.get_table_names())

            if 'users' not in table_names:
                db.create_all()
                seed_database(app)
                return

            demo_login = DEMO_ACCOUNTS[0]['login']
            admin = User.query.filter_by(email=demo_login).first()
            if not admin:
                seed_database(app)
        except Exception as e:
            print(f"Demo data setup warning: {e}")


if auto_setup_enabled():
    setup_database_schema()

if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
    ensure_demo_data()

# WSGI application for Vercel
application = app
