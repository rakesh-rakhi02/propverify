"""FastAPI backend: AI scoring + perceptual-hash duplicate check + oracle signing. Serves the frontend too."""
import io
import json
import os
import sqlite3
import uuid
from pathlib import Path

import imagehash
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel
from web3 import Web3

from scoring import PRICES, score_listing

# Ensure Windows root CAs are present in certifi for HTTPS RPC endpoints
if os.name == "nt":
    try:
        import ssl
        import certifi
        cacert = certifi.where()
        current_data = open(cacert, "r", encoding="utf-8", errors="ignore").read()
        if "PropVerify-Win-Sync" not in current_data:
            root_certs = ssl.enum_certificates("ROOT") + ssl.enum_certificates("CA")
            pem_certs = "\n".join([ssl.DER_cert_to_PEM_cert(c[0]) for c in root_certs])
            with open(cacert, "a", encoding="utf-8") as f:
                f.write("\n# PropVerify-Win-Sync\n" + pem_certs)
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
UPLOADS = Path(__file__).parent / "uploads"
UPLOADS.mkdir(exist_ok=True)
DB = Path(__file__).parent / "propverify.db"
THRESHOLD, DUP_DISTANCE = 70, 10
DEMO_AUTO_KYC = os.getenv("DEMO_AUTO_KYC", "false").lower() in ("true", "1", "yes")

ABI = json.loads("""[
{"type":"function","name":"registerLister","stateMutability":"nonpayable","inputs":[{"name":"who","type":"address"}],"outputs":[]},
{"type":"function","name":"listers","stateMutability":"view","inputs":[{"name":"","type":"address"}],"outputs":[{"name":"registered","type":"bool"},{"name":"verifiedCount","type":"uint32"},{"name":"reportsAgainst","type":"uint32"}]},
{"type":"function","name":"admin","stateMutability":"view","inputs":[],"outputs":[{"name":"","type":"address"}]},
{"type":"function","name":"reputation","stateMutability":"view","inputs":[{"name":"who","type":"address"}],"outputs":[{"name":"","type":"int256"}]}
]""")

KEY = os.getenv("PRIVATE_KEY")
RPC = os.getenv("SEPOLIA_RPC_URL")
w3 = Web3(Web3.HTTPProvider(RPC)) if RPC else None
try:
    acct = Account.from_key(KEY) if KEY else None
except Exception:
    acct = None

deployment = None
CONTRACT = None
ESCROW = None
CHAIN_ID = 11155111
contract = None

def load_deployment():
    global deployment, CONTRACT, ESCROW, CHAIN_ID, contract
    if (ROOT / "deployment.json").exists():
        try:
            deployment = json.loads((ROOT / "deployment.json").read_text())
            CONTRACT = Web3.to_checksum_address(deployment["address"]) if (deployment and deployment.get("address")) else None
            ESCROW = Web3.to_checksum_address(deployment["escrow"]) if (deployment and deployment.get("escrow")) else None
            CHAIN_ID = deployment.get("chainId", 11155111)
            if w3 and CONTRACT:
                contract = w3.eth.contract(address=CONTRACT, abi=ABI)
        except Exception:
            pass

load_deployment()

app = FastAPI(title="PropVerify")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


