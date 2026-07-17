import os
import pytest
from datetime import date
from decimal import Decimal

# Set required env vars before any app imports (JWT_SECRET_KEY is now mandatory)
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-only")
os.environ.setdefault("ADMIN_PASSWORD", "admin123")
os.environ.setdefault("ACCOUNTANT_PASSWORD", "accountant1")
os.environ.setdefault("AUDITOR_PASSWORD", "auditor123")
# Prevent .env from downgrading cookie security during tests
os.environ.setdefault("ENVIRONMENT", "development")

# Pin DATABASE_URL to an absolute path so SessionLocal and backup/restore
# always target the test database regardless of CWD.
# Set PG_TEST_DATABASE_URL to run tests against PostgreSQL instead of SQLite.
# Example: PG_TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/testdb
_PG_TEST_URL = os.environ.get("PG_TEST_DATABASE_URL", "")
if _PG_TEST_URL:
    os.environ["DATABASE_URL"] = _PG_TEST_URL
    _TEST_DB_PATH = None
else:
    _TEST_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_financial.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# main.py's load_dotenv(override=True) clobbers test env vars with .env values.
# Re-assert test values so seed passwords match what tests hardcode.
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-only"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["ACCOUNTANT_PASSWORD"] = "accountant1"
os.environ["AUDITOR_PASSWORD"] = "auditor123"
os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
from app.rate_limit import get_limiter
from app.models.financial import (
    Ledger,
    Account,
    AccountType,
    AccountDirection,
    Voucher,
    VoucherEntry,
    VoucherStatus,
    AccountingPeriod,
    PeriodStatus,
    FixedAsset,
    Currency,
    ExchangeRate,
    VoucherNumberCounter,
    BusinessPartner,
    PartnerType,
    User,
    UserRole,
)
import bcrypt


if _PG_TEST_URL:
    from sqlalchemy.pool import NullPool
    engine = create_engine(_PG_TEST_URL, poolclass=NullPool)
