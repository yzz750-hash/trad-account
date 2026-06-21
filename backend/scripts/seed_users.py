"""Seed default admin/accountant/auditor users if they don't exist.
Safe to run on every container start — only creates missing users.
Does NOT overwrite existing users (preserves password changes).
"""
import bcrypt
from app.database import SessionLocal
from app.models.financial import User, UserRole

session = SessionLocal()

default_users = [
    {"username": "admin", "password": b"admin123", "role": UserRole.ADMIN},
    {"username": "accountant", "password": b"accountant1", "role": UserRole.ACCOUNTANT},
    {"username": "auditor", "password": b"auditor123", "role": UserRole.AUDITOR},
]

created = 0
for u in default_users:
    existing = session.query(User).filter(User.username == u["username"]).first()
    if not existing:
        session.add(User(
            username=u["username"],
            hashed_password=bcrypt.hashpw(u["password"], bcrypt.gensalt()).decode(),
            role=u["role"],
            is_active=True,
        ))
        created += 1

session.commit()
print(f"Seed users: {created} created, existing unchanged.")

for u in session.query(User).all():
    print(f"  {u.username} / {u.role.value} / active={u.is_active}")

session.close()
