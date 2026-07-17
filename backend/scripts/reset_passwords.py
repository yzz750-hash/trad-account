"""Force-reset passwords of all default users to the values in .env.

Use this after changing ADMIN_PASSWORD / ACCOUNTANT_PASSWORD / AUDITOR_PASSWORD
in .env — seed_users.py only creates missing users and won't update existing ones.

Usage:
    cd backend
    .\\venv\\Scripts\\python.exe scripts\\reset_passwords.py
"""
import os
import sys
import bcrypt
from dotenv import load_dotenv

# Make the backend/ root importable (so `app.*` resolves) and load .env
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_ROOT)
load_dotenv(os.path.join(_BACKEND_ROOT, ".env"))

from app.database import SessionLocal
from app.models.financial import User, UserRole

session = SessionLocal()

targets = [
    {"username": "admin", "password": os.environ.get("ADMIN_PASSWORD", ""), "role": UserRole.ADMIN},
    {"username": "accountant", "password": os.environ.get("ACCOUNTANT_PASSWORD", ""), "role": UserRole.ACCOUNTANT},
    {"username": "auditor", "password": os.environ.get("AUDITOR_PASSWORD", ""), "role": UserRole.AUDITOR},
]

updated = 0
for t in targets:
    if not t["password"]:
        print(f"  SKIP {t['username']}: no password set in env")
        continue
    user = session.query(User).filter(User.username == t["username"]).first()
    new_hash = bcrypt.hashpw(t["password"].encode(), bcrypt.gensalt()).decode()
    if user:
        user.hashed_password = new_hash
        user.role = t["role"]
        user.is_active = True
        updated += 1
        print(f"  RESET {t['username']}: password updated")
    else:
        session.add(User(
            username=t["username"],
            hashed_password=new_hash,
            role=t["role"],
            is_active=True,
        ))
        updated += 1
        print(f"  CREATED {t['username']}: password set")

session.commit()
print(f"\nDone. {updated} users reset/created. Passwords sourced from .env")
session.close()
