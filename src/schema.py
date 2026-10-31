from typing import Optional
from pydantic import BaseModel, Field
from typing import Literal, Optional   


class Sourced(BaseModel):
    value: Optional[float] = None
    unit_as_written: Optional[str] = None   # e.g. "kg", "lb", "kN"
    source_quote: Optional[str] = None      # exact text it came from


class Stage(BaseModel):
    dry_mass_kg: Sourced = Field(default_factory=Sourced)
    propellant_mass_kg: Sourced = Field(default_factory=Sourced)
    isp_vac_s: Sourced = Field(default_factory=Sourced)
    isp_sl_s: Sourced = Field(default_factory=Sourced)
    thrust_vac_n: Sourced = Field(default_factory=Sourced)
    thrust_sl_n: Sourced = Field(default_factory=Sourced)


class RocketSpec(BaseModel):
    name: str
    variant: Optional[str] = None
    stages: list[Stage]
    published_reference: dict = Field(default_factory=dict)  # eval only, never fed to physics
    ambiguities: list[str] = Field(default_factory=list)

class MissionRequest(BaseModel):
    payload_kg: Optional[float] = None
    destination: Literal["LEO", "ISS", "GTO", "TLI", "Moon", "Mars", "unknown"] = "unknown"
    vehicle_name: Optional[str] = None
    missing_fields: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)


class Mission(BaseModel):
    request: MissionRequest
    rocket: RocketSpec
    blocking_issues: list[str] = Field(default_factory=list)