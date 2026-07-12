"""
Module d'authentification JWT email + mot de passe.
- Routes /api/auth : register, login, logout, me, refresh
- Helper get_current_user (à utiliser comme dépendance FastAPI sur les routes protégées)
- Seed admin idempotent au démarrage
- Protection brute force via collection login_attempts
"""
import os
import re
import bcrypt
import jwt
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from pydantic import BaseModel, EmailStr, Field
from bson import ObjectId
from typing import Optional

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = 60 * 24  # 24h
REFRESH_TOKEN_TTL_DAYS = 7
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, AttributeError):
        return False


def create_access_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def _set_auth_cookies(response: Response, access: str, refresh: str):
    # secure=True nécessaire pour SameSite=None en HTTPS (cross-origin preview)
    is_https = os.environ.get("FRONTEND_URL", "").startswith("https://")
    samesite = "none" if is_https else "lax"
    secure = is_https
    response.set_cookie(
        key="access_token", value=access, httponly=True,
        secure=secure, samesite=samesite, max_age=ACCESS_TOKEN_TTL_MINUTES * 60, path="/",
    )
    response.set_cookie(
        key="refresh_token", value=refresh, httponly=True,
        secure=secure, samesite=samesite, max_age=REFRESH_TOKEN_TTL_DAYS * 86400, path="/",
    )


def _clear_auth_cookies(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


class RegisterPayload(BaseModel):
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=6, max_length=200)
    name: Optional[str] = ""


class LoginPayload(BaseModel):
    email: str
    password: str


def _normalize_email(e: str) -> str:
    return (e or "").strip().lower()


def _validate_email(e: str):
    if not EMAIL_RE.match(e or ""):
        raise HTTPException(status_code=400, detail="Adresse email invalide")


def _user_to_public(u: dict) -> dict:
    return {
        "id": str(u["_id"]),
        "email": u["email"],
        "name": u.get("name") or "",
        "role": u.get("role") or "user",
        "created_at": u.get("created_at").isoformat() if isinstance(u.get("created_at"), datetime) else u.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Brute force
# ---------------------------------------------------------------------------
async def _check_brute_force(db, identifier: str):
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if not rec:
        return
    attempts = rec.get("attempts", 0)
    locked_until = rec.get("locked_until")
    if attempts >= MAX_FAILED_ATTEMPTS and locked_until and locked_until > datetime.now(timezone.utc):
        remaining = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60) + 1
        raise HTTPException(status_code=429, detail=f"Trop de tentatives. Réessayez dans {remaining} min.")


async def _record_failed_attempt(db, identifier: str):
    now = datetime.now(timezone.utc)
    rec = await db.login_attempts.find_one({"identifier": identifier})
    attempts = (rec.get("attempts") if rec else 0) + 1
    locked_until = now + timedelta(minutes=LOCKOUT_MINUTES) if attempts >= MAX_FAILED_ATTEMPTS else None
    await db.login_attempts.update_one(
        {"identifier": identifier},
        {"$set": {"attempts": attempts, "locked_until": locked_until, "updated_at": now}},
        upsert=True,
    )


async def _clear_attempts(db, identifier: str):
    await db.login_attempts.delete_one({"identifier": identifier})


