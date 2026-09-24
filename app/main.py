"""SambiraPandoraBox — ISP Operations Dashboard.

Stack: FastAPI + Jinja2 (server-rendered) + SQLite. No external services required.
Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import os, json, csv, io, sqlite3, datetime, secrets, calendar, random, time
from typing import Optional
from fastapi import FastAPI, Request, Form, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import RedirectResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, seed as seeder, routeros, notify

BASE = os.path.dirname(__file__)
DATA = os.path.abspath(os.path.join(BASE, "..", "data"))
BACKUP_DIR = os.path.join(DATA, "backups"); UPLOAD_DIR = os.path.join(DATA, "uploads")
os.makedirs(BACKUP_DIR, exist_ok=True); os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="SambiraPandoraBox", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

# ---------------------------------------------------------------- bootstrap

# ------------------------------------------------------------- page fallback
from starlette.middleware.base import BaseHTTPMiddleware as _BHM

PAGE_MODULES = {'/login': None, '/logout': None, '/forgot-password': None, '/reset-password': None, '/profile': None, '/': None, '/dashboard': None, '/customers': None, '/customers/new': None, '/customers/{cid}': None, '/customers/{cid}/edit': None, '/export/customers.csv': None, '/packages': None, '/pppoe': None, '/pppoe/new': None, '/pppoe/{aid}': None, '/pppoe/{aid}/edit': None, '/hotspot': None, '/hotspot/vouchers': None, '/export/vouchers.csv': None, '/routers': None, '/routers/new': None, '/routers/{rid}': None, '/routers/{rid}/edit': None, '/monitoring': None, '/billing': None, '/billing/overdue': None, '/billing/new': None, '/billing/{iid}': None, '/billing/{iid}/print': None, '/export/invoices.csv': None, '/payments': None, '/payments/new': None, '/payments/{pid}': None, '/export/payments.csv': None, '/finance': None, '/expenses': None, '/backups': None, '/backups/{bid}/download': None, '/notifications': None, '/qris': None, '/uploads/{fn}': None, '/users': None, '/activity-log': None, '/settings': None, '/landing-editor': None, '/sambutan': None, '/favicon.ico': None}

def _page_fallback(request, exc):
    """Route GET yang belum diimplementasi -> placeholder jujur, bukan traceback 500."""
    rp = request.url.path
    u = current_user(request)
    mod = PAGE_MODULES.get(rp) or next((v for k, v in PAGE_MODULES.items()
                                        if "{" in k and _re.match("^" + k.replace("{", "(?:").replace("}", ")[a-z0-9-]+)?") + "$", rp)), None) if False else PAGE_MODULES.get(rp)
    # resolve parameterized routes: match template pattern against real path
    if mod is None and rp not in PAGE_MODULES:
        import re as _r
        for k, v in PAGE_MODULES.items():
            if "{" in k:
                pat = "^" + _r.escape(k).replace("\\{", "{").replace("\\}", "}")
                pat = _r.sub(r"\\\{[^}]+\\\}", "[^/]+", pat)
                pat = _r.sub(r"\{[^}]+\}", "[^/]+", _r.escape(k).replace("\{","{").replace("\}","}")) + "$"
                if _r.match(pat, rp): mod = v; break
    if u is None: raise exc
    if mod and not can(u["role"], mod):
        return templates.TemplateResponse(request, "error.html", ctx(
            request, u, code="403", status_code=403,
            message="Akses ditolak: modul ini tidak tersedia untuk peran Anda.", active=""))
    return templates.TemplateResponse(request, "error.html", ctx(
        request, u, code="INFO", status_code=200,
        message="Halaman ini <b>segera tersedia</b> — belum diimplementasi pada build demo ini.",
        active=""))

_init = db.connect(); _init.executescript(db.SCHEMA); seeder.seed(_init); _init.close()

@app.middleware("http")
async def db_mw(request: Request, call_next):
    request.state.con = db.connect()
    try:
        return await call_next(request)
    finally:
        request.state.con.close()

def C(request): return request.state.con

# ---------------------------------------------------------------- auth/roles
ROLES = {"superadmin": "Super Admin", "admin": "Admin", "operator": "Operator", "finance": "Finance"}
PERMS = {
  "dashboard": ["superadmin","admin","operator","finance"],
  "customers": ["superadmin","admin","operator"],
  "packages":  ["superadmin","admin","operator"],
  "pppoe":     ["superadmin","admin","operator"],
  "hotspot":   ["superadmin","admin","operator"],
  "routers":   ["superadmin","admin","operator"],
  "monitoring":["superadmin","admin","operator"],
  "billing":   ["superadmin","admin","finance"],
  "payments":  ["superadmin","admin","finance"],
  "finance":   ["superadmin","admin","finance"],
  "expenses":  ["superadmin","admin","finance"],
  "backups":   ["superadmin","admin"],
  "notifications": ["superadmin","admin","operator","finance"],
  "qris":      ["superadmin","admin","finance"],
  "landing":   ["superadmin","admin"],
  "users":     ["superadmin"],
  "activity":  ["superadmin","admin"],
  "settings":  ["superadmin"],
}
def can(role, mod): return (role or "") in PERMS.get(mod, [])

class PermissionDenied(Exception): pass

def current_user(request):
    sid = request.cookies.get("spb_sid")
    if not sid: return None
    return db.one(C(request),
        "SELECT u.* FROM sessions_tbl s JOIN users u ON u.id=s.user_id WHERE s.sid=? AND u.active=1", (sid,))

def require(request, module=None):
    u = current_user(request)
    if not u: raise NeedLogin()
    if module and not can(u["role"], module): raise PermissionDenied()
    return u

class NeedLogin(Exception): pass

@app.exception_handler(NeedLogin)
async def exc_login(request, exc):
    return RedirectResponse("/login", status_code=303)

@app.exception_handler(PermissionDenied)
async def exc_perm(request, exc):
    return templates.TemplateResponse(request, "error.html",
        ctx(request, current_user(request), code=403,
            message="Akses ditolak: peran Anda tidak memiliki izin untuk modul ini."), status_code=403)

@app.exception_handler(HTTPException)
async def exc_http(request, exc):
    if exc.status_code in (307, 303): return RedirectResponse(exc.headers.get("Location","/login"), 303)
    msg = {404: "Halaman / data tidak ditemukan."}.get(exc.status_code, str(exc.detail))
    return templates.TemplateResponse(request, "error.html",
        ctx(request, current_user(request), code=exc.status_code, message=msg), status_code=exc.status_code)

# ---------------------------------------------------------------- helpers
def fmt_rp(n):
    try: n = int(n)
    except Exception: n = 0
    neg = "-" if n < 0 else ""
    return f"{neg}Rp{abs(n):,}".replace(",", ".")

def rp_filter(v): return fmt_rp(v)
templates.env.filters["rp"] = rp_filter

async def form(request):
    fd = await request.form()
    return {k: (v[0] if isinstance(v, list) else v) for k, v in fd.items()}

def pint(v, d=0):
    try: return int(str(v).strip())
    except Exception: return d

def flash_set(response: RedirectResponse, msg, kind="ok"):
    response.set_cookie("spb_flash", json.dumps({"m": msg, "k": kind}), path="/", max_age=60, httponly=True)
    return response

NAV = [
 ("Dashboard","/dashboard","gauge","dashboard","dashboard"),
 ("Pelanggan","/customers","users","customers","customers"),
 ("Paket Internet","/packages","box","packages","packages"),
 ("PPPoE","/pppoe","network","pppoe","pppoe"),
 ("Hotspot","/hotspot","wifi","hotspot","hotspot"),
 ("Voucher Hotspot","/hotspot/vouchers","ticket","hotspot","vouchers"),
 ("Router","/routers","router","routers","routers"),
 ("Monitoring Jaringan","/monitoring","pulse","monitoring","monitoring"),
 ("Penagihan","/billing","receipt","billing","billing"),
 ("Pembayaran","/payments","wallet","payments","payments"),
 ("Keuangan","/finance","chart","finance","finance"),
 ("Pengeluaran","/expenses","money","expenses","expenses"),
 ("Backup","/backups","disk","backups","backups"),
 ("Notifikasi","/notifications","bell","notifications","notifications"),
 ("QRIS","/qris","qr","qris","qris"),
 ("Editor Landing Page","/landing-editor","edit","landing","landing"),
 ("Pengguna & Peran","/users","shield","users","users"),
 ("Log Aktivitas","/activity-log","list","activity","activity"),
 ("Pengaturan","/settings","cog","settings","settings"),
]

def ctx(request, user, **kw):
    con = C(request)
    settings = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    flash = None
    raw = request.cookies.get("spb_flash")
    if raw:
        try: flash = json.loads(raw)
        except Exception: flash = None
    tc = request.cookies.get("spb_theme")
    if tc: settings["theme"] = tc
    d = {"user": user, "settings": settings, "flash": flash, "today": datetime.date.today().isoformat(),
         "nav": [n for n in NAV if can(user["role"] if user else None, n[3])],
         "app_name": "SambiraPandoraBox", "active": kw.pop("active", ""), "roles": ROLES}
    d.update(kw)
    return d

def paginate(request, total, page_str, size):
    try: p = max(1, int(page_str))
    except Exception: p = 1
    pages = max(1, (total + size - 1) // size)
    p = min(p, pages)
    return p, pages, (p - 1) * size

def qs(**kw):
    items = {k: v for k, v in kw.items() if v not in (None, "", "asc_default")}
    return "&".join(f"{k}={v}" for k, v in items.items())

templates.env.globals["qs"] = qs

# ================================================================= LOGIN
@app.get("/login", response_class=Response)
def login_page(request: Request):
    if current_user(request): return RedirectResponse("/dashboard", 303)
    return templates.TemplateResponse(request, "login.html", ctx(request, None))

@app.post("/login")
async def login_do(request: Request, username: str = Form(""), password: str = Form("")):
    con = C(request)
    u = db.one(con, "SELECT * FROM users WHERE username=?", (username.strip(),))
    if not u or not db.check_pw(password, u["password_hash"]):
        return templates.TemplateResponse(request, "login.html",
            ctx(request, None, error="Username atau kata sandi salah."), status_code=401)
    if not u["active"]:
        return templates.TemplateResponse(request, "login.html",
            ctx(request, None, error="Akun dinonaktifkan. Hubungi Super Admin."), status_code=403)
    sid = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions_tbl VALUES(?,?,?)", (sid, u["id"], db.now()))
    db.log_activity(con, u["username"], "login", "Sesi", f"Login ({ROLES[u['role']]})")
    con.commit()
    r = RedirectResponse("/dashboard", status_code=303)
    r.set_cookie("spb_sid", sid, httponly=True, samesite="lax")
    return r

@app.get("/logout")
def logout(request: Request):
    con = C(request); sid = request.cookies.get("spb_sid"); u = current_user(request)
    if sid: con.execute("DELETE FROM sessions_tbl WHERE sid=?", (sid,))
    if u: db.log_activity(con, u["username"], "logout", "Sesi", "")
    con.commit()
    r = RedirectResponse("/login", status_code=303); r.delete_cookie("spb_sid"); r.delete_cookie("spb_flash")
    return r

@app.get("/forgot-password", response_class=Response)
def forgot_page(request: Request):
    return templates.TemplateResponse(request, "forgot.html", ctx(request, None))

@app.post("/forgot-password")
async def forgot_do(request: Request, email: str = Form("")):
    con = C(request)
    u = db.one(con, "SELECT * FROM users WHERE email=?", (email.strip(),))
    token = None; msg = "Permintaan dicatat. Jika email tidak terdaftar, tidak ada tautan yang dibuat."
    if u:
        token = secrets.token_urlsafe(16)
        con.execute("INSERT INTO resets(email,token,created_at) VALUES(?,?,?)", (u["email"], token, db.now()))
        con.commit()
        msg = ("Tautan reset dibuat. SMTP tidak tersedia di lingkungan ini, jadi tautan ditampilkan "
               "langsung (mode DEMO — tidak ada email yang benar-benar dikirim).")
    return templates.TemplateResponse(request, "forgot.html",
        ctx(request, None, result_msg=msg, reset_token=token))

@app.get("/reset-password", response_class=Response)
def reset_get(request: Request, token: str = ""):
    r = db.one(C(request), "SELECT * FROM resets WHERE token=?", (token,))
    return templates.TemplateResponse(request, "reset.html", ctx(request, None, token=token, valid=bool(r)))

@app.post("/reset-password")
async def reset_post(request: Request, token: str = Form(""), password: str = Form("")):
    con = C(request)
    r = db.one(con, "SELECT * FROM resets WHERE token=?", (token,))
    if not r:
        return templates.TemplateResponse(request, "reset.html",
            ctx(request, None, token=token, error="Token tidak valid / kedaluwarsa."), status_code=400)
    if len(password) < 6:
        return templates.TemplateResponse(request, "reset.html",
            ctx(request, None, token=token, error="Kata sandi minimal 6 karakter."), status_code=400)
    con.execute("UPDATE users SET password_hash=? WHERE email=?", (db.hash_pw(password), r["email"]))
    con.execute("DELETE FROM resets WHERE token=?", (token,)); con.commit()
    return templates.TemplateResponse(request, "reset.html", ctx(request, None, done=True, token=""))

@app.get("/profile", response_class=Response)
def profile(request: Request):
    u = require(request)
    return templates.TemplateResponse(request, "profile.html", ctx(request, u, me=u))

@app.post("/profile/password")
async def profile_password(request: Request, old: str = Form(""), new: str = Form(""), confirm: str = Form("")):
    u = require(request); con = C(request)
    if not db.check_pw(old, u["password_hash"]):
        return flash_set(RedirectResponse("/profile", 303), "Kata sandi lama salah.", "err")
    if len(new) < 6:
        return flash_set(RedirectResponse("/profile", 303), "Kata sandi baru minimal 6 karakter.", "err")
    if new != confirm:
        return flash_set(RedirectResponse("/profile", 303), "Konfirmasi kata sandi tidak cocok.", "err")
    con.execute("UPDATE users SET password_hash=? WHERE id=?", (db.hash_pw(new), u["id"]))
    db.log_activity(con, u["username"], "user.password", "Profil", "Ganti kata sandi"); con.commit()
    return flash_set(RedirectResponse("/profile", 303), "Kata sandi berhasil diubah.")

# ================================================================= DASHBOARD
@app.get("/", response_class=Response)
def home(request: Request):
    return RedirectResponse("/dashboard" if current_user(request) else "/sambutan", 303)

@app.get("/dashboard", response_class=Response)
def dashboard(request: Request):
    u = require(request, "dashboard"); con = C(request)
    month = datetime.date.today().strftime("%Y-%m")
    cnt = lambda w, a=(): db.one(con, f"SELECT COUNT(*) n FROM {w}", a)["n"]
    stats = {
      "cust_total": cnt("customers"),
      "cust_active": cnt("customers WHERE status='aktif'"),
      "cust_suspend": cnt("customers WHERE status='suspend'"),
      "inv_unpaid": cnt("invoices WHERE status IN ('belum_bayar','lewat_jatuh_tempo')"),
      "unpaid_amount": db.one(con, "SELECT COALESCE(SUM(amount-paid_amount),0) s FROM invoices WHERE status IN ('belum_bayar','lewat_jatuh_tempo')")["s"],
      "revenue_month": db.one(con, "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE date LIKE ?", (month+"%",))["s"],
      "pppoe_online": cnt("pppoe_accounts WHERE online=1"),
      "pppoe_total": cnt("pppoe_accounts"),
      "hs_active": cnt("hotspot_users WHERE used=0 AND status='aktif'"),
      "overdue": cnt("invoices WHERE status='lewat_jatuh_tempo'"),
    }
    routers = db.q(con, "SELECT * FROM routers ORDER BY id")
    payments = db.q(con, """SELECT p.*, c.name cname, i.number inv FROM payments p
        JOIN customers c ON c.id=p.customer_id LEFT JOIN invoices i ON i.id=p.invoice_id
        ORDER BY p.date DESC, p.id DESC LIMIT 6""")
    events = db.q(con, "SELECT * FROM events ORDER BY time DESC LIMIT 6")
    acts = db.q(con, "SELECT * FROM activity_log ORDER BY ts DESC, id DESC LIMIT 8")
    rev = db.q(con, "SELECT substr(date,1,7) m, SUM(amount) s FROM payments GROUP BY m ORDER BY m DESC LIMIT 6")
    rev.reverse()
    st = db.q(con, "SELECT status, COUNT(*) n FROM invoices GROUP BY status")
    return templates.TemplateResponse(request, "dashboard.html", ctx(request, u,
        stats=stats, routers=routers, payments=payments, events=events, acts=acts,
        chart_rev=json.dumps([{"label": r["m"], "value": r["s"]} for r in rev]),
        chart_status=json.dumps([{"label": s["status"], "value": s["n"]} for s in st])))

# ================================================================= CUSTOMERS
CUST_SELECT = """SELECT c.*, p.name pname, p.price pprice, r.name rname
    FROM customers c LEFT JOIN packages p ON p.id=c.package_id LEFT JOIN routers r ON r.id=c.router_id"""

@app.get("/customers", response_class=Response)
def customers(request: Request, search: str = "", status: str = "", pkg: str = "",
              sort: str = "id", dir: str = "asc", page: str = "1"):
    u = require(request, "customers"); con = C(request)
    where, args = [], []
    if search:
        where.append("(c.name LIKE ? OR c.code LIKE ? OR c.phone LIKE ? OR c.pppoe_username LIKE ?)")
        args += [f"%{search}%"] * 4
    if status: where.append("c.status=?"); args.append(status)
    if pkg: where.append("c.package_id=?"); args.append(pkg)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    col = sort if sort in {"id","name","code","status","balance","install_date"} else "id"
    order = "DESC" if dir.lower() == "desc" else "ASC"
    total = db.one(con, f"SELECT COUNT(*) n FROM customers c {w}", args)["n"]
    p, pages, off = paginate(request, total, page, 12)
    rows = db.q(con, f"{CUST_SELECT} {w} ORDER BY {col} {order} LIMIT ? OFFSET ?", args + [12, off])
    pkgs = db.q(con, "SELECT * FROM packages ORDER BY name")
    return templates.TemplateResponse(request, "customers.html", ctx(request, u,
        rows=rows, total=total, page=p, pages=pages, search=search, status=status, pkg=pkg,
        sort=sort, dir=dir, pkgs=pkgs, active="customers"))

def _validate_customer(f):
    errs = {}
    if not str(f.get("name", "")).strip(): errs["name"] = "Nama wajib diisi."
    ph = str(f.get("phone", "")).strip()
    if ph and not ph.replace("-", "").replace("+", "").isdigit(): errs["phone"] = "Telepon hanya boleh angka (contoh 08123456789)."
    em = str(f.get("email", "")).strip()
    if em and "@" not in em: errs["email"] = "Format email tidak valid."
    if not str(f.get("address", "")).strip(): errs["address"] = "Alamat wajib diisi."
    bd = pint(f.get("billing_day", "1"), 1)
    if bd < 1 or bd > 28: errs["billing_day"] = "Hari tagih harus 1–28."
    return errs

@app.get("/customers/new", response_class=Response)
def customer_new(request: Request):
    u = require(request, "customers"); con = C(request)
    return templates.TemplateResponse(request, "customer_form.html", ctx(request, u,
        c=None, pkgs=db.q(con, "SELECT * FROM packages WHERE status='aktif'"),
        routers=db.q(con, "SELECT * FROM routers"), active="customers"))

@app.get("/customers/{cid}", response_class=Response)
def customer_detail(request: Request, cid: int, tab: str = "tagihan", page: str = "1"):
    u = require(request, "customers"); con = C(request)
    c = db.one(con, CUST_SELECT + " WHERE c.id=?", (cid,))
    if not c: raise HTTPException(404)
    pp = db.one(con, PPP_SELECT + " WHERE a.customer_id=?", (cid,))
    inv_total = db.one(con, "SELECT COUNT(*) n FROM invoices WHERE customer_id=?", (cid,))["n"]
    ip, ipages, ioff = paginate(request, inv_total, page, 10)
    invoices = db.q(con, "SELECT * FROM invoices WHERE customer_id=? ORDER BY period DESC, id DESC LIMIT ? OFFSET ?", (cid, 10, ioff))
    pays = db.q(con, """SELECT p.*, i.number inv FROM payments p LEFT JOIN invoices i ON i.id=p.invoice_id
        WHERE p.customer_id=? ORDER BY p.date DESC, p.id DESC LIMIT 10""", (cid,))
    logs = db.q(con, "SELECT * FROM activity_log WHERE obj LIKE ? OR detail LIKE ? ORDER BY ts DESC, id DESC LIMIT 10",
                (f"%{c['code']}%", f"%{c['name']}%"))
    hs = db.one(con, "SELECT COUNT(*) n FROM hotspot_users WHERE comment LIKE ?", (f"%{c['code']}%",))["n"]
    return templates.TemplateResponse(request, "customer_detail.html", ctx(request, u,
        c=c, pppoe=pp, invoices=invoices, pays=pays, logs=logs, tab=tab, hs_count=hs,
        inv_total=inv_total, page=ip, pages=ipages, active="customers"))

@app.get("/customers/{cid}/edit", response_class=Response)
def customer_edit(request: Request, cid: int):
    u = require(request, "customers"); con = C(request)
    c = db.one(con, "SELECT * FROM customers WHERE id=?", (cid,))
    if not c: raise HTTPException(404)
    return templates.TemplateResponse(request, "customer_form.html", ctx(request, u,
        c=c, pkgs=db.q(con, "SELECT * FROM packages"), routers=db.q(con, "SELECT * FROM routers"), active="customers"))

def _sync_balance(con, cid):
    con.execute("""UPDATE customers SET balance=COALESCE((SELECT SUM(amount-paid_amount) FROM invoices
        WHERE customer_id=? AND status IN ('belum_bayar','lewat_jatuh_tempo')),0) WHERE id=?""", (cid, cid))

@app.post("/customers/create")
async def customer_create(request: Request):
    u = require(request, "customers"); con = C(request)
    f = await form(request)
    errs = _validate_customer(f)
    if errs:
        return templates.TemplateResponse(request, "customer_form.html", ctx(request, u,
            c=f, pkgs=db.q(con, "SELECT * FROM packages WHERE status='aktif'"),
            routers=db.q(con, "SELECT * FROM routers"), errors=errs, active="customers"), status_code=422)
    nxt = db.one(con, "SELECT COALESCE(MAX(id),0)+1 n FROM customers")["n"]
    code = f"CUST-{nxt:04d}"
    cur = con.execute("""INSERT INTO customers(code,name,phone,email,address,package_id,router_id,pppoe_username,
        install_date,billing_day,status,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (code, f["name"].strip(), f.get("phone", ""), f.get("email", ""), f.get("address", ""),
         pint(f.get("package_id")) or None, pint(f.get("router_id")) or None, f.get("pppoe_username", ""),
         f.get("install_date") or datetime.date.today().isoformat(), pint(f.get("billing_day", "1"), 1),
         f.get("status", "aktif"), f.get("notes", ""), db.now()))
    _sync_balance(con, cur.lastrowid)
    db.log_activity(con, u["username"], "customer.create", code, f["name"]); con.commit()
    return flash_set(RedirectResponse(f"/customers/{cur.lastrowid}", 303), f"Pelanggan {code} berhasil dibuat.")

