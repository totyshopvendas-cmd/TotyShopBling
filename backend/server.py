from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
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
    encrypt_secret,
    decrypt_secret,
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
                        "description": p.get("description") or p["title"],
                        "sale_value": sale_value_str,
                    },
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
            result = await c.push_product(
                p["jd_id"],
                {
                    "name": title,
                    "description": description,
                    "sale_value": sale_value_str,
                },
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


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
