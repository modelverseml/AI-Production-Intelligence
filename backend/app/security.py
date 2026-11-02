from datetime import datetime, timedelta, timezone
import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

hasher = PasswordHash.recommended()
bearer = HTTPBearer()

def hash_password(password: str) ->str:
    return hasher.hash(password)

def verify_password(password :str, stored_hash :str) -> bool:
    return hasher.verify(password, stored_hash)

def create_token(user: User) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_MINUTES
    )

    return jwt.encode(
        {
            "sub" : str(user.id),
            "exp" : expiry,
            "type" : "access"
        },
        settings.JWT_SECRET,
        algorithm = settings.JWT_ALGORITHM
    )

def current_user(
        credentials : HTTPAuthorizationCredentials = Depends(bearer),
        db : Session = Depends(get_db)
)-> User :
    error = HTTPException(
        status_code = 401,
        detail = "Invalid or expired authentication token",
        headers = {"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms = [settings.JWT_ALGORITHM],
        )
        if payload.get("type") != 'access':
            raise error
        user_id = int(payload['sub'])
    except (InvalidTokenError, KeyError, ValueError):
        raise error

    # Role is read from the database on every request, so role changes
    # take effect immediately rather than trusting a stale JWT claim.
    user = db.get(User, user_id)
    if user is None:
        raise error
    return user

def require_roles(*roles):
    def check(user : User = Depends(current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code = 403,
                detail = "Insufficient permissions"
            )
        return user
    return check
