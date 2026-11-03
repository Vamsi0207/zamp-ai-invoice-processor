from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Identifier = Annotated[str, Field(min_length=1, max_length=120)]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
Quantity = Annotated[int, Field(gt=0, le=1_000_000)]


def cents(value: Decimal) -> int:
    return int(value * 100)


class Vendor(Model):
    id: Identifier
    name: Identifier
    active: bool = True


class POLine(Model):
    id: Identifier
    description: Identifier
    quantity: Quantity
    unit_price: Money


class PurchaseOrder(Model):
    id: Identifier
    vendor_id: Identifier
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    total: Money
    tolerance_enabled: bool = False
    lines: Annotated[list[POLine], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def valid_lines(self):
        if len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("PO line IDs must be unique")
        if sum(line.quantity * line.unit_price for line in self.lines) > self.total:
            raise ValueError("PO total must cover line subtotal")
        return self


class Receipt(Model):
    id: Identifier
    po_id: Identifier
    po_line_id: Identifier
    quantity: Quantity


class InvoiceLine(Model):
    po_line_id: Identifier
    description: Identifier
    quantity: Quantity
    unit_price: Money


class Invoice(Model):
    vendor_id: Identifier
    number: Identifier
    po_id: Identifier | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    total: Money
    tax: Money = Decimal("0")
    shipping: Money = Decimal("0")
    discount: Money = Decimal("0")
    lines: Annotated[list[InvoiceLine], Field(min_length=1, max_length=200)]

    @field_validator("number")
    @classmethod
    def meaningful_number(cls, value):
        if not any(c.isalnum() for c in value):
            raise ValueError("invoice number must contain letters or digits")
        return value

    @model_validator(mode="after")
    def unique_lines(self):
        if len({line.po_line_id for line in self.lines}) != len(self.lines):
            raise ValueError("invoice PO line IDs must be unique")
        return self


class ProcessRequest(Model):
    idempotency_key: Identifier
