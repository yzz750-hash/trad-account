"""Shared custom types for Pydantic schemas."""
from decimal import Decimal
from typing import Annotated
from pydantic import PlainSerializer, PlainValidator


def _to_decimal(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _round_money(v: Decimal) -> str:
    """Serialize Money as a string for financial precision in JSON API."""
    return f"{v:.2f}"


Money = Annotated[
    Decimal,
    PlainValidator(_to_decimal),
    PlainSerializer(_round_money, return_type=str),
]
