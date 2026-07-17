"""Seed default admin/accountant/auditor users if they don't exist.

Safe to run on every container start — only creates missing users.
Reads passwords from environment variables (ADMIN_PASSWORD, etc.).
Does NOT overwrite existing users (preserves password changes).

To force-reset all default users' passwords to the env values, run:
    python scripts/reset_passwords.py
"""
import os
import sys
import bcrypt
from dotenv import load_dotenv

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_ROOT)
load_dotenv(os.path.join(_BACKEND_ROOT, ".env"))

from app.database import SessionLocal
from app.models.financial import User, UserRole

session = SessionLocal()

# Read passwords from env; fall back to insecure defaults ONLY so the script
# doesn't crash on a fresh checkout — main.py will refuse to boot in production
# with these defaults.
default_users = [
    {"username": "admin", "password": os.environ.get("ADMIN_PASSWORD", "admin123"), "role": UserRole.ADMIN},
    {"username": "accountant", "password": os.environ.get("ACCOUNTANT_PASSWORD", "accountant1"), "role": UserRole.ACCOUNTANT},
    {"username": "auditor", "password": os.environ.get("AUDITOR_PASSWORD", "auditor123"), "role": UserRole.AUDITOR},
]

created = 0
for u in default_users:
    existing = session.query(User).filter(User.username == u["username"]).first()
    if not existing:
        session.add(User(
            username=u["username"],
            hashed_password=bcrypt.hashpw(u["password"].encode(), bcrypt.gensalt()).decode(),
            role=u["role"],
            is_active=True,
        ))
        created += 1

session.commit()
print(f"Seed users: {created} created, existing unchanged.")

for u in session.query(User).all():
    print(f"  {u.username} / {u.role.value} / active={u.is_active}")

session.close()