else:
    engine = create_engine(f"sqlite:///{_TEST_DB_PATH}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_users(session):
    """Create default users for tests."""
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    accountant_password = os.environ.get("ACCOUNTANT_PASSWORD", "accountant1")
    auditor_password = os.environ.get("AUDITOR_PASSWORD", "auditor123")
    try:
        session.add_all([
            User(username="admin", hashed_password=bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode(), role=UserRole.ADMIN, is_active=True),
            User(username="accountant", hashed_password=bcrypt.hashpw(accountant_password.encode(), bcrypt.gensalt()).decode(), role=UserRole.ACCOUNTANT, is_active=True),
            User(username="auditor", hashed_password=bcrypt.hashpw(auditor_password.encode(), bcrypt.gensalt()).decode(), role=UserRole.AUDITOR, is_active=True),
        ])
        session.commit()
    except Exception:
        session.rollback()


@pytest.fixture(autouse=True)
def clean_db():
    """Recreate all tables and reset rate limiter before each test."""
    import gc as _gc
    import time as _time

    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
    get_limiter().reset()
    _gc.collect()
    engine.dispose()
    _time.sleep(0.15)  # ponytail: Windows needs time to release SQLite WAL file handles

    # Retry on Windows where SQLite WAL locks can linger
    for attempt in range(5):
        try:
            Base.metadata.drop_all(bind=engine)
            Base.metadata.create_all(bind=engine)
            break
        except Exception:
            if attempt == 4:
                raise
            _time.sleep(0.3 * (attempt + 1))
            _gc.collect()
            engine.dispose()

    session = TestingSessionLocal()
    try:
        _seed_users(session)
    finally:
        session.close()
    yield
    _gc.collect()
    engine.dispose()
    _time.sleep(0.05)
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception:
        pass  # ponytail: cleanup is best-effort, next setup recreates fresh


@pytest.fixture
def db():
    """Provide a clean DB session."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """FastAPI test client with overridden DB dependency and auto-auth."""
    from app.auth import get_current_user, CurrentUser

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return CurrentUser(id=1, username="admin", role="admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def ledger(db):
    """Create a test ledger with default accounts."""
    ledger = Ledger(
        name="Test Company",
        company_name="Test Corp",
        base_currency="CNY",
        start_year=2024,
        start_month=1,
    )
    db.add(ledger)
    db.commit()
    db.refresh(ledger)

    period = AccountingPeriod(
        ledger_id=ledger.id, year=2024, month=1, status=PeriodStatus.OPEN
    )
    db.add(period)
    db.commit()

    # Initialize chart of accounts
    accounts_data = [
        ("1001", "库存现金", AccountType.ASSET, AccountDirection.DEBIT),
        ("1002", "银行存款", AccountType.ASSET, AccountDirection.DEBIT),
        ("1122", "应收账款", AccountType.ASSET, AccountDirection.DEBIT),
        ("1123", "预付账款", AccountType.ASSET, AccountDirection.DEBIT),
        ("1405", "库存商品", AccountType.ASSET, AccountDirection.DEBIT),
        ("1601", "固定资产", AccountType.ASSET, AccountDirection.DEBIT),
        ("1602", "累计折旧", AccountType.ASSET, AccountDirection.CREDIT),
        ("2202", "应付账款", AccountType.LIABILITY, AccountDirection.CREDIT),
        ("2203", "预收账款", AccountType.LIABILITY, AccountDirection.CREDIT),
        ("2221", "应交税费", AccountType.LIABILITY, AccountDirection.CREDIT),
        ("4001", "实收资本", AccountType.EQUITY, AccountDirection.CREDIT),
        ("4103", "本年利润", AccountType.EQUITY, AccountDirection.CREDIT),
        ("4104", "利润分配", AccountType.EQUITY, AccountDirection.CREDIT),
        ("5001", "主营业务收入", AccountType.PROFIT_LOSS, AccountDirection.CREDIT),
        ("5401", "主营业务成本", AccountType.PROFIT_LOSS, AccountDirection.DEBIT),
        ("6601", "销售费用", AccountType.PROFIT_LOSS, AccountDirection.DEBIT),
        ("6602", "管理费用", AccountType.PROFIT_LOSS, AccountDirection.DEBIT),
        ("6603", "财务费用", AccountType.PROFIT_LOSS, AccountDirection.DEBIT),
        ("660303", "财务费用-汇兑损益", AccountType.PROFIT_LOSS, AccountDirection.DEBIT),
    ]
    for code, name, atype, adir in accounts_data:
        db.add(
            Account(
                ledger_id=ledger.id,
                code=code,
                name=name,
                account_type=atype,
                balance_direction=adir,
                opening_balance=0.00,
                is_active=True,
            )
        )
    db.commit()
    return ledger


@pytest.fixture
def ledger_id(ledger):
    return ledger.id


@pytest.fixture
def posted_voucher(db, ledger):
    """
    Create and post a simple voucher:
    Debit  1002 银行存款  100,000
    Credit 4001 实收资本  100,000
    """
    v = Voucher(
        ledger_id=ledger.id,
        voucher_number="记-1",
        voucher_date=date(2024, 1, 15),
        status=VoucherStatus.POSTED,
    )
    db.add(v)
    db.flush()

    bank = (
        db.query(Account)
        .filter(Account.ledger_id == ledger.id, Account.code == "1002")
        .first()
    )
    capital = (
        db.query(Account)
        .filter(Account.ledger_id == ledger.id, Account.code == "4001")
        .first()
    )

    db.add(
        VoucherEntry(
            voucher_id=v.id,
            account_id=bank.id,
            summary="收到投资款",
            direction=AccountDirection.DEBIT,
            amount=Decimal("100000.00"),
        )
    )
    db.add(
        VoucherEntry(
            voucher_id=v.id,
            account_id=capital.id,
            summary="实收资本",
            direction=AccountDirection.CREDIT,
            amount=Decimal("100000.00"),
        )
    )

    counter = VoucherNumberCounter(ledger_id=ledger.id, prefix="记-", current_number=1)
    db.add(counter)
    db.commit()
    db.refresh(v)
    return v


@pytest.fixture
def revenue_voucher(db, ledger):
    """
    Create and post a revenue voucher:
    Debit  1002 银行存款  50,000
    Credit 5001 主营业务收入 50,000
    """
    v = Voucher(
        ledger_id=ledger.id,
        voucher_number="记-2",
        voucher_date=date(2024, 1, 20),
        status=VoucherStatus.POSTED,
    )
    db.add(v)
    db.flush()

    bank = (
        db.query(Account)
        .filter(Account.ledger_id == ledger.id, Account.code == "1002")
        .first()
    )
    revenue = (
        db.query(Account)
        .filter(Account.ledger_id == ledger.id, Account.code == "5001")
        .first()
    )

    db.add(
        VoucherEntry(
            voucher_id=v.id,
            account_id=bank.id,
            summary="销售收款",
            direction=AccountDirection.DEBIT,
            amount=Decimal("50000.00"),
        )
    )
    db.add(
        VoucherEntry(
            voucher_id=v.id,
            account_id=revenue.id,
            summary="销售收入",
            direction=AccountDirection.CREDIT,
            amount=Decimal("50000.00"),
        )
    )

    db.commit()
    db.refresh(v)
    return v


@pytest.fixture
def expense_voucher(db, ledger):
    """
    Debit  6602 管理费用  5,000
    Credit 1002 银行存款  5,000
    """
    v = Voucher(
        ledger_id=ledger.id,
        voucher_number="记-3",
        voucher_date=date(2024, 1, 25),
        status=VoucherStatus.POSTED,
    )
    db.add(v)
    db.flush()

    admin_exp = (
        db.query(Account)
        .filter(Account.ledger_id == ledger.id, Account.code == "6602")
        .first()
    )
    bank = (
        db.query(Account)
        .filter(Account.ledger_id == ledger.id, Account.code == "1002")
        .first()
    )

    db.add(
        VoucherEntry(
            voucher_id=v.id,
            account_id=admin_exp.id,
            summary="支付办公费",
            direction=AccountDirection.DEBIT,
            amount=Decimal("5000.00"),
        )
    )
    db.add(
        VoucherEntry(
            voucher_id=v.id,
            account_id=bank.id,
            summary="支付办公费",
            direction=AccountDirection.CREDIT,
            amount=Decimal("5000.00"),
        )
    )
    db.commit()
    db.refresh(v)
    return v


@pytest.fixture
def auth_headers(client):
    """Return auth headers with a real JWT from the seeded admin user."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, f"auth_headers login failed: {resp.json()}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ledger_headers(ledger):
    """Headers with ledger_id."""
    return {"X-Ledger-Id": str(ledger.id)}
