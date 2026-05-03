"""Bling API v3 client (OAuth 2.0).
Docs: https://developer.bling.com.br/bling-api
"""
from __future__ import annotations

import base64
import secrets
from typing import Optional
from datetime import datetime, timezone, timedelta

import httpx


AUTHORIZE_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://www.bling.com.br/Api/v3/oauth/token"
API_BASE = "https://api.bling.com.br/Api/v3"


class BlingAuthError(Exception):
    pass


class BlingAPIError(Exception):
    pass


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """OAuth consent page URL."""
    from urllib.parse import urlencode
    params = {
        "response_type": "code",
        "client_id": client_id,
        "state": state,
        "redirect_uri": redirect_uri,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def generate_state() -> str:
    return secrets.token_urlsafe(24)


async def exchange_code_for_tokens(client_id: str, client_secret: str, code: str) -> dict:
    """Exchange authorization code for access_token + refresh_token."""
    auth_str = f"{client_id}:{client_secret}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
            },
        )
        if r.status_code != 200:
            raise BlingAuthError(f"Token exchange failed: {r.status_code} - {r.text[:300]}")
        return r.json()


async def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    auth_str = f"{client_id}:{client_secret}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if r.status_code != 200:
            raise BlingAuthError(f"Refresh failed: {r.status_code} - {r.text[:300]}")
        return r.json()


class BlingClient:
    """Authenticated client using access_token.
    Caller is responsible for providing a valid token (handling refresh externally)."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=30,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json",
            },
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # ---- Products ----
    async def list_products(self, page: int = 1, limit: int = 100, criterio: int = 1, tipo: Optional[str] = None) -> list:
        params = {"pagina": page, "limite": min(limit, 100), "criterio": criterio}
        if tipo:
            params["tipo"] = tipo
        r = await self._client.get("/produtos", params=params)
        if r.status_code == 401:
            raise BlingAuthError("Token inválido ou expirado")
        if r.status_code != 200:
            raise BlingAPIError(f"list_products: {r.status_code} - {r.text[:200]}")
        return r.json().get("data", [])

    async def get_product(self, product_id: str | int) -> dict:
        r = await self._client.get(f"/produtos/{product_id}")
        if r.status_code == 401:
            raise BlingAuthError("Token expirado")
        if r.status_code != 200:
            raise BlingAPIError(f"get_product: {r.status_code} - {r.text[:200]}")
        return r.json().get("data", {})

    async def update_product(self, product_id: str | int, payload: dict) -> dict:
        """PUT full product (Bling v3 uses PUT for full replace, PATCH deprecated in favor of partial fields)."""
        r = await self._client.put(f"/produtos/{product_id}", json=payload)
        if r.status_code == 401:
            raise BlingAuthError("Token expirado")
        if r.status_code not in (200, 204):
            raise BlingAPIError(f"update_product {product_id}: {r.status_code} - {r.text[:300]}")
        try:
            return r.json().get("data", {})
        except Exception:
            return {}

    # ---- Categorias de produtos ----
    async def list_categories(self, page: int = 1, limit: int = 100) -> list:
        r = await self._client.get("/categorias/produtos", params={"pagina": page, "limite": limit})
        if r.status_code == 401:
            raise BlingAuthError("Token expirado")
        if r.status_code != 200:
            raise BlingAPIError(f"list_categories: {r.status_code} - {r.text[:200]}")
        return r.json().get("data", [])

    async def create_category(self, descricao: str, categoria_pai_id: Optional[int] = None) -> dict:
        body = {"descricao": descricao}
        if categoria_pai_id:
            body["categoriaPai"] = {"id": categoria_pai_id}
        r = await self._client.post("/categorias/produtos", json=body)
        if r.status_code == 401:
            raise BlingAuthError("Token expirado")
        if r.status_code not in (200, 201):
            raise BlingAPIError(f"create_category: {r.status_code} - {r.text[:200]}")
        return r.json().get("data", {})

    # ---- Contatos (Fornecedores) ----
    async def list_contacts(self, page: int = 1, limit: int = 100, tipo: str = "F") -> list:
        """tipo=F: Fornecedor, C: Cliente, etc."""
        r = await self._client.get("/contatos", params={"pagina": page, "limite": limit})
        if r.status_code == 401:
            raise BlingAuthError("Token expirado")
        if r.status_code != 200:
            raise BlingAPIError(f"list_contacts: {r.status_code} - {r.text[:200]}")
        return r.json().get("data", [])

    # ---- Depositos ----
    async def list_deposits(self) -> list:
        r = await self._client.get("/depositos")
        if r.status_code == 401:
            raise BlingAuthError("Token expirado")
        if r.status_code != 200:
            raise BlingAPIError(f"list_deposits: {r.status_code} - {r.text[:200]}")
        return r.json().get("data", [])

    # ---- Campos Customizados (produtos) ----
    async def list_custom_field_modules(self) -> list:
        r = await self._client.get("/campos-customizados/modulos")
        if r.status_code != 200:
            return []
        return r.json().get("data", [])

    async def list_custom_fields(self, module_id: int) -> list:
        """Lista campos customizados de um módulo. Para produtos, idModulo costuma ser específico.
        Retorna definições com {id, nome, tipo, valoresDePreenchimento?}."""
        r = await self._client.get(f"/campos-customizados/modulos/{module_id}")
        if r.status_code != 200:
            return []
        return r.json().get("data", [])

    async def list_product_custom_fields(self) -> list:
        """Tenta localizar o módulo de produtos e lista seus campos."""
        modulos = await self.list_custom_field_modules()
        # Identifica o módulo de produtos pelo nome
        produto_mod = None
        for m in modulos:
            nome = (m.get("nome") or "").lower()
            if "produto" in nome:
                produto_mod = m
                break
        if not produto_mod:
            return []
        return await self.list_custom_fields(produto_mod["id"])