@app.post("/customers/update/{cid}")
async def customer_update(request: Request, cid: int):
    u = require(request, "customers"); con = C(request)
    f = await form(request)
    c = db.one(con, "SELECT * FROM customers WHERE id=?", (cid,))
    if not c: raise HTTPException(404)
    errs = _validate_customer(f)
    if errs:
        merged = dict(c); merged.update({k: v for k, v in f.items() if k in merged})
        return templates.TemplateResponse(request, "customer_form.html", ctx(request, u,
            c=merged, pkgs=db.q(con, "SELECT * FROM packages"), routers=db.q(con, "SELECT * FROM routers"),
            errors=errs, active="customers"), status_code=422)
    con.execute("""UPDATE customers SET name=?,phone=?,email=?,address=?,package_id=?,router_id=?,
        pppoe_username=?,install_date=?,billing_day=?,status=?,notes=? WHERE id=?""",
        (f["name"].strip(), f.get("phone", ""), f.get("email", ""), f.get("address", ""),
         pint(f.get("package_id")) or None, pint(f.get("router_id")) or None, f.get("pppoe_username", ""),
         f.get("install_date", ""), pint(f.get("billing_day", "1"), 1), f.get("status", "aktif"),
         f.get("notes", ""), cid))
    _sync_balance(con, cid)
    db.log_activity(con, u["username"], "customer.update", c["code"], f["name"]); con.commit()
    return flash_set(RedirectResponse(f"/customers/{cid}", 303), "Data pelanggan diperbarui.")

@app.post("/customers/{cid}/status")
async def customer_status(request: Request, cid: int, status: str = Form(...)):
    u = require(request, "customers"); con = C(request)
    c = db.one(con, "SELECT * FROM customers WHERE id=?", (cid,))
    if not c: raise HTTPException(404)
    if status not in ("aktif", "suspend", "nonaktif"): raise HTTPException(400)
    con.execute("UPDATE customers SET status=? WHERE id=?", (status, cid))
    if status == "suspend":
        con.execute("UPDATE pppoe_accounts SET status='disabled', online=0 WHERE customer_id=?", (cid,))
    elif status == "aktif":
        con.execute("UPDATE pppoe_accounts SET status='aktif' WHERE customer_id=? AND status='disabled'", (cid,))
    db.log_activity(con, u["username"], "customer.status", c["code"], f"Status → {status}"); con.commit()
    label = {"aktif": "diaktifkan kembali", "suspend": "disuspend (PPPoE ikut disabled)", "nonaktif": "dinonaktifkan"}[status]
    return flash_set(RedirectResponse(request.headers.get("referer", f"/customers/{cid}"), 303),
                     f"Pelanggan {c['name']} {label}.")

@app.post("/customers/{cid}/delete")
async def customer_delete(request: Request, cid: int):
    u = require(request, "customers"); con = C(request)
    if not can(u["role"], "customers") or u["role"] not in ("superadmin", "admin"):
        return flash_set(RedirectResponse(f"/customers/{cid}", 303), "Hanya Admin/Super Admin yang dapat menghapus pelanggan.", "err")
    c = db.one(con, "SELECT * FROM customers WHERE id=?", (cid,))
    if not c: raise HTTPException(404)
    open_inv = db.one(con, "SELECT COUNT(*) n FROM invoices WHERE customer_id=? AND status NOT IN ('lunas','batal')", (cid,))["n"]
    if open_inv:
        return flash_set(RedirectResponse(f"/customers/{cid}", 303),
                         f"Tidak dapat menghapus: masih ada {open_inv} tagihan belum selesai.", "err")
    con.execute("UPDATE pppoe_accounts SET customer_id=NULL WHERE customer_id=?", (cid,))
    con.execute("DELETE FROM customers WHERE id=?", (cid,))
    db.log_activity(con, u["username"], "customer.delete", c["code"], c["name"]); con.commit()
    return flash_set(RedirectResponse("/customers", 303), f"Pelanggan {c['code']} ({c['name']}) dihapus.")

