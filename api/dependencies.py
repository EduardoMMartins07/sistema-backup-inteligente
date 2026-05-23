from fastapi import Depends, Header, HTTPException, Request, status
from jwt import InvalidTokenError
from sqlite3 import Connection

from api.database import get_db
from api.security import decode_access_token
from api.services import get_user_by_id


def extract_bearer_token(authorization):
    if not authorization:
        return None

    prefix = "Bearer "

    if not authorization.startswith(prefix):
        return None

    return authorization[len(prefix):].strip()


def current_user_from_token(db: Connection, token: str):
    try:
        payload = decode_access_token(token)
    except InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido ou expirado.",
        ) from error

    user_id = payload.get("userId") or payload.get("sub")
    company_id = payload.get("companyId")
    user = get_user_by_id(db, user_id, company_id=company_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario autenticado nao encontrado.",
        )

    return user


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Connection = Depends(get_db),
):
    token = extract_bearer_token(authorization) or request.cookies.get("smartbackup_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticacao obrigatoria.",
        )

    return current_user_from_token(db, token)


def require_roles(roles):
    allowed = set(roles)

    def dependency(current_user=Depends(get_current_user)):
        if current_user["role"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Perfil sem permissao para esta acao.",
            )

        return current_user

    return dependency

