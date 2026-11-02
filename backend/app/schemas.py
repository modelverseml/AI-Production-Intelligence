from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, ConfigDict, Field

Role = Literal["viewer", "analyst", "admin"]

class RegisterRequest(BaseModel):
    email : EmailStr
    password : str = Field(min_length = 10)

class LoginRequest(BaseModel):
    email : EmailStr
    password : str

class RoleUpdate(BaseModel):
    role : Role

class UserOut(BaseModel):
    id : int
    email : str
    role : str
    model_config = ConfigDict(from_attributes = True)

class ServiceOut(BaseModel):
    id : int
    name : str
    dependencies : list[str]
    model_config = ConfigDict(from_attributes = True)

class IncidentSummary(BaseModel):
    id : int
    title : str
    severity : str
    service_id : int
    system : str | None
    created_at : datetime
    investigations : int = 0
    latest_prediction : str | None = None
    latest_method : str | None = None
    latest_correct : bool | None = None

    model_config = ConfigDict(from_attributes = True)

class IncidentOut(BaseModel):
    id : int
    title : str
    description : str
    severity : str
    service_id : int
    logs : list[str]
    metrics : dict
    root_cause : str
    system : str | None
    created_at : datetime

    model_config = ConfigDict(from_attributes = True)

class InvestigationOut(BaseModel):
    id : int
    incident_id : int
    user_id : int
    predicted_cause : str
    method : str
    confidence : float
    explanation : str
    evidence : list[dict]
    report : dict
    verification : dict
    trace : list[dict]
    usage : dict
    created_at : datetime

    model_config = ConfigDict(from_attributes = True)
