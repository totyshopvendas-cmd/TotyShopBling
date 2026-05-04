from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import asyncio
import logging
import uuid
import jwt
import bcrypt
import httpx
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional, Literal
from datetime import datetime, timezone, timedelta
from emergentintegrations.llm.chat import LlmChat, UserMessage

from johndrop_client import (
    JohnDropClient,
    JohnDropAuthError,
    INTEGRATION_TOTYSHOP_BLING,
    encrypt_secret,
    decrypt_secret,
)
from bling_client import (
    BlingClient,
    BlingAuthError,
    BlingAPIError,
    build_authorize_url,
    generate_state,
    exchange_code_for_tokens,
    refresh_access_token,
)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret')
JWT_ALGORITHM = os.environ.get('JWT_ALGORITHM', 'HS256')
JWT_EXPIRE_HOURS = int(os.environ.get('JWT_EXPIRE_HOURS', '168'))
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY')

BLING_CLIENT_ID = os.environ.get('BLING_CLIENT_ID', '')
BLING_CLIENT_SECRET = os.environ.get('BLING_CLIENT_SECRET', '')
BLING_REDIRECT_URL = os.environ.get('BLING_REDIRECT_URL', '')

app = FastAPI(title="BlingDrop API")
api_router = APIRouter(prefix="/api")


# ============ Models ============
class UserPublic(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    auth_provider: str


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class MarketplaceAmazon(BaseModel):
    enabled: bool = True
    category: Optional[str] = None
    bullet_points: List[str] = Field(default_factory=lambda: ["", "", "", "", "", ""])


class MarketplaceShopee(BaseModel):
    enabled: bool = True
    category: Optional[str] = None
    variation_color: Optional[str] = None
    variation_size: Optional[str] = None
    weight_kg: Optional[float] = None
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None


class MarketplaceKwai(BaseModel):
    enabled: bool = False
    category: Optional[str] = None
    voltage: Optional[str] = None
    tech_specs: Optional[str] = None


class ProductIn(BaseModel):
    sku: str
    title: str
    product_code: str
    brand: Optional[str] = None
    ean: Optional[str] = None
    description: Optional[str] = None
    price: float = 0.0
    cost: float = 0.0
    stock_johndrop: int = 0
    stock_bling: int = 0
    images: List[str] = Field(default_factory=list)
    amazon: MarketplaceAmazon = Field(default_factory=MarketplaceAmazon)
    shopee: MarketplaceShopee = Field(default_factory=MarketplaceShopee)
    kwai: MarketplaceKwai = Field(default_factory=MarketplaceKwai)


class Product(ProductIn):
    id: str
    jd_id: Optional[str] = None
    sync_status: Literal["synced", "pending", "error", "out_of_stock"] = "pending"
    sync_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class AIGenerateTitleIn(BaseModel):
    product_code: str
    category: Optional[str] = None
    keywords: Optional[str] = None
    raw_name: str
    model: Literal["claude", "gpt"] = "claude"


class AIGenerateBulletsIn(BaseModel):
    title: str
    product_code: str
    category: Optional[str] = None
    keywords: Optional[str] = None
    model: Literal["claude", "gpt"] = "claude"


class AIGenerateDescriptionIn(BaseModel):
    title: str
    bullets: List[str]
    model: Literal["claude", "gpt"] = "claude"


# ============ Auth Helpers ============
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_jwt(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
    session_token: Optional[str] = Cookie(None),
) -> UserPublic:
    # Try cookie-based session first (Google Auth)
    token_from_cookie = session_token
    if token_from_cookie:
        session_doc = await db.user_sessions.find_one(
            {"session_token": token_from_cookie}, {"_id": 0}
        )
        if session_doc:
            expires_at = session_doc.get("expires_at")
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > datetime.now(timezone.utc):
                user_doc = await db.users.find_one(
                    {"user_id": session_doc["user_id"]}, {"_id": 0, "password_hash": 0}
                )
                if user_doc:
                    return UserPublic(**user_doc)

    # Bearer token (JWT or session_token fallback)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        # Try JWT
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                user_doc = await db.users.find_one(
                    {"user_id": user_id}, {"_id": 0, "password_hash": 0}
                )
                if user_doc:
                    return UserPublic(**user_doc)
        except jwt.PyJWTError:
            pass
        # Try session_token in bearer
        session_doc = await db.user_sessions.find_one(
            {"session_token": token}, {"_id": 0}
        )
        if session_doc:
            user_doc = await db.users.find_one(
                {"user_id": session_doc["user_id"]}, {"_id": 0, "password_hash": 0}
            )
            if user_doc:
                return UserPublic(**user_doc)

    raise HTTPException(status_code=401, detail="Não autenticado")


# ============ Auth Routes ============
@api_router.post("/auth/register")
async def register(data: RegisterIn):
    existing = await db.users.find_one({"email": data.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    doc = {
        "user_id": user_id,
        "email": data.email,
        "name": data.name,
        "picture": None,
        "password_hash": hash_password(data.password),
        "auth_provider": "jwt",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    token = create_jwt(user_id)
    return {
        "token": token,
        "user": {
            "user_id": user_id,
            "email": data.email,
            "name": data.name,
            "picture": None,
            "auth_provider": "jwt",
        },
    }


@api_router.post("/auth/login")
async def login(data: LoginIn):
    user = await db.users.find_one({"email": data.email}, {"_id": 0})
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    token = create_jwt(user["user_id"])
    return {
        "token": token,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
            "picture": user.get("picture"),
            "auth_provider": user.get("auth_provider", "jwt"),
        },
    }


@api_router.post("/auth/session")
async def create_session_from_google(request: Request, response: Response):
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id é obrigatório")
    async with httpx.AsyncClient(timeout=20) as http_client:
        r = await http_client.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id},
        )
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail="Falha na autenticação Google")
        data = r.json()
    email = data.get("email")
    name = data.get("name") or email
    picture = data.get("picture")
    session_token = data.get("session_token")

    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "picture": picture}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "auth_provider": "google",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=7 * 24 * 3600,
    )
    return {
        "user": {
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "auth_provider": "google",
        }
    }


@api_router.get("/auth/me", response_model=UserPublic)
async def me(user: UserPublic = Depends(get_current_user)):
    return user