# ---------------------------------------------------------------------------
# get_current_user dépendance
# ---------------------------------------------------------------------------
def make_get_current_user(db):
    async def get_current_user(request: Request) -> dict:
        token = request.cookies.get("access_token")
        if not token:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        if not token:
            raise HTTPException(status_code=401, detail="Non authentifié")
        try:
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
            if payload.get("type") != "access":
                raise HTTPException(status_code=401, detail="Type de token invalide")
            user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
            if not user:
                raise HTTPException(status_code=401, detail="Utilisateur introuvable")
            return user
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expiré")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Token invalide")

    return get_current_user


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
def build_auth_router(db) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])
    get_current_user = make_get_current_user(db)

    @router.post("/register")
    async def register(payload: RegisterPayload, response: Response):
        email = _normalize_email(payload.email)
        _validate_email(email)
        if await db.users.find_one({"email": email}):
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
        doc = {
            "email": email,
            "password_hash": hash_password(payload.password),
            "name": (payload.name or "").strip(),
            "role": "user",
            "created_at": datetime.now(timezone.utc),
        }
        res = await db.users.insert_one(doc)
        doc["_id"] = res.inserted_id
        user_id = str(res.inserted_id)
        access = create_access_token(user_id, email)
        refresh = create_refresh_token(user_id)
        _set_auth_cookies(response, access, refresh)
        return _user_to_public(doc)

    @router.post("/login")
    async def login(payload: LoginPayload, request: Request, response: Response):
        email = _normalize_email(payload.email)
        ip = request.client.host if request.client else "unknown"
        identifier = f"{ip}:{email}"
        await _check_brute_force(db, identifier)

        user = await db.users.find_one({"email": email})
        if not user or not user.get("password_hash") or not verify_password(payload.password, user["password_hash"]):
            await _record_failed_attempt(db, identifier)
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

        await _clear_attempts(db, identifier)
        user_id = str(user["_id"])
        access = create_access_token(user_id, email)
        refresh = create_refresh_token(user_id)
        _set_auth_cookies(response, access, refresh)
        return _user_to_public(user)

    @router.post("/logout")
    async def logout(response: Response):
        _clear_auth_cookies(response)
        return {"ok": True}

    @router.get("/me")
    async def me(user=Depends(get_current_user)):
        return _user_to_public(user)

    @router.post("/refresh")
    async def refresh(request: Request, response: Response):
        token = request.cookies.get("refresh_token")
        if not token:
            raise HTTPException(status_code=401, detail="Pas de refresh token")
        try:
            payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
            if payload.get("type") != "refresh":
                raise HTTPException(status_code=401, detail="Type de token invalide")
            user_id = payload["sub"]
            user = await db.users.find_one({"_id": ObjectId(user_id)})
            if not user:
                raise HTTPException(status_code=401, detail="Utilisateur introuvable")
            access = create_access_token(user_id, user["email"])
            # Ne pas régénérer le refresh, on garde l'existant
            is_https = os.environ.get("FRONTEND_URL", "").startswith("https://")
            response.set_cookie(
                key="access_token", value=access, httponly=True,
                secure=is_https, samesite="none" if is_https else "lax",
                max_age=ACCESS_TOKEN_TTL_MINUTES * 60, path="/",
            )
            return {"ok": True}
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Refresh token expiré")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Refresh token invalide")

    # ---- Récupération mot de passe -------------------------------------
    class ForgotPasswordPayload(BaseModel):
        email: str

    class ResetPasswordPayload(BaseModel):
        token: str
        password: str = Field(..., min_length=6, max_length=200)

    @router.post("/forgot-password")
    async def forgot_password(payload: ForgotPasswordPayload):
        """Génère un token de réinitialisation et le loggue dans la console serveur.
        Pour ne pas leaker quels emails existent, on renvoie toujours la même réponse.
        Limite : 1 demande / 60s / email."""
        import secrets as _secrets_local
        email = _normalize_email(payload.email)
        user = await db.users.find_one({"email": email})
        # Throttle
        recent = await db.password_reset_tokens.find_one({
            "email": email,
            "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(seconds=60)},
        })
        if user and not recent:
            token = _secrets_local.token_urlsafe(32)
            await db.password_reset_tokens.insert_one({
                "token": token,
                "email": email,
                "user_id": str(user["_id"]),
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
                "used": False,
            })
            base = os.environ.get("FRONTEND_URL", "").rstrip("/")
            reset_link = f"{base}/reset-password?token={token}" if base else f"/reset-password?token={token}"
            logger.info(
                "\n" + "=" * 60 +
                f"\n[PASSWORD RESET] Lien pour {email} :\n   {reset_link}\n"
                f"   (Valable 1h, à transmettre manuellement à l'utilisateur)\n"
                + "=" * 60
            )
        return {"ok": True, "message": "Si un compte existe pour cet email, un lien de réinitialisation a été généré."}

    @router.post("/reset-password")
    async def reset_password(payload: ResetPasswordPayload):
        rec = await db.password_reset_tokens.find_one({"token": payload.token, "used": False})
        if not rec:
            raise HTTPException(status_code=400, detail="Lien invalide ou déjà utilisé")
        expires_at = rec.get("expires_at")
        # Mongo retourne parfois des datetime naïfs ; on s'assure d'avoir un offset
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Lien expiré (1h max)")
        await db.users.update_one(
            {"_id": ObjectId(rec["user_id"])},
            {"$set": {"password_hash": hash_password(payload.password)}},
        )
        await db.password_reset_tokens.update_one(
            {"_id": rec["_id"]},
            {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
        )
        return {"ok": True, "message": "Mot de passe réinitialisé. Vous pouvez vous connecter."}

    return router


# ---------------------------------------------------------------------------
# Setup au démarrage
# ---------------------------------------------------------------------------
async def setup_auth(db):
    """À appeler au startup : crée les indexes + seed admin (idempotent)."""
    # Indexes
    await db.users.create_index("email", unique=True)
    await db.login_attempts.create_index("identifier")
    await db.datasets.create_index("user_id")
    await db.datasets.create_index("share_token", sparse=True)
    # TTL : Mongo supprime automatiquement les reset tokens expirés
    try:
        await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    except Exception:
        pass

    # Seed admin
    admin_email = _normalize_email(os.environ.get("ADMIN_EMAIL", "admin@example.com"))
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
        logger.info(f"Admin user seeded: {admin_email}")
    elif not verify_password(admin_password, existing.get("password_hash") or ""):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
        logger.info(f"Admin password updated: {admin_email}")

    # Seed super-admin (créateur de l'outil : accès à TOUS les phasages)
    super_email = _normalize_email(os.environ.get("SUPERADMIN_EMAIL", "") or "")
    super_password = os.environ.get("SUPERADMIN_PASSWORD", "") or ""
    if super_email and super_password:
        existing_su = await db.users.find_one({"email": super_email})
        if existing_su is None:
            await db.users.insert_one({
                "email": super_email,
                "password_hash": hash_password(super_password),
                "name": "Créateur",
                "role": "superadmin",
                "created_at": datetime.now(timezone.utc),
            })
            logger.info(f"Superadmin user seeded: {super_email}")
        else:
            updates = {}
            if not verify_password(super_password, existing_su.get("password_hash") or ""):
                updates["password_hash"] = hash_password(super_password)
            if existing_su.get("role") != "superadmin":
                updates["role"] = "superadmin"
            if updates:
                await db.users.update_one({"email": super_email}, {"$set": updates})
                logger.info(f"Superadmin refreshed: {super_email}")
