from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import require_write
from app.routers.ledgers import get_ledger_id
from app.models.financial import BusinessPartner, PartnerType
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class PartnerSchema(BaseModel):
    id: int
    code: str
    name: str
    partner_type: str
    model_config = ConfigDict(from_attributes=True)


class PartnerCreate(BaseModel):
    code: str
    name: str
    partner_type: str


class PartnerUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


@router.get("/", response_model=list[PartnerSchema])
def get_partners(db: Session = Depends(get_db), ledger_id: int = Depends(get_ledger_id)):
    partners = db.query(BusinessPartner).filter(
        BusinessPartner.ledger_id == ledger_id,
        BusinessPartner.is_active == True,
    ).all()
    return [PartnerSchema.model_validate(p) for p in partners]


@router.post("/", response_model=PartnerSchema)
def create_partner(
    partner: PartnerCreate,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    _: None = Depends(require_write),
):
    existing = db.query(BusinessPartner).filter(
        BusinessPartner.ledger_id == ledger_id,
        BusinessPartner.code == partner.code,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Partner code already exists.")

    try:
        p_type = PartnerType(partner.partner_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid partner_type: {partner.partner_type}. Valid values: CUSTOMER, VENDOR, BOTH",
        )

    new_p = BusinessPartner(
        ledger_id=ledger_id,
        code=partner.code,
        name=partner.name,
        partner_type=p_type,
    )
    db.add(new_p)
    db.commit()
    db.refresh(new_p)
    return PartnerSchema.model_validate(new_p)


@router.put("/{partner_id}", response_model=PartnerSchema)
def update_partner(
    partner_id: int,
    data: PartnerUpdate,
    db: Session = Depends(get_db),
    ledger_id: int = Depends(get_ledger_id),
    _: None = Depends(require_write),
):
    p = db.query(BusinessPartner).filter(
        BusinessPartner.ledger_id == ledger_id,
        BusinessPartner.id == partner_id,
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partner not found.")

    if data.name is not None:
        p.name = data.name
    if data.is_active is not None:
        p.is_active = data.is_active

    db.commit()
    db.refresh(p)
    return PartnerSchema.model_validate(p)