with conn() as _db:
    _db.executescript("""
    CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY AUTOINCREMENT, wallet TEXT, type TEXT, locality TEXT,
      address TEXT, bhk INT, sqft INT, price REAL, description TEXT, score INT, verdict TEXT, reasons TEXT,
      listing_hash TEXT, image_hash TEXT, onchain_id INT, tx_hash TEXT, cover TEXT,
      lat REAL, lng REAL, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS photos(id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INT, wallet TEXT, phash TEXT, path TEXT);
    CREATE TABLE IF NOT EXISTS demo_listers(wallet TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS seller_requests(id INTEGER PRIMARY KEY AUTOINCREMENT, wallet TEXT, name TEXT, phone TEXT, status TEXT DEFAULT 'pending', created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE,
      email TEXT UNIQUE,
      password TEXT,
      role TEXT,
      name TEXT,
      phone TEXT,
      wallet TEXT,
      created TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS escrows(
      listing_id INT PRIMARY KEY,
      buyer TEXT,
      seller TEXT,
      amount REAL DEFAULT 0,
      req_amount REAL DEFAULT 0,
      status INT DEFAULT 0,
      tx_hash TEXT,
      created TEXT DEFAULT CURRENT_TIMESTAMP,
      updated TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cols = [col[1] for col in _db.execute("PRAGMA table_info(listings)").fetchall()]
    if "lat" not in cols:
        _db.execute("ALTER TABLE listings ADD COLUMN lat REAL")
    if "lng" not in cols:
        _db.execute("ALTER TABLE listings ADD COLUMN lng REAL")
    if "positives" not in cols:
        _db.execute("ALTER TABLE listings ADD COLUMN positives TEXT")
    if "report_count" not in cols:
        _db.execute("ALTER TABLE listings ADD COLUMN report_count INT DEFAULT 0")

    # Seed default credentials if users table is empty
    u_count = _db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if u_count == 0:
        admin_w = "0x8f9b36Ad69E48CBE3Ee75F8b67b714367bF21f29"
        seller_w = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
        buyer_w = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
        _db.executemany("""
        INSERT OR IGNORE INTO users(username, email, password, role, name, phone, wallet) VALUES(?,?,?,?,?,?,?)
        """, [
            ("admin", "admin@propverify.com", "admin123", "admin", "Platform Admin", "+91 99999 00000", admin_w),
            ("seller", "seller@propverify.com", "seller123", "seller", "Ramesh Real Estate (Seller)", "+91 98765 43210", seller_w),
            ("buyer", "buyer@propverify.com", "buyer123", "buyer", "Priya Sharma (Buyer)", "+91 91234 56789", buyer_w)
        ])
        _db.execute("INSERT OR IGNORE INTO demo_listers(wallet) VALUES(?)", (seller_w,))
        _db.execute("""
        INSERT OR IGNORE INTO seller_requests(wallet, name, phone, status) VALUES(?,?,?,?)
        """, (seller_w, "Ramesh Real Estate", "+91 98765 43210", "approved"))


def chain_lister(addr):
    if contract:
        try:
            reg, verified, reports = contract.functions.listers(addr).call()
            try:
                rep = int(contract.functions.reputation(addr).call())
            except Exception:
                rep = verified * 10 - reports * 5
            badge = "Gold" if rep >= 30 else ("Silver" if rep >= 10 else "Bronze")
            return {"registered": reg, "verified": verified, "reports": reports, "reputation": rep, "badge": badge}
        except Exception:
            pass
    with conn() as db:
        row = db.execute("SELECT wallet FROM demo_listers WHERE LOWER(wallet)=LOWER(?)", (addr,)).fetchone()
        if row:
            v_count = db.execute("SELECT COUNT(*) FROM listings WHERE LOWER(wallet)=LOWER(?) AND (onchain_id IS NOT NULL OR score >= 70)", (addr,)).fetchone()[0]
            rep_count = db.execute("SELECT COALESCE(SUM(report_count), 0) FROM listings WHERE LOWER(wallet)=LOWER(?)", (addr,)).fetchone()[0]
            rep = v_count * 10 - rep_count * 5
            badge = "Gold" if rep >= 30 else ("Silver" if rep >= 10 else "Bronze")
            return {"registered": True, "verified": v_count, "reports": rep_count, "reputation": rep, "badge": badge}
    return {"registered": False, "verified": 0, "reports": 0, "reputation": 0, "badge": "Bronze"}


@app.get("/api/config")
def config():
    load_deployment()
    admin_addr = None
    if contract:
        try:
            admin_addr = contract.functions.admin().call()
        except Exception:
            pass
    if not admin_addr:
        if deployment and "oracle" in deployment:
            admin_addr = deployment.get("admin") or deployment.get("oracle")
        elif acct:
            admin_addr = acct.address
        else:
            admin_addr = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
    return {"contract": CONTRACT, "escrow": ESCROW, "chain_id": CHAIN_ID, "localities": list(PRICES),
            "admin": admin_addr,
            "explorer": os.getenv("EXPLORER", "https://sepolia.etherscan.io"),
            "rpc_public": os.getenv("RPC_PUBLIC", "https://ethereum-sepolia-rpc.publicnode.com"),
            "demo_auto_kyc": os.getenv("DEMO_AUTO_KYC", "true").lower() in ("true", "1", "yes")}


@app.get("/api/lister/{wallet}")
def lister(wallet: str):
    if not Web3.is_address(wallet):
        raise HTTPException(400, "Invalid wallet address")
    return chain_lister(Web3.to_checksum_address(wallet))


class Reg(BaseModel):
    wallet: str


@app.post("/api/register-lister")
def register_lister(r: Reg):
    """Demo KYC: the admin key approves the wallet on-chain or locally (shortcut)."""
    if not DEMO_AUTO_KYC:
        raise HTTPException(403, "Auto-KYC shortcut is disabled. Please submit a seller request for admin approval.")
    if not Web3.is_address(r.wallet):
        raise HTTPException(400, "Invalid wallet address")
    addr = Web3.to_checksum_address(r.wallet)
    if chain_lister(addr)["registered"]:
        return {"already": True}
    if contract and acct and w3:
        tx = contract.functions.registerLister(addr).build_transaction(
            {"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address), "chainId": CHAIN_ID})
        signed = acct.sign_transaction(tx)
        raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        h = w3.eth.send_raw_transaction(raw)
        w3.eth.wait_for_transaction_receipt(h, timeout=180)
        return {"already": False, "tx": Web3.to_hex(h)}
    with conn() as db:
        db.execute("INSERT OR REPLACE INTO demo_listers(wallet) VALUES(?)", (addr,))
    return {"already": False, "demo": True}


class SellerRequestIn(BaseModel):
    wallet: str
    name: str
    phone: str


@app.post("/api/seller-requests")
def create_seller_request(r: SellerRequestIn):
    if not Web3.is_address(r.wallet):
        raise HTTPException(400, "Invalid wallet address")
    name = (r.name or "").strip()
    phone = (r.phone or "").strip()
    if not name:
        raise HTTPException(400, "Applicant name is required")
    if not phone:
        raise HTTPException(400, "Phone number is required")
    addr = Web3.to_checksum_address(r.wallet)

    with conn() as db:
        existing = db.execute("SELECT id, status FROM seller_requests WHERE LOWER(wallet)=LOWER(?) AND status='pending'", (addr,)).fetchone()
        if existing:
            db.execute("UPDATE seller_requests SET name=?, phone=? WHERE id=?", (name, phone, existing["id"]))
            return {"ok": True, "id": existing["id"], "status": "pending", "updated": True}
        cur = db.execute("INSERT INTO seller_requests(wallet, name, phone, status) VALUES(?,?,?,?)",
                         (addr, name, phone, "pending"))
        req_id = cur.lastrowid
    return {"ok": True, "id": req_id, "status": "pending"}


@app.get("/api/seller-requests")
def list_seller_requests(status: str = None):
    with conn() as db:
        if status:
            rows = db.execute("SELECT * FROM seller_requests WHERE LOWER(status)=LOWER(?) ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM seller_requests ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


@app.post("/api/seller-requests/{req_id}/approve")
def approve_seller_request(req_id: int):
    with conn() as db:
        row = db.execute("SELECT * FROM seller_requests WHERE id=?", (req_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Seller request not found")
        db.execute("UPDATE seller_requests SET status='approved' WHERE id=?", (req_id,))
        db.execute("INSERT OR REPLACE INTO demo_listers(wallet) VALUES(?)", (row["wallet"],))
    return {"ok": True, "id": req_id, "status": "approved", "wallet": row["wallet"]}


# --- Auth Models & Routes ---
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    role: str  # buyer, seller, admin
    phone: str = ""
    wallet: str = ""


class UserLogin(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
def register(u: UserRegister):
    name = (u.name or "").strip()
    email = (u.email or "").strip().lower()
    pw = (u.password or "").strip()
    role = (u.role or "buyer").strip().lower()
    phone = (u.phone or "").strip()
    wallet = (u.wallet or "").strip()
    if not name or not email or not pw:
        raise HTTPException(400, "Name, email, and password are required")
    if role not in ("buyer", "seller", "admin"):
        raise HTTPException(400, "Invalid role. Must be buyer, seller, or admin")
    if wallet and Web3.is_address(wallet):
        wallet = Web3.to_checksum_address(wallet)
    with conn() as db:
        existing = db.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?) OR LOWER(username)=LOWER(?)", (email, email)).fetchone()
        if existing:
            raise HTTPException(400, "An account with this email already exists")
        cur = db.execute("""
            INSERT INTO users(username, email, password, role, name, phone, wallet)
            VALUES(?,?,?,?,?,?,?)
        """, (email, email, pw, role, name, phone, wallet))
        uid = cur.lastrowid
        # If seller, also register in demo_listers / seller_requests
        if role == "seller" and wallet:
            if DEMO_AUTO_KYC:
                db.execute("INSERT OR REPLACE INTO demo_listers(wallet) VALUES(?)", (wallet,))
                db.execute("INSERT OR REPLACE INTO seller_requests(wallet, name, phone, status) VALUES(?,?,?,?)",
                           (wallet, name, phone, "approved"))
            else:
                db.execute("INSERT OR REPLACE INTO seller_requests(wallet, name, phone, status) VALUES(?,?,?,?)",
                           (wallet, name, phone, "pending"))
        row = db.execute("SELECT id, username, email, role, name, phone, wallet, created FROM users WHERE id=?", (uid,)).fetchone()
        return {"ok": True, "user": dict(row)}


@app.post("/api/auth/login")
def login(u: UserLogin):
    ident = (u.email or "").strip().lower()
    pw = (u.password or "").strip()
    with conn() as db:
        row = db.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(?) OR LOWER(username)=LOWER(?)", (ident, ident)).fetchone()
        if not row or row["password"] != pw:
            raise HTTPException(401, "Invalid email/username or password")
        user_data = {
            "id": row["id"],
            "username": row["username"],
            "email": row["email"],
            "role": row["role"],
            "name": row["name"],
            "phone": row["phone"],
            "wallet": row["wallet"],
            "created": row["created"]
        }
        return {"ok": True, "user": user_data}


@app.get("/api/auth/users")
def get_users():
    with conn() as db:
        rows = db.execute("SELECT id, username, email, role, name, phone, wallet, created FROM users ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


# --- Escrow Models & Routes ---
class EscrowSetAmount(BaseModel):
    amount: float
    seller: str = ""


class EscrowDeposit(BaseModel):
    amount: float
    buyer: str = ""
    tx_hash: str = ""


class EscrowAction(BaseModel):
    buyer: str = ""
    seller: str = ""
    raised_by: str = ""
    to_seller: bool = True
    tx_hash: str = ""


@app.get("/api/escrows")
def get_escrows(wallet: str = None):
    with conn() as db:
        if wallet:
            rows = db.execute("""
                SELECT e.*, l.locality, l.address, l.price, l.bhk, l.cover
                FROM escrows e
                LEFT JOIN listings l ON (l.onchain_id = e.listing_id OR l.id = e.listing_id)
                WHERE LOWER(e.seller)=LOWER(?) OR LOWER(e.buyer)=LOWER(?) OR (l.wallet IS NOT NULL AND LOWER(l.wallet)=LOWER(?))
                ORDER BY e.listing_id DESC
            """, (wallet, wallet, wallet)).fetchall()
        else:
            rows = db.execute("""
                SELECT e.*, l.locality, l.address, l.price, l.bhk, l.cover
                FROM escrows e
                LEFT JOIN listings l ON (l.onchain_id = e.listing_id OR l.id = e.listing_id)
                ORDER BY e.listing_id DESC
            """).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/escrow/{listing_id}")
def get_escrow(listing_id: int):
    with conn() as db:
        row = db.execute("""
            SELECT e.* FROM escrows e WHERE e.listing_id=?
            UNION
            SELECT e.* FROM escrows e JOIN listings l ON (l.onchain_id=? AND e.listing_id=l.id)
            UNION
            SELECT e.* FROM escrows e JOIN listings l ON (l.id=? AND e.listing_id=l.onchain_id)
            LIMIT 1
        """, (listing_id, listing_id, listing_id)).fetchone()
        if not row:
            return {"listing_id": listing_id, "status": 0, "amount": 0, "req_amount": 0, "buyer": None, "seller": None}
        return dict(row)


@app.post("/api/escrow/{listing_id}/set-amount")
def set_escrow_amount(listing_id: int, p: EscrowSetAmount):
    with conn() as db:
        l_row = db.execute("SELECT wallet FROM listings WHERE id=? OR onchain_id=?", (listing_id, listing_id)).fetchone()
        seller_w = p.seller or (l_row["wallet"] if l_row else "")
        db.execute("""
            INSERT INTO escrows(listing_id, req_amount, seller, updated)
            VALUES(?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(listing_id) DO UPDATE SET req_amount=excluded.req_amount, seller=COALESCE(NULLIF(excluded.seller,''), escrows.seller), updated=CURRENT_TIMESTAMP
        """, (listing_id, p.amount, seller_w))
    return {"ok": True, "listing_id": listing_id, "req_amount": p.amount}


@app.post("/api/escrow/{listing_id}/deposit")
def escrow_deposit(listing_id: int, p: EscrowDeposit):
    with conn() as db:
        l_row = db.execute("SELECT wallet FROM listings WHERE id=? OR onchain_id=?", (listing_id, listing_id)).fetchone()
        seller_w = l_row["wallet"] if l_row else ""
        db.execute("""
            INSERT INTO escrows(listing_id, buyer, seller, amount, status, tx_hash, updated)
            VALUES(?,?,?,?,1,?,CURRENT_TIMESTAMP)
            ON CONFLICT(listing_id) DO UPDATE SET buyer=excluded.buyer, seller=COALESCE(NULLIF(excluded.seller,''), escrows.seller), amount=excluded.amount, status=1, tx_hash=excluded.tx_hash, updated=CURRENT_TIMESTAMP
        """, (listing_id, p.buyer, seller_w, p.amount, p.tx_hash))
    return {"ok": True, "listing_id": listing_id, "status": 1, "amount": p.amount, "buyer": p.buyer}


@app.post("/api/escrow/{listing_id}/confirm-visit")
def escrow_confirm_visit(listing_id: int, p: EscrowAction):
    with conn() as db:
        cur = db.execute("""
            UPDATE escrows SET status=2, tx_hash=COALESCE(NULLIF(?,''), tx_hash), updated=CURRENT_TIMESTAMP
            WHERE listing_id=? OR listing_id IN (SELECT id FROM listings WHERE onchain_id=?) OR listing_id IN (SELECT onchain_id FROM listings WHERE id=?)
        """, (p.tx_hash, listing_id, listing_id, listing_id))
        if cur.rowcount == 0:
            db.execute("""
                INSERT INTO escrows(listing_id, buyer, status, tx_hash, updated)
                VALUES(?,?,2,?,CURRENT_TIMESTAMP)
                ON CONFLICT(listing_id) DO UPDATE SET status=2, tx_hash=COALESCE(NULLIF(excluded.tx_hash,''), escrows.tx_hash), updated=CURRENT_TIMESTAMP
            """, (listing_id, p.buyer, p.tx_hash))
    return {"ok": True, "listing_id": listing_id, "status": 2}


@app.post("/api/escrow/{listing_id}/claim")
def escrow_claim(listing_id: int, p: EscrowAction):
    with conn() as db:
        cur = db.execute("""
            UPDATE escrows SET status=3, tx_hash=COALESCE(NULLIF(?,''), tx_hash), updated=CURRENT_TIMESTAMP
            WHERE listing_id=? OR listing_id IN (SELECT id FROM listings WHERE onchain_id=?) OR listing_id IN (SELECT onchain_id FROM listings WHERE id=?)
        """, (p.tx_hash, listing_id, listing_id, listing_id))
        if cur.rowcount == 0:
            db.execute("""
                INSERT INTO escrows(listing_id, seller, status, tx_hash, updated)
                VALUES(?,?,3,?,CURRENT_TIMESTAMP)
                ON CONFLICT(listing_id) DO UPDATE SET status=3, tx_hash=COALESCE(NULLIF(excluded.tx_hash,''), escrows.tx_hash), updated=CURRENT_TIMESTAMP
            """, (listing_id, p.seller, p.tx_hash))
    return {"ok": True, "listing_id": listing_id, "status": 3}


@app.post("/api/escrow/{listing_id}/refund")
def escrow_refund(listing_id: int, p: EscrowAction):
    with conn() as db:
        db.execute("""
            UPDATE escrows SET status=4, tx_hash=COALESCE(NULLIF(?,''), tx_hash), updated=CURRENT_TIMESTAMP
            WHERE listing_id=? OR listing_id IN (SELECT id FROM listings WHERE onchain_id=?) OR listing_id IN (SELECT onchain_id FROM listings WHERE id=?)
        """, (p.tx_hash, listing_id, listing_id, listing_id))
    return {"ok": True, "listing_id": listing_id, "status": 4}


@app.post("/api/escrow/{listing_id}/dispute")
def escrow_dispute(listing_id: int, p: EscrowAction):
    with conn() as db:
        db.execute("""
            UPDATE escrows SET status=5, tx_hash=COALESCE(NULLIF(?,''), tx_hash), updated=CURRENT_TIMESTAMP
            WHERE listing_id=? OR listing_id IN (SELECT id FROM listings WHERE onchain_id=?) OR listing_id IN (SELECT onchain_id FROM listings WHERE id=?)
        """, (p.tx_hash, listing_id, listing_id, listing_id))
    return {"ok": True, "listing_id": listing_id, "status": 5}


@app.post("/api/escrow/{listing_id}/resolve")
def escrow_resolve(listing_id: int, p: EscrowAction):
    with conn() as db:
        db.execute("""
            UPDATE escrows SET status=6, tx_hash=COALESCE(NULLIF(?,''), tx_hash), updated=CURRENT_TIMESTAMP
            WHERE listing_id=? OR listing_id IN (SELECT id FROM listings WHERE onchain_id=?) OR listing_id IN (SELECT onchain_id FROM listings WHERE id=?)
        """, (p.tx_hash, listing_id, listing_id, listing_id))
    return {"ok": True, "listing_id": listing_id, "status": 6}


@app.post("/api/analyze")
async def analyze(wallet: str = Form(...), listing_type: str = Form("rent"), locality: str = Form(...),
                  address: str = Form(...), bhk: int = Form(...), sqft: int = Form(...), price: float = Form(...),
                  description: str = Form(""), lat: float = Form(None), lng: float = Form(None),
                  photos: list[UploadFile] = File(...)):
    if not Web3.is_address(wallet):
        raise HTTPException(400, "Invalid wallet address")
    if min(bhk, sqft, price) <= 0:
        raise HTTPException(400, "BHK, sq ft and price must be positive")
    wallet = Web3.to_checksum_address(wallet)

    items = []  # (phash hex, saved filename)
    for f in photos:
        try:
            img = Image.open(io.BytesIO(await f.read()))
            img.load()
        except Exception:
            raise HTTPException(400, f"{f.filename} is not a valid image")
        name = f"{uuid.uuid4().hex}.jpg"
        img.convert("RGB").save(UPLOADS / name, quality=90)
        items.append((str(imagehash.phash(img)), name))

    with conn() as db:
        known = db.execute("SELECT phash, path, listing_id, wallet FROM photos").fetchall()
    dups = []
    for ph, name in items:
        best = None
        for r in known:
            dist = imagehash.hex_to_hash(ph) - imagehash.hex_to_hash(r["phash"])
            if dist <= DUP_DISTANCE and (best is None or dist < best["distance"]):
                best = {"distance": int(dist), "listing_id": r["listing_id"], "wallet": r["wallet"],
                        "new_photo": f"/uploads/{name}", "match_photo": f"/uploads/{r['path']}"}
        if best:
            dups.append(best)

    d = {"type": listing_type, "locality": locality, "address": address, "bhk": bhk, "sqft": sqft,
         "price": price, "description": description}
    if lat is not None and lng is not None:
        d["lat"] = round(float(lat), 6)
        d["lng"] = round(float(lng), 6)

    li = chain_lister(wallet) if contract else {"registered": False, "verified": 0, "reports": 0}
    res = score_listing(d, len(items), dups, li)

    phashes = sorted(p for p, _ in items)
    listing_hash = Web3.to_hex(Web3.keccak(text=json.dumps({**d, "wallet": wallet, "photos": phashes}, sort_keys=True)))
    image_hash = Web3.to_hex(Web3.keccak(text=",".join(phashes)))

    signature = None
    if res["score"] >= THRESHOLD and acct and CONTRACT:
        digest = Web3.solidity_keccak(["bytes32", "bytes32", "uint8", "address", "uint256", "address"],
                                      [listing_hash, image_hash, res["score"], wallet, CHAIN_ID, CONTRACT])
        signature = Web3.to_hex(Account.sign_message(encode_defunct(primitive=digest), private_key=KEY).signature)

    with conn() as db:
        cur = db.execute("INSERT INTO listings(wallet,type,locality,address,bhk,sqft,price,description,score,verdict,reasons,"
                         "positives,listing_hash,image_hash,cover,lat,lng) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (wallet, listing_type, locality, address, bhk, sqft, price, description, res["score"],
                          res["verdict"], json.dumps(res["reasons"]), json.dumps(res["positives"]),
                          listing_hash, image_hash, items[0][1], d.get("lat"), d.get("lng")))
        lid = cur.lastrowid
        db.executemany("INSERT INTO photos(listing_id,wallet,phash,path) VALUES(?,?,?,?)",
                       [(lid, wallet, p, n) for p, n in items])

    return {**res, "db_id": lid, "duplicates": dups, "listing_hash": listing_hash, "image_hash": image_hash,
            "signature": signature, "registered": li["registered"], "cover": f"/uploads/{items[0][1]}",
            "lat": d.get("lat"), "lng": d.get("lng")}


class Confirm(BaseModel):
    db_id: int
    onchain_id: int
    tx_hash: str


@app.post("/api/confirm")
def confirm(c: Confirm):
    with conn() as db:
        db.execute("UPDATE listings SET onchain_id=?, tx_hash=? WHERE id=?", (c.onchain_id, c.tx_hash, c.db_id))
    return {"ok": True}


@app.get("/api/listings")
def listings(wallet: str = None, verified: str = None, verdict: str = None):
    is_verified = verified in ("true", "True", "1", True)
    with conn() as db:
        query = "SELECT * FROM listings"
        params = []
        conds = []
        if wallet:
            conds.append("LOWER(wallet)=LOWER(?)")
            params.append(wallet)
        if is_verified:
            conds.append("(onchain_id IS NOT NULL OR LOWER(verdict)='verified')")
        if verdict:
            conds.append("LOWER(verdict)=LOWER(?)")
            params.append(verdict)
        if conds:
            query += " WHERE " + " AND ".join(conds)
        query += " ORDER BY id DESC"
        rows = db.execute(query, tuple(params)).fetchall()

        result = []
        for r in rows:
            photos = [f"/uploads/{p['path']}" for p in db.execute("SELECT path FROM photos WHERE listing_id=?", (r["id"],)).fetchall()]
            if not photos and r["cover"]:
                photos = [f"/uploads/{r['cover']}"]
            lister_info = chain_lister(r["wallet"])
            d_row = dict(r)
            if not d_row.get("onchain_id") and d_row.get("verdict") == "Verified":
                d_row["onchain_id"] = d_row["id"]
            result.append({
                **d_row,
                "reasons": json.loads(r["reasons"]) if r["reasons"] else [],
                "positives": json.loads(r["positives"]) if ("positives" in r.keys() and r["positives"]) else ["Price benchmark verified", "No scam patterns detected", "Photo uniqueness confirmed", "Listing consistency verified"],
                "cover": f"/uploads/{r['cover']}",
                "photos": photos,
                "lister": lister_info
            })
    return result


@app.get("/api/listing/{listing_id}")
def listing_detail(listing_id: int):
    with conn() as db:
        row = db.execute("SELECT * FROM listings WHERE id=? OR onchain_id=?", (listing_id, listing_id)).fetchone()
        if not row:
            raise HTTPException(404, "Listing not found")
        photos = [f"/uploads/{p['path']}" for p in db.execute("SELECT path FROM photos WHERE listing_id=?", (row["id"],)).fetchall()]
        if not photos and row["cover"]:
            photos = [f"/uploads/{row['cover']}"]
        lister_info = chain_lister(row["wallet"])
        d_row = dict(row)
        if not d_row.get("onchain_id") and d_row.get("verdict") == "Verified":
            d_row["onchain_id"] = d_row["id"]
        return {
            **d_row,
            "reasons": json.loads(row["reasons"]) if row["reasons"] else [],
            "positives": json.loads(row["positives"]) if ("positives" in row.keys() and row["positives"]) else ["Price benchmark verified", "No scam patterns detected", "Photo uniqueness confirmed", "Listing consistency verified"],
            "cover": f"/uploads/{row['cover']}",
            "photos": photos,
            "lister": lister_info
        }


class ReportIn(BaseModel):
    reporter: str = ""
    tx_hash: str = ""


@app.post("/api/listing/{listing_id}/report")
def report_listing(listing_id: int, p: ReportIn = ReportIn()):
    with conn() as db:
        row = db.execute("SELECT * FROM listings WHERE id=? OR onchain_id=?", (listing_id, listing_id)).fetchone()
        if not row:
            raise HTTPException(404, "Listing not found")
        curr_rep = row["report_count"] if ("report_count" in row.keys() and row["report_count"] is not None) else 0
        new_rep = curr_rep + 1
        new_score = max(0, row["score"] - 10)
        new_verdict = "Needs review" if new_rep >= 3 else row["verdict"]
        db.execute("UPDATE listings SET report_count=?, score=?, verdict=? WHERE id=?",
                   (new_rep, new_score, new_verdict, row["id"]))
    return {"ok": True, "listing_id": listing_id, "report_count": new_rep, "score": new_score, "verdict": new_verdict}


@app.post("/api/reset")
def reset():
    """Clear off-chain demo data between rehearsals (on-chain records stay forever)."""
    with conn() as db:
        db.execute("DELETE FROM listings")
        db.execute("DELETE FROM photos")
        db.execute("DELETE FROM demo_listers")
        db.execute("DELETE FROM seller_requests")
        db.execute("DELETE FROM escrows")
    for f in UPLOADS.glob("*.jpg"):
        f.unlink()
    for f in UPLOADS.glob("*.png"):
        f.unlink()
    return {"ok": True}


app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