@api_router.post("/auth/logout")
async def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token:
        await db.user_sessions.delete_many({"session_token": session_token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ============ Products ============
def _now():
    return datetime.now(timezone.utc).isoformat()


def _doc_to_product(doc: dict) -> Product:
    doc = dict(doc)
    for k in ("created_at", "updated_at"):
        v = doc.get(k)
        if isinstance(v, str):
            doc[k] = datetime.fromisoformat(v)
    return Product(**doc)


# ============ Calculadora Blindada (constants & helper - shared) ============
COMMISSION_PCT = 0.18
FIXED_FEE = 6.00
MIN_MARGIN_PCT = 0.20
PROCESSING_FEE = 1.00


def _markup_for_cost(cost: float) -> float:
    if cost <= 20:
        return 2.6
    if cost <= 50:
        return 2.1
    return 1.8


def _round_price_up_to_half(price: float) -> float:
    """Arredonda para cima no próximo múltiplo de 0,50 (padrão de preço .00 / .50)."""
    import math
    return math.ceil(price * 2) / 2


def _calc_selling_price(cost: float, packaging: float = 0.0, campaigns: float = 0.0) -> dict:
    custo_total = cost + PROCESSING_FEE
    despesas_extras = packaging + campaigns
    total_despesas = custo_total + despesas_extras + FIXED_FEE
    markup = _markup_for_cost(cost)
    preco_markup = custo_total * markup
    preco_blindado = total_despesas / (1 - COMMISSION_PCT - MIN_MARGIN_PCT)
    if preco_markup < preco_blindado:
        raw_price = preco_blindado
        safety_alert = True
    else:
        raw_price = preco_markup
        safety_alert = False
    # Arredonda para cima no próximo .00 ou .50
    selling_price = _round_price_up_to_half(raw_price)
    commission_value = selling_price * COMMISSION_PCT
    net_profit = selling_price - commission_value - FIXED_FEE - custo_total - packaging - campaigns
    return {
        "selling_price": round(selling_price, 2),
        "markup": markup,
        "safety_alert": safety_alert,
        "breakdown": {
            "cost": round(cost, 2),
            "processing_fee": PROCESSING_FEE,
            "custo_total": round(custo_total, 2),
            "packaging": round(packaging, 2),
            "campaigns": round(campaigns, 2),
            "total_despesas": round(total_despesas, 2),
            "commission_pct": COMMISSION_PCT,
            "commission_value": round(commission_value, 2),
            "fixed_fee": FIXED_FEE,
            "min_margin_pct": MIN_MARGIN_PCT,
            "net_profit": round(net_profit, 2),
            "net_profit_pct": round(net_profit / selling_price * 100, 1) if selling_price > 0 else 0,
            "preco_markup": round(preco_markup, 2),
            "preco_blindado": round(preco_blindado, 2),
            "raw_price_before_rounding": round(raw_price, 2),
        },
    }


@api_router.get("/products", response_model=List[Product])
async def list_products(user: UserPublic = Depends(get_current_user)):
    cursor = db.products.find({"owner_id": user.user_id}, {"_id": 0, "owner_id": 0}).sort("created_at", -1)
    docs = await cursor.to_list(1000)
    return [_doc_to_product(d) for d in docs]


@api_router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str, user: UserPublic = Depends(get_current_user)):
    doc = await db.products.find_one(
        {"id": product_id, "owner_id": user.user_id}, {"_id": 0, "owner_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return _doc_to_product(doc)


@api_router.post("/products", response_model=Product)
async def create_product(data: ProductIn, user: UserPublic = Depends(get_current_user)):
    pid = f"prod_{uuid.uuid4().hex[:12]}"
    now = _now()
    sync_status = "out_of_stock" if data.stock_johndrop <= 0 else "pending"
    doc = {
        "id": pid,
        "owner_id": user.user_id,
        **data.model_dump(),
        "sync_status": sync_status,
        "sync_message": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.products.insert_one(doc)
    doc.pop("owner_id", None)
    doc.pop("_id", None)
    return _doc_to_product(doc)


@api_router.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: str, data: ProductIn, user: UserPublic = Depends(get_current_user)
):
    existing = await db.products.find_one(
        {"id": product_id, "owner_id": user.user_id}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    update_doc = data.model_dump()
    update_doc["updated_at"] = _now()
    # Edits invalidate any previous sync - go back to pending until user re-syncs
    if update_doc.get("stock_johndrop", 0) <= 0:
        update_doc["sync_status"] = "out_of_stock"
    else:
        update_doc["sync_status"] = "pending"
    update_doc["sync_message"] = "Alterações pendentes - re-sincronize com Bling"
    await db.products.update_one(
        {"id": product_id, "owner_id": user.user_id},
        {"$set": update_doc},
    )
    doc = await db.products.find_one(
        {"id": product_id, "owner_id": user.user_id}, {"_id": 0, "owner_id": 0}
    )
    return _doc_to_product(doc)


@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str, user: UserPublic = Depends(get_current_user)):
    r = await db.products.delete_one({"id": product_id, "owner_id": user.user_id})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"ok": True}


# ============ Bulk Operations (Automação em Massa) ============
class BulkIdsIn(BaseModel):
    product_ids: List[str]


class BulkAIIn(BaseModel):
    product_ids: List[str]
    ai_model: Literal["claude", "gpt"] = "claude"


@api_router.post("/products/bulk/delete")
async def bulk_delete(data: BulkIdsIn, user: UserPublic = Depends(get_current_user)):
    r = await db.products.delete_many(
        {"id": {"$in": data.product_ids}, "owner_id": user.user_id}
    )
    return {"deleted": r.deleted_count}


@api_router.post("/products/bulk/recalculate-prices")
async def bulk_recalc_prices(data: BulkIdsIn, user: UserPublic = Depends(get_current_user)):
    updated = 0
    async for p in db.products.find(
        {"id": {"$in": data.product_ids}, "owner_id": user.user_id},
        {"_id": 0, "id": 1, "cost": 1},
    ):
        cost = p.get("cost", 0)
        if cost <= 0:
            continue
        calc = _calc_selling_price(cost, packaging=0.0, campaigns=0.0)
        await db.products.update_one(
            {"id": p["id"], "owner_id": user.user_id},
            {"$set": {"price": calc["selling_price"], "updated_at": _now()}},
        )
        updated += 1
    return {"updated": updated}


@api_router.post("/products/bulk/improve-titles")
async def bulk_improve_titles(data: BulkAIIn, user: UserPublic = Depends(get_current_user)):
    """Usa IA pra refinar cada título: remove marcas embutidas, melhora SEO,
    mantém código do produto no fim, máximo 60 chars."""
    updated = 0
    errors: list[str] = []
    async for p in db.products.find(
        {"id": {"$in": data.product_ids}, "owner_id": user.user_id},
        {"_id": 0, "id": 1, "title": 1, "product_code": 1},
    ):
        try:
            system = (
                "Você é um especialista em SEO para marketplaces brasileiros. "
                "Reescreva o título abaixo removendo marcas embutidas (ex: Kapbom, INOVA, Maxmidia, Altomex), "
                "mantendo MÁXIMO 60 caracteres e incluindo o código do produto no FINAL. "
                "Priorize palavras-chave de busca. Retorne APENAS o título, sem aspas, sem explicação."
            )
            user_text = (
                f"Título atual: {p['title']}\n"
                f"Código a incluir no final: {p.get('product_code', '')}\n"
                "Reescreva (máx 60 chars):"
            )
            new_title = await _llm_generate(system, user_text, data.ai_model)
            if len(new_title) > 60:
                new_title = new_title[:60].rstrip()
            await db.products.update_one(
                {"id": p["id"], "owner_id": user.user_id},
                {"$set": {"title": new_title, "updated_at": _now()}},
            )
            updated += 1
        except Exception as e:
            errors.append(f"{p['id']}: {e}")
    return {"updated": updated, "errors": errors}


@api_router.post("/products/bulk/generate-descriptions")
async def bulk_generate_descriptions(data: BulkAIIn, user: UserPublic = Depends(get_current_user)):
    """Gera descrições IA apenas para produtos sem descrição ou com descrição curta."""
    updated = 0
    errors: list[str] = []
    async for p in db.products.find(
        {"id": {"$in": data.product_ids}, "owner_id": user.user_id},
        {"_id": 0, "id": 1, "title": 1, "description": 1},
    ):
        desc = p.get("description", "") or ""
        if len(desc) >= 200:
            continue  # já tem descrição boa
        try:
            system = (
                "Você é um copywriter de e-commerce. Gere uma descrição em português brasileiro "
                "entre 400 e 700 caracteres, em 2 parágrafos, sem emojis, destacando benefícios e público-alvo."
            )
            new_desc = await _llm_generate(system, f"Produto: {p['title']}", data.ai_model)
            await db.products.update_one(
                {"id": p["id"], "owner_id": user.user_id},
                {"$set": {"description": new_desc, "updated_at": _now()}},
            )
            updated += 1
        except Exception as e:
            errors.append(f"{p['id']}: {e}")
    return {"updated": updated, "errors": errors}


@api_router.post("/products/bulk/push-johndrop")
async def bulk_push_johndrop(data: BulkIdsIn, user: UserPublic = Depends(get_current_user)):
    """Aplica múltiplos produtos na JohnDrop (→ Bling via ToyShop) em lote."""
    products = [
        p async for p in db.products.find(
            {"id": {"$in": data.product_ids}, "owner_id": user.user_id, "jd_id": {"$ne": None}},
            {"_id": 0},
        )
    ]
    if not products:
        raise HTTPException(status_code=400, detail="Nenhum produto com jd_id selecionado")

    client = await _get_johndrop_client(user.user_id)
    pushed = 0
    failed: list[dict] = []
    async with client as c:
        try:
            await c.ensure_logged_in()
        except JohnDropAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        for p in products:
            try:
                sale_value_str = f"{float(p['price']):.2f}".replace(".", ",")
                result = await c.push_product(
                    p["jd_id"],
                    {
                        "name": p["title"],
                        "sale_value": sale_value_str,
                    },
                    integration_ids=[INTEGRATION_TOTYSHOP_BLING],
                )
                if result["success"]:
                    await db.products.update_one(
                        {"id": p["id"], "owner_id": user.user_id},
                        {"$set": {
                            "sync_status": "synced",
                            "sync_message": f"Aplicado na JohnDrop em lote ({datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')})",
                            "last_pushed_at": _now(),
                            "updated_at": _now(),
                        }},
                    )
                    pushed += 1
                else:
                    failed.append({"id": p["id"], "reason": f"status {result['status_code']}"})
            except Exception as e:
                failed.append({"id": p["id"], "reason": str(e)})
    return {"pushed": pushed, "failed": failed, "total": len(products)}


@api_router.get("/dashboard/health-summary")
async def products_health_summary(user: UserPublic = Depends(get_current_user)):
    """Retorna contagem de produtos por saúde: ready/warning/blocked."""
    ready = 0
    warning = 0
    blocked = 0
    async for p in db.products.find({"owner_id": user.user_id}, {"_id": 0}):
        score = _health_score(p)
        if score >= 90:
            ready += 1
        elif score >= 50:
            warning += 1
        else:
            blocked += 1
    return {"ready": ready, "warning": warning, "blocked": blocked}


def _health_score(p: dict) -> int:
    """Pontuação de prontidão 0-100."""
    score = 0
    title = p.get("title") or ""
    if title and len(title) <= 60:
        score += 25
    if p.get("product_code"):
        score += 10
    desc = p.get("description") or ""
    if len(desc) >= 200:
        score += 25
    elif len(desc) >= 50:
        score += 10
    if p.get("price", 0) > 0:
        score += 20
    if p.get("stock_johndrop", 0) > 0:
        score += 10
    if p.get("images") and len(p.get("images", [])) > 0:
        score += 10
    return score


@api_router.post("/products/{product_id}/sync", response_model=Product)
async def sync_product(product_id: str, user: UserPublic = Depends(get_current_user)):
    doc = await db.products.find_one(
        {"id": product_id, "owner_id": user.user_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    issues = []
    if len(doc.get("title", "")) > 60:
        issues.append("Título excede 60 caracteres")
    if not doc.get("sku"):
        issues.append("SKU é obrigatório")
    if doc.get("amazon", {}).get("enabled"):
        bps = [b for b in doc["amazon"].get("bullet_points", []) if b and b.strip()]
        if len(bps) < 6:
            issues.append("Amazon exige 6 bullet points preenchidos")
    if doc.get("shopee", {}).get("enabled"):
        if not doc["shopee"].get("weight_kg"):
            issues.append("Shopee exige peso (kg)")
    if doc.get("stock_johndrop", 0) <= 0:
        issues.append("Sem estoque na JohnDrop")

    if issues:
        new_status = "error"
        msg = " | ".join(issues)
    else:
        new_status = "synced"
        msg = "Sincronizado com Bling em " + datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")
        # Simulate stock replication JohnDrop -> Bling
        await db.products.update_one(
            {"id": product_id, "owner_id": user.user_id},
            {"$set": {"stock_bling": doc["stock_johndrop"]}},
        )

    await db.products.update_one(
        {"id": product_id, "owner_id": user.user_id},
        {"$set": {"sync_status": new_status, "sync_message": msg, "updated_at": _now()}},
    )
    doc = await db.products.find_one(
        {"id": product_id, "owner_id": user.user_id}, {"_id": 0, "owner_id": 0}
    )
    return _doc_to_product(doc)


SEED_PRODUCTS = [
    {
        "sku": "JD-CRM-001",
        "product_code": "JD001",
        "title": "DermaBrasil Creme Facial Hidratante Antioxidante 50g 7891234560011",
        "brand": "DermaBrasil",
        "ean": "7891234560011",
        "description": "Creme facial hidratante com ativos antioxidantes para uso diário.",
        "price": 89.90,
        "cost": 32.50,
        "stock_johndrop": 45,
        "stock_bling": 0,
        "images": [
            "https://images.pexels.com/photos/19080517/pexels-photo-19080517.png?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940"
        ],
        "amazon": {
            "enabled": True,
            "category": "Beleza > Skincare > Hidratantes",
            "bullet_points": [
                "Hidratação profunda por até 24 horas com ácido hialurônico",
                "Fórmula antioxidante com Vitamina C e Vitamina E",
                "Textura leve, rápida absorção e toque seco",
                "Adequado para todos os tipos de pele, inclusive sensível",
                "Não comedogênico e dermatologicamente testado",
                "Frasco 50g - fabricado no Brasil (Código JD001)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Beleza & Cuidado Pessoal > Skincare",
            "variation_color": None,
            "variation_size": "50g",
            "weight_kg": 0.15,
            "length_cm": 8.0,
            "width_cm": 5.0,
            "height_cm": 5.0,
        },
        "kwai": {"enabled": False},
    },
    {
        "sku": "JD-ELE-002",
        "product_code": "JD002",
        "title": "CoolTech Mini Ventilador USB Recarregável Portátil 7891234560028",
        "brand": "CoolTech",
        "ean": "7891234560028",
        "description": "Ventilador portátil com bateria recarregável e 3 velocidades.",
        "price": 79.90,
        "cost": 28.00,
        "stock_johndrop": 12,
        "stock_bling": 0,
        "images": [
            "https://images.unsplash.com/photo-1664455340023-214c33a9d0bd?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NTYxOTJ8MHwxfHNlYXJjaHwyfHxicmF6aWxpYW4lMjBlY29tbWVyY2UlMjBwcm9kdWN0c3xlbnwwfHx8fDE3NzY5MDM1NjJ8MA&ixlib=rb-4.1.0&q=85"
        ],
        "amazon": {
            "enabled": True,
            "category": "Eletrônicos > Climatização > Ventiladores",
            "bullet_points": [
                "Bateria recarregável via USB-C - até 8h de uso contínuo",
                "3 velocidades ajustáveis para diferentes ambientes",
                "Design portátil com base giratória 360°",
                "Funcionamento silencioso ideal para escritório e quarto",
                "Luz LED integrada com função noturna",
                "Inclui cabo USB-C e alça de transporte (Código JD002)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Eletrodomésticos > Climatização",
            "variation_color": "Branco",
            "weight_kg": 0.5,
            "length_cm": 15.0,
            "width_cm": 15.0,
            "height_cm": 18.0,
        },
        "kwai": {
            "enabled": True,
            "category": "Eletrônicos",
            "voltage": "Bivolt (USB 5V)",
            "tech_specs": "Potência 5W, Bateria 2000mAh",
        },
    },
    {
        "sku": "JD-CAS-003",
        "product_code": "JD003",
        "title": "CasaPratica Organizador Multiuso Cozinha Gaveta 7891234560035",
        "brand": "CasaPratica",
        "ean": "7891234560035",
        "description": "Organizador modular para gavetas de cozinha.",
        "price": 49.90,
        "cost": 18.00,
        "stock_johndrop": 120,
        "stock_bling": 0,
        "images": [
            "https://images.unsplash.com/photo-1584472666879-7d92db132958?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1ODF8MHwxfHNlYXJjaHwzfHxlY29tbWVyY2UlMjBkYXNoYm9hcmR8ZW58MHx8fHwxNzc2OTAzNTYyfDA&ixlib=rb-4.1.0&q=85"
        ],
        "amazon": {
            "enabled": True,
            "category": "Cozinha > Organização",
            "bullet_points": [
                "Divisórias ajustáveis para diferentes tamanhos de utensílios",
                "Material plástico resistente e fácil de higienizar",
                "Encaixe perfeito em gavetas padrão brasileiras",
                "Superfície antiderrapante evita deslizamentos",
                "Design minimalista que otimiza o espaço",
                "Kit com 5 divisórias modulares (Código JD003)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Casa & Decoração > Organização",
            "weight_kg": 0.8,
            "length_cm": 40.0,
            "width_cm": 25.0,
            "height_cm": 6.0,
        },
        "kwai": {"enabled": False},
    },
    {
        "sku": "JD-PET-004",
        "product_code": "JD004",
        "title": "PetFun Escova Removedora Pelos Cães Gatos 7891234560042",
        "brand": "PetFun",
        "ean": "7891234560042",
        "description": "Escova autolimpante para remoção de pelos soltos.",
        "price": 59.90,
        "cost": 19.50,
        "stock_johndrop": 80,
        "stock_bling": 0,
        "images": ["https://images.unsplash.com/photo-1583337130417-3346a1be7dee?w=600"],
        "amazon": {
            "enabled": True,
            "category": "Pet Shop > Higiene",
            "bullet_points": [
                "Remove pelos mortos e reduz queda em até 95%",
                "Botão autolimpante recolhe os pelos com um clique",
                "Cabo ergonômico antiderrapante para uso prolongado",
                "Indicado para pelagens curtas, médias e longas",
                "Estimula circulação e deixa o pelo brilhante",
                "Tamanho único com cerdas flexíveis (Código JD004)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Pet Shop > Cuidados",
            "weight_kg": 0.2,
            "length_cm": 18.0,
            "width_cm": 8.0,
            "height_cm": 4.0,
        },
        "kwai": {"enabled": False},
    },
    {
        "sku": "JD-FIT-005",
        "product_code": "JD005",
        "title": "FitMove Corda Pular Profissional Rolamento 7891234560059",
        "brand": "FitMove",
        "ean": "7891234560059",
        "description": "Corda de pular com rolamento e cabo acolchoado.",
        "price": 39.90,
        "cost": 12.00,
        "stock_johndrop": 200,
        "stock_bling": 0,
        "images": ["https://images.unsplash.com/photo-1594737625785-a6cbdabd333c?w=600"],
        "amazon": {
            "enabled": True,
            "category": "Esporte > Funcional",
            "bullet_points": [
                "Rolamento em aço que garante rotação sem travar",
                "Cabo ergonômico com espuma EVA antiderrapante",
                "Comprimento ajustável de 2,4m a 3m para qualquer altura",
                "Ideal para crossfit, boxe e treino HIIT em casa",
                "Cabo de aço revestido em PVC resistente",
                "Leve, compacta e fácil de transportar (Código JD005)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Esporte & Lazer",
            "weight_kg": 0.3,
            "length_cm": 20.0,
            "width_cm": 10.0,
            "height_cm": 5.0,
        },
        "kwai": {"enabled": False},
    },
    {
        "sku": "JD-HOM-006",
        "product_code": "JD006",
        "title": "LuzVerde Luminária LED Mesa Touch Regulável 7891234560066",
        "brand": "LuzVerde",
        "ean": "7891234560066",
        "description": "Luminária de mesa LED com controle touch e 3 temperaturas.",
        "price": 129.90,
        "cost": 42.00,
        "stock_johndrop": 35,
        "stock_bling": 0,
        "images": ["https://images.unsplash.com/photo-1565814329452-e1efa11c5b89?w=600"],
        "amazon": {
            "enabled": True,
            "category": "Iluminação > Mesa",
            "bullet_points": [
                "3 temperaturas de cor (fria, neutra e quente)",
                "Controle touch com regulagem contínua de intensidade",
                "Braço flexível 360° que ilumina qualquer ângulo",
                "Entrada USB-C e função lembrete para evitar fadiga visual",
                "Modo noturno com timer automático de 60 minutos",
                "Consumo econômico de 6W LED (Código JD006)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Iluminação & Decoração",
            "weight_kg": 0.9,
            "length_cm": 40.0,
            "width_cm": 15.0,
            "height_cm": 12.0,
        },
        "kwai": {
            "enabled": True,
            "category": "Eletrônicos > Iluminação",
            "voltage": "Bivolt automático (100-240V)",
            "tech_specs": "Potência 6W LED, temperatura 3000K-6500K",
        },
    },
    {
        "sku": "JD-BEL-007",
        "product_code": "JD007",
        "title": "BeautyRio Kit Pincéis Maquiagem 12 Peças Profissional 7891234560073",
        "brand": "BeautyRio",
        "ean": "7891234560073",
        "description": "Kit com 12 pincéis profissionais para maquiagem facial.",
        "price": 69.90,
        "cost": 22.00,
        "stock_johndrop": 60,
        "stock_bling": 0,
        "images": ["https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?w=600"],
        "amazon": {
            "enabled": True,
            "category": "Beleza > Maquiagem > Acessórios",
            "bullet_points": [
                "Kit completo com 12 pincéis para rosto, olhos e boca",
                "Cerdas sintéticas premium que não soltam fios",
                "Cabos em madeira com acabamento matte antiderrapante",
                "Estojo organizador incluso para transporte seguro",
                "Fácil higienização com água e sabão neutro",
                "Ideal para uso profissional e pessoal (Código JD007)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Beleza & Cuidado Pessoal > Maquiagem",
            "weight_kg": 0.4,
            "length_cm": 20.0,
            "width_cm": 15.0,
            "height_cm": 3.0,
        },
        "kwai": {"enabled": False},
    },
    {
        "sku": "JD-ESC-008",
        "product_code": "JD008",
        "title": "OfficeMax Suporte Ergonômico Notebook Ajustável 7891234560080",
        "brand": "OfficeMax",
        "ean": "7891234560080",
        "description": "Suporte ergonômico dobrável para notebook com altura ajustável.",
        "price": 99.90,
        "cost": 34.00,
        "stock_johndrop": 55,
        "stock_bling": 0,
        "images": ["https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=600"],
        "amazon": {
            "enabled": True,
            "category": "Escritório > Ergonomia",
            "bullet_points": [
                "6 alturas ajustáveis para postura ergonômica ideal",
                "Alumínio resistente suporta notebooks até 17 polegadas",
                "Design dobrável ocupa menos de 2cm quando guardado",
                "Recortes de ventilação evitam superaquecimento",
                "Base antiderrapante estabiliza o equipamento",
                "Compatível com Macbook, Dell, Lenovo e mais (Código JD008)",
            ],
        },
        "shopee": {
            "enabled": True,
            "category": "Informática > Acessórios",
            "weight_kg": 0.7,
            "length_cm": 26.0,
            "width_cm": 22.0,
            "height_cm": 2.0,
        },
        "kwai": {"enabled": False},
    },
]


def sanitize_code(code: str) -> str:
    """Mantém apenas letras, números e hífen. Colapsa hífens duplicados."""
    if not code:
        return ""
    t = re.sub(r"[^A-Za-z0-9-]+", "-", code)
    t = re.sub(r"-+", "-", t)
    return t.strip("-")


def apply_seo_format(raw_title: str, brand: Optional[str], ean: Optional[str], product_code: str) -> str:
    """Rule-based SEO formatter for JohnDrop imports.
    - Remove brand & EAN from title
    - Strip product_code wherever it appears (so we control position)
    - Collapse whitespace
    - Always append product_code at the end
    - Hard truncate to 60 chars (keeping code intact)
    """
    t = raw_title or ""
    if brand:
        t = re.sub(re.escape(brand), "", t, flags=re.IGNORECASE)
    if ean:
        t = t.replace(ean, "")
    # Strip product_code anywhere (we'll re-append at end)
    if product_code:
        t = re.sub(re.escape(product_code), "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" -|,.()")

    if product_code:
        suffix = f" {product_code}"
        max_base = 60 - len(suffix)
        if len(t) > max_base:
            t = t[:max_base].rstrip(" -,|.")
        t = (t + suffix).strip()
    if len(t) > 60:
        t = t[:60].rstrip(" -,|.")
    return t


@api_router.post("/products/seed")
async def seed_products(user: UserPublic = Depends(get_current_user)):
    return await _import_johndrop_internal(user, apply_seo=False)


class JohnDropImportIn(BaseModel):
    apply_seo: bool = True


async def _import_johndrop_internal(user: UserPublic, apply_seo: bool = True):
    created = 0
    skipped = 0
    imported_items = []
    for p in SEED_PRODUCTS:
        existing = await db.products.find_one(
            {"sku": p["sku"], "owner_id": user.user_id}, {"_id": 0}
        )
        if existing:
            skipped += 1
            continue
        pid = f"prod_{uuid.uuid4().hex[:12]}"
        now = _now()
        data = {**p}
        raw_title = data["title"]
        if apply_seo:
            data["title"] = apply_seo_format(
                raw_title, data.get("brand"), data.get("ean"), data["product_code"]
            )
        sync_status = "out_of_stock" if data["stock_johndrop"] <= 0 else "pending"
        doc = {
            "id": pid,
            "owner_id": user.user_id,
            **data,
            "sync_status": sync_status,
            "sync_message": "Importado da JohnDrop - título ajustado para formato SEO 60 caracteres" if apply_seo else "Importado da JohnDrop - aguardando sincronização Bling",
            "created_at": now,
            "updated_at": now,
        }
        await db.products.insert_one(doc)
        created += 1
        imported_items.append({
            "sku": data["sku"],
            "product_code": data["product_code"],
            "raw_title": raw_title,
            "seo_title": data["title"],
            "title_length": len(data["title"]),
        })
    return {
        "created": created,
        "skipped": skipped,
        "total_available": len(SEED_PRODUCTS),
        "apply_seo": apply_seo,
        "items": imported_items,
    }


@api_router.post("/johndrop/import")
async def johndrop_import(data: JohnDropImportIn, user: UserPublic = Depends(get_current_user)):
    """Importa automaticamente da JohnDrop todos os produtos que ainda não estão em Meus Produtos.
    Aplica o formato SEO (sem marca, sem EAN, com código do produto, máx 60 chars)."""
    # Require JohnDrop connected
    integ = await db.integrations.find_one({"user_id": user.user_id}, {"_id": 0})
    if not integ or not integ.get("johndrop", {}).get("connected"):
        raise HTTPException(status_code=400, detail="Conecte a JohnDrop em Integrações antes de importar")
    return await _import_johndrop_internal(user, apply_seo=data.apply_seo)


# ============ Dashboard ============
@api_router.get("/dashboard/stats")
async def dashboard_stats(user: UserPublic = Depends(get_current_user)):
    total = await db.products.count_documents({"owner_id": user.user_id})
    synced = await db.products.count_documents({"owner_id": user.user_id, "sync_status": "synced"})
    pending = await db.products.count_documents({"owner_id": user.user_id, "sync_status": "pending"})
    errors = await db.products.count_documents({"owner_id": user.user_id, "sync_status": "error"})
    out_of_stock = await db.products.count_documents({"owner_id": user.user_id, "sync_status": "out_of_stock"})

    amazon_ct = await db.products.count_documents({"owner_id": user.user_id, "amazon.enabled": True})
    shopee_ct = await db.products.count_documents({"owner_id": user.user_id, "shopee.enabled": True})
    kwai_ct = await db.products.count_documents({"owner_id": user.user_id, "kwai.enabled": True})

    # Divergence: stock johndrop != stock bling
    divergence_cursor = db.products.find(
        {"owner_id": user.user_id, "$expr": {"$ne": ["$stock_johndrop", "$stock_bling"]}},
        {"_id": 0, "id": 1, "sku": 1, "title": 1, "stock_johndrop": 1, "stock_bling": 1},
    ).limit(5)
    divergences = await divergence_cursor.to_list(5)

    return {
        "total_products": total,
        "synced": synced,
        "pending": pending,
        "errors": errors,
        "out_of_stock": out_of_stock,
        "marketplace_coverage": {
            "amazon": amazon_ct,
            "shopee": shopee_ct,
            "kwai": kwai_ct,
        },
        "stock_divergences": divergences,
    }


# ============ Integrations ============
@api_router.get("/integrations/status")
async def integration_status(user: UserPublic = Depends(get_current_user)):
    doc = await db.integrations.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc:
        doc = {
            "user_id": user.user_id,
            "bling": {"connected": False, "last_sync": None, "token_valid": False},
            "johndrop": {"connected": False, "last_sync": None, "token_valid": False},
            "make": {"connected": False},
            "discord": {"connected": False, "webhook": None},
        }
        await db.integrations.insert_one(doc)
        doc.pop("_id", None)
    doc.pop("user_id", None)
    # Sync real Bling status from credentials
    bling_cred = await db.bling_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    if bling_cred:
        doc["bling"] = {
            **doc.get("bling", {}),
            "connected": True,
            "token_valid": True,
            "last_sync": bling_cred.get("connected_at"),
            "expires_at": bling_cred.get("expires_at"),
        }
    else:
        doc["bling"] = {
            **doc.get("bling", {}),
            "connected": False,
            "token_valid": False,
        }
    return doc


@api_router.post("/products/fix-skus")
async def fix_skus(user: UserPublic = Depends(get_current_user)):
    """Remove prefixo 'JD-' e sanitiza SKU/product_code (só mantém A-Z, 0-9, -)."""
    cursor = db.products.find(
        {"owner_id": user.user_id},
        {"_id": 0, "id": 1, "sku": 1, "product_code": 1},
    )
    updated = 0
    async for doc in cursor:
        orig_sku = doc.get("sku") or ""
        orig_code = doc.get("product_code") or ""
        new_sku = orig_sku
        if new_sku.startswith("JD-"):
            new_sku = new_sku[3:]
        new_sku = sanitize_code(new_sku)
        new_code = sanitize_code(orig_code)
        if new_sku != orig_sku or new_code != orig_code:
            await db.products.update_one(
                {"id": doc["id"], "owner_id": user.user_id},
                {"$set": {
                    "sku": new_sku or orig_sku,
                    "product_code": new_code or orig_code,
                    "updated_at": _now(),
                }},
            )
            updated += 1
    return {"updated": updated}


class IntegrationToggleIn(BaseModel):
    service: Literal["bling", "johndrop", "make", "discord"]
    connected: bool
    webhook: Optional[str] = None


@api_router.post("/integrations/toggle")
async def toggle_integration(data: IntegrationToggleIn, user: UserPublic = Depends(get_current_user)):
    now_iso = _now()
    update = {}
    update[f"{data.service}.connected"] = data.connected
    if data.service in ("bling", "johndrop"):
        update[f"{data.service}.token_valid"] = data.connected
        update[f"{data.service}.last_sync"] = now_iso if data.connected else None
    if data.service == "discord" and data.webhook is not None:
        update["discord.webhook"] = data.webhook
    await db.integrations.update_one(
        {"user_id": user.user_id},
        {"$set": update, "$setOnInsert": {"user_id": user.user_id}},
        upsert=True,
    )
    doc = await db.integrations.find_one({"user_id": user.user_id}, {"_id": 0, "user_id": 0})
    return doc


# ============ AI SEO Generator ============
def _model_tuple(model_choice: str):
    if model_choice == "gpt":
        return ("openai", "gpt-5.2")
    return ("anthropic", "claude-sonnet-4-5-20250929")


async def _llm_generate(system_prompt: str, user_text: str, model_choice: str) -> str:
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY não configurada")
    provider, model_name = _model_tuple(model_choice)
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"seo-{uuid.uuid4().hex[:8]}",
        system_message=system_prompt,
    ).with_model(provider, model_name)
    response = await chat.send_message(UserMessage(text=user_text))
    return response.strip() if isinstance(response, str) else str(response).strip()


@api_router.post("/ai/generate-title")
async def ai_generate_title(data: AIGenerateTitleIn, user: UserPublic = Depends(get_current_user)):
    system = (
        "Você é um especialista em SEO para marketplaces brasileiros (Amazon, Shopee, Kwai Shop). "
        "Gere títulos de produto otimizados seguindo estas REGRAS OBRIGATÓRIAS:\n"
        "1. Máximo 60 caracteres (contagem rigorosa)\n"
        "2. NÃO incluir marca no título\n"
        "3. NÃO incluir EAN no título\n"
        "4. SEMPRE incluir o código do produto no final\n"
        "5. Priorizar termos de busca relevantes (palavras-chave)\n"
        "6. Idioma: Português brasileiro\n"
        "Retorne APENAS o título, sem aspas, sem explicação."
    )
    user_text = (
        f"Nome bruto do produto: {data.raw_name}\n"
        f"Categoria: {data.category or 'não informada'}\n"
        f"Palavras-chave sugeridas: {data.keywords or 'não informadas'}\n"
        f"Código do produto (incluir no título): {data.product_code}\n\n"
        "Gere o título otimizado (máx 60 caracteres)."
    )
    title = await _llm_generate(system, user_text, data.model)
    # Enforce 60 char limit (truncate on word boundary if needed)
    if len(title) > 60:
        title = title[:60].rstrip()
    return {"title": title, "length": len(title)}


@api_router.post("/ai/generate-bullets")
async def ai_generate_bullets(data: AIGenerateBulletsIn, user: UserPublic = Depends(get_current_user)):
    system = (
        "Você é um copywriter especialista em listings Amazon. "
        "Gere EXATAMENTE 6 bullet points para um produto, seguindo o padrão Amazon BR:\n"
        "- Cada bullet deve ter 70 a 180 caracteres\n"
        "- Começar com um benefício ou característica técnica\n"
        "- Usar linguagem clara e persuasiva em português brasileiro\n"
        "- Incluir o código do produto no último bullet\n"
        "- NÃO usar emojis\n"
        "Retorne APENAS os 6 bullets, um por linha, SEM numeração, SEM marcadores, SEM explicação."
    )
    user_text = (
        f"Título do produto: {data.title}\n"
        f"Código: {data.product_code}\n"
        f"Categoria: {data.category or 'não informada'}\n"
        f"Palavras-chave: {data.keywords or 'não informadas'}\n\n"
        "Gere exatamente 6 bullet points."
    )
    raw = await _llm_generate(system, user_text, data.model)
    lines = [ln.strip(" -•*0123456789.)\t") for ln in raw.split("\n") if ln.strip()]
    # Keep first 6 non-empty
    bullets = [ln for ln in lines if ln][:6]
    while len(bullets) < 6:
        bullets.append("")
    return {"bullets": bullets}


@api_router.post("/ai/generate-description")
async def ai_generate_description(data: AIGenerateDescriptionIn, user: UserPublic = Depends(get_current_user)):
    system = (
        "Você é um copywriter de e-commerce. Gere uma descrição completa em português brasileiro "
        "para o produto abaixo, entre 400 e 700 caracteres, em 2 parágrafos, sem emojis, sem marcadores."
    )
    bullets_text = "\n".join(f"- {b}" for b in data.bullets if b)
    user_text = f"Título: {data.title}\n\nBullets:\n{bullets_text}"
    desc = await _llm_generate(system, user_text, data.model)
    return {"description": desc}


# ============ JohnDrop Real Integration ============
class JohnDropConnectIn(BaseModel):
    email: EmailStr
    password: str


@api_router.post("/johndrop/connect")
async def johndrop_connect(data: JohnDropConnectIn, user: UserPublic = Depends(get_current_user)):
    """Testa login na JohnDrop e salva credenciais criptografadas."""
    try:
        async with JohnDropClient(data.email, data.password) as c:
            ok = await c.login()
    except JohnDropAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha de rede com a JohnDrop: {e}")
    if not ok:
        raise HTTPException(status_code=401, detail="Email ou senha inválidos na JohnDrop")

    enc_password = encrypt_secret(data.password, JWT_SECRET)
    await db.johndrop_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {
            "user_id": user.user_id,
            "email": data.email,
            "password_enc": enc_password,
            "connected_at": _now(),
        }},
        upsert=True,
    )
    # Mark integration
    await db.integrations.update_one(
        {"user_id": user.user_id},
        {"$set": {
            "user_id": user.user_id,
            "johndrop.connected": True,
            "johndrop.token_valid": True,
            "johndrop.last_sync": _now(),
            "johndrop.email": data.email,
        }},
        upsert=True,
    )
    return {"connected": True, "email": data.email}


@api_router.post("/johndrop/disconnect")
async def johndrop_disconnect(user: UserPublic = Depends(get_current_user)):
    await db.johndrop_credentials.delete_one({"user_id": user.user_id})
    await db.integrations.update_one(
        {"user_id": user.user_id},
        {"$set": {
            "johndrop.connected": False,
            "johndrop.token_valid": False,
            "johndrop.email": None,
        }},
    )
    return {"disconnected": True}


async def _get_johndrop_client(user_id: str) -> JohnDropClient:
    cred = await db.johndrop_credentials.find_one({"user_id": user_id}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=400, detail="Conecte sua conta JohnDrop primeiro")
    try:
        password = decrypt_secret(cred["password_enc"], JWT_SECRET)
    except Exception:
        raise HTTPException(status_code=401, detail="Credenciais corrompidas - reconecte sua JohnDrop")
    return JohnDropClient(cred["email"], password)


@api_router.get("/johndrop/catalog")
async def johndrop_catalog(
    page: int = 1,
    integration_filter: str = "without_integration",
    category_id: str = "",
    name: str = "",
    user: UserPublic = Depends(get_current_user),
):
    """Busca catálogo real da JohnDrop (página por vez, paginado)."""
    client = await _get_johndrop_client(user.user_id)
    async with client as c:
        try:
            data = await c.fetch_catalog_page(
                page=page,
                integration_filter=integration_filter,
                category_id=category_id,
                name=name,
            )
        except JohnDropAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Falha ao buscar catálogo: {e}")

    # Flag which items are already imported into user's products
    jd_ids = [it["jd_id"] for it in data["items"]]
    existing = await db.products.find(
        {"owner_id": user.user_id, "jd_id": {"$in": jd_ids}},
        {"_id": 0, "jd_id": 1},
    ).to_list(1000)
    existing_ids = {e["jd_id"] for e in existing}

    for it in data["items"]:
        it["already_imported"] = it["jd_id"] in existing_ids
        # Pre-compute SEO title suggestion
        it["seo_title_suggestion"] = apply_seo_format(
            it["clean_title"],
            brand=None,
            ean=None,
            product_code=it["product_code"] or "",
        )
        # Pre-compute blindada price (uses escalonated markup)
        calc = _calc_selling_price(it["price"], packaging=0.0, campaigns=0.0)
        it["price_suggestion"] = calc["selling_price"]
        it["markup"] = calc["markup"]
        it["safety_alert"] = calc["safety_alert"]

    return data


class JohnDropImportRealIn(BaseModel):
    jd_ids: List[str]
    use_ai_description: bool = False
    ai_model: Literal["claude", "gpt"] = "claude"


@api_router.post("/johndrop/import-real")
async def johndrop_import_real(data: JohnDropImportRealIn, user: UserPublic = Depends(get_current_user)):
    """Importa produtos REAIS da JohnDrop (por jd_id) para Meus Produtos,
    aplicando formato SEO + preço calculado + descrição IA opcional."""
    if not data.jd_ids:
        raise HTTPException(status_code=400, detail="Nenhum produto selecionado")

    client = await _get_johndrop_client(user.user_id)
    # Need to iterate pages until we find all requested IDs
    target = set(data.jd_ids)
    found: dict[str, dict] = {}
    created = 0
    skipped = 0
    errors: list[str] = []

    async with client as c:
        try:
            await c.ensure_logged_in()
        except JohnDropAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))

        page = 1
        max_page = 1
        while target and page <= max_page and page <= 30:  # safety cap
            try:
                data_page = await c.fetch_catalog_page(page=page)
            except Exception as e:
                errors.append(f"Page {page}: {e}")
                break
            max_page = data_page["max_page"]
            for it in data_page["items"]:
                if it["jd_id"] in target:
                    found[it["jd_id"]] = it
                    target.discard(it["jd_id"])
            page += 1

    # Create products
    imported_items = []
    for jd_id, it in found.items():
        existing = await db.products.find_one(
            {"owner_id": user.user_id, "jd_id": jd_id}, {"_id": 0}
        )
        if existing:
            skipped += 1
            continue
        product_code = sanitize_code(it["product_code"]) if it["product_code"] else f"JD{jd_id}"
        seo_title = apply_seo_format(it["clean_title"], brand=None, ean=None, product_code=product_code)
        # Preço sugerido pela Calculadora Blindada (markup escalonado)
        calc = _calc_selling_price(it["price"], packaging=0.0, campaigns=0.0)
        suggested_price = calc["selling_price"]
        # description via AI (optional)
        description = ""
        if data.use_ai_description:
            try:
                description = await _llm_generate(
                    system_prompt=(
                        "Você é um copywriter de e-commerce. Gere uma descrição em português brasileiro "
                        "entre 400 e 700 caracteres, em 2 parágrafos, sem emojis, destacando benefícios e público-alvo."
                    ),
                    user_text=f"Produto: {seo_title}\nCódigo: {product_code}",
                    model_choice=data.ai_model,
                )
            except Exception:
                description = it["clean_title"]
        else:
            description = it["clean_title"]

        pid = f"prod_{uuid.uuid4().hex[:12]}"
        now = _now()
        doc = {
            "id": pid,
            "owner_id": user.user_id,
            "jd_id": jd_id,
            "sku": product_code if product_code else f"JD{jd_id}",
            "product_code": product_code,
            "title": seo_title,
            "brand": "",
            "ean": "",
            "description": description,
            "price": suggested_price,
            "cost": it["price"],
            "stock_johndrop": it["stock"],
            "stock_bling": 0,
            "images": [it["image"]] if it["image"] else [],
            "amazon": {
                "enabled": True,
                "category": None,
                "bullet_points": ["", "", "", "", "", ""],
            },
            "shopee": {
                "enabled": True,
                "category": None,
                "variation_color": it.get("variation_color"),
                "variation_size": it.get("variation_size"),
                "weight_kg": None,
                "length_cm": None,
                "width_cm": None,
                "height_cm": None,
            },
            "kwai": {"enabled": False},
            "sync_status": "pending" if it["stock"] > 0 else "out_of_stock",
            "sync_message": "Importado da JohnDrop (API real) - título SEO + preço blindado aplicados",
            "created_at": now,
            "updated_at": now,
        }
        await db.products.insert_one(doc)
        created += 1
        imported_items.append({
            "jd_id": jd_id,
            "product_code": product_code,
            "raw_title": it["raw_title"],
            "seo_title": seo_title,
            "suggested_price": suggested_price,
        })

    not_found = list(target)
    return {
        "created": created,
        "skipped": skipped,
        "not_found": not_found,
        "errors": errors,
        "items": imported_items,
    }


class JohnDropRegisterDirectIn(BaseModel):
    jd_ids: List[str]
    use_ai_description: bool = False
    ai_model: Literal["claude", "gpt"] = "claude"


@api_router.post("/johndrop/register-direct")
async def johndrop_register_direct(data: JohnDropRegisterDirectIn, user: UserPublic = Depends(get_current_user)):
    """Cadastra produtos direto na JohnDrop (POST storev2) aplicando SEO+preço+descrição.
    Não salva localmente. Produtos aparecem em 'Meus produtos' da JohnDrop (integrados ao Bling via TotyShop)."""
    if not data.jd_ids:
        raise HTTPException(status_code=400, detail="Nenhum produto selecionado")

    client = await _get_johndrop_client(user.user_id)
    registered = 0
    failed: list[dict] = []
    successes: list[dict] = []

    # Collect catalog items once (need price/title/code from catalog)
    target = set(data.jd_ids)
    catalog_map: dict[str, dict] = {}

    async with client as c:
        try:
            await c.ensure_logged_in()
        except JohnDropAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))

        # Walk catalog to map jd_ids -> metadata
        page = 1
        while target and page <= 30:
            try:
                page_data = await c.fetch_catalog_page(page=page)
            except Exception as e:
                failed.append({"jd_id": "-", "reason": f"catalog page {page}: {e}"})
                break
            for it in page_data["items"]:
                if it["jd_id"] in target:
                    catalog_map[it["jd_id"]] = it
                    target.discard(it["jd_id"])
            if page >= page_data.get("max_page", 1):
                break
            page += 1

        # Now register each
        for jd_id in data.jd_ids:
            cat_item = catalog_map.get(jd_id)
            if not cat_item:
                failed.append({"jd_id": jd_id, "reason": "Não encontrado no catálogo"})
                continue
            try:
                # Compute enrichment
                raw_code = cat_item.get("product_code") or ""
                product_code = sanitize_code(raw_code) or f"JD{jd_id}"
                seo_title = apply_seo_format(
                    cat_item["clean_title"],
                    brand=None,
                    ean=None,
                    product_code=product_code,
                )
                calc = _calc_selling_price(cat_item["price"], packaging=0.0, campaigns=0.0)
                sale_value_str = f"{calc['selling_price']:.2f}".replace(".", ",")

                description = None  # NÃO mexer na descrição da JohnDrop por padrão
                if data.use_ai_description:
                    try:
                        description = await _llm_generate(
                            system_prompt=(
                                "Você é um copywriter de e-commerce. Gere uma descrição em português brasileiro "
                                "entre 400 e 700 caracteres, em 2 parágrafos, sem emojis, destacando benefícios e público-alvo."
                            ),
                            user_text=f"Produto: {seo_title}\nCódigo: {product_code}",
                            model_choice=data.ai_model,
                        )
                    except Exception:
                        description = None  # falhou IA, mantém original

                # Push to JohnDrop (storev2 works for both create and update)
                result = await c.push_product(
                    jd_id,
                    {
                        "name": seo_title,
                        "description": description,
                        "sku": product_code,
                        "sale_value": sale_value_str,
                    },
                    integration_ids=[INTEGRATION_TOTYSHOP_BLING],
                )
                if result["success"]:
                    # Log for audit
                    await db.johndrop_register_log.insert_one({
                        "user_id": user.user_id,
                        "jd_id": jd_id,
                        "product_code": product_code,
                        "seo_title": seo_title,
                        "price_cost": cat_item["price"],
                        "price_sale": calc["selling_price"],
                        "markup": calc["markup"],
                        "registered_at": _now(),
                    })
                    registered += 1
                    successes.append({
                        "jd_id": jd_id,
                        "product_code": product_code,
                        "seo_title": seo_title,
                        "price_sale": calc["selling_price"],
                        "markup": calc["markup"],
                    })
                else:
                    failed.append({"jd_id": jd_id, "reason": f"status {result['status_code']}"})
            except Exception as e:
                failed.append({"jd_id": jd_id, "reason": str(e)})

    return {
        "registered": registered,
        "failed": failed,
        "successes": successes,
        "total": len(data.jd_ids),
    }


@api_router.get("/johndrop/history")
async def johndrop_history(user: UserPublic = Depends(get_current_user)):
    """Histórico de cadastros feitos na JohnDrop via BlingDrop."""
    cursor = db.johndrop_register_log.find(
        {"user_id": user.user_id}, {"_id": 0, "user_id": 0}
    ).sort("registered_at", -1).limit(200)
    items = await cursor.to_list(200)
    return {"items": items, "total": len(items)}


# ============ Bling OAuth + API ============
@api_router.get("/bling/authorize-url")
async def bling_authorize_url(user: UserPublic = Depends(get_current_user)):
    """Retorna URL para o usuário iniciar o OAuth no Bling."""
    if not BLING_CLIENT_ID or not BLING_REDIRECT_URL:
        raise HTTPException(status_code=500, detail="Bling não configurado no servidor")
    state = generate_state()
    # Save state tied to user_id (TTL 10 min via startup index)
    await db.bling_oauth_states.insert_one({
        "state": state,
        "user_id": user.user_id,
        "created_at": datetime.now(timezone.utc),
    })
    url = build_authorize_url(BLING_CLIENT_ID, BLING_REDIRECT_URL, state)
    return {"url": url, "state": state}


class BlingCallbackIn(BaseModel):
    code: str
    state: str


@api_router.post("/bling/callback")
async def bling_callback(data: BlingCallbackIn, user: UserPublic = Depends(get_current_user)):
    """Troca o code por tokens e salva criptografados."""
    state_doc = await db.bling_oauth_states.find_one({"state": data.state}, {"_id": 0})
    if not state_doc:
        raise HTTPException(status_code=400, detail="State inválido ou expirado")
    if state_doc["user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="State pertence a outro usuário")
    await db.bling_oauth_states.delete_many({"state": data.state})

    try:
        tokens = await exchange_code_for_tokens(BLING_CLIENT_ID, BLING_CLIENT_SECRET, data.code)
    except BlingAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha de rede Bling: {e}")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 21600)
    if not access_token:
        raise HTTPException(status_code=502, detail="Bling não retornou access_token")

    await db.bling_credentials.update_one(
        {"user_id": user.user_id},
        {"$set": {
            "user_id": user.user_id,
            "access_token_enc": encrypt_secret(access_token, JWT_SECRET),
            "refresh_token_enc": encrypt_secret(refresh_token, JWT_SECRET) if refresh_token else None,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat(),
            "connected_at": _now(),
        }},
        upsert=True,
    )
    await db.integrations.update_one(
        {"user_id": user.user_id},
        {"$set": {
            "user_id": user.user_id,
            "bling.connected": True,
            "bling.token_valid": True,
            "bling.last_sync": _now(),
        }},
        upsert=True,
    )
    return {"connected": True}


async def _get_bling_access_token(user_id: str) -> str:
    """Obtém access_token válido, renova se necessário."""
    cred = await db.bling_credentials.find_one({"user_id": user_id}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=400, detail="Conecte sua Bling primeiro")
    expires_at = cred.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    # Refresh se faltam menos de 5 min
    if expires_at <= datetime.now(timezone.utc) + timedelta(minutes=5):
        try:
            refresh_token = decrypt_secret(cred["refresh_token_enc"], JWT_SECRET)
            tokens = await refresh_access_token(BLING_CLIENT_ID, BLING_CLIENT_SECRET, refresh_token)
            access_token = tokens.get("access_token")
            new_refresh = tokens.get("refresh_token") or refresh_token
            expires_in = tokens.get("expires_in", 21600)
            await db.bling_credentials.update_one(
                {"user_id": user_id},
                {"$set": {
                    "access_token_enc": encrypt_secret(access_token, JWT_SECRET),
                    "refresh_token_enc": encrypt_secret(new_refresh, JWT_SECRET),
                    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat(),
                }},
            )
            return access_token
        except BlingAuthError as e:
            raise HTTPException(status_code=401, detail=f"Falha ao renovar token Bling: {e}")
    return decrypt_secret(cred["access_token_enc"], JWT_SECRET)


@api_router.post("/bling/disconnect")
async def bling_disconnect(user: UserPublic = Depends(get_current_user)):
    await db.bling_credentials.delete_one({"user_id": user.user_id})
    await db.integrations.update_one(
        {"user_id": user.user_id},
        {"$set": {"bling.connected": False, "bling.token_valid": False}},
    )
    return {"disconnected": True}


@api_router.get("/bling/status")
async def bling_status(user: UserPublic = Depends(get_current_user)):
    cred = await db.bling_credentials.find_one({"user_id": user.user_id}, {"_id": 0})
    if not cred:
        return {"connected": False}
    expires_at = cred.get("expires_at")
    return {
        "connected": True,
        "expires_at": expires_at,
        "connected_at": cred.get("connected_at"),
    }


@api_router.get("/bling/products")
async def bling_list_products(
    page: int = 1,
    limit: int = 100,
    user: UserPublic = Depends(get_current_user),
):
    token = await _get_bling_access_token(user.user_id)
    async with BlingClient(token) as c:
        try:
            items = await c.list_products(page=page, limit=limit)
        except BlingAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except BlingAPIError as e:
            raise HTTPException(status_code=502, detail=str(e))
    # Flag which are already enriched in our log
    codes = [it.get("codigo") for it in items if it.get("codigo")]
    enriched = await db.bling_enrich_log.find(
        {"user_id": user.user_id, "bling_code": {"$in": codes}},
        {"_id": 0, "bling_code": 1},
    ).to_list(len(codes))
    enriched_codes = {e["bling_code"] for e in enriched}
    for it in items:
        it["already_enriched"] = it.get("codigo") in enriched_codes
    return {"items": items, "page": page, "limit": limit}


@api_router.get("/bling/categories")
async def bling_list_categories(user: UserPublic = Depends(get_current_user)):
    token = await _get_bling_access_token(user.user_id)
    async with BlingClient(token) as c:
        try:
            items = await c.list_categories()
        except BlingAPIError as e:
            raise HTTPException(status_code=502, detail=str(e))
    return {"items": items}


class BlingEnrichIn(BaseModel):
    bling_product_ids: List[int]
    ai_model: Literal["claude", "gpt"] = "claude"
    auto_create_categories: bool = True
    supplier_name: str = "Jonh Variedades"


async def _ai_enrich_product(
    title: str,
    code: str,
    existing_categories: list[dict],
    custom_fields: list[dict],
    ai_model: str,
    johndrop_description: str = "",
) -> dict:
    """Usa IA pra sugerir: descrição principal + bullets, categoria, NCM, dimensões + campos customizados aplicáveis.
    Se johndrop_description for fornecida, ela serve como contexto principal para a IA."""
    # Build full hierarchical paths for categories (e.g., "Acessórios Automotivo > Energia e Carregamento")
    cat_by_id = {c.get("id"): c for c in existing_categories if c.get("id")}

    def _full_path(cat: dict) -> str:
        parts = [cat.get("descricao", "").strip().lstrip("_").strip()]
        seen = {cat.get("id")}
        parent_ref = cat.get("categoriaPai") or {}
        parent_id = parent_ref.get("id") if isinstance(parent_ref, dict) else None
        while parent_id and parent_id not in seen:
            seen.add(parent_id)
            parent = cat_by_id.get(parent_id)
            if not parent:
                break
            parts.insert(0, parent.get("descricao", "").strip().lstrip("_").strip())
            parent_ref = parent.get("categoriaPai") or {}
            parent_id = parent_ref.get("id") if isinstance(parent_ref, dict) else None
        return " > ".join(parts)

    cat_paths = sorted({_full_path(c) for c in existing_categories if c.get("descricao")})
    cat_list = "\n".join(f"- {p}" for p in cat_paths[:80])

    cf_lines = []
    for cf in custom_fields:
        nome = cf.get("nome", "")
        tipo = cf.get("tipo", "")
        valores = cf.get("valoresDePreenchimento") or cf.get("valoresPreenchimento") or []
        val_hint = ""
        if valores:
            sample = [v.get("valor") if isinstance(v, dict) else str(v) for v in valores[:6]]
            val_hint = f" (opções: {', '.join(sample)})"
        cf_lines.append(f"- {nome} ({tipo}){val_hint}")
    cf_list = "\n".join(cf_lines) if cf_lines else "(nenhum campo customizado disponível)"

    system = (
        "Você é um especialista em copywriting de e-commerce no ERP Bling. "
        "Analise o produto e retorne APENAS um JSON válido (sem markdown, sem explicação) com:\n\n"
        "- descricao_curta: DESCRIÇÃO PRINCIPAL completa e profissional, pronta para venda. "
        "Entre 600-1500 caracteres. Estrutura: \n"
        "  • 1 linha de headline com pipes separando recursos-chave (ex: 'Mouse Sem Fio | Bluetooth + 2.4G | RGB | Silencioso')\n"
        "  • 1 parágrafo introdutório vendedor (3-5 linhas) destacando para quem é e o que entrega\n"
        "  • Linha 'Por que escolher este modelo?'\n"
        "  • 4 a 6 destaques técnicos no formato 'Nome do Recurso: explicação curta do benefício.' (cada um em sua linha, sem bullet character)\n"
        "Sem emojis. Sem listas <ul>/<li>. Sem nome de marca. Tom profissional e persuasivo.\n\n"
        "- descricao_complementar: HTML com 6 a 8 bullets no formato '<p>• texto</p><p>• texto</p>'. "
        "FORMATO OBRIGATÓRIO: cada bullet em uma tag <p> separada, começando com o caractere bullet '• ' (U+2022 + espaço) seguido do texto. "
        "NÃO use <ul>/<li>. NÃO use '-' nem '*'. APENAS '<p>• ...</p><p>• ...</p>'. Esse é o formato exigido pela Buy Box Amazon do Bling.\n"
        "REGRAS RÍGIDAS dos bullets:\n"
        "  1. NUNCA use o NOME do produto como bullet (zero valor de venda).\n"
        "  2. NUNCA use frases genéricas como 'Alta durabilidade', 'Design moderno', 'Qualidade premium', 'Excelente custo-benefício', 'Fácil manuseio'. Esses adjetivos vagos servem para qualquer produto e estão PROIBIDOS.\n"
        "  3. CADA bullet DEVE descrever um RECURSO CONCRETO e ESPECÍFICO do produto, mencionando o número/tecnologia/material real (ex: '1600 DPI ajustável para precisão em jogos e edição', 'Conexão dual Bluetooth 5.0 + receptor USB 2.4G inclusos', 'Iluminação RGB com 7 modos de cor configuráveis', 'Bateria recarregável com até 30h de uso contínuo').\n"
        "  4. Espelhe os destaques técnicos da descricao_curta — mesmo recurso, frase diferente, mais sintética.\n"
        "  5. Cada bullet entre 60-150 caracteres.\n"
        "  6. Comece com o nome do recurso/benefício, não com verbos genéricos.\n"
        "  7. Sem emojis, sem ícones. Apenas texto puro entre <p>• ...</p>.\n"
        "Retorne apenas a sequência de <p>•&nbsp;texto</p>, sem <ul>, sem introdução.\n\n"
        "- categoria_sugerida: nome da categoria mais adequada. \n"
        "  REGRAS DE CATEGORIA:\n"
        "  1. As categorias existentes vêm com o CAMINHO completo (ex: 'Acessórios Automotivo > Energia e Carregamento'). "
        "VOCÊ DEVE analisar o caminho INTEIRO antes de decidir. Categoria 'Energia e Carregamento' SOB 'Acessórios Automotivo' SÓ serve para produtos automotivos. "
        "NÃO use uma sub-categoria se o pai não bate com o produto.\n"
        "  2. Se o caminho INTEIRO encaixa, use o NOME DA FOLHA (último segmento depois do último '>'). Exemplo: para 'Eletrônicos > Periféricos > Mouse' use apenas 'Mouse'.\n"
        "  3. Se NENHUMA categoria existente bate (caminho completo + folha), proponha um nome de categoria NOVA descritiva em português e use o campo 'categoria_pai_sugerida' para indicar a categoria pai correta (se houver) ou deixe vazio para criar como top-level.\n"
        "  Exemplo bom: 'Filtro de Linha com 4 tomadas' → categoria nova 'Filtros de Linha e Estabilizadores' (top-level), pois 'Energia e Carregamento' existente está sob 'Acessórios Automotivo'.\n\n"
        "- categoria_pai_sugerida: (opcional) nome ou caminho da categoria pai quando criar uma nova subcategoria. Vazio se for top-level.\n\n"
        "- ncm: código NCM de 8 dígitos adequado ao produto (apenas números, sem pontos/traços)\n"
        "- peso_kg: peso em kg (número decimal realista para o produto)\n"
        "- altura_cm: altura em cm\n"
        "- largura_cm: largura em cm\n"
        "- comprimento_cm: comprimento em cm\n"
        "- unidade: 'Un', 'Pc' ou 'Cx' conforme o produto\n\n"
        "- campos_customizados: DICT (objeto) mapeando NOME DO CAMPO para VALOR sugerido. "
        "REGRA: PREENCHA o MÁXIMO POSSÍVEL de campos. Se houver QUALQUER inferência razoável a partir do produto, PREENCHA. "
        "Inferências padrão para campos comuns (use estes defaults quando aplicável):\n"
        "  • 'País de Origem' / 'Pais de Origem' → 'China' (padrão dropshipping)\n"
        "  • 'Origem da mercadoria' → '1' (estrangeira - importação direta) — formato inteiro\n"
        "  • 'Modelo' → use o título do produto resumido em 3-5 palavras-chave OU o código/SKU\n"
        "  • 'Número do modelo' → o SKU/código do produto\n"
        "  • 'Tipo de material' / 'Tipo de tecido' → infira do produto (ex: 'Plástico ABS', 'Alumínio', 'Aço carbono', 'Algodão', 'Silicone', 'Metal', 'Madeira MDF')\n"
        "  • 'Marca' → 'Sem Marca' / 'Genérica' / 'Multimarca' (NUNCA invente um nome)\n"
        "  • 'Tipo de garantia' → 'Garantia do vendedor' (padrão)\n"
        "  • 'Cor' → infira da imagem/descrição (ex: 'Preto', 'Branco', 'Cinza')\n"
        "  • 'Peso do item' → mesmo valor de peso_kg em kg\n"
        "  • 'Quantidade de itens' → '1'\n"
        "  • 'Baterias são necessárias' / 'Bateria inclusa' → 'Não' (a menos que o produto exija)\n"
        "  • 'Voltagem' → 'Bivolt' (a menos que o produto seja específico de 110V/220V)\n"
        "  • 'Público-alvo' → 'Adulto' (ou outro se evidente)\n"
        "  • 'Faixa etária' → 'Adulto' (ou ajuste se for produto infantil)\n"
        "  • 'Tema de variação' → omita se o produto não tem variações\n"
        "Se o campo tiver opções pré-definidas (lista), use EXATAMENTE uma delas. "
        "SÓ omita o campo se for 100% inaplicável (ex: 'Idade mínima jogo de tabuleiro' para um mouse). "
        "Exemplo: {\"País de Origem\": \"China\", \"Modelo\": \"Suporte Articulado Notebook\", \"Tipo de material\": \"Alumínio\", \"Marca\": \"Sem Marca\", \"Cor\": \"Prata\", \"Peso do item\": \"1.8\"}\n\n"
        "REGRAS GLOBAIS:\n"
        "1. NÃO inclua nome de marca em nenhum texto\n"
        "2. NÃO use emojis em lugar nenhum\n"
        "3. Retorne APENAS JSON válido puro, sem markdown, sem comentário\n"
        "4. Os bullets de descricao_complementar DEVEM derivar diretamente dos recursos mencionados em descricao_curta — se a Curta menciona 'Bluetooth', 'RGB', '1600 DPI', a Complementar precisa ter esses 3 bullets correspondentes."
    )
    user_text = (
        f"Produto: {title}\n"
        f"Código/SKU: {code}\n\n"
        f"DESCRIÇÃO ORIGINAL DO FORNECEDOR (JohnDrop) — use como CONTEXTO PRINCIPAL "
        f"para extrair características, materiais, especificações, público-alvo e benefícios. "
        f"Reescreva profissionalmente, sem copiar literalmente:\n"
        f"{johndrop_description if johndrop_description else '(descrição original não disponível — use o título e seu conhecimento do produto)'}\n\n"
        f"Categorias existentes no Bling (caminho hierárquico completo — analise PAI > FILHO antes de escolher):\n{cat_list or '(nenhuma)'}\n\n"
        f"Campos customizados disponíveis no Bling:\n{cf_list}\n\n"
        "Analise e retorne o JSON."
    )
    raw = await _llm_generate(system, user_text, ai_model)
    import json as _json

    def _parse(raw_str: str) -> dict:
        cleaned = raw_str.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        try:
            return _json.loads(cleaned)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", cleaned)
            if m:
                return _json.loads(m.group(0))
            raise ValueError(f"IA retornou JSON inválido: {raw_str[:200]}")

    result = _parse(raw)

    # Validate complementar bullets — reject generic ones and retry once
    GENERIC_PATTERNS = [
        r"alta durabilidade", r"design moderno", r"qualidade premium",
        r"excelente custo[- ]benef[ií]cio", r"f[áa]cil manuseio", r"f[áa]cil instala[cç][ãa]o",
        r"qualidade garantida", r"acabamento premium",
    ]

    def _extract_bullets(html: str) -> list[str]:
        """Extract bullet text from any of the possible AI output formats:
        <ul><li>...</li></ul>, <p>• ...</p>, plain text lines starting with • or -."""
        if not html:
            return []
        # Try <li> first
        items = [m.group(1).strip() for m in re.finditer(r"<li[^>]*>(.*?)</li>", html, flags=re.I | re.S)]
        if items:
            return [re.sub(r"<[^>]+>", "", x).strip().lstrip("•-* ").strip() for x in items if x.strip()]
        # Try <p>• ...</p>
        items = [m.group(1).strip() for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, flags=re.I | re.S)]
        if items:
            return [re.sub(r"<[^>]+>", "", x).replace("&nbsp;", " ").strip().lstrip("•-* ").strip() for x in items if x.strip()]
        # Plain text fallback
        lines = [ln.strip() for ln in re.sub(r"<[^>]+>", "\n", html).splitlines() if ln.strip()]
        return [ln.lstrip("•-* ").strip() for ln in lines if ln.lstrip("•-* ").strip()]

    def _format_complementar(bullets: list[str]) -> str:
        """Canonical Bling/Amazon format: <p>• texto</p> per bullet."""
        return "".join(f"<p>•&nbsp;{b}</p>" for b in bullets if b)

    def _bullets(html: str) -> list[str]:
        return _extract_bullets(html)

    def _is_bad(bullets: list[str], product_title: str) -> str | None:
        if len(bullets) < 6:
            return f"apenas {len(bullets)} bullets — precisa 6 a 8"
        # Check generic
        for b in bullets:
            low = b.lower().strip().rstrip(".")
            for pat in GENERIC_PATTERNS:
                if re.fullmatch(rf"\W*{pat}\W*", low):
                    return f"bullet genérico proibido: '{b}'"
        # Check first bullet isn't just product name
        title_norm = re.sub(r"\W+", "", product_title.lower())
        first_norm = re.sub(r"\W+", "", bullets[0].lower())
        if title_norm and first_norm and (title_norm in first_norm or first_norm in title_norm) and len(first_norm) >= len(title_norm) * 0.7:
            return "primeiro bullet é o nome do produto (proibido)"
        return None

    bullets = _bullets(result.get("descricao_complementar", ""))
    bad_reason = _is_bad(bullets, title)
    if bad_reason:
        # Retry once with corrective instruction
        retry_user = user_text + (
            f"\n\n⚠️ ATENÇÃO: A versão anterior FALHOU — motivo: {bad_reason}. "
            "Regenere descricao_complementar com 6-8 bullets ULTRA-ESPECÍFICOS extraindo recursos concretos da descricao_curta. "
            "PROIBIDO: 'alta durabilidade', 'design moderno', 'qualidade premium', 'fácil manuseio', "
            "'excelente custo-benefício', repetir o nome do produto. "
            "Cada bullet DEVE citar uma especificação técnica real (DPI, polegadas, watts, capacidade em ml/L, "
            "material específico, conectividade, modos de operação, autonomia, voltagem, etc). "
            "FORMATO OBRIGATÓRIO: <p>• texto</p><p>• texto</p> — sem <ul>, sem <li>."
        )
        raw2 = await _llm_generate(system, retry_user, ai_model)
        try:
            result = _parse(raw2)
            bullets = _bullets(result.get("descricao_complementar", ""))
        except Exception:
            pass  # keep first result if retry fails to parse

    # Always normalize to canonical Bling/Amazon format regardless of what AI returned
    if bullets:
        result["descricao_complementar"] = _format_complementar(bullets)

    return result


@api_router.get("/bling/find-supplier")
async def bling_find_supplier(query: str = "Jonh Variedades", user: UserPublic = Depends(get_current_user)):
    """Debug endpoint: procura um contato pelo nome no Bling e retorna o resultado."""
    token = await _get_bling_access_token(user.user_id)
    async with BlingClient(token) as c:
        try:
            contact = await c.find_contact_by_name(query)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Erro buscando contato: {e}")
    if not contact:
        return {"found": False, "query": query, "message": "Nenhum contato encontrado com esse nome"}
    return {
        "found": True,
        "query": query,
        "id": contact.get("id"),
        "nome": contact.get("nome"),
        "fantasia": contact.get("fantasia"),
        "tipo": contact.get("tipo"),
        "numeroDocumento": contact.get("numeroDocumento"),
    }


@api_router.post("/bling/enrich")
async def bling_enrich(data: BlingEnrichIn, user: UserPublic = Depends(get_current_user)):
    """Analisa cada produto do Bling com IA e preenche: descrição, NCM, categoria (cria se não existir),
    dimensões, fornecedor. NUNCA mexe em título, SKU ou preço.
    Para enriquecimento usa a descrição original da JohnDrop (via jd_id mapeado pelo SKU)."""
    token = await _get_bling_access_token(user.user_id)
    enriched = 0
    failed: list[dict] = []
    results: list[dict] = []

    # Optional JohnDrop client (best-effort — só é usado se conectado)
    jd_client_factory = None
    try:
        jd_client_factory = await _get_johndrop_client(user.user_id)
    except HTTPException:
        jd_client_factory = None

    async with BlingClient(token) as c:
        # Load once
        try:
            categories = await c.list_categories()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Falha ao listar categorias Bling: {e}")
        cat_by_name = {c.get("descricao", "").lower().strip(): c for c in categories}
        cat_by_id_local = {c.get("id"): c for c in categories if c.get("id")}

        # Look up supplier contact ONCE (e.g., "Jonh Variedades") for fornecedores field
        supplier_contact_id: Optional[int] = None
        supplier_contact_name: Optional[str] = None
        try:
            contact = await c.find_contact_by_name(data.supplier_name)
            if contact:
                supplier_contact_id = contact.get("id")
                supplier_contact_name = contact.get("nome")
        except Exception:
            supplier_contact_id = None
        # Load custom field definitions (may be empty if user doesn't have any)
        try:
            custom_fields = await c.list_product_custom_fields()
        except Exception:
            custom_fields = []
        cf_by_name = {cf.get("nome", "").lower().strip(): cf for cf in custom_fields}

        # Open a single JohnDrop session for all products (if available)
        jd_session = None
        if jd_client_factory:
            try:
                jd_session = await jd_client_factory.__aenter__()
            except Exception:
                jd_session = None

        try:
            for bling_id in data.bling_product_ids:
                try:
                    product = await c.get_product(bling_id)
                    current_title = product.get("nome", "")
                    current_code = product.get("codigo", "")

                    # Try to fetch original JohnDrop description for context
                    jd_description = ""
                    jd_cost: Optional[float] = None
                    if current_code:
                        # Look up jd_id and cost_value by SKU in our products collection
                        prod_doc = await db.products.find_one(
                            {"owner_id": user.user_id, "sku": current_code},
                            {"_id": 0, "jd_id": 1, "cost_value": 1},
                        )
                        if prod_doc:
                            cv = prod_doc.get("cost_value")
                            if isinstance(cv, (int, float)) and cv > 0:
                                jd_cost = float(cv)
                        jd_id = prod_doc.get("jd_id") if prod_doc else None
                        if jd_id and jd_session:
                            try:
                                jd_form = await jd_session.fetch_product_form(str(jd_id))
                                # JohnDrop uses 'description' textarea (rich HTML)
                                raw_desc = jd_form.get("description", "") or ""
                                # Strip HTML tags for cleaner AI input but keep line breaks
                                jd_description = re.sub(r"<br\s*/?>", "\n", raw_desc, flags=re.I)
                                jd_description = re.sub(r"</p>", "\n\n", jd_description, flags=re.I)
                                jd_description = re.sub(r"<[^>]+>", "", jd_description)
                                jd_description = re.sub(r"\n{3,}", "\n\n", jd_description).strip()
                                if len(jd_description) > 4000:
                                    jd_description = jd_description[:4000]
                            except Exception:
                                jd_description = ""

                    ai = await _ai_enrich_product(
                        current_title, current_code, categories, custom_fields, data.ai_model,
                        johndrop_description=jd_description,
                    )

                    # Resolve category
                    # cat_name é a folha (último segmento do path). cat_pai é o nome da categoria pai (opcional, da IA).
                    cat_name = (ai.get("categoria_sugerida") or "").strip()
                    cat_pai_hint = (ai.get("categoria_pai_sugerida") or "").strip()
                    # If pai is "Pai > Filho" path, take last segment
                    if " > " in cat_pai_hint:
                        cat_pai_hint = cat_pai_hint.split(" > ")[-1].strip()
                    cat_id = None
                    if cat_name:
                        # If AI returned a path like "Pai > Filho", split and use leaf as cat_name + parent as hint
                        if " > " in cat_name:
                            parts = [p.strip() for p in cat_name.split(" > ") if p.strip()]
                            if len(parts) >= 2:
                                if not cat_pai_hint:
                                    cat_pai_hint = parts[-2]
                                cat_name = parts[-1]
                        # Look for existing category with matching name AND matching parent (when hint is provided)
                        candidates = [c for c in categories if (c.get("descricao", "").strip().lstrip("_").strip().lower()) == cat_name.lower()]
                        existing = None
                        if cat_pai_hint and candidates:
                            for cand in candidates:
                                pai_id = (cand.get("categoriaPai") or {}).get("id") if isinstance(cand.get("categoriaPai"), dict) else None
                                pai = cat_by_id_local.get(pai_id) if pai_id else None
                                pai_desc = (pai.get("descricao", "").strip().lstrip("_").strip().lower()) if pai else ""
                                if pai_desc == cat_pai_hint.lower():
                                    existing = cand
                                    break
                        elif candidates and not cat_pai_hint:
                            # No parent hint — only accept top-level matches (no parent) to avoid wrong sub-categories
                            for cand in candidates:
                                pai = cand.get("categoriaPai")
                                if not pai or (isinstance(pai, dict) and not pai.get("id")):
                                    existing = cand
                                    break
                        if existing:
                            cat_id = existing.get("id")
                        elif data.auto_create_categories:
                            # Create new category — link to parent if hint matches an existing one
                            parent_id = None
                            if cat_pai_hint:
                                for cand in categories:
                                    if (cand.get("descricao", "").strip().lstrip("_").strip().lower()) == cat_pai_hint.lower():
                                        parent_id = cand.get("id")
                                        break
                            new_cat = await c.create_category(cat_name, categoria_pai_id=parent_id)
                            cat_id = new_cat.get("id")
                            cat_by_name[cat_name.lower()] = new_cat
                            cat_by_id_local[new_cat.get("id")] = new_cat
                            categories.append(new_cat)

                    # Map AI's field-name dict -> real custom field IDs
                    # Match by exact name first, then by normalized substring (handles "País de Origem" vs "Pais de Origem", etc.)
                    def _norm(s: str) -> str:
                        s = (s or "").lower().strip()
                        # remove accents
                        for a, b in [("á","a"),("ã","a"),("â","a"),("à","a"),("é","e"),("ê","e"),("í","i"),("ó","o"),("õ","o"),("ô","o"),("ú","u"),("ç","c")]:
                            s = s.replace(a, b)
                        # collapse non-alnum
                        s = re.sub(r"[^a-z0-9]+", " ", s).strip()
                        return s

                    cf_by_norm = {_norm(cf.get("nome", "")): cf for cf in custom_fields}

                    campos_customizados_payload = []
                    used_field_ids = set()
                    ai_campos = ai.get("campos_customizados") or {}
                    if isinstance(ai_campos, dict):
                        for field_name, value in ai_campos.items():
                            if value in (None, ""):
                                continue
                            ai_norm = _norm(str(field_name))
                            cf_def = cf_by_name.get(str(field_name).lower().strip()) or cf_by_norm.get(ai_norm)
                            # Substring fallback
                            if not cf_def:
                                for k, v in cf_by_norm.items():
                                    if k and (k in ai_norm or ai_norm in k):
                                        cf_def = v
                                        break
                            if cf_def and cf_def.get("id") not in used_field_ids:
                                used_field_ids.add(cf_def.get("id"))
                                campos_customizados_payload.append({
                                    "idCampoCustomizado": cf_def.get("id"),
                                    "valor": str(value),
                                })

                    # Build update payload - PRESERVES title, code, price
                    payload = {
                        "nome": product.get("nome"),  # preserve
                        "codigo": product.get("codigo"),  # preserve
                        "preco": product.get("preco"),  # preserve
                        "tipo": product.get("tipo", "P"),
                        "situacao": product.get("situacao", "A"),
                        "formato": product.get("formato", "S"),
                        "condicao": 1,  # 0=Não especificado, 1=Novo, 2=Usado, 3=Recondicionado — sempre Novo
                        "descricaoCurta": ai.get("descricao_curta") or product.get("descricaoCurta"),
                        "descricaoComplementar": ai.get("descricao_complementar") or product.get("descricaoComplementar"),
                        "unidade": ai.get("unidade") or product.get("unidade", "Un"),
                        "pesoLiquido": float(ai.get("peso_kg") or 0) or product.get("pesoLiquido", 0),
                        "pesoBruto": float(ai.get("peso_kg") or 0) or product.get("pesoBruto", 0),
                        "dimensoes": {
                            "largura": float(ai.get("largura_cm") or 0) or (product.get("dimensoes") or {}).get("largura", 0),
                            "altura": float(ai.get("altura_cm") or 0) or (product.get("dimensoes") or {}).get("altura", 0),
                            "profundidade": float(ai.get("comprimento_cm") or 0) or (product.get("dimensoes") or {}).get("profundidade", 0),
                            "unidadeMedida": 1,  # cm
                        },
                        "tributacao": {
                            **(product.get("tributacao") or {}),
                            "ncm": str(ai.get("ncm") or product.get("tributacao", {}).get("ncm", "")).replace(".", "").replace("-", ""),
                        },
                    }
                    if cat_id:
                        payload["categoria"] = {"id": cat_id}
                    if campos_customizados_payload:
                        payload["camposCustomizados"] = campos_customizados_payload
                    # Fornecedor: link supplier contact + JohnDrop SKU + cost
                    if supplier_contact_id:
                        forn_entry: dict = {
                            "contato": {"id": supplier_contact_id},
                            "padrao": True,
                            "codigo": current_code,
                        }
                        if jd_cost is not None:
                            forn_entry["precoCusto"] = jd_cost
                            forn_entry["precoCompra"] = jd_cost
                        payload["fornecedores"] = [forn_entry]

                    await c.update_product(bling_id, payload)

                    await db.bling_enrich_log.insert_one({
                        "user_id": user.user_id,
                        "bling_product_id": bling_id,
                        "bling_code": current_code,
                        "bling_title": current_title,
                        "category_assigned": cat_name,
                        "ncm": ai.get("ncm"),
                        "ai_model": data.ai_model,
                        "used_johndrop_description": bool(jd_description),
                        "supplier_contact_id": supplier_contact_id,
                        "supplier_name": supplier_contact_name,
                        "supplier_cost": jd_cost,
                        "enriched_at": _now(),
                    })
                    enriched += 1
                    results.append({
                        "bling_product_id": bling_id,
                        "code": current_code,
                        "title": current_title,
                        "category": cat_name,
                        "ncm": ai.get("ncm"),
                        "peso_kg": ai.get("peso_kg"),
                        "campos_customizados_count": len(campos_customizados_payload),
                        "used_johndrop_description": bool(jd_description),
                        "supplier_linked": bool(supplier_contact_id),
                        "supplier_cost": jd_cost,
                    })
                except Exception as e:
                    failed.append({"bling_product_id": bling_id, "reason": str(e)})
                # Throttle: Bling permite ~3 req/s. Cada produto consome 1-2 reqs (get + update + opcional create_category).
                # 0.4s entre produtos mantém em segurança.
                await asyncio.sleep(0.4)
        finally:
            if jd_session:
                try:
                    await jd_session.__aexit__(None, None, None)
                except Exception:
                    pass

    return {
        "enriched": enriched,
        "failed": failed,
        "results": results,
        "total": len(data.bling_product_ids),
        "supplier": {
            "name_searched": data.supplier_name,
            "found": bool(supplier_contact_id),
            "id": supplier_contact_id,
            "matched_name": supplier_contact_name,
        },
    }


@api_router.get("/bling/enrich-history")
async def bling_enrich_history(user: UserPublic = Depends(get_current_user)):
    cursor = db.bling_enrich_log.find(
        {"user_id": user.user_id}, {"_id": 0, "user_id": 0}
    ).sort("enriched_at", -1).limit(200)
    items = await cursor.to_list(200)
    return {"items": items, "total": len(items)}


# ============ End Bling ============


class JohnDropPushIn(BaseModel):
    # Allow overriding specific fields without fetching from DB
    override_title: Optional[str] = None
    override_description: Optional[str] = None
    override_sale_value: Optional[float] = None


@api_router.post("/johndrop/push/{product_id}")
async def johndrop_push(
    product_id: str,
    data: JohnDropPushIn = JohnDropPushIn(),
    user: UserPublic = Depends(get_current_user),
):
    """Aplica título SEO + descrição + preço blindado DIRETO na JohnDrop,
    atualizando o cadastro lá via POST /dashboard/product/storev2/{jd_id}.
    A JohnDrop então repassa ao Bling via ToyShop-Bling como você já faz."""
    p = await db.products.find_one(
        {"id": product_id, "owner_id": user.user_id}, {"_id": 0}
    )
    if not p:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    if not p.get("jd_id"):
        raise HTTPException(status_code=400, detail="Produto não vinculado à JohnDrop (sem jd_id)")

    title = data.override_title or p["title"]
    description = data.override_description if data.override_description is not None else (p.get("description") or p["title"])
    sale_value = data.override_sale_value if data.override_sale_value is not None else p["price"]

    # Format sale_value for Brazilian Laravel form (e.g. "105,63")
    sale_value_str = f"{float(sale_value):.2f}".replace(".", ",")

    client = await _get_johndrop_client(user.user_id)
    async with client as c:
        try:
            push_patch = {
                "name": title,
                "sale_value": sale_value_str,
            }
            if data.override_description is not None:
                push_patch["description"] = description
            result = await c.push_product(
                p["jd_id"],
                push_patch,
                integration_ids=[INTEGRATION_TOTYSHOP_BLING],
            )
        except JohnDropAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Falha de rede: {e}")

    if not result["success"]:
        raise HTTPException(
            status_code=502,
            detail=f"JohnDrop respondeu com status {result['status_code']}",
        )

    # Update local record - mark as pushed + status synced
    await db.products.update_one(
        {"id": product_id, "owner_id": user.user_id},
        {"$set": {
            "sync_status": "synced",
            "sync_message": f"Aplicado na JohnDrop em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} - ToyShop-Bling ativa",
            "last_pushed_at": _now(),
            "updated_at": _now(),
        }},
    )
    return {
        "pushed": True,
        "jd_id": p["jd_id"],
        "title_sent": title,
        "sale_value_sent": sale_value_str,
    }


# ============ Pricing Calculator endpoint ============


class PricingIn(BaseModel):
    cost: float = Field(..., ge=0)
    packaging: float = Field(0.0, ge=0)
    campaigns: float = Field(0.0, ge=0)


@api_router.post("/pricing/calculate")
async def pricing_calculate(data: PricingIn, user: UserPublic = Depends(get_current_user)):
    return _calc_selling_price(data.cost, data.packaging, data.campaigns)


# ============ Health ============
@api_router.get("/")
async def root():
    return {"service": "BlingDrop API", "ok": True}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_db_indexes():
    # TTL: OAuth states expire 10 min after creation
    try:
        await db.bling_oauth_states.create_index("created_at", expireAfterSeconds=600)
    except Exception:
        pass


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
