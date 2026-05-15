"""API request/response schemas."""

from typing import Optional

from pydantic import BaseModel

from app.domain.models import Bill


class AssignItemRequest(BaseModel):
    bill_id: str
    item_id: str
    person_name: str
    units: Optional[float] = None
    version: Optional[int] = None


class AddPersonRequest(BaseModel):
    bill_id: str
    person_name: str
    version: Optional[int] = None


class UpdateTipTaxRequest(BaseModel):
    bill_id: str
    tip_percent: Optional[float] = None
    tax: Optional[float] = None
    version: Optional[int] = None


class UpdateBillTitleRequest(BaseModel):
    bill_id: str
    title: str
    version: Optional[int] = None


class UpdateFintocUsernameRequest(BaseModel):
    bill_id: str
    fintoc_username: str
    version: Optional[int] = None


class CreateBillRequest(BaseModel):
    title: Optional[str] = None


class AddItemRequest(BaseModel):
    bill_id: str
    name: str
    price: float
    quantity: int = 1
    version: Optional[int] = None


class LockBillRequest(BaseModel):
    bill_id: str
    locked: bool
    version: Optional[int] = None


class MarkPaidRequest(BaseModel):
    bill_id: str
    person_name: str
    paid: bool
    version: Optional[int] = None


class JoinBillRequest(BaseModel):
    person_name: str


class SelfAssignRequest(BaseModel):
    person_name: str
    item_id: str
    assigned: bool
    units: float = 1.0


class SetBillStatusRequest(BaseModel):
    status: str
    version: Optional[int] = None


class SplitBillEquallyRequest(BaseModel):
    bill_id: str
    version: Optional[int] = None


class RestoreBillRequest(BaseModel):
    bill: Bill
    expected_version: int


class RequestMagicLinkBody(BaseModel):
    email: str


class ClaimBillBody(BaseModel):
    host_token: str


class ParticipantMarkPaidRequest(BaseModel):
    person_name: str
    paid: bool
