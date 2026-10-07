"""Pydantic models for invoice extraction.

Gemini's response_schema works best with plain types, so money is returned as a number
by the model and converted to Decimal-safe values by validators (rounded to 2 dp).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: Optional[str] = Field(None, description="Item or service description")
    quantity: Optional[float] = Field(None, description="Quantity; null if not printed")
    unit_price: Optional[float] = Field(None, description="Price per unit, as printed")
    amount: Optional[float] = Field(None, description="Line total as printed")
    hsn_code: Optional[str] = Field(None, description="HSN/SAC code as printed; null if not printed")
    gst_rate: Optional[float] = Field(None, description="GST rate % for this line (e.g. 18); null if not printed")


class Confidence(BaseModel):
    """Fixed keys (Gemini response_schema does not support free-form dicts)."""
    invoice_number: float = Field(1.0, ge=0, le=1)
    invoice_date: float = Field(1.0, ge=0, le=1)
    vendor_name: float = Field(1.0, ge=0, le=1)
    currency: float = Field(1.0, ge=0, le=1)
    total_amount: float = Field(1.0, ge=0, le=1)


class Invoice(BaseModel):
    invoice_number: Optional[str] = Field(None, description="Invoice number exactly as printed; null if absent")
    invoice_date: Optional[str] = Field(None, description="Issue date in ISO YYYY-MM-DD; null if absent or ambiguous")
    due_date: Optional[str] = Field(None, description="Due date in ISO YYYY-MM-DD; null if absent")
    vendor_name: Optional[str] = Field(None, description="Seller / issuer name")
    buyer_name: Optional[str] = Field(None, description="Buyer / bill-to name")
    currency: Optional[str] = Field(None, description="ISO 4217 code, e.g. INR, USD, EUR")
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Optional[float] = Field(None, description="Sum of lines before tax, as printed")
    tax_amount: Optional[float] = Field(None, description="Total tax as printed (all taxes combined)")
    total_amount: Optional[float] = Field(None, description="Grand total payable, as printed")
    vendor_gstin: Optional[str] = Field(None, description="Seller GSTIN exactly as printed (15 chars); null if absent")
    buyer_gstin: Optional[str] = Field(None, description="Buyer GSTIN exactly as printed; null if absent")
    vendor_pan: Optional[str] = Field(None, description="Seller PAN as printed; null if absent")
    cgst: Optional[float] = Field(None, description="CGST amount as printed; null if not printed")
    sgst: Optional[float] = Field(None, description="SGST amount as printed; null if not printed")
    igst: Optional[float] = Field(None, description="IGST amount as printed; null if not printed")
    confidence: Confidence = Field(
        default_factory=Confidence,
        description="Confidence 0-1 per key field. Use a low value (<0.8) when unsure, unreadable or ambiguous.",
    )


REQUIRED_FIELDS = ["invoice_number", "invoice_date", "vendor_name", "currency", "total_amount"]
CONFIDENCE_FIELDS = REQUIRED_FIELDS


class ExtractionResult(BaseModel):
    file: str
    status: Literal["ok", "needs_review", "failed"]
    invoice: Optional[Invoice] = None
    review_reasons: list[str] = Field(default_factory=list)
    attempts: int = 0
    error: Optional[str] = None
