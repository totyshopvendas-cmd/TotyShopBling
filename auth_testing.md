# Auth Testing Playbook (BlingDrop)

Backend supports TWO auth flows (both valid simultaneously):
1. **JWT email/password** - Bearer token (localStorage `bd_token`)
2. **Emergent Google Auth** - httpOnly cookie `session_token` OR Bearer <session_token>

## Step 1: Register/Login via JWT (fastest)
```bash
API=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)
curl -X POST "$API/api/auth/register" -H "Content-Type: application/json" \
  -d '{"email":"test@blingdrop.com","password":"Test1234!","name":"Test User"}'
# => { "token": "...", "user": {...} }

# Login
TOKEN=$(curl -s -X POST "$API/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"test@blingdrop.com","password":"Test1234!"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl "$API/api/auth/me" -H "Authorization: Bearer $TOKEN"
```

## Step 2: Direct MongoDB session seeding (for Google Auth simulation)
```bash
mongosh --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: null,
  auth_provider: 'google',
  created_at: new Date().toISOString()
});
var expires = new Date(Date.now() + 7*24*60*60*1000);
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: expires.toISOString(),
  created_at: new Date().toISOString()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 3: Test protected endpoints
```bash
curl "$API/api/dashboard/stats" -H "Authorization: Bearer $TOKEN"
curl "$API/api/products" -H "Authorization: Bearer $TOKEN"
curl -X POST "$API/api/products/seed" -H "Authorization: Bearer $TOKEN"
```

## Step 4: Browser testing (for session_token cookie)
```python
await page.context.add_cookies([{
    "name": "session_token",
    "value": "<SESSION_TOKEN>",
    "domain": "<preview-domain>",
    "path": "/",
    "httpOnly": True,
    "secure": True,
    "sameSite": "None"
}])
await page.goto("https://<preview-domain>/dashboard")
```

## Checklist
- [ ] JWT register/login returns token + user
- [ ] /api/auth/me works with Bearer JWT
- [ ] /api/auth/me works with session_token cookie (Google flow)
- [ ] All queries use `{"_id": 0}` projection
- [ ] Product CRUD requires auth
- [ ] AI endpoints (/api/ai/*) require auth
- [ ] Title generator enforces 60-char max
- [ ] Bullets generator returns 6 items
- [ ] Sync validator catches: >60 chars, <6 bullets, no weight (Shopee), no stock
EOF