from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.config import settings

_bearer = HTTPBearer()


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return credentials.credentials
