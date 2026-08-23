import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

ALGORITHM = "HS256"
JWT_ISSUER = "kiani-exchange"
USER_AUDIENCE = "kiani-user"

pwd_context = CryptContext(schemes=["bcrypt", "sha256_crypt"], deprecated="auto")
security = HTTPBearer()


def get_jwt_secret() -> str:
    """Return the server-side JWT secret.

    There is intentionally no source-code fallback. Production must provide a
    strong JWT_SECRET_KEY in the backend environment.
    """
    secret = os.getenv("JWT_SECRET_KEY", "").strip()
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET_KEY must be configured with at least 32 characters")
    return secret


def get_access_token_expire_hours() -> int:
    raw = os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "4").strip()
    try:
        hours = int(raw)
    except ValueError as exc:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_HOURS must be an integer") from exc
    if not 1 <= hours <= 168:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_HOURS must be between 1 and 168")
    return hours


def validate_auth_config() -> None:
    """Fail fast at application startup when auth configuration is unsafe."""
    get_jwt_secret()
    get_access_token_expire_hours()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=get_access_token_expire_hours())
    to_encode = {
        **data,
        "token_type": "user",
        "iss": JWT_ISSUER,
        "aud": USER_AUDIENCE,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(to_encode, get_jwt_secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=[ALGORITHM],
            audience=USER_AUDIENCE,
            issuer=JWT_ISSUER,
        )
        if payload.get("token_type") != "user":
            raise JWTError("wrong token type")
        return payload
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
