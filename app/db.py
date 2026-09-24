"""SQLite persistence layer for SambiraPandoraBox ISP manager."""
import sqlite3, os, hashlib, secrets, datetime

DB_PATH = os.environ.get("SPB_DB", os.path.join(os.path.dirname(__file__), "..", "data", "spb.db"))
DB_PATH = os.path.abspath(DB_PATH)

def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, username TEXT UNIQUE NOT NULL, email TEXT DEFAULT '',
  password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'operator',
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, phone TEXT DEFAULT '', email TEXT DEFAULT '',
  address TEXT DEFAULT '', package_id INTEGER REFERENCES packages(id),
  router_id INTEGER REFERENCES routers(id), pppoe_username TEXT DEFAULT '',
  install_date TEXT, billing_day INTEGER DEFAULT 1, status TEXT DEFAULT 'aktif',
  balance INTEGER DEFAULT 0, notes TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS packages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  download_mbps REAL, upload_mbps REAL, price INTEGER, description TEXT DEFAULT '',
  status TEXT DEFAULT 'aktif');
CREATE TABLE IF NOT EXISTS routers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, host TEXT NOT NULL,
  port INTEGER DEFAULT 8728, version TEXT DEFAULT '', location TEXT DEFAULT '',
  identity TEXT DEFAULT '', status TEXT DEFAULT 'unknown', uptime TEXT DEFAULT '',
  cpu REAL DEFAULT 0, mem REAL DEFAULT 0, last_checked TEXT, api_mode TEXT DEFAULT 'demo');
CREATE TABLE IF NOT EXISTS interfaces(
  id INTEGER PRIMARY KEY AUTOINCREMENT, router_id INTEGER REFERENCES routers(id) ON DELETE CASCADE,
  name TEXT, type TEXT, mac TEXT DEFAULT '', rx_mbps REAL DEFAULT 0, tx_mbps REAL DEFAULT 0,
  status TEXT DEFAULT 'up', comment TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS pppoe_accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
  customer_id INTEGER REFERENCES customers(id), profile TEXT DEFAULT '',
  router_id INTEGER REFERENCES routers(id), ip_addr TEXT DEFAULT '',
  status TEXT DEFAULT 'aktif', online INTEGER DEFAULT 0, session_uptime TEXT DEFAULT '-',
  bytes_rx INTEGER DEFAULT 0, bytes_tx INTEGER DEFAULT 0, last_seen TEXT, service TEXT DEFAULT 'PPPoE');
CREATE TABLE IF NOT EXISTS hotspot_users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
  profile TEXT DEFAULT 'default', valid_until TEXT, status TEXT DEFAULT 'aktif',
  used INTEGER DEFAULT 0, price INTEGER DEFAULT 0, comment TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS vouchers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, username TEXT, password TEXT,
  profile TEXT, validity_days INTEGER, price INTEGER, printed INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS invoices(
  id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE NOT NULL,
  customer_id INTEGER REFERENCES customers(id), period TEXT, issue_date TEXT, due_date TEXT,
  amount INTEGER NOT NULL DEFAULT 0, paid_amount INTEGER DEFAULT 0,
  status TEXT DEFAULT 'belum_bayar', notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ref TEXT UNIQUE NOT NULL, invoice_id INTEGER REFERENCES invoices(id),
  customer_id INTEGER REFERENCES customers(id), amount INTEGER NOT NULL, method TEXT DEFAULT 'Tunai',
  date TEXT, reference TEXT DEFAULT '', notes TEXT DEFAULT '', user_id INTEGER, confirmed TEXT DEFAULT 'manual');
CREATE TABLE IF NOT EXISTS expenses(
  id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, description TEXT, amount INTEGER,
  date TEXT, notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS backups(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT, scope TEXT DEFAULT '',
  size INTEGER DEFAULT 0, mode TEXT DEFAULT 'DEMO', status TEXT DEFAULT 'OK',
  path TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT DEFAULT 'telegram', to_addr TEXT DEFAULT '',
  subject TEXT DEFAULT '', body TEXT, status TEXT DEFAULT 'pending', mode TEXT DEFAULT 'DEMO',
  error TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS templates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, name TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, router_id INTEGER, router_name TEXT, time TEXT,
  type TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS activity_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, user TEXT, action TEXT, obj TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS landing(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
CREATE TABLE IF NOT EXISTS sessions_tbl(sid TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS resets(id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, token TEXT, created_at TEXT);
"""

def hash_pw(pw):
    salt = secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), (salt+pw).encode(), 50_000).hex()
    return f"pbkdf2${salt}${h}"

def check_pw(pw, stored):
    try:
        _, salt, h = stored.split("$")
        return hashlib.pbkdf2_hmac("sha256", pw.encode(), (salt+pw).encode(), 50_000).hex() == h
    except Exception:
        return False

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log_activity(con, user, action, obj, detail=""):
    con.execute("INSERT INTO activity_log(ts,user,action,obj,detail) VALUES(?,?,?,?,?)",
                (now(), user, action, obj, detail))

def get_setting(con, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default

def set_setting(con, key, value):
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))

def q(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]

def one(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None
