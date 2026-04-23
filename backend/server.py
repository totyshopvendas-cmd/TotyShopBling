from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Cookie, Header
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
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
    if update_doc.get("stock_johndrop", 0) <= 0:
        update_doc["sync_status"] = "out_of_stock"
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
        "title": "Creme Facial Hidratante Antioxidante 50g JD001",
        "brand": "DermaBrasil",
        "ean": "7891234560011",
        "description": "Creme facial hidratante com ativos antioxidantes para uso diário.",
        "price": 89.90,
        "cost": 32.50,
        "stock_johndrop": 45,
        "stock_bling": 45,
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
        "kwai": {
            "enabled": False,
        },
    },
    {
        "sku": "JD-ELE-002",
        "product_code": "JD002",
        "title": "Mini Ventilador USB Recarregável Portátil JD002",
        "brand": "CoolTech",
        "ean": "7891234560028",
        "description": "Ventilador portátil com bateria recarregável e 3 velocidades.",
        "price": 79.90,
        "cost": 28.00,
        "stock_johndrop": 0,
        "stock_bling": 12,
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
        "title": "Organizador Multiuso Cozinha Gaveta JD003",
        "brand": "CasaPratica",
        "ean": "7891234560035",
        "description": "Organizador modular para gavetas de cozinha.",
        "price": 49.90,
        "cost": 18.00,
        "stock_johndrop": 120,
        "stock_bling": 80,
        "images": [
            "https://images.unsplash.com/photo-1584472666879-7d92db132958?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1ODF8MHwxfHNlYXJjaHwzfHxlY29tbWVyY2UlMjBsb2dpc3RpY3MlMjBkYXNoYm9hcmR8ZW58MHx8fHwxNzc2OTAzNTYyfDA&ixlib=rb-4.1.0&q=85"
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
]


@api_router.post("/products/seed")
async def seed_products(user: UserPublic = Depends(get_current_user)):
    created = 0
    for p in SEED_PRODUCTS:
        existing = await db.products.find_one(
            {"sku": p["sku"], "owner_id": user.user_id}, {"_id": 0}
        )
        if existing:
            continue
        pid = f"prod_{uuid.uuid4().hex[:12]}"
        now = _now()
        sync_status = "pending"
        if p["stock_johndrop"] != p["stock_bling"]:
            sync_status = "pending"
        if p["stock_johndrop"] <= 0:
            sync_status = "out_of_stock"
        doc = {
            "id": pid,
            "owner_id": user.user_id,
            **p,
            "sync_status": sync_status,
            "sync_message": "Importado da JohnDrop - aguardando sincronização Bling",
            "created_at": now,
            "updated_at": now,
        }
        await db.products.insert_one(doc)
        created += 1
    return {"created": created, "total_available": len(SEED_PRODUCTS)}


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