@app.get("/export/customers.csv")
def export_customers(request: Request):
    u = require(request, "customers"); con = C(request)
    rows = db.q(con, CUST_SELECT + " ORDER BY c.id")
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Kode","Nama","Telepon","Email","Alamat","Paket","Router","PPPoE","Pasang","Hari Tagih","Status","Saldo"])
    for r in rows:
        w.writerow([r["code"], r["name"], r["phone"], r["email"], r["address"], r["pname"] or "", r["rname"] or "",
                    r["pppoe_username"], r["install_date"], r["billing_day"], r["status"], r["balance"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=pelanggan.csv"})

# ================================================================= PACKAGES
@app.get("/packages", response_class=Response)
def packages(request: Request):
    u = require(request, "packages"); con = C(request)
    rows = db.q(con, """SELECT p.*, (SELECT COUNT(*) FROM customers c WHERE c.package_id=p.id) usage
        FROM packages p ORDER BY p.price""")
    edit_id = request.query_params.get("edit")
    editing = db.one(con, "SELECT * FROM packages WHERE id=?", (int(edit_id),)) if edit_id else None
    return templates.TemplateResponse(request, "packages.html", ctx(request, u, rows=rows, editing=editing, active="packages"))

@app.post("/packages/save")
async def package_save(request: Request):
    u = require(request, "packages"); con = C(request)
    f = await form(request)
    pid = pint(f.get("id", ""))
    errs = {}
    if not str(f.get("name", "")).strip(): errs["name"] = "Nama paket wajib diisi."
    try:
        price = int(float(f.get("price", "0")))
        if price <= 0: errs["price"] = "Harga harus lebih dari 0."
    except Exception:
        errs["price"] = "Harga harus angka."
    if errs:
        rows = db.q(con, "SELECT p.*,(SELECT COUNT(*) FROM customers c WHERE c.package_id=p.id) usage FROM packages p ORDER BY price")
        return templates.TemplateResponse(request, "packages.html",
            ctx(request, u, rows=rows, editing=dict(f), errors=errs, active="packages"), status_code=422)
    if pid:
        con.execute("UPDATE packages SET name=?,download_mbps=?,upload_mbps=?,price=?,description=?,status=? WHERE id=?",
            (f["name"], float(f.get("download", 0)), float(f.get("upload", 0)), price, f.get("description", ""),
             f.get("status", "aktif"), pid))
        db.log_activity(con, u["username"], "package.update", f["name"], "Edit paket"); msg = "Paket diperbarui."
    else:
        con.execute("INSERT INTO packages(name,download_mbps,upload_mbps,price,description,status) VALUES(?,?,?,?,?,?)",
            (f["name"], float(f.get("download", 0)), float(f.get("upload", 0)), price, f.get("description", ""),
             f.get("status", "aktif")))
        db.log_activity(con, u["username"], "package.create", f["name"], "Tambah paket"); msg = "Paket baru dibuat."
    con.commit()
    return flash_set(RedirectResponse("/packages", 303), msg)

@app.post("/packages/{pid}/toggle")
def package_toggle(request: Request, pid: int):
    u = require(request, "packages"); con = C(request)
    p = db.one(con, "SELECT * FROM packages WHERE id=?", (pid,))
    if not p: raise HTTPException(404)
    ns = "nonaktif" if p["status"] == "aktif" else "aktif"
    con.execute("UPDATE packages SET status=? WHERE id=?", (ns, pid))
    db.log_activity(con, u["username"], "package.toggle", p["name"], f"status → {ns}"); con.commit()
    return flash_set(RedirectResponse("/packages", 303), f"Paket '{p['name']}' sekarang {ns}.")

@app.post("/packages/{pid}/delete")
def package_delete(request: Request, pid: int):
    u = require(request, "packages"); con = C(request)
    p = db.one(con, "SELECT * FROM packages WHERE id=?", (pid,))
    if not p: raise HTTPException(404)
    n = db.one(con, "SELECT COUNT(*) n FROM customers WHERE package_id=?", (pid,))["n"]
    if n: return flash_set(RedirectResponse("/packages", 303), f"Tidak dapat menghapus: paket dipakai {n} pelanggan.", "err")
    con.execute("DELETE FROM packages WHERE id=?", (pid,))
    db.log_activity(con, u["username"], "package.delete", p["name"], ""); con.commit()
    return flash_set(RedirectResponse("/packages", 303), "Paket dihapus.")

# ================================================================= PPPoE
PPP_SELECT = """SELECT a.*, c.name cname, c.code ccode, r.name rname FROM pppoe_accounts a
  LEFT JOIN customers c ON c.id=a.customer_id LEFT JOIN routers r ON r.id=a.router_id"""

@app.get("/pppoe", response_class=Response)
def pppoe_list(request: Request, search: str = "", router: str = "", state: str = "", page: str = "1"):
    u = require(request, "pppoe"); con = C(request)
    where, args = [], []
    if search: where.append("(a.username LIKE ? OR c.name LIKE ? OR c.code LIKE ?)"); args += [f"%{search}%"]*3
    if router: where.append("a.router_id=?"); args.append(pint(router))
    if state == "online": where.append("a.online=1")
    elif state == "offline": where.append("a.online=0")
    elif state: where.append("a.status=?"); args.append(state)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(con, f"SELECT COUNT(*) n FROM pppoe_accounts a LEFT JOIN customers c ON c.id=a.customer_id {w}", args)["n"]
    p, pages, off = paginate(request, total, page, 12)
    rows = db.q(con, f"{PPP_SELECT} {w} ORDER BY a.username LIMIT ? OFFSET ?", args + [12, off])
    routers = db.q(con, "SELECT * FROM routers ORDER BY name")
    return templates.TemplateResponse(request, "pppoe.html", ctx(request, u, rows=rows, routers=routers,
        total=total, page=p, pages=pages, search=search, router=router, state=state, active="pppoe"))

@app.get("/pppoe/new", response_class=Response)
def pppoe_new(request: Request):
    u = require(request, "pppoe"); con = C(request)
    return templates.TemplateResponse(request, "pppoe_form.html", ctx(request, u, a=None,
        custs=db.q(con, "SELECT id,name,code FROM customers ORDER BY name"),
        pkgs=db.q(con, "SELECT * FROM packages WHERE status='aktif'"),
        routers=db.q(con, "SELECT * FROM routers"), active="pppoe"))

@app.get("/pppoe/{aid}", response_class=Response)
def pppoe_detail(request: Request, aid: int):
    u = require(request, "pppoe"); con = C(request)
    a = db.one(con, PPP_SELECT + " WHERE a.id=?", (aid,))
    if not a: raise HTTPException(404)
    evs = db.q(con, "SELECT * FROM activity_log WHERE obj LIKE ? ORDER BY ts DESC LIMIT 8", (f"%{a['username']}%",))
    return templates.TemplateResponse(request, "pppoe_detail.html", ctx(request, u, a=a, evs=evs, active="pppoe"))

@app.get("/pppoe/{aid}/edit", response_class=Response)
def pppoe_edit(request: Request, aid: int):
    u = require(request, "pppoe"); con = C(request)
    a = db.one(con, "SELECT * FROM pppoe_accounts WHERE id=?", (aid,))
    if not a: raise HTTPException(404)
    return templates.TemplateResponse(request, "pppoe_form.html", ctx(request, u, a=a,
        custs=db.q(con, "SELECT id,name,code FROM customers ORDER BY name"),
        pkgs=db.q(con, "SELECT * FROM packages"), routers=db.q(con, "SELECT * FROM routers"), active="pppoe"))

@app.post("/pppoe/save")
async def pppoe_save(request: Request):
    u = require(request, "pppoe"); con = C(request)
    f = await form(request)
    aid = pint(f.get("id", ""))
    errs = {}
    un = str(f.get("username", "")).strip()
    if not un: errs["username"] = "Username wajib diisi."
    elif db.one(con, "SELECT id FROM pppoe_accounts WHERE username=? AND id<>?", (un, aid)):
        errs["username"] = "Username sudah dipakai."
    if not f.get("password", "") and not aid: errs["password"] = "Password wajib diisi."
    if errs:
        return templates.TemplateResponse(request, "pppoe_form.html", ctx(request, u, a=dict(f),
            custs=db.q(con, "SELECT id,name,code FROM customers ORDER BY name"),
            pkgs=db.q(con, "SELECT * FROM packages"), routers=db.q(con, "SELECT * FROM routers"),
            errors=errs, active="pppoe"), status_code=422)
    cid = pint(f.get("customer_id")) or None
    profile_name = f.get("profile", "")
    pid = pint(f.get("package_id"))
    if pid:
        pn = db.one(con, "SELECT name FROM packages WHERE id=?", (pid,))
        if pn: profile_name = pn["name"]
    old = db.one(con, "SELECT password FROM pppoe_accounts WHERE id=?", (aid,)) if aid else None
    pw = f.get("password") or (old["password"] if old else "")
    if aid:
        con.execute("""UPDATE pppoe_accounts SET username=?,password=?,customer_id=?,profile=?,router_id=?,
            ip_addr=?,status=?,last_seen=? WHERE id=?""",
            (un, pw, cid, profile_name, pint(f.get("router_id")) or None, f.get("ip_addr",""),
             f.get("status","aktif"), db.now(), aid))
        msg = "Akun PPPoE diperbarui di database aplikasi (adapter DEMO)."
    else:
        con.execute("""INSERT INTO pppoe_accounts(username,password,customer_id,profile,router_id,ip_addr,
            status,last_seen,online,session_uptime,service) VALUES(?,?,?,?,?,?,?, ?,0,'-','PPPoE')""",
            (un, pw, cid, profile_name, pint(f.get("router_id")) or None, f.get("ip_addr",""),
             f.get("status","aktif"), db.now()))
        aid = con.execute("SELECT last_insert_rowid() n").fetchone()["n"]
        msg = "Akun PPPoE dibuat. Catatan: adapter DEMO — TIDAK dikirim ke RouterOS sungguhan."
    if cid:
        con.execute("UPDATE customers SET pppoe_username=? WHERE id=?", (un, cid))
    db.log_activity(con, u["username"], "pppoe.save", un, ("edit" if f.get("id") else "buat baru") + " (DEMO adapter)")
    con.commit()
    return flash_set(RedirectResponse(f"/pppoe/{aid}", 303), msg)

@app.post("/pppoe/{aid}/toggle")
def pppoe_toggle(request: Request, aid: int):
    u = require(request, "pppoe"); con = C(request)
    a = db.one(con, "SELECT * FROM pppoe_accounts WHERE id=?", (aid,))
    if not a: raise HTTPException(404)
    ns = "disabled" if a["status"] == "aktif" else "aktif"
    con.execute("UPDATE pppoe_accounts SET status=? WHERE id=?", (ns, aid))
    db.log_activity(con, u["username"], "pppoe.toggle", a["username"], f"status -> {ns} (DEMO adapter)")
    con.commit()
    return flash_set(RedirectResponse(f"/pppoe/{aid}", 303),
                     f"Akun {a['username']} {'dinonaktifkan' if ns=='disabled' else 'diaktifkan'} pada state aplikasi (DEMO — RouterOS tidak tersambung).")

@app.post("/pppoe/{aid}/disconnect")
def pppoe_disconnect(request: Request, aid: int):
    u = require(request, "pppoe"); con = C(request)
    a = db.one(con, "SELECT * FROM pppoe_accounts WHERE id=?", (aid,))
    if not a: raise HTTPException(404)
    con.execute("UPDATE pppoe_accounts SET online=0, session_uptime='-' WHERE id=?", (aid,))
    db.log_activity(con, u["username"], "pppoe.disconnect", a["username"], "Sesi diputus (DEMO adapter)")
    con.commit()
    return flash_set(RedirectResponse(f"/pppoe/{aid}", 303),
                     f"Sesi {a['username']} diputus pada state aplikasi. MODE DEMO: perintah remove tidak dikirim ke RouterOS.")

@app.post("/pppoe/{aid}/delete")
def pppoe_delete(request: Request, aid: int):
    u = require(request, "pppoe"); con = C(request)
    if u["role"] not in ("superadmin", "admin"):
        return flash_set(RedirectResponse(f"/pppoe/{aid}", 303), "Hanya Admin yang dapat menghapus akun PPPoE.", "err")
    a = db.one(con, "SELECT * FROM pppoe_accounts WHERE id=?", (aid,))
    if not a: raise HTTPException(404)
    con.execute("DELETE FROM pppoe_accounts WHERE id=?", (aid,))
    db.log_activity(con, u["username"], "pppoe.delete", a["username"], ""); con.commit()
    return flash_set(RedirectResponse("/pppoe", 303), f"Akun {a['username']} dihapus.")

# ================================================================= HOTSPOT
@app.get("/hotspot", response_class=Response)
def hotspot(request: Request, search: str = "", state: str = "", page: str = "1"):
    u = require(request, "hotspot"); con = C(request)
    where, args = [], []
    if search: where.append("(username LIKE ? OR password LIKE ? OR profile LIKE ?)"); args += [f"%{search}%"]*3
    if state == "unused": where.append("used=0")
    elif state == "used": where.append("used=1")
    elif state: where.append("status=?"); args.append(state)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(con, f"SELECT COUNT(*) n FROM hotspot_users {w}", args)["n"]
    p, pages, off = paginate(request, total, page, 15)
    rows = db.q(con, f"SELECT * FROM hotspot_users {w} ORDER BY id DESC LIMIT ? OFFSET ?", args + [15, off])
    return templates.TemplateResponse(request, "hotspot.html", ctx(request, u, rows=rows, total=total,
        page=p, pages=pages, search=search, state=state, editing=None, active="hotspot"))

@app.post("/hotspot/save")
async def hotspot_save(request: Request):
    u = require(request, "hotspot"); con = C(request)
    f = await form(request)
    hid = pint(f.get("id", ""))
    errs = {}
    un = str(f.get("username", "")).strip()
    if not un: errs["username"] = "Username wajib diisi."
    elif db.one(con, "SELECT id FROM hotspot_users WHERE username=? AND id<>?", (un, hid)):
        errs["username"] = "Username sudah ada."
    if not f.get("password") and not hid: errs["password"] = "Password/kode wajib diisi."
    if errs:
        rows = db.q(con, "SELECT * FROM hotspot_users ORDER BY id DESC LIMIT 15")
        return templates.TemplateResponse(request, "hotspot.html", ctx(request, u, editing=dict(f), errors=errs,
            rows=rows, total=len(rows), page=1, pages=1, search="", state="", active="hotspot"), status_code=422)
    if hid:
        con.execute("""UPDATE hotspot_users SET username=?,password=?,profile=?,valid_until=?,status=?,price=?,comment=? WHERE id=?""",
            (un, f.get("password",""), f.get("profile","default"), f.get("valid_until",""),
             f.get("status","aktif"), pint(f.get("price","0")), f.get("comment",""), hid))
        msg = "Pengguna hotspot diperbarui."
    else:
        con.execute("""INSERT INTO hotspot_users(username,password,profile,valid_until,status,price,comment,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (un, f.get("password",""), f.get("profile","default"), f.get("valid_until",""),
             f.get("status","aktif"), pint(f.get("price","0")), f.get("comment",""), db.now()))
        msg = "Pengguna hotspot dibuat (DEMO adapter — belum didaftarkan ke RouterOS)."
    db.log_activity(con, u["username"], "hotspot.save", un, ""); con.commit()
    return flash_set(RedirectResponse("/hotspot", 303), msg)

@app.post("/hotspot/{hid}/toggle")
def hotspot_toggle(request: Request, hid: int):
    u = require(request, "hotspot"); con = C(request)
    h = db.one(con, "SELECT * FROM hotspot_users WHERE id=?", (hid,))
    if not h: raise HTTPException(404)
    ns = "disabled" if h["status"] == "aktif" else "aktif"
    con.execute("UPDATE hotspot_users SET status=? WHERE id=?", (ns, hid))
    db.log_activity(con, u["username"], "hotspot.toggle", h["username"], f"-> {ns}"); con.commit()
    return flash_set(RedirectResponse("/hotspot", 303), f"{h['username']} sekarang {ns}.")

@app.post("/hotspot/{hid}/delete")
def hotspot_delete(request: Request, hid: int):
    u = require(request, "hotspot"); con = C(request)
    h = db.one(con, "SELECT * FROM hotspot_users WHERE id=?", (hid,))
    if not h: raise HTTPException(404)
    con.execute("DELETE FROM hotspot_users WHERE id=?", (hid,))
    db.log_activity(con, u["username"], "hotspot.delete", h["username"], ""); con.commit()
    return flash_set(RedirectResponse("/hotspot", 303), f"{h['username']} dihapus.")

# ================================================================= VOUCHERS
HS_PROFILES = [("reguler-1hari", 1, 10000), ("vip-harian", 1, 15000), ("malam", 8, 5000), ("mingguan", 7, 50000)]

def _voucher_batches(con):
    return db.q(con, """SELECT batch, COUNT(*) n, MIN(created_at) made FROM vouchers GROUP BY batch
        ORDER BY MAX(id) DESC LIMIT 20""")

@app.get("/hotspot/vouchers", response_class=Response)
def vouchers(request: Request, batch: str = ""):
    u = require(request, "hotspot"); con = C(request)
    batches = _voucher_batches(con)
    if not batch and batches: batch = batches[0]["batch"]
    rows = db.q(con, "SELECT * FROM vouchers WHERE batch=? ORDER BY id", (batch,)) if batch else []
    return templates.TemplateResponse(request, "vouchers.html", ctx(request, u, rows=rows, batch=batch,
        batches=batches, profiles=HS_PROFILES, formdata=None, active="vouchers"))

@app.post("/hotspot/vouchers/generate")
async def voucher_generate(request: Request):
    u = require(request, "hotspot"); con = C(request)
    f = await form(request)
    qty = pint(f.get("qty", "0")); errs = {}
    if qty < 1 or qty > 500: errs["qty"] = "Jumlah harus 1-500."
    plen = pint(f.get("pwlen", "8"))
    if plen < 4 or plen > 16: errs["pwlen"] = "Panjang password 4-16."
    days = pint(f.get("days", "1"))
    if days < 1 or days > 365: errs["days"] = "Masa aktif 1-365 hari."
    prefix = str(f.get("prefix", "hs")).strip() or "hs"
    price = pint(f.get("price", "0")); prof = f.get("profile", "reguler-1hari")
    if errs:
        return templates.TemplateResponse(request, "vouchers.html", ctx(request, u, rows=[], batch="",
            batches=_voucher_batches(con), profiles=HS_PROFILES, errors=errs, formdata=dict(f),
            active="vouchers"), status_code=422)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    batch = f"VCH-{datetime.datetime.now().strftime('%y%m%d-%H%M%S')}"
    for i in range(qty):
        pw = "".join(random.choice(alphabet) for _ in range(plen))
        uname = f"{prefix}{i+1:03d}"
        while db.one(con, "SELECT id FROM hotspot_users WHERE username=?", (uname,)) or \
              db.one(con, "SELECT id FROM vouchers WHERE username=?", (uname,)):
            uname = f"{prefix}{random.randint(100,99999)}"
        con.execute("INSERT INTO vouchers(batch,username,password,profile,validity_days,price,created_at) VALUES(?,?,?,?,?,?,?)",
                    (batch, uname, pw, prof, days, price, db.now()))
        con.execute("""INSERT INTO hotspot_users(username,password,profile,valid_until,status,used,price,comment,created_at)
            VALUES(?,?,?,?,?,0,?,?,?)""",
            (uname, pw, prof, (datetime.date.today()+datetime.timedelta(days=days)).isoformat(),
             "aktif", price, batch, db.now()))
    db.log_activity(con, u["username"], "voucher.generate", batch, f"{qty} voucher profil {prof}")
    con.commit()
    return flash_set(RedirectResponse(f"/hotspot/vouchers?batch={batch}", 303),
                     f"{qty} voucher dibuat (batch {batch}) dan tersimpan di database. Cetak/CSV tersedia. Belum dikirim ke RouterOS (DEMO).")

@app.get("/export/vouchers.csv")
def export_vouchers(request: Request, batch: str = ""):
    u = require(request, "hotspot"); con = C(request)
    rows = db.q(con, "SELECT * FROM vouchers WHERE batch=? ORDER BY id", (batch,)) if batch else \
         db.q(con, "SELECT * FROM vouchers ORDER BY id DESC LIMIT 500")
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Batch","Username","Password","Profil","Berlaku (hari)","Harga"])
    for r in rows: w.writerow([r["batch"], r["username"], r["password"], r["profile"], r["validity_days"], r["price"]])
    return Response("\ufeff"+buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=voucher-{(batch or 'all').replace('=','_')}.csv"})

# ================================================================= ROUTERS
@app.get("/routers", response_class=Response)
def routers(request: Request):
    u = require(request, "routers"); con = C(request)
    rows = db.q(con, """SELECT r.*,
        (SELECT COUNT(*) FROM pppoe_accounts a WHERE a.router_id=r.id) pcount,
        (SELECT COUNT(*) FROM pppoe_accounts a WHERE a.router_id=r.id AND a.online=1) ponline
        FROM routers r ORDER BY r.name""")
    return templates.TemplateResponse(request, "routers.html", ctx(request, u, rows=rows, active="routers"))

@app.get("/routers/new", response_class=Response)
def router_new(request: Request):
    u = require(request, "routers")
    return templates.TemplateResponse(request, "router_form.html", ctx(request, u, r=None, active="routers"))

@app.get("/routers/{rid}", response_class=Response)
def router_detail(request: Request, rid: int, tab: str = "ringkasan"):
    u = require(request, "routers"); con = C(request)
    r = db.one(con, "SELECT * FROM routers WHERE id=?", (rid,))
    if not r: raise HTTPException(404)
    ifs = db.q(con, "SELECT * FROM interfaces WHERE router_id=? ORDER BY name", (rid,))
    ppp = db.q(con, "SELECT * FROM pppoe_accounts WHERE router_id=? ORDER BY username", (rid,))
    hs = db.one(con, "SELECT COUNT(*) n FROM hotspot_users")["n"]
    evs = db.q(con, "SELECT * FROM events WHERE router_id=? ORDER BY time DESC LIMIT 10", (rid,))
    return templates.TemplateResponse(request, "router_detail.html", ctx(request, u, r=r, ifs=ifs, ppp=ppp,
        hs_count=hs, evs=evs, tab=tab, active="routers"))

@app.get("/routers/{rid}/edit", response_class=Response)
def router_edit(request: Request, rid: int):
    u = require(request, "routers"); con = C(request)
    r = db.one(con, "SELECT * FROM routers WHERE id=?", (rid,))
    if not r: raise HTTPException(404)
    return templates.TemplateResponse(request, "router_form.html", ctx(request, u, r=r, active="routers"))

@app.post("/routers/save")
async def router_save(request: Request):
    u = require(request, "routers"); con = C(request)
    f = await form(request)
    rid = pint(f.get("id", ""))
    errs = {}
    if not str(f.get("name","")).strip(): errs["name"] = "Nama router wajib diisi."
    if not str(f.get("host","")).strip(): errs["host"] = "IP/hostname wajib diisi."
    if errs:
        return templates.TemplateResponse(request, "router_form.html", ctx(request, u, r=dict(f),
            errors=errs, active="routers"), status_code=422)
    if rid:
        con.execute("""UPDATE routers SET name=?,host=?,port=?,version=?,location=?,identity=? WHERE id=?""",
            (f["name"], f["host"], pint(f.get("port","8728"),8728), f.get("version",""),
             f.get("location",""), f.get("identity",""), rid))
        msg = "Data router diperbarui."
    else:
        con.execute("""INSERT INTO routers(name,host,port,version,location,identity,status,api_mode,last_checked)
            VALUES(?,?,?,?,?,?, 'unknown','demo',?)""",
            (f["name"], f["host"], pint(f.get("port","8728"),8728), f.get("version",""),
             f.get("location",""), f.get("identity",""), db.now()))
        rid = con.execute("SELECT last_insert_rowid() n").fetchone()["n"]
        msg = "Router ditambahkan. Gunakan tombol 'Cek Koneksi' untuk memprobe API."
    db.log_activity(con, u["username"], "router.update", f["name"], "Simpan data router"); con.commit()
    return flash_set(RedirectResponse(f"/routers/{rid}", 303), msg)

@app.post("/routers/{rid}/check")
def router_check(request: Request, rid: int, mode: str = Form("demo")):
    u = require(request, "routers"); con = C(request)
    r = db.one(con, "SELECT * FROM routers WHERE id=?", (rid,))
    if not r: raise HTTPException(404)
    adapter = routeros.get_adapter("real" if mode == "real" else "demo")
    st = adapter.probe(r["host"], r["port"] or 8728)
    new_status = "ok" if st.reachable else "offline"
    if mode == "real" and not st.reachable:
        con.execute("UPDATE routers SET status='offline', last_checked=? WHERE id=?", (db.now(), rid))
        con.execute("INSERT INTO events(router_id,router_name,time,type,message) VALUES(?,?,?,?,?)",
            (rid, r["name"], db.now(), "alert", f"Probe REAL gagal: {st.version[:80]}"))
        db.log_activity(con, u["username"], "router.check", r["name"], "Probe REAL gagal - tidak terhubung")
        con.commit()
        return flash_set(RedirectResponse(f"/routers/{rid}", 303),
                         f"Probe REAL gagal ({st.version[:60]}). Router TIDAK terhubung - tidak ada telemetri live.", "err")
    con.execute("""UPDATE routers SET status=?, uptime=?, cpu=?, mem=?, last_checked=?,
        version=CASE WHEN ?!='' THEN ? ELSE version END,
        identity=CASE WHEN ?!='' THEN ? ELSE identity END WHERE id=?""",
        (new_status, st.uptime or "-", st.cpu, st.mem, db.now(),
         st.version if st.mode=="DEMO" else "", st.version if st.mode=="DEMO" else "",
         st.identity, st.identity, rid))
    if not st.reachable:
        con.execute("INSERT INTO events(router_id,router_name,time,type,message) VALUES(?,?,?,?,?)",
                    (rid, r["name"], db.now(), "alert", "Probe koneksi: router tidak merespon (OFFLINE)"))
    db.log_activity(con, u["username"], "router.check", r["name"], f"mode {adapter.name.upper()} -> {new_status}")
    con.commit()
    note = "Angka hasil probe adalah DATA DEMO, bukan telemetri RouterOS live." if st.mode=="DEMO" else "Probe TCP nyata ke port API berhasil."
    return flash_set(RedirectResponse(f"/routers/{rid}", 303),
                     f"Hasil probe [{st.mode}]: {'ONLINE' if st.reachable else 'OFFLINE / TIDAK TERHUBUNG'}. {note}")

@app.post("/routers/{rid}/delete")
def router_delete(request: Request, rid: int):
    u = require(request, "routers"); con = C(request)
    if u["role"] != "superadmin":
        return flash_set(RedirectResponse(f"/routers/{rid}", 303), "Hanya Super Admin yang dapat menghapus router.", "err")
    r = db.one(con, "SELECT * FROM routers WHERE id=?", (rid,))
    if not r: raise HTTPException(404)
    n = db.one(con, "SELECT COUNT(*) n FROM customers WHERE router_id=?", (rid,))["n"]
    if n: return flash_set(RedirectResponse(f"/routers/{rid}", 303), f"Tidak dapat menghapus: masih dipakai {n} pelanggan.", "err")
    con.execute("DELETE FROM routers WHERE id=?", (rid,))
    db.log_activity(con, u["username"], "router.delete", r["name"], ""); con.commit()
    return flash_set(RedirectResponse("/routers", 303), f"Router {r['name']} dihapus.")

# ================================================================= MONITORING
@app.get("/monitoring", response_class=Response)
def monitoring(request: Request, rng: str = "24h", rfilter: str = "", refresh: str = ""):
    u = require(request, "monitoring"); con = C(request)
    routers = db.q(con, "SELECT * FROM routers ORDER BY name")
    if rfilter: routers = [r for r in routers if str(r["id"]) == rfilter]
    rnd = random.Random(int(time.time()) // 30 if not refresh else time.time_ns())
    cards = []
    for r in routers:
        on = r["status"] == "ok"
        sess = db.one(con, "SELECT COUNT(*) n FROM pppoe_accounts WHERE router_id=? AND online=1", (r["id"],))["n"]
        rx = round(sess * rnd.uniform(0.8, 2.5), 1) if on else 0.0
        tx = round(sess * rnd.uniform(0.3, 1.2), 1) if on else 0.0
        lat = round(rnd.uniform(6, 45), 1) if on else None
        loss = round(rnd.uniform(0, 1.5), 2) if on else 100.0
        cards.append({"r": r, "sessions": sess, "rx": rx, "tx": tx, "lat": lat, "loss": loss})
    disc = db.q(con, """SELECT a.username, c.name cname, a.last_seen FROM pppoe_accounts a
        LEFT JOIN customers c ON c.id=a.customer_id WHERE a.online=0 ORDER BY a.last_seen DESC LIMIT 8""")
    alerts = db.q(con, "SELECT * FROM events WHERE type IN ('alert','warn') ORDER BY time DESC LIMIT 8")
    return templates.TemplateResponse(request, "monitoring.html", ctx(request, u, cards=cards, disc=disc,
        alerts=alerts, rng=rng, rfilter=rfilter, all_routers=db.q(con,"SELECT id,name FROM routers ORDER BY name"),
        generated=time.strftime("%H:%M:%S"), active="monitoring"))


# ================================================================= BILLING
INV_SELECT = """SELECT i.*, c.name cname, c.code ccode FROM invoices i
  JOIN customers c ON c.id=i.customer_id"""

def _inv_overdue_sync(con):
    today = datetime.date.today().isoformat()
    con.execute("UPDATE invoices SET status='lewat_jatuh_tempo' WHERE status='belum_bayar' AND due_date<?", (today,))

@app.get("/billing", response_class=Response)
def billing(request: Request, search: str = "", status: str = "", page: str = "1"):
    u = require(request, "billing"); con = C(request)
    _inv_overdue_sync(con); con.commit()
    where, args = [], []
    if search: where.append("(i.number LIKE ? OR c.name LIKE ? OR c.code LIKE ?)"); args += [f"%{search}%"]*3
    if status: where.append("i.status=?"); args.append(status)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(con, f"SELECT COUNT(*) n FROM invoices i JOIN customers c ON c.id=i.customer_id {w}", args)["n"]
    p, pages, off = paginate(request, total, page, 12)
    rows = db.q(con, f"{INV_SELECT} {w} ORDER BY i.period DESC, i.id DESC LIMIT ? OFFSET ?", args + [12, off])
    counts = {r["status"]: r["n"] for r in db.q(con, "SELECT status, COUNT(*) n FROM invoices GROUP BY status")}
    return templates.TemplateResponse(request, "billing.html", ctx(request, u, rows=rows, total=total, page=p,
        pages=pages, search=search, status=status, counts=counts, active="billing"))

@app.get("/billing/overdue", response_class=Response)
def billing_overdue(request: Request):
    u = require(request, "billing"); con = C(request)
    _inv_overdue_sync(con); con.commit()
    rows = db.q(con, INV_SELECT + " WHERE i.status='lewat_jatuh_tempo' ORDER BY i.due_date")
    return templates.TemplateResponse(request, "billing.html", ctx(request, u, rows=rows, total=len(rows),
        page=1, pages=1, search="", status="lewat_jatuh_tempo", counts={}, overdue_only=True, active="billing"))

@app.get("/billing/new", response_class=Response)
def invoice_new(request: Request, customer: str = ""):
    u = require(request, "billing"); con = C(request)
    custs = db.q(con, """SELECT c.id, c.name, c.code, c.billing_day, p.price, p.name pname
        FROM customers c LEFT JOIN packages p ON p.id=c.package_id ORDER BY c.name""")
    return templates.TemplateResponse(request, "invoice_form.html", ctx(request, u, inv=None, custs=custs,
        preselect=customer, active="billing"))

@app.get("/billing/{iid}", response_class=Response)
def invoice_detail(request: Request, iid: int):
    u = require(request, "billing"); con = C(request)
    _inv_overdue_sync(con); con.commit()
    inv = db.one(con, INV_SELECT + " WHERE i.id=?", (iid,))
    if not inv: raise HTTPException(404)
    pays = db.q(con, "SELECT * FROM payments WHERE invoice_id=? ORDER BY date", (iid,))
    cust = db.one(con, "SELECT * FROM customers WHERE id=?", (inv["customer_id"],))
    return templates.TemplateResponse(request, "invoice_detail.html", ctx(request, u, inv=inv, pays=pays,
        cust=cust, active="billing"))

@app.post("/billing/save")
async def invoice_save(request: Request):
    u = require(request, "billing"); con = C(request)
    f = await form(request)
    iid = pint(f.get("id", ""))
    errs = {}
    cid = pint(f.get("customer_id"))
    if not cid or not db.one(con, "SELECT id FROM customers WHERE id=?", (cid,)):
        errs["customer_id"] = "Pilih pelanggan yang valid."
    try:
        amount = int(float(f.get("amount", "0")))
        if amount <= 0: errs["amount"] = "Nominal harus > 0."
    except Exception:
        errs["amount"] = "Nominal harus angka."
    period = str(f.get("period", "")).strip()
    if not period: errs["period"] = "Periode wajib diisi (YYYY-MM)."
    if errs:
        custs = db.q(con, """SELECT c.id,c.name,c.code,p.price FROM customers c LEFT JOIN packages p ON p.id=c.package_id ORDER BY c.name""")
        return templates.TemplateResponse(request, "invoice_form.html", ctx(request, u, inv=dict(f),
            custs=custs, errors=errs, active="billing"), status_code=422)
    issue = f.get("issue_date") or datetime.date.today().isoformat()
    due = f.get("due_date") or issue
    status = f.get("status", "belum_bayar")
    if status not in ("draft","belum_bayar","lunas","lewat_jatuh_tempo","batal"): status = "belum_bayar"
    if iid:
        old = db.one(con, "SELECT * FROM invoices WHERE id=?", (iid,))
        if not old: raise HTTPException(404)
        if old["paid_amount"] >= old["amount"] and status != "lunas":
            return flash_set(RedirectResponse(f"/billing/{iid}", 303), "Invoice sudah lunas — tidak dapat diubah statusnya selain Lunas.", "err")
        con.execute("""UPDATE invoices SET customer_id=?,period=?,issue_date=?,due_date=?,amount=?,status=?,notes=? WHERE id=?""",
            (cid, period, issue, due, amount, status, f.get("notes",""), iid))
        num = old["number"]; msg = "Invoice diperbarui."
    else:
        num = f"INV-{period.replace('-','')}-{db.one(con,'SELECT COUNT(*)+1 n FROM invoices')['n']:03d}"
        while db.one(con, "SELECT id FROM invoices WHERE number=?", (num,)):
            num = num + "B"
        con.execute("""INSERT INTO invoices(number,customer_id,period,issue_date,due_date,amount,paid_amount,status,notes)
            VALUES(?,?,?,?,?,?,0,?,?)""", (num, cid, period, issue, due, amount, status, f.get("notes","")))
        iid = con.execute("SELECT last_insert_rowid() n").fetchone()["n"]
        msg = f"Invoice {num} dibuat."
    _sync_balance(con, cid)
    db.log_activity(con, u["username"], "invoice.save", num, f"Rp{amount} periode {period} [{status}]")
    con.commit()
    return flash_set(RedirectResponse(f"/billing/{iid}", 303), msg)

def _mark_paid(con, iid, method, ref_note, user):
    inv = db.one(con, "SELECT * FROM invoices WHERE id=?", (iid,))
    if not inv: return None, "Invoice tidak ditemukan."
    if inv["status"] == "lunas": return None, "Invoice sudah lunas."
    if inv["status"] == "batal": return None, "Invoice dibatalkan — tidak dapat dibayar."
    sisa = inv["amount"] - inv["paid_amount"]
    nxt = db.one(con, "SELECT COUNT(*)+1 n FROM payments")["n"]
    pref = {"Tunai":"KT","Transfer":"TRF","QRIS":"QRIS","Lainnya":"OTH"}.get(method, "PAY")
    con.execute("""INSERT INTO payments(ref,invoice_id,customer_id,amount,method,date,reference,notes,user_id,confirmed)
        VALUES(?,?,?,?,?,?,?,?,?, 'manual')""",
        (f"PAY-{pref}-{datetime.date.today().strftime('%y%m%d')}-{nxt:03d}", iid, inv["customer_id"],
         sisa, method, datetime.date.today().isoformat(), ref_note or f"Pelunasan {inv['number']}",
         "Ditandai lunas dari halaman invoice", user["id"]))
    con.execute("UPDATE invoices SET paid_amount=amount, status='lunas' WHERE id=?", (iid,))
    _sync_balance(con, inv["customer_id"])
    db.log_activity(con, user["username"], "invoice.mark_paid", inv["number"], f"{method} Rp{sisa}")
    return sisa, None

@app.post("/billing/{iid}/mark-paid")
async def invoice_mark_paid(request: Request, iid: int):
    u = require(request, "billing"); con = C(request)
    f = await form(request)
    sisa, err = _mark_paid(con, iid, f.get("method","Tunai"), f.get("reference",""), u)
    con.commit()
    if err: return flash_set(RedirectResponse(f"/billing/{iid}", 303), err, "err")
    return flash_set(RedirectResponse(f"/billing/{iid}", 303),
                     f"Invoice dilunasi. Pembayaran Rp{sisa:,} dicatat (metode {f.get('method','Tunai')}). Saldo pelanggan diperbarui.".replace(",","."))

@app.post("/billing/{iid}/cancel")
def invoice_cancel(request: Request, iid: int):
    u = require(request, "billing"); con = C(request)
    inv = db.one(con, "SELECT * FROM invoices WHERE id=?", (iid,))
    if not inv: raise HTTPException(404)
    if inv["paid_amount"] > 0:
        return flash_set(RedirectResponse(f"/billing/{iid}", 303), "Tidak dapat membatalkan invoice yang sudah ada pembayaran.", "err")
    con.execute("UPDATE invoices SET status='batal' WHERE id=?", (iid,))
    _sync_balance(con, inv["customer_id"])
    db.log_activity(con, u["username"], "invoice.cancel", inv["number"], ""); con.commit()
    return flash_set(RedirectResponse(f"/billing/{iid}", 303), f"Invoice {inv['number']} dibatalkan.")

@app.get("/billing/{iid}/print", response_class=HTMLResponse)
def invoice_print(request: Request, iid: int):
    u = require(request, "billing"); con = C(request)
    inv = db.one(con, INV_SELECT + " WHERE i.id=?", (iid,))
    if not inv: raise HTTPException(404)
    cust = db.one(con, "SELECT * FROM customers WHERE id=?", (inv["customer_id"],))
    pays = db.q(con, "SELECT * FROM payments WHERE invoice_id=?", (iid,))
    st = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    return templates.TemplateResponse(request, "invoice_print.html",
        {"inv": inv, "cust": cust, "pays": pays, "st": st, "rp": fmt_rp})

@app.get("/export/invoices.csv")
def export_invoices(request: Request, status: str = ""):
    u = require(request, "billing"); con = C(request)
    rows = db.q(con, INV_SELECT + (" WHERE i.status=?" if status else "") + " ORDER BY i.period DESC",
                (status,) if status else ())
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Nomor","Kode Pelanggan","Pelanggan","Periode","Tgl Terbit","Jatuh Tempo","Nominal","Dibayar","Status"])
    for r in rows: w.writerow([r["number"], r["ccode"], r["cname"], r["period"], r["issue_date"],
                               r["due_date"], r["amount"], r["paid_amount"], r["status"]])
    return Response("\ufeff"+buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=invoice.csv"})

# ================================================================= PAYMENTS
PAY_SELECT = """SELECT p.*, c.name cname, c.code ccode, i.number inv, i.amount inv_amount
  FROM payments p JOIN customers c ON c.id=p.customer_id LEFT JOIN invoices i ON i.id=p.invoice_id"""

@app.get("/payments", response_class=Response)
def payments(request: Request, search: str = "", method: str = "", from_: str = "", to: str = "", page: str = "1"):
    u = require(request, "payments"); con = C(request)
    where, args = [], []
    if search: where.append("(p.ref LIKE ? OR c.name LIKE ? OR i.number LIKE ?)"); args += [f"%{search}%"]*3
    if method: where.append("p.method=?"); args.append(method)
    if from_: where.append("p.date>=?"); args.append(from_)
    if to: where.append("p.date<=?"); args.append(to)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(con, f"SELECT COUNT(*) n FROM payments p JOIN customers c ON c.id=p.customer_id LEFT JOIN invoices i ON i.id=p.invoice_id {w}", args)["n"]
    sumamt = db.one(con, f"SELECT COALESCE(SUM(p.amount),0) s FROM payments p JOIN customers c ON c.id=p.customer_id LEFT JOIN invoices i ON i.id=p.invoice_id {w}", args)["s"]
    p_, pages, off = paginate(request, total, page, 15)
    rows = db.q(con, f"{PAY_SELECT} {w} ORDER BY p.date DESC, p.id DESC LIMIT ? OFFSET ?", args + [15, off])
    return templates.TemplateResponse(request, "payments.html", ctx(request, u, rows=rows, total=total,
        sumamt=sumamt, page=p_, pages=pages, search=search, method=method, from_=from_, to=to, active="payments"))

@app.get("/payments/new", response_class=Response)
def payment_new(request: Request, invoice: str = ""):
    u = require(request, "payments"); con = C(request)
    _inv_overdue_sync(con)
    unpaid = db.q(con, """SELECT i.id, i.number, i.amount, i.paid_amount, c.name cname, c.code ccode
        FROM invoices i JOIN customers c ON c.id=i.customer_id
        WHERE i.status IN ('belum_bayar','lewat_jatuh_tempo') ORDER BY i.due_date LIMIT 200""")
    custs = db.q(con, "SELECT id,name,code FROM customers ORDER BY name")
    return templates.TemplateResponse(request, "payment_form.html", ctx(request, u, unpaid=unpaid,
        custs=custs, preselect=invoice, active="payments"))

@app.post("/payments/save")
async def payment_save(request: Request):
    u = require(request, "payments"); con = C(request)
    f = await form(request)
    errs = {}
    iid = pint(f.get("invoice_id"))
    inv = db.one(con, "SELECT * FROM invoices WHERE id=?", (iid,)) if iid else None
    if not inv: errs["invoice_id"] = "Pilih invoice yang valid."
    try:
        amount = int(float(f.get("amount", "0")))
        if amount <= 0: errs["amount"] = "Nominal harus > 0."
    except Exception:
        errs["amount"] = "Nominal harus angka."
    if inv and amount > inv["amount"] - inv["paid_amount"]:
        errs["amount"] = f"Melebihi sisa tagihan ({fmt_rp(inv['amount']-inv['paid_amount'])})."
    method = f.get("method", "Tunai")
    if method not in ("Tunai","Transfer","QRIS","Lainnya"): errs["method"] = "Metode tidak valid."
    if errs:
        unpaid = db.q(con, """SELECT i.id,i.number,i.amount,i.paid_amount,c.name cname,c.code ccode
            FROM invoices i JOIN customers c ON c.id=i.customer_id WHERE i.status IN ('belum_bayar','lewat_jatuh_tempo') LIMIT 200""")
        custs = db.q(con, "SELECT id,name,code FROM customers ORDER BY name")
        return templates.TemplateResponse(request, "payment_form.html", ctx(request, u, unpaid=unpaid,
            custs=custs, preselect="", formdata=dict(f), errors=errs, active="payments"), status_code=422)
    nxt = db.one(con, "SELECT COUNT(*)+1 n FROM payments")["n"]
    pref = {"Tunai":"KT","Transfer":"TRF","QRIS":"QRIS","Lainnya":"OTH"}[method]
    date = f.get("date") or datetime.date.today().isoformat()
    con.execute("""INSERT INTO payments(ref,invoice_id,customer_id,amount,method,date,reference,notes,user_id,confirmed)
        VALUES(?,?,?,?,?,?,?,?,?, 'manual')""",
        (f"PAY-{pref}-{date.replace('-','')[2:]}-{nxt:03d}", iid, inv["customer_id"], amount, method,
         date, f.get("reference",""), f.get("notes",""), u["id"]))
    new_paid = inv["paid_amount"] + amount
    ns = "lunas" if new_paid >= inv["amount"] else inv["status"]
    con.execute("UPDATE invoices SET paid_amount=?, status=? WHERE id=?", (min(new_paid, inv["amount"]), ns, iid))
    _sync_balance(con, inv["customer_id"])
    db.log_activity(con, u["username"], "payment.create", f"PAY#{nxt}",
                    f"{method} Rp{amount} utk {inv['number']} → invoice {ns}")
    con.commit()
    return flash_set(RedirectResponse("/payments", 303),
        f"Pembayaran {method} Rp{amount:,} dicatat untuk {inv['number']}. Status invoice: {ns}.".replace(",", ".") + (" Saldo pelanggan diperbarui." if ns=="lunas" else ""))

@app.get("/payments/{pid}", response_class=Response)
def payment_detail(request: Request, pid: int):
    u = require(request, "payments"); con = C(request)
    p = db.one(con, PAY_SELECT + " WHERE p.id=?", (pid,))
    if not p: raise HTTPException(404)
    return templates.TemplateResponse(request, "payment_detail.html", ctx(request, u, p=p, active="payments"))

@app.get("/export/payments.csv")
def export_payments(request: Request):
    u = require(request, "payments"); con = C(request)
    rows = db.q(con, PAY_SELECT + " ORDER BY p.date DESC")
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Ref","Tanggal","Invoice","Kode","Pelanggan","Nominal","Metode","Referensi","Dicatat oleh"])
    for r in rows: w.writerow([r["ref"], r["date"], r["inv"] or "-", r["ccode"], r["cname"], r["amount"], r["method"], r["reference"], ""])
    return Response("\ufeff"+buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=pembayaran.csv"})

# ================================================================= FINANCE
@app.get("/finance", response_class=Response)
def finance(request: Request, from_: str = "", to: str = ""):
    u = require(request, "finance"); con = C(request)
    today = datetime.date.today()
    if not from_: from_ = today.replace(day=1).isoformat()
    if not to: to = today.isoformat()
    rng = (from_, to)
    rev = db.one(con, "SELECT COALESCE(SUM(amount),0) s, COUNT(*) n FROM payments WHERE date BETWEEN ? AND ?", rng)["s"]
    revn = db.one(con, "SELECT COUNT(*) n FROM payments WHERE date BETWEEN ? AND ?", rng)["n"]
    exp = db.one(con, "SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE date BETWEEN ? AND ?", rng)["s"]
    unpaid = db.one(con, "SELECT COALESCE(SUM(amount-paid_amount),0) s, COUNT(*) n FROM invoices WHERE status='belum_bayar'")["s"]
    overdue_row = db.one(con, "SELECT COALESCE(SUM(amount-paid_amount),0) s, COUNT(*) n FROM invoices WHERE status='lewat_jatuh_tempo'")
    methods = db.q(con, "SELECT method, SUM(amount) s, COUNT(*) n FROM payments WHERE date BETWEEN ? AND ? GROUP BY method ORDER BY s DESC", rng)
    monthly = db.q(con, """SELECT substr(date,1,7) m, SUM(amount) s FROM payments
        WHERE date>=date(?,'-5 month') AND date<=? GROUP BY m ORDER BY m""", (from_, to))
    recent = db.q(con, """SELECT p.*, c.name cname FROM payments p JOIN customers c ON c.id=p.customer_id
        ORDER BY p.date DESC, p.id DESC LIMIT 8""")
    return templates.TemplateResponse(request, "finance.html", ctx(request, u, rev=rev, revn=revn, exp=exp,
        unpaid=unpaid, overdue=overdue_row["s"], overdue_n=overdue_row["n"], methods=methods, monthly=monthly,
        recent=recent, from_=from_, to=to,
        chart_monthly=json.dumps([{"label": r["m"], "value": r["s"]} for r in monthly]),
        chart_methods=json.dumps([{"label": r["method"], "value": r["s"]} for r in methods]),
        active="finance"))

# ================================================================= EXPENSES
EXP_CATS = ["Bandwidth","Listrik","Operasional","Peralatan","Gaji","Internet Cadangan","Lainnya"]

@app.get("/expenses", response_class=Response)
def expenses(request: Request, cat: str = "", from_: str = "", to: str = "", page: str = "1"):
    u = require(request, "expenses"); con = C(request)
    where, args = [], []
    if cat: where.append("category=?"); args.append(cat)
    if from_: where.append("date>=?"); args.append(from_)
    if to: where.append("date<=?"); args.append(to)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(con, f"SELECT COUNT(*) n FROM expenses {w}", args)["n"]
    ssum = db.one(con, f"SELECT COALESCE(SUM(amount),0) s FROM expenses {w}", args)["s"]
    p, pages, off = paginate(request, total, page, 15)
    rows = db.q(con, f"SELECT * FROM expenses {w} ORDER BY date DESC, id DESC LIMIT ? OFFSET ?", args + [15, off])
    edit_id = request.query_params.get("edit")
    editing = db.one(con, "SELECT * FROM expenses WHERE id=?", (int(edit_id),)) if edit_id else None
    return templates.TemplateResponse(request, "expenses.html", ctx(request, u, rows=rows, total=total,
        ssum=ssum, page=p, pages=pages, cat=cat, from_=from_, to=to, cats=EXP_CATS, editing=editing, active="expenses"))

@app.post("/expenses/save")
async def expense_save(request: Request):
    u = require(request, "expenses"); con = C(request)
    f = await form(request)
    eid = pint(f.get("id", "")); errs = {}
    if not str(f.get("description","")).strip(): errs["description"] = "Deskripsi wajib diisi."
    try:
        amount = int(float(f.get("amount","0")))
        if amount <= 0: errs["amount"] = "Nominal harus > 0."
    except Exception:
        errs["amount"] = "Nominal harus angka."
    if errs:
        rows = db.q(con, "SELECT * FROM expenses ORDER BY date DESC LIMIT 15")
        return templates.TemplateResponse(request, "expenses.html", ctx(request, u, rows=rows, total=len(rows),
            ssum=sum(r["amount"] for r in rows), page=1, pages=1, cat="", from_="", to="", cats=EXP_CATS,
            editing=dict(f), errors=errs, active="expenses"), status_code=422)
    cat = f.get("category","Lainnya"); date = f.get("date") or datetime.date.today().isoformat()
    if eid:
        con.execute("UPDATE expenses SET category=?,description=?,amount=?,date=?,notes=? WHERE id=?",
                    (cat, f["description"], amount, date, f.get("notes",""), eid))
        msg = "Pengeluaran diperbarui."
    else:
        con.execute("INSERT INTO expenses(category,description,amount,date,notes) VALUES(?,?,?,?,?)",
                    (cat, f["description"], amount, date, f.get("notes","")))
        msg = "Pengeluaran dicatat."
    db.log_activity(con, u["username"], "expense.save", cat, f"{f['description']} Rp{amount}"); con.commit()
    return flash_set(RedirectResponse("/expenses", 303), msg)

@app.post("/expenses/{eid}/delete")
def expense_delete(request: Request, eid: int):
    u = require(request, "expenses"); con = C(request)
    e = db.one(con, "SELECT * FROM expenses WHERE id=?", (eid,))
    if not e: raise HTTPException(404)
    con.execute("DELETE FROM expenses WHERE id=?", (eid,))
    db.log_activity(con, u["username"], "expense.delete", e["category"], e["description"]); con.commit()
    return flash_set(RedirectResponse("/expenses", 303), "Pengeluaran dihapus.")

# ================================================================= BACKUPS
def _backup_db_file(name):
    src = sqlite3.connect(db.DB_PATH)
    dst = sqlite3.connect(os.path.join(BACKUP_DIR, name))
    with dst: src.backup(dst)
    src.close(); dst.close()
    return os.path.join(BACKUP_DIR, name)

@app.get("/backups", response_class=Response)
def backups(request: Request):
    u = require(request, "backups"); con = C(request)
    rows = db.q(con, "SELECT * FROM backups ORDER BY created_at DESC, id DESC")
    return templates.TemplateResponse(request, "backups.html", ctx(request, u, rows=rows, active="backups"))

@app.post("/backups/create")
async def backup_create(request: Request):
    u = require(request, "backups"); con = C(request)
    f = await form(request)
    kind = f.get("kind", "Database")
    scope = f.get("scope", "")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if kind == "Database":
        name = f"spb-db-{ts}.sqlite"
        try:
            path = _backup_db_file(name)
            size = os.path.getsize(path)
            con.execute("""INSERT INTO backups(name,kind,scope,size,mode,status,path,created_by,created_at)
                VALUES(?,?,?,?, 'REAL','OK',?,?,?)""", (name, kind, "Seluruh database aplikasi", size, path, u["username"], db.now()))
            db.log_activity(con, u["username"], "backup.create", name, "REAL salinan SQLite dibuat"); con.commit()
            return flash_set(RedirectResponse("/backups", 303), f"Backup REAL berhasil: {name} ({size:,} byte).".replace(",", ".") )
        except Exception as e:
            con.execute("""INSERT INTO backups(name,kind,scope,size,mode,status,created_by,created_at)
                VALUES(?,?,?,?, 'REAL','FAILED',?,?)""", (f"spb-db-{ts}.sqlite", kind, "Database", 0, str(e), u["username"], db.now()))
            con.commit()
            return flash_set(RedirectResponse("/backups", 303), f"Backup database GAGAL: {e}", "err")
    elif kind == "RouterOS Config":
        # Try a real API export first; RouterOS API export protocol is NOT implemented,
        # so we record an explicitly DEMO placeholder file. Never claim REAL here.
        name = f"{(scope or 'router').lower().replace(' ','-')}-{ts}.backup"
        content = (f"# SAMBIRA PANDORA BOX - BACKUP PLACEHOLDER (MODE: DEMO)\n"
                   f"# Router scope : {scope}\n# Created      : {db.now()} by {u['username']}\n"
                   f"# NOTE: Export konfigurasi RouterOS TIDAK dilakukan — protokol API export\n"
                   f"#       belum diimplementasi pada build ini dan router tidak dapat dijangkau.\n"
                   f"# File ini adalah penanda demo, BUKAN konfigurasi perangkat.\n")
        try:
            with open(os.path.join(BACKUP_DIR, name), "w") as fh: fh.write(content)
            con.execute("""INSERT INTO backups(name,kind,scope,size,mode,status,path,created_by,created_at)
                VALUES(?,?,?,?, 'DEMO','OK',?,?,?)""",
                (name, kind, scope, len(content), os.path.join(BACKUP_DIR, name), u["username"], db.now()))
            db.log_activity(con, u["username"], "backup.create", name, "DEMO placeholder (bukan config RouterOS asli)")
            con.commit()
            return flash_set(RedirectResponse("/backups", 303),
                             f"Backup '{name}' dibuat sebagai REKAMAN DEMO — konfigurasi TIDAK diambil dari RouterOS.")
        except Exception as e:
            con.execute("""INSERT INTO backups(name,kind,scope,size,mode,status,created_by,created_at)
                VALUES(?,?,?,?, 'DEMO','FAILED',?,?)""", (name, kind, scope, 0, str(e), u["username"], db.now()))
            con.commit()
            return flash_set(RedirectResponse("/backups", 303), f"Pembuatan file gagal: {e}", "err")
    else:  # Aplikasi
        name = f"spb-app-{ts}.tar"
        import tarfile
        try:
            with tarfile.open(os.path.join(BACKUP_DIR, name), "w") as tf:
                tf.add(BASE, arcname="app")
            size = os.path.getsize(os.path.join(BACKUP_DIR, name))
            con.execute("""INSERT INTO backups(name,kind,scope,size,mode,status,path,created_by,created_at)
                VALUES(?,?,?,?, 'REAL','OK',?,?,?)""",
                (name, "Aplikasi", "Kode aplikasi", size, os.path.join(BACKUP_DIR, name), u["username"], db.now()))
            db.log_activity(con, u["username"], "backup.create", name, "REAL arsip kode aplikasi")
            con.commit()
            return flash_set(RedirectResponse("/backups", 303), f"Backup aplikasi REAL dibuat: {name}")
        except Exception as e:
            con.execute("""INSERT INTO backups(name,kind,scope,size,mode,status,created_by,created_at)
                VALUES(?,?,?,?, 'REAL','FAILED',?,?)""", (name, "Aplikasi", "Kode aplikasi", 0, str(e), u["username"], db.now()))
            con.commit()
            return flash_set(RedirectResponse("/backups", 303), f"Backup aplikasi gagal: {e}", "err")

@app.get("/backups/{bid}/download")
def backup_download(request: Request, bid: int):
    u = require(request, "backups"); con = C(request)
    b = db.one(con, "SELECT * FROM backups WHERE id=?", (bid,))
    if not b: raise HTTPException(404)
    if b["status"] != "OK" or not b["path"] or not os.path.exists(b["path"]):
        return Response(f"Berkas backup tidak tersedia (status: {b['status']}, mode: {b['mode']}). "
                        f"Rekaman lama mungkin hanya catatan tanpa berkas.", media_type="text/plain", status_code=404)
    with open(b["path"], "rb") as fh: data = fh.read()
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f"attachment; filename={b['name']}"})

@app.post("/backups/{bid}/delete")
def backup_delete(request: Request, bid: int):
    u = require(request, "backups"); con = C(request)
    b = db.one(con, "SELECT * FROM backups WHERE id=?", (bid,))
    if not b: raise HTTPException(404)
    if b["path"] and os.path.exists(b["path"]) and b["mode"] in ("REAL","DEMO"):
        try: os.remove(b["path"])
        except Exception: pass
    con.execute("DELETE FROM backups WHERE id=?", (bid,))
    db.log_activity(con, u["username"], "backup.delete", b["name"], ""); con.commit()
    return flash_set(RedirectResponse("/backups", 303), f"Backup {b['name']} dihapus.")

# ================================================================= NOTIFICATIONS
@app.get("/notifications", response_class=Response)
def notifications(request: Request, page: str = "1"):
    u = require(request, "notifications"); con = C(request)
    total = db.one(con, "SELECT COUNT(*) n FROM notifications")["n"]
    p, pages, off = paginate(request, total, page, 15)
    rows = db.q(con, f"SELECT * FROM notifications ORDER BY id DESC LIMIT ? OFFSET ?", (15, off))
    tpls = db.q(con, "SELECT * FROM templates ORDER BY id")
    st = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    return templates.TemplateResponse(request, "notifications.html", ctx(request, u, rows=rows, tpls=tpls,
        page=p, pages=pages, st=st, active="notifications"))

@app.post("/notifications/send")
async def notification_send(request: Request):
    u = require(request, "notifications"); con = C(request)
    f = await form(request)
    channel = f.get("channel", "telegram"); to = f.get("to", "").strip(); body = f.get("body", "").strip()
    subject = f.get("subject", "").strip()
    if not body:
        return flash_set(RedirectResponse("/notifications", 303), "Isi pesan kosong — tidak ada yang dikirim.", "err")
    st = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    enabled = {"telegram": st.get("tg_enabled"), "whatsapp": st.get("wa_enabled"), "email": st.get("email_enabled")}[channel]
    ok, mode, detail = notify.dispatch(channel, st, to, subject, body)
    status = "sent" if ok else ("queued" if mode == "DEMO" else "failed")
    con.execute("""INSERT INTO notifications(channel,to_addr,subject,body,status,mode,error,created_at)
        VALUES(?,?,?,?,?,?,?,?)""", (channel, to, subject, body, status, mode, detail if not ok else "", db.now()))
    db.log_activity(con, u["username"], "notify.send", channel, f"[{mode}] {'ok' if ok else 'tidak terkirim'}: {detail[:60]}")
    con.commit()
    prefix = f"[{channel.upper()}]"
    if ok:
        msg = f"{prefix} Pesan TERKIRIM via API ({detail})"
    else:
        msg = f"{prefix} MODE DEMO — TIDAK ADA PESAN KELUAR. {detail}"
        if enabled != "1": msg += f" (Catatan: kanal {channel} dinonaktifkan di Pengaturan.)"
    return flash_set(RedirectResponse("/notifications", 303), msg, "ok" if ok else "warn")

@app.post("/notifications/test-telegram")
def notification_test_telegram(request: Request):
    u = require(request, "notifications"); con = C(request)
    st = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    ok, mode, detail = notify.send_telegram(st.get("tg_token",""), st.get("tg_chat",""),
                                            "Uji koneksi dari SambiraPandoraBox.")
    con.execute("""INSERT INTO notifications(channel,to_addr,subject,body,status,mode,error,created_at)
        VALUES('telegram',?, 'Test Telegram', ?,?,?,?,?)""",
        (st.get("tg_chat",""), "Uji koneksi", "Terkirim." if ok else detail, "sent" if ok else "failed", mode, "" if ok else detail, db.now()))
    db.log_activity(con, u["username"], "notify.test", "telegram", f"[{mode}] {detail[:80]}"); con.commit()
    kind = "ok" if ok else "warn"
    return flash_set(RedirectResponse("/settings#notifikasi", 303),
                     (f"Telegram REAL: pesan uji TERKIRIM ke chat {st.get('tg_chat')}." if ok
                      else f"Telegram {mode}: {detail}"), kind)

@app.post("/notifications/template/{tid}")
async def template_update(request: Request, tid: int):
    u = require(request, "notifications"); con = C(request)
    f = await form(request)
    body = f.get("body", "").strip()
    if not body:
        return flash_set(RedirectResponse("/notifications", 303), "Template tidak boleh kosong.", "err")
    con.execute("UPDATE templates SET body=? WHERE id=?", (body, tid))
    db.log_activity(con, u["username"], "template.update", str(tid), f.get("name","")); con.commit()
    return flash_set(RedirectResponse("/notifications", 303), "Template disimpan.")

@app.post("/notifications/{nid}/delete")
def notification_delete(request: Request, nid: int):
    u = require(request, "notifications"); con = C(request)
    con.execute("DELETE FROM notifications WHERE id=?", (nid,)); con.commit()
    return flash_set(RedirectResponse("/notifications", 303), "Riwayat notifikasi dihapus.")

# ================================================================= QRIS
@app.get("/qris", response_class=Response)
def qris(request: Request):
    u = require(request, "qris"); con = C(request)
    st = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    pending = db.q(con, """SELECT i.*, c.name cname, c.code ccode FROM invoices i JOIN customers c ON c.id=i.customer_id
        WHERE i.status IN ('belum_bayar','lewat_jatuh_tempo') ORDER BY i.due_date LIMIT 50""")
    confirmed_qr = db.q(con, """SELECT p.*, c.name cname FROM payments p JOIN customers c ON c.id=p.customer_id
        WHERE p.method='QRIS' ORDER BY p.id DESC LIMIT 10""")
    return templates.TemplateResponse(request, "qris.html", ctx(request, u, st=st, pending=pending,
        confirmed=confirmed_qr, active="qris"))

@app.post("/qris/settings")
async def qris_settings(request: Request):
    u = require(request, "qris"); con = C(request)
    f = await form(request)
    db.set_setting(con, "qris_merchant", f.get("merchant",""))
    db.set_setting(con, "qris_instructions", f.get("instructions",""))
    db.set_setting(con, "qris_enabled", "1" if f.get("enabled") else "0")
    img = f.get("qr_image")
    if img and hasattr(img, "read"):
        data = img.file.read()
        if data and len(data) < 2_000_000:
            fn = "qris_" + secrets.token_hex(6) + os.path.splitext(img.filename or "")[1].lower()
            if fn.endswith((".png",".jpg",".jpeg",".webp",".svg")):
                with open(os.path.join(UPLOAD_DIR, fn), "wb") as fh: fh.write(data)
                db.set_setting(con, "qris_image", "/uploads/" + fn)
            else:
                return flash_set(RedirectResponse("/qris", 303), "Format gambar harus png/jpg/webp/svg.", "err")
        elif data:
            return flash_set(RedirectResponse("/qris", 303), "Gambar terlalu besar (maks 2MB).", "err")
    db.log_activity(con, u["username"], "qris.settings", "QRIS", "Perubahan konfigurasi QRIS"); con.commit()
    return flash_set(RedirectResponse("/qris", 303), "Pengaturan QRIS disimpan.")

@app.post("/qris/confirm")
async def qris_confirm(request: Request):
    u = require(request, "qris"); con = C(request)
    if u["role"] not in ("superadmin","admin","finance"):
        return flash_set(RedirectResponse("/qris", 303), "Konfirmasi pembayaran QRIS hanya untuk Finance/Admin.", "err")
    f = await form(request)
    iid = pint(f.get("invoice_id"))
    inv = db.one(con, "SELECT * FROM invoices WHERE id=?", (iid,)) if iid else None
    if not inv:
        return flash_set(RedirectResponse("/qris", 303), "Pilih invoice terlebih dahulu.", "err")
    if inv["status"] == "lunas":
        return flash_set(RedirectResponse("/qris", 303), "Invoice sudah lunas.", "err")
    ref = f.get("reference","").strip()
    sisa = inv["amount"] - inv["paid_amount"]
    nxt = db.one(con, "SELECT COUNT(*)+1 n FROM payments")["n"]
    con.execute("""INSERT INTO payments(ref,invoice_id,customer_id,amount,method,date,reference,notes,user_id,confirmed)
        VALUES(?,?,?,?, 'QRIS', ?,?,?,?, 'manual-staff')""",
        (f"PAY-QRIS-{datetime.date.today().strftime('%y%m%d')}-{nxt:03d}", iid, inv["customer_id"], sisa,
         datetime.date.today().isoformat(), ref or "QRIS manual", "Konfirmasi manual staff atas scan QRIS pelanggan", u["id"]))
    con.execute("UPDATE invoices SET paid_amount=amount, status='lunas' WHERE id=?", (iid,))
    _sync_balance(con, inv["customer_id"])
    db.log_activity(con, u["username"], "qris.confirm", inv["number"], f"QRIS manual Rp{sisa}")
    con.commit()
    return flash_set(RedirectResponse(f"/billing/{iid}", 303),
        f"Pembayaran QRIS dikonfirmasi MANUAL oleh {u['name']} ({fmt_rp(sisa)}). Catatan: tidak ada payment gateway otomatis di sistem ini.")

@app.get("/uploads/{fn}")
def upload_file(fn: str):
    safe = os.path.basename(fn)
    path = os.path.join(UPLOAD_DIR, safe)
    if not os.path.exists(path): raise HTTPException(404)
    ext = safe.rsplit(".", 1)[-1].lower()
    mime = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","webp":"image/webp","svg":"image/svg+xml"}.get(ext,"application/octet-stream")
    with open(path, "rb") as fh: return Response(fh.read(), media_type=mime)

# ================================================================= USERS & ROLES
@app.get("/users", response_class=HTMLResponse)
def users(request: Request):
    u = require(request, "users"); con = C(request)
    rows = db.q(con, "SELECT * FROM users ORDER BY id")
    return templates.TemplateResponse(request, "users.html", ctx(request, u, rows=rows, active="users"))

@app.post("/users/save")
async def user_save(request: Request):
    u = require(request, "users"); con = C(request)
    f = await form(request)
    uid = pint(f.get("id", ""))
    errs = {}
    if not str(f.get("name","")).strip(): errs["name"] = "Nama wajib diisi."
    un = str(f.get("username","")).strip()
    if not un: errs["username"] = "Username wajib diisi."
    elif db.one(con, "SELECT id FROM users WHERE username=? AND id<>?", (un, uid)):
        errs["username"] = "Username sudah dipakai."
    if f.get("role") not in ROLES: errs["role"] = "Peran tidak valid."
    if not uid and len(str(f.get("password",""))) < 6: errs["password"] = "Kata sandi minimal 6 karakter."
    if uid and f.get("password"):
        if len(str(f["password"])) < 6: errs["password"] = "Kata sandi minimal 6 karakter."
    if uid == u["id"] and f.get("role") != "superadmin":
        errs["role"] = "Tidak dapat menurunkan peran akun sendiri."
    if errs:
        rows = db.q(con, "SELECT * FROM users ORDER BY id")
        return templates.TemplateResponse(request, "users.html", ctx(request, u, rows=rows, editing=dict(f),
            errors=errs, active="users"), status_code=422)
    active = 1 if f.get("active") else 0
    if uid:
        if int(uid) == int(u["id"]) and not active:
            return flash_set(RedirectResponse("/users", 303), "Tidak dapat menonaktifkan akun sendiri.", "err")
        con.execute("UPDATE users SET name=?,username=?,email=?,role=?,active=? WHERE id=?",
                    (f["name"], un, f.get("email",""), f["role"], active, uid))
        if f.get("password"):
            con.execute("UPDATE users SET password_hash=? WHERE id=?", (db.hash_pw(f["password"]), uid))
        msg = "Pengguna diperbarui."
    else:
        con.execute("INSERT INTO users(name,username,email,password_hash,role,active,created_at) VALUES(?,?,?,?,?,?,?)",
                    (f["name"], un, f.get("email",""), db.hash_pw(f["password"]), f["role"], active, db.now()))
        msg = "Pengguna baru dibuat."
    db.log_activity(con, u["username"], "user.save", un, f"role={f['role']} active={active}"); con.commit()
    return flash_set(RedirectResponse("/users", 303), msg)

@app.post("/users/{uid}/toggle")
def user_toggle(request: Request, uid: int):
    u = require(request, "users"); con = C(request)
    t = db.one(con, "SELECT * FROM users WHERE id=?", (uid,))
    if not t: raise HTTPException(404)
    if t["id"] == u["id"]:
        return flash_set(RedirectResponse("/users", 303), "Tidak dapat menonaktifkan akun sendiri.", "err")
    con.execute("UPDATE users SET active=? WHERE id=?", (0 if t["active"] else 1, uid))
    if not t["active"] is None and t["active"]:
        con.execute("DELETE FROM sessions_tbl WHERE user_id=?", (uid,))
    db.log_activity(con, u["username"], "user.toggle", t["username"], "nonaktif" if t["active"] else "aktif")
    con.commit()
    return flash_set(RedirectResponse("/users", 303), f"Akun {t['username']} {'dinonaktifkan (sesi dihapus)' if t['active'] else 'diaktifkan'}.")

@app.post("/users/{uid}/delete")
def user_delete(request: Request, uid: int):
    u = require(request, "users"); con = C(request)
    t = db.one(con, "SELECT * FROM users WHERE id=?", (uid,))
    if not t: raise HTTPException(404)
    if t["id"] == u["id"]:
        return flash_set(RedirectResponse("/users", 303), "Tidak dapat menghapus akun sendiri.", "err")
    if t["role"] == "superadmin" and db.one(con,"SELECT COUNT(*) n FROM users WHERE role='superadmin'")["n"] <= 1:
        return flash_set(RedirectResponse("/users", 303), "Harus ada minimal satu Super Admin.", "err")
    con.execute("DELETE FROM sessions_tbl WHERE user_id=?", (uid,))
    con.execute("DELETE FROM users WHERE id=?", (uid,))
    db.log_activity(con, u["username"], "user.delete", t["username"], ""); con.commit()
    return flash_set(RedirectResponse("/users", 303), f"Pengguna {t['username']} dihapus.")

# ================================================================= ACTIVITY LOG
@app.get("/activity-log", response_class=HTMLResponse)
def activity_log(request: Request, search: str = "", user_f: str = "", page: str = "1"):
    u = require(request, "activity"); con = C(request)
    where, args = [], []
    if search: where.append("(action LIKE ? OR obj LIKE ? OR detail LIKE ?)"); args += [f"%{search}%"]*3
    if user_f: where.append("user=?"); args.append(user_f)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.one(con, f"SELECT COUNT(*) n FROM activity_log {w}", args)["n"]
    p, pages, off = paginate(request, total, page, 25)
    rows = db.q(con, f"SELECT * FROM activity_log {w} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", args + [25, off])
    users_ = db.q(con, "SELECT DISTINCT user FROM activity_log ORDER BY user")
    return templates.TemplateResponse(request, "activity_log.html", ctx(request, u, rows=rows, total=total,
        page=p, pages=pages, search=search, user_f=user_f, users_=users_, active="activity"))

# ================================================================= SETTINGS
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    u = require(request, "settings"); con = C(request)
    st = {r["key"]: r["value"] for r in db.q(con, "SELECT * FROM settings")}
    return templates.TemplateResponse(request, "settings.html", ctx(request, u, st=st, active="settings"))

@app.post("/settings/general")
async def settings_general(request: Request):
    u = require(request, "settings"); con = C(request)
    f = await form(request)
    if not str(f.get("isp_name","")).strip():
        return flash_set(RedirectResponse("/settings", 303), "Nama ISP tidak boleh kosong.", "err")
    for k in ("isp_name","timezone","currency","language"):
        db.set_setting(con, k, f.get(k, ""))
    db.log_activity(con, u["username"], "settings.update", "general", f.get("isp_name","")); con.commit()
    return flash_set(RedirectResponse("/settings", 303), "Pengaturan umum disimpan.")

@app.post("/settings/network")
async def settings_network(request: Request):
    u = require(request, "settings"); con = C(request)
    f = await form(request)
    pi = pint(f.get("poll_interval","60"), 60)
    if pi < 10 or pi > 3600:
        return flash_set(RedirectResponse("/settings", 303), "Interval polling harus 10-3600 detik.", "err")
    db.set_setting(con, "ros_default_port", pint(f.get("ros_default_port","8728"),8728))
    db.set_setting(con, "ros_default_user", f.get("ros_default_user",""))
    db.set_setting(con, "poll_interval", pi)
    db.log_activity(con, u["username"], "settings.update", "network", f"port={pi}"); con.commit()
    return flash_set(RedirectResponse("/settings", 303), "Pengaturan jaringan disimpan.")

@app.post("/settings/billing")
async def settings_billing(request: Request):
    u = require(request, "settings"); con = C(request)
    f = await form(request)
    bd = pint(f.get("billing_day","1"),1); gp = pint(f.get("grace_period","3"),3)
    if bd < 1 or bd > 28: return flash_set(RedirectResponse("/settings", 303), "Hari tagih harus 1-28.", "err")
    if gp < 0 or gp > 30: return flash_set(RedirectResponse("/settings", 303), "Masa tenggang harus 0-30 hari.", "err")
    db.set_setting(con, "billing_day", bd); db.set_setting(con, "grace_period", gp)
    db.set_setting(con, "late_behavior", f.get("late_behavior","suspend") if f.get("late_behavior") in ("suspend","denda","biarkan") else "suspend")
    db.log_activity(con, u["username"], "settings.update", "billing", f"day={bd} grace={gp}"); con.commit()
    return flash_set(RedirectResponse("/settings", 303), "Pengaturan penagihan disimpan.")

@app.post("/settings/notifications")
async def settings_notifications(request: Request):
    u = require(request, "settings"); con = C(request)
    f = await form(request)
    db.set_setting(con, "tg_token", f.get("tg_token","").strip())
    db.set_setting(con, "tg_chat", f.get("tg_chat","").strip())
    db.set_setting(con, "tg_enabled", "1" if f.get("tg_enabled") else "0")
    db.set_setting(con, "wa_enabled", "1" if f.get("wa_enabled") else "0")
    db.set_setting(con, "wa_number", f.get("wa_number",""))
    db.set_setting(con, "email_enabled", "1" if f.get("email_enabled") else "0")
    db.set_setting(con, "smtp_host", f.get("smtp_host","")); db.set_setting(con, "smtp_user", f.get("smtp_user",""))
    db.log_activity(con, u["username"], "settings.update", "notifications", "token" if f.get("tg_token") else "-")
    con.commit()
    return flash_set(RedirectResponse("/settings", 303), "Pengaturan notifikasi disimpan.")

@app.post("/settings/appearance")
async def settings_appearance(request: Request):
    u = require(request, "settings"); con = C(request)
    f = await form(request)
    theme = f.get("theme","system")
    if theme not in ("light","dark","system"): theme = "system"
    db.set_setting(con, "theme", theme)
    db.set_setting(con, "compact", "1" if f.get("compact") else "0")
    db.log_activity(con, u["username"], "settings.update", "appearance", theme); con.commit()
    return flash_set(RedirectResponse("/settings", 303), "Tampilan disimpan. Menyegarkan…")

@app.post("/theme")
async def theme_switch(request: Request):
    """Quick theme toggle available to all logged-in users (stored per-browser cookie)."""
    f = await form(request)
    mode = f.get("mode","system")
    r = RedirectResponse(request.headers.get("referer","/dashboard"), status_code=303)
    r.set_cookie("spb_theme", mode, path="/", max_age=31536000)
    return r

# ================================================================= LANDING EDITOR + PUBLIC PAGE
DEFAULT_LANDING = {"isp_name":"SambiraNet ISP","headline":"Internet Cepat & Stabil untuk Bandung Selatan",
 "description":"","logo_text":"SN","whatsapp":"6281234567890","phone":"","email":"","address":"",
 "cta_text":"Pasang Sekarang","hero_badge":"","show_packages":"1","footer":""}

LANDING_FIELDS = ["isp_name","headline","description","logo_text","whatsapp","phone","email","address",
                  "cta_text","hero_badge","footer"]

def _landing(con):
    row = db.one(con, "SELECT data FROM landing WHERE id=1")
    d = dict(DEFAULT_LANDING)
    if row:
        try: d.update(json.loads(row["data"]))
        except Exception: pass
    return d

@app.get("/landing-editor", response_class=HTMLResponse)
def landing_editor(request: Request, tab: str = "edit"):
    u = require(request, "landing"); con = C(request)
    data = _landing(con)
    pkgs = db.q(con, "SELECT * FROM packages WHERE status='aktif' ORDER BY price")
    return templates.TemplateResponse(request, "landing_editor.html", ctx(request, u, data=data, pkgs=pkgs,
        tab=tab, active="landing"))

@app.post("/landing-editor/save")
async def landing_save(request: Request):
    u = require(request, "landing"); con = C(request)
    f = await form(request)
    data = _landing(con)
    for k in LANDING_FIELDS:
        if k in f: data[k] = f[k]
    data["show_packages"] = "1" if f.get("show_packages") else "0"
    img = f.get("logo_file")
    if img and hasattr(img, "read"):
        raw = img.file.read()
        if raw and len(raw) < 1_000_000:
            fn = "logo_" + secrets.token_hex(5) + os.path.splitext(img.filename or "")[1].lower()
            if fn.endswith((".png",".jpg",".jpeg",".webp",".svg")):
                with open(os.path.join(UPLOAD_DIR, fn), "wb") as fh: fh.write(raw)
                data["logo_img"] = "/uploads/" + fn
            else:
                return flash_set(RedirectResponse("/landing-editor", 303), "Logo harus png/jpg/webp/svg.", "err")
        elif raw:
            return flash_set(RedirectResponse("/landing-editor", 303), "Logo terlalu besar (maks 1MB).", "err")
    con.execute("INSERT INTO landing(id,data) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (json.dumps(data),))
    db.log_activity(con, u["username"], "landing.save", "Landing page", data["headline"][:60]); con.commit()
    return flash_set(RedirectResponse("/landing-editor?tab=preview", 303), "Landing page disimpan — halaman publik langsung berubah.")

@app.get("/sambutan", response_class=HTMLResponse)
def landing_public(request: Request):
    con = C(request)
    data = _landing(con)
    pkgs = db.q(con, "SELECT * FROM packages WHERE status='aktif' ORDER BY price")
    return templates.TemplateResponse(request, "landing_public.html", {"data": data, "pkgs": pkgs, "rp": fmt_rp})

# ---------------------------------------------------------------- favicon
@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)
