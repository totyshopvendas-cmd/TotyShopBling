"""BlingDrop backend regression tests - auth, products, sync, dashboard, integrations, AI."""
import os
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://bling-johndrop-sync.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

EMAIL = f"test+{uuid.uuid4().hex[:6]}@blingdrop.com"
PASSWORD = "Test1234!"
NAME = "Test User"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def auth(session):
    r = session.post(f"{API}/auth/register", json={"email": EMAIL, "password": PASSWORD, "name": NAME}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "_id" not in data and "_id" not in data["user"]
    token = data["token"]
    return {"token": token, "user_id": data["user"]["user_id"], "email": EMAIL}


@pytest.fixture(scope="module")
def headers(auth):
    return {"Authorization": f"Bearer {auth['token']}", "Content-Type": "application/json"}


# -------- Auth --------
def test_health(session):
    r = session.get(f"{API}/", timeout=15)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_register_duplicate(session, auth):
    r = session.post(f"{API}/auth/register", json={"email": auth["email"], "password": PASSWORD, "name": NAME}, timeout=15)
    assert r.status_code == 400


def test_login_ok(session, auth):
    r = session.post(f"{API}/auth/login", json={"email": auth["email"], "password": PASSWORD}, timeout=15)
    assert r.status_code == 200 and r.json()["user"]["email"] == auth["email"]


def test_login_bad(session, auth):
    r = session.post(f"{API}/auth/login", json={"email": auth["email"], "password": "wrong"}, timeout=15)
    assert r.status_code == 401


def test_me_jwt(session, headers):
    r = session.get(f"{API}/auth/me", headers=headers, timeout=15)
    assert r.status_code == 200
    assert "_id" not in r.json()


def test_me_no_auth(session):
    r = session.get(f"{API}/auth/me", timeout=15)
    assert r.status_code == 401


def test_me_session_cookie(session, auth):
    """Seed a session_token directly in MongoDB and verify cookie + bearer auth."""
    from pymongo import MongoClient
    from datetime import datetime, timezone, timedelta
    mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mc[os.environ.get("DB_NAME", "test_database")]
    stoken = f"sess_{uuid.uuid4().hex}"
    db.user_sessions.insert_one({
        "user_id": auth["user_id"],
        "session_token": stoken,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # cookie
    r = requests.get(f"{API}/auth/me", cookies={"session_token": stoken}, timeout=15)
    assert r.status_code == 200, r.text
    # bearer fallback
    r2 = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {stoken}"}, timeout=15)
    assert r2.status_code == 200


def test_logout(session):
    r = session.post(f"{API}/auth/logout", timeout=15)
    assert r.status_code == 200


# -------- Products --------
def test_products_auth_gated(session):
    for path in ["/products", "/dashboard/stats", "/integrations/status"]:
        assert session.get(f"{API}{path}", timeout=15).status_code == 401


def test_seed_products(session, headers):
    r = session.post(f"{API}/products/seed", headers=headers, timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["created"] == 3 and j["total_available"] == 3
    # idempotent
    r2 = session.post(f"{API}/products/seed", headers=headers, timeout=20)
    assert r2.json()["created"] == 0


def test_list_and_get(session, headers):
    r = session.get(f"{API}/products", headers=headers, timeout=15)
    assert r.status_code == 200
    products = r.json()
    assert len(products) == 3
    for p in products:
        assert "_id" not in p
        assert "amazon" in p and "shopee" in p and "kwai" in p
    pid = products[0]["id"]
    r2 = session.get(f"{API}/products/{pid}", headers=headers, timeout=15)
    assert r2.status_code == 200 and r2.json()["id"] == pid


def test_create_update_delete(session, headers):
    payload = {
        "sku": f"TEST_{uuid.uuid4().hex[:6]}", "title": "Produto Teste", "product_code": "T001",
        "price": 10.0, "cost": 5.0, "stock_johndrop": 5, "stock_bling": 5,
    }
    r = session.post(f"{API}/products", headers=headers, json=payload, timeout=15)
    assert r.status_code == 200
    pid = r.json()["id"]
    payload["title"] = "Atualizado"
    r2 = session.put(f"{API}/products/{pid}", headers=headers, json=payload, timeout=15)
    assert r2.status_code == 200 and r2.json()["title"] == "Atualizado"
    r3 = session.delete(f"{API}/products/{pid}", headers=headers, timeout=15)
    assert r3.status_code == 200
    r4 = session.get(f"{API}/products/{pid}", headers=headers, timeout=15)
    assert r4.status_code == 404


def test_sync_success_and_stock_replication(session, headers):
    # JD001 has 6 bullets, weight, valid
    products = session.get(f"{API}/products", headers=headers, timeout=15).json()
    jd001 = next(p for p in products if p["sku"] == "JD-CRM-001")
    r = session.post(f"{API}/products/{jd001['id']}/sync", headers=headers, timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["sync_status"] == "synced"
    assert j["stock_bling"] == j["stock_johndrop"]


def test_sync_out_of_stock(session, headers):
    products = session.get(f"{API}/products", headers=headers, timeout=15).json()
    jd002 = next(p for p in products if p["sku"] == "JD-ELE-002")
    r = session.post(f"{API}/products/{jd002['id']}/sync", headers=headers, timeout=20)
    j = r.json()
    assert j["sync_status"] == "error"
    assert "estoque" in j["sync_message"].lower()


def test_sync_validation_title_too_long(session, headers):
    payload = {
        "sku": f"TEST_{uuid.uuid4().hex[:6]}",
        "title": "T" * 70, "product_code": "X",
        "stock_johndrop": 10, "stock_bling": 10,
        "amazon": {"enabled": True, "bullet_points": ["a"] * 6},
        "shopee": {"enabled": True, "weight_kg": 0.5},
    }
    r = session.post(f"{API}/products", headers=headers, json=payload, timeout=15)
    pid = r.json()["id"]
    r2 = session.post(f"{API}/products/{pid}/sync", headers=headers, timeout=20)
    msg = r2.json()["sync_message"]
    assert "60" in msg


def test_sync_validation_bullets_and_weight(session, headers):
    payload = {
        "sku": f"TEST_{uuid.uuid4().hex[:6]}",
        "title": "Curto", "product_code": "X",
        "stock_johndrop": 10, "stock_bling": 10,
        "amazon": {"enabled": True, "bullet_points": ["a", "b", "", "", "", ""]},
        "shopee": {"enabled": True, "weight_kg": None},
    }
    r = session.post(f"{API}/products", headers=headers, json=payload, timeout=15)
    pid = r.json()["id"]
    r2 = session.post(f"{API}/products/{pid}/sync", headers=headers, timeout=20)
    msg = r2.json()["sync_message"]
    assert "bullet" in msg.lower() and "peso" in msg.lower()


# -------- Dashboard --------
def test_dashboard_stats(session, headers):
    r = session.get(f"{API}/dashboard/stats", headers=headers, timeout=15)
    assert r.status_code == 200
    j = r.json()
    for k in ("total_products", "synced", "pending", "errors", "marketplace_coverage", "stock_divergences"):
        assert k in j
    assert "amazon" in j["marketplace_coverage"]


# -------- Integrations --------
def test_integrations_default_and_toggle(session, headers):
    r = session.get(f"{API}/integrations/status", headers=headers, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["bling"]["connected"] is False
    r2 = session.post(f"{API}/integrations/toggle", headers=headers,
                      json={"service": "bling", "connected": True}, timeout=15)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["bling"]["connected"] is True and j2["bling"]["token_valid"] is True
    assert j2["bling"]["last_sync"] is not None


# -------- AI --------
@pytest.mark.parametrize("model", ["claude", "gpt"])
def test_ai_generate_title(session, headers, model):
    body = {"product_code": "JD001", "category": "Skincare", "keywords": "creme facial",
            "raw_name": "Creme Facial Hidratante 50g", "model": model}
    r = session.post(f"{API}/ai/generate-title", headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"LLM ({model}) error {r.status_code}: {r.text[:200]}")
    j = r.json()
    assert len(j["title"]) <= 60 and j["length"] == len(j["title"])


def test_ai_generate_bullets(session, headers):
    body = {"title": "Creme Facial Hidratante 50g JD001", "product_code": "JD001",
            "category": "Skincare", "keywords": "hidratante", "model": "claude"}
    r = session.post(f"{API}/ai/generate-bullets", headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"LLM error: {r.text[:200]}")
    bullets = r.json()["bullets"]
    assert len(bullets) == 6


def test_ai_generate_description(session, headers):
    body = {"title": "Creme Facial Hidratante 50g JD001",
            "bullets": ["Hidrata por 24h", "Vitamina C", "Toque seco", "Todos os tipos", "Não comedogênico", "JD001"],
            "model": "claude"}
    r = session.post(f"{API}/ai/generate-description", headers=headers, json=body, timeout=60)
    if r.status_code != 200:
        pytest.skip(f"LLM error: {r.text[:200]}")
    assert isinstance(r.json()["description"], str) and len(r.json()["description"]) > 50


# -------- AI auth gating --------
def test_ai_auth_gated(session):
    r = session.post(f"{API}/ai/generate-title",
                     json={"product_code": "x", "raw_name": "x", "model": "claude"}, timeout=15)
    assert r.status_code == 401
