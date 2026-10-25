"""NAVS (National Academic Verification System), an APAAR verification platform PROTOTYPE (v5). Every person, college, ID and certificate here is FICTIONAL.
Run: pip install -r requirements.txt && python app.py  ->  http://127.0.0.1:5000
Sign-in = username + password, then a one-time code (and, for the AICTE console, an authenticator-app code).
Optional MongoDB: set MONGO_URI; otherwise an in-memory store is used (demo data is re-created on every start)."""
import base64, csv, functools, hashlib, hmac, io, ipaddress, json, os, random, re, secrets, struct, threading, time
from difflib import SequenceMatcher
import datetime, ssl, urllib.parse, urllib.request
from urllib.parse import urlparse
from flask import Flask, Response, g, jsonify, request, session, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
SECURE = bool(os.environ.get("APAAR_HTTPS") or os.environ.get("APAAR_PROXY"))
app = Flask(__name__, static_folder=None)
if os.environ.get("APAAR_PROXY"):      # behind Caddy / nginx / Cloudflare that terminates HTTPS
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
def _secret():
    p = os.path.join(BASE, ".secret_key")
    if os.environ.get("SECRET_KEY"): return os.environ["SECRET_KEY"]
    if not os.path.exists(p):
        with open(p, "w") as f: f.write(secrets.token_hex(32))
        try: os.chmod(p, 0o600)
        except OSError: pass
    return open(p).read().strip()
app.secret_key = _secret()
SECRET_B = app.secret_key.encode()
try:
    import certifi; _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception: _SSL_CTX = ssl.create_default_context()
app.config.update(SESSION_COOKIE_NAME="__Host-navs" if SECURE else "navs_s", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                  SESSION_COOKIE_SECURE=SECURE, MAX_CONTENT_LENGTH=1_000_000)

# ------------------------------------------------------------ storage (Mongo or memory)
class Mem:
    kind, persistent = "In-memory (demo)", False
    def __init__(s): s.c = {}
    def add(s, n, d): s.c.setdefault(n, []).append(dict(d))
    def reset(s, n, docs): s.c[n] = [dict(d) for d in docs]
    def find(s, n, q=None): return [dict(d) for d in s.c.get(n, []) if all(d.get(k) == v for k, v in (q or {}).items())]
    def last(s, n): return dict(s.c[n][-1]) if s.c.get(n) else None
    def count(s, n): return len(s.c.get(n, []))
class Mongo:
    persistent = True
    def __init__(s, uri):
        from pymongo import MongoClient
        kw = dict(serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, retryWrites=True)
        try:                                   # Atlas (mongodb+srv) needs an up-to-date CA bundle on some hosts
            import certifi
            if uri.startswith("mongodb+srv") or "mongodb.net" in uri: kw["tlsCAFile"] = certifi.where()
        except ImportError: pass
        s.d = MongoClient(uri, **kw)[os.environ.get("MONGO_DB", "navs")]
        s.d.command("ping"); s.kind = "MongoDB"
    def add(s, n, d): s.d[n].insert_one(dict(d))
    def reset(s, n, docs):
        s.d[n].drop()
        if docs: s.d[n].insert_many([dict(d) for d in docs])
    def find(s, n, q=None): return list(s.d[n].find(q or {}, {"_id": 0}).sort("_id", 1))
    def last(s, n): return next(iter(s.d[n].find({}, {"_id": 0}).sort("_id", -1).limit(1)), None)
    def count(s, n): return s.d[n].count_documents({})
def open_store():
    uri = (os.environ.get("MONGO_URI") or "").strip()
    if uri:
        try: return Mongo(uri)
        except Exception as e: print("MongoDB unavailable, using memory:", type(e).__name__, str(e)[:200].replace(uri, "<MONGO_URI>"))
    return Mem()
DB = open_store()

# ------------------------------------------------------------ fictional seed data (60 colleges, 600 students)
FNM = "Aarav Vivaan Ishaan Rahul Arjun Vikram Rohit Kabir Aditya Karthik Sanjay Dev Nikhil Varun".split()
FNF = "Priya Ananya Sneha Neha Meera Diya Isha Pooja Tara Kavya Riya Anjali Nandini Sana".split()
LN = "Kumar Sharma Nair Verma Mehta Jain Reddy Iyer Singh Das Patel Menon Gupta Rao".split()
PRE = "Northfield Riverbend Kestrel Alder Quill Harbour Zenith Orchid Meridian Cobalt Juniper Saffron Lakeview Pinecrest Sunrise Granite Maple Aster Beacon Cedar".split()
KIND = ["Institute of Technology", "College of Engineering", "School of Management", "Institute of Applied Sciences", "Polytechnic"]
PLACES = [("Pune","Maharashtra"),("Nagpur","Maharashtra"),("Chennai","Tamil Nadu"),("Coimbatore","Tamil Nadu"),("Bengaluru","Karnataka"),("Mysuru","Karnataka"),
 ("Lucknow","Uttar Pradesh"),("Kanpur","Uttar Pradesh"),("Ahmedabad","Gujarat"),("Surat","Gujarat"),("Jaipur","Rajasthan"),("Hyderabad","Telangana"),
 ("Kolkata","West Bengal"),("Kochi","Kerala"),("Bhopal","Madhya Pradesh"),("Indore","Madhya Pradesh"),("Patna","Bihar"),("Bhubaneswar","Odisha"),
 ("Chandigarh","Punjab"),("Dehradun","Uttarakhand"),("Guwahati","Assam"),("Ranchi","Jharkhand"),("Raipur","Chhattisgarh"),("Visakhapatnam","Andhra Pradesh")]
COURSES = [("B.Tech","CSE"),("B.Tech","ECE"),("B.Tech","Mechanical"),("B.Tech","AI&DS")]
def make_insts():
    R, out = random.Random(7), []
    for k in range(60):
        city, state = PLACES[(k * 5) % len(PLACES)]; intake = R.choice([120, 180, 240, 300, 360, 420])
        rep = int(intake * R.uniform(1.18, 1.4)) if k % 9 == 4 else intake - R.randint(0, intake // 20)   # every 9th college reports more than its approved intake
        out.append((f"1-D{k+1:04d}", f"{PRE[k % 20]} {KIND[(k // 20 + k % 2) % 5]}", city, state, intake, rep))
    return out
INSTS = make_insts()
SEED_VERSION = "navs-5"
def seed():
    if DB.persistent and os.environ.get("RESEED") != "1":
        m = DB.find("meta", {"k": "seed"})
        if m and m[0].get("v") == SEED_VERSION and DB.count("students") and DB.count("institutions") and DB.count("users"): return    # already loaded in MongoDB
    R, stu, reg, n = random.Random(26263), [], {}, 0
    for code, nm, city, st, intake, rep in INSTS:
        for _ in range(10):
            n += 1; g = R.choice("MF"); f = R.choice(FNM if g == "M" else FNF); l = R.choice(LN)
            if n == 1: g, f, l = "M", "Rahul", "Kumar"
            c = ("MBA", "Finance") if "Management" in nm else R.choice(COURSES)
            s = dict(apaar=str(900000000000 + n), name=f"{f} {l}", dob=f"{R.randint(1,28):02d}-{R.randint(1,12):02d}-{R.randint(2004,2007)}", gender=g, program=c[0], branch=c[1],
                     year=R.choice([2023, 2024, 2025]), inst=code, roll=f"R{code[-3:]}-{n:04d}", category=R.choice(["General", "OBC", "SC", "ST", "EWS"]), cgpa=round(R.uniform(6.2, 9.4), 2),
                     phone=f"98{n:08d}", email=f"{f.lower()}.{l.lower()}{n}@demo.example", status="ACTIVE", face=(n % 5) + (5 if g == "F" else 0))
            reg[s["apaar"]] = dict(apaar=s["apaar"], name=s["name"].upper(), dob=s["dob"], inst=code); stu.append(s)
    for a in range(15, 300, 37): stu[a + 211]["apaar"] = stu[a]["apaar"]                       # same APAAR ID claimed by two colleges
    for i in range(3, 600, 41): stu[i]["name"] = stu[i]["name"].split()[0] + " X"                # clear name mismatch
    for i in range(23, 600, 61): stu[i]["name"] = stu[i]["name"].replace("a", "aa", 1)           # near-match spelling -> needs review
    for i in range(7, 600, 53): stu[i]["dob"] = "01-01-2005"                                      # DOB mismatch
    for i in range(11, 600, 97): stu[i]["apaar"] = stu[i]["apaar"][:11]                           # invalid format
    for i in range(19, 600, 89): reg.pop(stu[i]["apaar"], None)                                   # missing from registry
    stu[0].update(name="Rahul Kumar", apaar="900000000001")
    for s in stu: s["cert_id"] = "APR-" + hashlib.sha1((s["apaar"] + s["inst"] + s["roll"]).encode()).hexdigest()[:12].upper()
    inst = [dict(code=c, name=nm, city=ci, state=st, intake=i, reported=r) for c, nm, ci, st, i, r in INSTS]
    users = [dict(role="institution", ident=f"admin@{c.lower()}.demo.example", phone=f"97{k:08d}", name=f"Registrar, {nm}", ref=c) for k, (c, nm, *_) in enumerate(INSTS, 1)]
    users += [dict(role="aicte", ident="officer@aicte.demo.example", phone="9600000001", name="AICTE Verification Officer (demo)", ref="AICTE"),
              dict(role="employer", ident="hr@acme.demo.example", phone="9500000001", name="ACME Talent Team (demo)", ref="ACME"),
              dict(role="employer", ident="hr@globex.demo.example", phone="9500000002", name="Globex HR (demo)", ref="GLOBEX")]
    DB.reset("students", stu); DB.reset("registry", list(reg.values())); DB.reset("institutions", inst); DB.reset("users", users)
    DB.reset("meta", [dict(k="seed", v=SEED_VERSION)])
seed()

# ------------------------------------------------------------ simulated national register (summary rows only, no student records)
# The 60 colleges above are "live": they have student records, logins and real mismatch checks. To make the AICTE console look like a national
# register, a further block of SIMULATED institutions is generated (fixed seed, so the numbers never change between restarts or workers).
NAT_TOTAL, NAT_FLAGGED = 2650, 78          # institutions in the national register (live + simulated); simulated ones that carry a flag
PRE2 = "Vindhya Himalaya Sahyadri Kaveri Narmada Godavari Ganga Aravali Nilgiri Konark Deccan Malwa Kalinga Avadh Mithila Coastal Capital Heritage Emerald Crescent Lotus Ashoka Tagore Raman Bose Sarabhai Visvesvaraya Kalam Bhabha".split()
NAT_PREFIXES = PRE + PRE2     # captured now: the name PRE is re-used further down for pending sign-ins
NAT_PLACES = [("Mumbai","Maharashtra",5),("Pune","Maharashtra",6),("Nagpur","Maharashtra",3),("Nashik","Maharashtra",2),("Aurangabad","Maharashtra",2),("Chennai","Tamil Nadu",6),("Coimbatore","Tamil Nadu",4),("Madurai","Tamil Nadu",3),
 ("Tiruchirappalli","Tamil Nadu",3),("Salem","Tamil Nadu",2),("Bengaluru","Karnataka",6),("Mysuru","Karnataka",3),("Mangaluru","Karnataka",2),("Hubballi","Karnataka",2),("Lucknow","Uttar Pradesh",4),("Kanpur","Uttar Pradesh",3),
 ("Noida","Uttar Pradesh",4),("Varanasi","Uttar Pradesh",2),("Agra","Uttar Pradesh",2),("Ghaziabad","Uttar Pradesh",3),("Hyderabad","Telangana",6),("Warangal","Telangana",2),("Visakhapatnam","Andhra Pradesh",4),("Vijayawada","Andhra Pradesh",3),
 ("Guntur","Andhra Pradesh",2),("Tirupati","Andhra Pradesh",2),("Ahmedabad","Gujarat",4),("Surat","Gujarat",3),("Vadodara","Gujarat",3),("Rajkot","Gujarat",2),("Jaipur","Rajasthan",4),("Jodhpur","Rajasthan",2),("Kota","Rajasthan",2),
 ("Udaipur","Rajasthan",1),("Kolkata","West Bengal",4),("Durgapur","West Bengal",2),("Siliguri","West Bengal",1),("Kochi","Kerala",3),("Thiruvananthapuram","Kerala",3),("Kozhikode","Kerala",2),("Bhopal","Madhya Pradesh",3),("Indore","Madhya Pradesh",4),
 ("Gwalior","Madhya Pradesh",2),("Jabalpur","Madhya Pradesh",2),("Patna","Bihar",3),("Gaya","Bihar",1),("Muzaffarpur","Bihar",1),("Bhubaneswar","Odisha",3),("Rourkela","Odisha",1),("Cuttack","Odisha",1),("Chandigarh","Chandigarh",2),
 ("Ludhiana","Punjab",3),("Amritsar","Punjab",2),("Jalandhar","Punjab",2),("Gurugram","Haryana",3),("Faridabad","Haryana",2),("Ambala","Haryana",2),("New Delhi","Delhi",4),("Dwarka","Delhi",2),("Dehradun","Uttarakhand",3),("Haridwar","Uttarakhand",1),
 ("Guwahati","Assam",2),("Ranchi","Jharkhand",2),("Jamshedpur","Jharkhand",2),("Raipur","Chhattisgarh",2),("Bhilai","Chhattisgarh",1),("Shimla","Himachal Pradesh",1),("Solan","Himachal Pradesh",1),("Jammu","Jammu and Kashmir",1),
 ("Srinagar","Jammu and Kashmir",1),("Panaji","Goa",1),("Imphal","Manipur",1),("Shillong","Meghalaya",1),("Puducherry","Puducherry",1)]
def make_national():
    R, seen, out = random.Random(2026), {(i[1], i[2]) for i in INSTS}, []
    pre, cities, wts = NAT_PREFIXES, [(c, st) for c, st, _ in NAT_PLACES], [w for *_, w in NAT_PLACES]
    flagged = set(R.sample(range(NAT_TOTAL - len(INSTS)), NAT_FLAGGED))
    scen = [["OVER_INTAKE"], ["MISMATCHES"], ["MISMATCHES"], ["MISMATCHES"], ["DUPLICATE_APAAR", "MISMATCHES"], ["OVER_INTAKE", "MISMATCHES"], ["OVER_INTAKE", "DUPLICATE_APAAR", "MISMATCHES"]]
    for k in range(NAT_TOTAL - len(INSTS)):
        while True:
            city, state = R.choices(cities, wts)[0]; nm = f"{R.choice(pre)} {R.choice(KIND)}"
            if (nm, city) not in seen: seen.add((nm, city)); break
        intake = R.choice([60, 120, 120, 180, 240, 300, 360, 420, 480, 600]); fl = k in flagged; flags = R.choice(scen) if fl else []
        rep_ = int(intake * R.uniform(1.08, 1.45)) if "OVER_INTAKE" in flags else intake - R.randint(0, intake // 10)
        over, sample = max(rep_ - intake, 0), int(rep_ * R.uniform(.55, .95))
        bad = R.randint(1, 7) if "MISMATCHES" in flags else 0; rev = R.randint(0, 6) if fl else R.randint(0, 3)
        out.append(dict(code=f"1-N{k + 1:05d}", name=nm, city=city, state=state, intake=intake, reported=rep_, over=over, sample=sample, VERIFIED=sample - bad - rev, REVIEW=rev, FLAGGED=bad,
                        flags=flags, risk=min(100, over * 100 // intake * 2 + bad * 12 + rev * 4), dups=R.randint(1, 3) if "DUPLICATE_APAAR" in flags else 0, sim=True))
    return out
NAT = make_national()

# ------------------------------------------------------------ mismatch engine
def sim(a, b):
    t = lambda x: " ".join(sorted(re.sub(r"[^A-Za-z ]", " ", x).upper().split()))
    return SequenceMatcher(None, t(a), t(b)).ratio()
def dupmap(stu):
    m = {}
    for s in stu: m.setdefault(s["apaar"], set()).add(s["inst"])
    return m
def check(s, reg, dm):
    out, a = [], s["apaar"]
    if not re.fullmatch(r"\d{12}", a): return [("high", "INVALID_APAAR", "APAAR ID must be exactly 12 digits")]
    if len(dm.get(a, ())) > 1: out.append(("high", "DUPLICATE_ACROSS_COLLEGES", "Same APAAR ID is claimed by " + ", ".join(sorted(dm[a]))))
    r = reg.get(a)
    if not r: return out + [("high", "NOT_IN_REGISTRY", "APAAR ID not found in the (demo) registry")]
    q = sim(s["name"], r["name"])
    if q < 1: out.append(("medium" if q >= .85 else "high", "NAME_MISMATCH", f"College: {s['name']} | Registry: {r['name'].title()} ({q:.0%})"))
    if r["dob"] != s["dob"]: out.append(("high", "DOB_MISMATCH", f"College: {s['dob']} | Registry: {r['dob']}"))
    if r["inst"] != s["inst"]: out.append(("medium", "REGISTRY_INSTITUTION_DIFFERS", f"Registry shows {r['inst']}"))
    return out
def verdict(iss): return "FLAGGED" if any(i[0] == "high" for i in iss) else "REVIEW" if iss else "VERIFIED"
def mask(a): return "•" * max(len(a) - 4, 0) + a[-4:]
def analyse(stu):
    reg = {r["apaar"]: r for r in DB.find("registry")}; dm = dupmap(DB.find("students")); rows = []
    for s in stu:
        iss = check(s, reg, dm); rows.append({**{k: s[k] for k in ("name", "roll", "program", "branch", "year", "inst", "cert_id", "face")},
            "apaar": mask(s["apaar"]), "status": verdict(iss), "issues": [dict(sev=a, code=b, msg=c) for a, b, c in iss]})
    return rows
def cnt(rows): return {k: sum(r["status"] == k for r in rows) for k in ("VERIFIED", "REVIEW", "FLAGGED")}


# ------------------------------------------------------------ security: accounts, 2-step sign-in, sessions, CSRF, audit
CAPTCHA_ON = os.environ.get("CAPTCHA", "1") == "1"                    # hCaptcha human check on every sign-in and password reset
HCAPTCHA_SITEKEY = os.environ.get("HCAPTCHA_SITEKEY", "9e0af896-09e6-4b0e-b16c-0f8e4c6cd512").strip()   # public: shown to browsers
HCAPTCHA_SECRET = os.environ.get("HCAPTCHA_SECRET", "").strip()        # PRIVATE: set in the environment / Render dashboard, never in code or git
HCAPTCHA_VERIFY_URL = "https://api.hcaptcha.com/siteverify"
HCAPTCHA_HOSTS = {h.strip().lower() for h in os.environ.get("HCAPTCHA_HOSTNAMES", "").split(",") if h.strip()}   # optional: only accept tokens solved on these sites, e.g. navs.onrender.com
CAP_SEEN, CAP_LOCK, CAP_TOKEN_RE = {}, threading.Lock(), re.compile(r"^[A-Za-z0-9._~+/=-]{20,20000}$")
TESTING = os.environ.get("APAAR_TESTING") == "1"                       # test runs only. NEVER set in real use.
DEMO_SHOW_OTP = os.environ.get("DEMO_SHOW_OTP", "1") == "1"        # set DEMO_SHOW_OTP=0 when a real SMS/email gateway is wired in
ROLES = {"student": "Student", "institution": "Institution", "aicte": "AICTE", "employer": "Employer"}
FACTORS = {"student": ["otp"], "employer": ["otp"], "institution": ["otp"], "aicte": ["otp", "totp"]}   # after the password
POLICY = {"student": dict(idle=1800, abs=8 * 3600), "employer": dict(idle=1800, abs=8 * 3600),
          "institution": dict(idle=900, abs=6 * 3600), "aicte": dict(idle=600, abs=4 * 3600)}              # seconds
STEPUP_TTL, STEPUP_METHOD = int(os.environ.get("APAAR_STEPUP_TTL", 600)), {"institution": "otp", "aicte": "totp"}   # seconds a confirmation stays fresh
OTPS, PRE, SES, FAILS, LOCKED, RL, TOTP_LAST, PWH, VERIFIED_LOG = {}, {}, {}, {}, {}, {}, {}, {}, []
AUDIT_LOCK = threading.Lock()
ALLOW = [ipaddress.ip_network(c.strip(), strict=False) for c in os.environ.get("AICTE_ALLOW_IPS", "").split(",") if c.strip()]

def hm(*parts): return hmac.new(SECRET_B, "|".join(parts).encode(), hashlib.sha256).hexdigest()
def ip(): return request.remote_addr or "?"
def ip_tag(): return hm("ip", ip())[:8]
def ua_tag(): return hm("ua", request.headers.get("User-Agent", ""))[:16]
def utag(u): return hm("u", u.lower())[:8]
def limited(key, n, win=600):
    now = time.time(); q = [t for t in RL.get(key, []) if now - t < win]
    hit = len(q) >= n
    if not hit: q.append(now)
    RL[key] = q; return hit
def net_ok(role):
    if role != "aicte" or not ALLOW: return True
    try: a = ipaddress.ip_address(ip())
    except ValueError: return False
    return any(a in n for n in ALLOW)

# ---- hash-chained audit log (keyed with the server secret, so it can't be recomputed without it)
def chain(prev, e):
    body = json.dumps({k: e[k] for k in ("ts", "actor", "role", "ip", "action", "detail")}, sort_keys=True)
    return hmac.new(SECRET_B, (prev + body).encode(), hashlib.sha256).hexdigest()[:16]
def audit(action, detail="", actor=None, role=None):
    ses = getattr(g, "ses", None)
    with AUDIT_LOCK:
        la = DB.last("audit"); prev = la["h"] if la else "0" * 16
        e = dict(ts=time.strftime("%Y-%m-%d %H:%M:%S"), actor=actor or (ses["name"] if ses else "anonymous"), role=role or (ses["role"] if ses else "-"),
                 ip=ip_tag(), action=action, detail=str(detail)[:140], prev=prev)
        e["h"] = chain(prev, e); DB.add("audit", e)
def posture(a):
    c = lambda *k: sum(1 for e in a if e["action"] in k)
    return dict(failed_logins=c("password_failed", "otp_failed", "totp_failed"), lockouts=c("account_locked"), blocked=c("access_denied", "net_blocked", "rate_limited"),
                stepups=c("stepup_ok"), active_sessions=len(SES), allowlist=bool(ALLOW), demo_otp=DEMO_SHOW_OTP, https=SECURE, store=DB.kind, persistent=DB.persistent)

# ---- accounts (demo): username + password. Demo passwords are derived from the server secret and shown only in demo mode.
ACCTS = {}
def build_accounts():
    ACCTS.clear()
    for s in DB.find("students"):
        ACCTS[s["roll"].lower()] = dict(username=s["roll"].lower(), role="student", name=s["name"], ref=s["apaar"], inst=s["inst"], email=s["email"], phone=s["phone"])
    for u in DB.find("users"):
        un = "reg." + u["ref"].split("-")[1].lower() if u["role"] == "institution" else "aicte.officer" if u["role"] == "aicte" else u["ref"].lower() + ".hr"
        ACCTS[un] = dict(username=un, role=u["role"], name=u["name"], ref=u["ref"], inst=u["ref"] if u["role"] == "institution" else None, email=u["ident"], phone=u["phone"])
build_accounts()
def demo_pw(u): return "Demo@" + hm("pw", u)[:8]
def hash_pw(pw):
    try: return generate_password_hash(pw)                                   # scrypt
    except Exception: return generate_password_hash(pw, method="pbkdf2:sha256:600000")
DUMMY_HASH = hash_pw("not-a-real-password")                                 # unknown users cost the same time as known ones
def pw_hash(u):
    ov = DB.find("pwchg", {"username": u})
    if ov: return ov[-1]["h"]
    if u not in PWH: PWH[u] = hash_pw(demo_pw(u))
    return PWH[u]
def pw_check(u, pw): return check_password_hash(pw_hash(u) if u in ACCTS else DUMMY_HASH, pw) and u in ACCTS
COMMON = {"password", "password123", "qwerty123456", "123456789012", "welcome12345", "iloveyou1234", "admin1234567", "letmein123456", "demo@12345678"}
def pw_problem(pw, un):
    if len(pw) < 12: return "Use at least 12 characters."
    if len(pw) > 128: return "Use at most 128 characters."
    if un.lower() in pw.lower() or pw.lower() in COMMON: return "That password is too easy to guess."
    if sum(bool(re.search(p, pw)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")) < 3: return "Mix at least three of: lower case, upper case, digits, symbols."
    return None
def locked(u): return LOCKED.get(u, 0) > time.time()
def register_fail(u, kind):
    now = time.time(); q = [t for t in FAILS.get(u, []) if now - t < 900] + [now]; FAILS[u] = q
    audit(kind + "_failed", "u:" + utag(u), actor="anonymous", role="-")
    if len(q) >= 5: LOCKED[u] = now + 900; FAILS[u] = []; audit("account_locked", "u:" + utag(u) + " 15 min", actor="anonymous", role="-")

# ---- one-time codes (email/SMS) and authenticator-app codes (TOTP, RFC 6238)
def mask_dest(a):
    l, _, d = a["email"].partition("@"); return (l[:1] + "•••@" + d) if d else "•••"
def deliver_otp(a, code):
    to, u, p = os.environ.get("DEMO_OTP_REDIRECT", "").strip(), os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD")
    if not (to and u and p): return                                           # demo addresses can't receive mail; set the 3 variables to test real delivery
    try:
        import smtplib; from email.message import EmailMessage
        m = EmailMessage(); m["Subject"] = "Your NAVS demo sign-in code"; m["From"] = f"NAVS (Demo) <{u}>"; m["To"] = to
        m.set_content(f"Demo project. Not from AICTE, DigiLocker or any government service.\n\nYour 6-digit code is {code}. It is valid for 5 minutes. Do not share it.\n(Test mode: intended for {mask_dest(a)}.)\n")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s: s.login(u, p); s.send_message(m)
    except Exception: pass
def issue_otp(key, a):
    code, salt = f"{secrets.randbelow(10**6):06d}", secrets.token_hex(8)
    OTPS[key] = dict(h=hashlib.sha256((salt + code).encode()).hexdigest(), salt=salt, t=time.time(), tries=0)
    deliver_otp(a, code); return code
def check_otp(key, code, burn=True):
    o = OTPS.get(key)
    if not o or time.time() - o["t"] > 300: return "expired"
    if hmac.compare_digest(o["h"], hashlib.sha256((o["salt"] + re.sub(r"\D", "", str(code))[:6]).encode()).hexdigest()):
        if burn: OTPS.pop(key, None)
        return "ok"
    o["tries"] += 1
    if o["tries"] >= 5: OTPS.pop(key, None); return "locked"
    return "bad"
def totp_secret(u): return base64.b32encode(hmac.new(SECRET_B, b"totp|" + u.encode(), hashlib.sha256).digest()[:20]).decode().rstrip("=")
def totp_at(sec, counter):
    key = base64.b32decode(sec + "=" * ((8 - len(sec) % 8) % 8)); h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest(); o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7fffffff) % 10**6:06d}"
def demo_totp_hint(u):
    """Demo only: the next code that will still be accepted (a code works once, so the one just used is skipped)."""
    now = int(time.time() // 30); c = max(now, TOTP_LAST.get(u, 0) + 1)
    return totp_at(totp_secret(u), c) if c <= now + 1 else None
def match_totp(u, code):
    code, now = re.sub(r"\D", "", str(code))[:6], int(time.time() // 30)
    for c in (now - 1, now, now + 1):                                          # allow 30 s clock drift either way
        if hmac.compare_digest(code, totp_at(totp_secret(u), c)) and c > TOTP_LAST.get(u, 0): return c   # a code works once
    return 0
def check_totp(u, code):
    c = match_totp(u, code)
    if c: TOTP_LAST[u] = c
    return bool(c)

# ---- request guard: CSRF + origin + server-side sessions (revocable, bound to the browser)
@app.before_request
def api_guard():
    g.ses, g.sid, g.expired = None, None, False
    if not request.path.startswith("/api/"): return
    if request.method != "GET":
        if request.headers.get("Sec-Fetch-Site") == "cross-site": return jsonify(error="Blocked cross-site request."), 403
        o = request.headers.get("Origin")
        if o and urlparse(o).netloc != request.host: return jsonify(error="Blocked cross-site request."), 403
        tok = request.headers.get("X-CSRF-Token", "")
        if not session.get("csrf") or not hmac.compare_digest(tok.encode(), session["csrf"].encode()): return jsonify(error="Session check failed. Reload the page."), 403
    sid = session.get("sid")
    if sid:
        r, now = SES.get(sid), time.time()
        if r and now - r["t"] <= POLICY[r["role"]]["idle"] and now - r["t0"] <= POLICY[r["role"]]["abs"] and r["ua"] == ua_tag(): r["t"] = now; g.ses, g.sid = r, sid
        else: SES.pop(sid, None); session.pop("sid", None); g.expired = True
@app.get("/api/csrf")
def csrf(): session.setdefault("csrf", secrets.token_urlsafe(24)); return jsonify(csrf=session["csrf"])
def guard(*roles, fresh=False):
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **k):
            if not g.ses: return jsonify(error="Your session expired. Please sign in again." if g.expired else "Please sign in.", expired=True), 401
            if roles and g.ses["role"] not in roles: audit("access_denied", request.path[:60]); return jsonify(error="Your role can't do this."), 403
            if not net_ok(g.ses["role"]): audit("net_blocked", request.path[:60]); return jsonify(error="This console isn't available from your network."), 403
            if fresh and time.time() - g.ses["mfa"] > STEPUP_TTL: return jsonify(error="Please confirm it's you to continue.", step_up=STEPUP_METHOD.get(g.ses["role"], "otp")), 428
            return fn(*a, **k)
        return w
    return deco


# ---- Human check: hCaptcha. The browser shows the widget and gets a one-time token; we verify that token with hCaptcha here, using the secret (which never leaves the server).
def hcaptcha_verify(token, remoteip=""):
    """True only if hCaptcha confirms the token. Any error (no secret, network down, bad reply) counts as a failure, so a broken check never lets anyone in."""
    if TESTING and token.startswith("test-pass-"): return True      # automated tests only (APAAR_TESTING=1): lets the UI test run without reaching hCaptcha
    if not HCAPTCHA_SECRET: print("hCaptcha: HCAPTCHA_SECRET is not set, so every human check fails."); return False
    data = {"secret": HCAPTCHA_SECRET, "response": token, "sitekey": HCAPTCHA_SITEKEY}
    if remoteip and remoteip != "?": data["remoteip"] = remoteip
    try:
        req = urllib.request.Request(HCAPTCHA_VERIFY_URL, data=urllib.parse.urlencode(data).encode(), headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=6, context=_SSL_CTX) as r: j = json.loads(r.read(65536).decode("utf-8", "replace"))
    except Exception as e: print("hCaptcha: could not reach the verification service:", type(e).__name__); return False
    if not (isinstance(j, dict) and j.get("success") is True): print("hCaptcha: token refused:", j.get("error-codes") if isinstance(j, dict) else "bad reply"); return False
    if HCAPTCHA_HOSTS and str(j.get("hostname", "")).lower() not in HCAPTCHA_HOSTS: print("hCaptcha: token was solved on another site:", str(j.get("hostname"))[:60]); return False
    ts = j.get("challenge_ts")
    if ts is not None:      # a token should be fresh: hCaptcha expires them after 2 minutes, we allow a little slack
        try: age = time.time() - datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except ValueError: print("hCaptcha: unreadable challenge time"); return False
        if age > 180 or age < -60: print("hCaptcha: stale token"); return False
    return True
@app.get("/api/captcha")
def captcha_config():
    """Tells the page which sitekey to show. Only the public sitekey is sent."""
    if not CAPTCHA_ON: return jsonify(enabled=False)
    if not (HCAPTCHA_SITEKEY and HCAPTCHA_SECRET): return jsonify(error="The human check isn't set up on this server yet. Ask the administrator."), 503
    return jsonify(enabled=True, sitekey=HCAPTCHA_SITEKEY)
CAP_FAIL_MAX = 10                                   # failed human checks per IP per 10 minutes, then a pause (also stops us hammering hCaptcha)
def captcha_blocked():
    now = time.time(); q = [t for t in RL.get(("capfail", ip()), []) if now - t < 600]; RL[("capfail", ip())] = q
    return len(q) >= CAP_FAIL_MAX
def _cap_fail(): RL.setdefault(("capfail", ip()), []).append(time.time()); return False
def captcha_ok(b):
    """The page sends the token hCaptcha gave it. A token is used once here (and hCaptcha accepts it once too), has to look right, and has to verify."""
    if not CAPTCHA_ON: return True
    tok = b.get("captcha_token")
    if not isinstance(tok, str) or not CAP_TOKEN_RE.match(tok): return _cap_fail()
    d, now = hashlib.sha256(tok.encode()).hexdigest(), time.time()
    with CAP_LOCK:
        for k in [k for k, t in CAP_SEEN.items() if now - t > 600]: CAP_SEEN.pop(k, None)
        if d in CAP_SEEN or len(CAP_SEEN) > 20000: return _cap_fail()                # replay (or flood): never ask hCaptcha again
        CAP_SEEN[d] = now                                                              # recorded before the check, so two parallel requests can't both use it
    return True if hcaptcha_verify(tok, ip()) else _cap_fail()
CAP_FAIL = ("The human check didn't pass. Please try it again.", 400)

# ---- sign-in: step 1 password, step 2 one-time code, step 3 (AICTE only) authenticator code
def _pre():
    pid = session.get("pre"); p = PRE.get(pid) if pid else None
    if p and time.time() - p["t"] < 600 and p["ua"] == ua_tag(): return pid, p
    PRE.pop(pid, None); session.pop("pre", None); return None, None
def _finish(pid, p):
    a, now = ACCTS[p["user"]], time.time(); sid = secrets.token_urlsafe(32); PRE.pop(pid, None)
    SES[sid] = dict(user=a["username"], role=a["role"], name=a["name"], ref=a["ref"], inst=a["inst"], ua=ua_tag(), ua_raw=request.headers.get("User-Agent", "")[:200], t0=now, t=now, mfa=now)
    session.clear(); session["sid"] = sid; session["csrf"] = secrets.token_urlsafe(24); g.ses = SES[sid]
    audit("login", a["role"] + " u:" + utag(a["username"])); return jsonify(done=True, role=a["role"], name=a["name"], csrf=session["csrf"])
@app.post("/api/auth/password")
def auth_password():
    b = request.get_json(silent=True) or {}; role = str(b.get("role")); un = str(b.get("username", "")).strip().lower()[:60]; pw = str(b.get("password", ""))[:200]
    if role not in ROLES: return jsonify(error="Choose a role."), 400
    if limited(("pw", ip()), 25): audit("rate_limited", "password", actor="anonymous"); return jsonify(error="Too many attempts. Wait a few minutes."), 429
    if not net_ok(role): audit("net_blocked", "login " + role, actor="anonymous", role=role); return jsonify(error="This console isn't available from your network."), 403
    if captcha_blocked(): audit("rate_limited", "captcha login", actor="anonymous"); return jsonify(error="Too many failed human checks. Wait a few minutes.", captcha=True), 429
    if not captcha_ok(b): audit("captcha_failed", "login", actor="anonymous", role=role); return jsonify(error=CAP_FAIL[0], captcha=True), 400
    if locked(un): return jsonify(error="Too many attempts. Try again in 15 minutes."), 429
    ok = pw_check(un, pw); a = ACCTS.get(un)
    if not (ok and a and a["role"] == role): register_fail(un, "password"); return jsonify(error="Incorrect username or password."), 401
    FAILS.pop(un, None); pid = secrets.token_urlsafe(24); PRE[pid] = dict(user=un, role=role, stage="otp", t=time.time(), ua=ua_tag())
    session.pop("sid", None); session["pre"] = pid; code = issue_otp(("login", pid), a)
    audit("password_ok", role + " u:" + utag(un), actor="anonymous", role=role)
    out = dict(stage="otp", masked=mask_dest(a), expires_in=300, factors=FACTORS[role], name=a["name"])
    if DEMO_SHOW_OTP: out["demo_otp"] = code
    return jsonify(out)
@app.post("/api/auth/resend")
def auth_resend():
    pid, p = _pre()
    if not p or p["stage"] != "otp": return jsonify(error="Your sign-in timed out. Start again.", restart=True), 401
    if limited(("resend", pid), 3): return jsonify(error="Too many code requests. Start again in a few minutes."), 429
    code = issue_otp(("login", pid), ACCTS[p["user"]]); out = dict(stage="otp", masked=mask_dest(ACCTS[p["user"]]), expires_in=300)
    if DEMO_SHOW_OTP: out["demo_otp"] = code
    return jsonify(out)
@app.post("/api/auth/otp")
def auth_otp():
    pid, p = _pre()
    if not p or p["stage"] != "otp": return jsonify(error="Your sign-in timed out. Start again.", restart=True), 401
    r = check_otp(("login", pid), (request.get_json(silent=True) or {}).get("code", ""))
    if r == "expired": return jsonify(error="That code has expired. Send a new one."), 400
    if r in ("bad", "locked"):
        register_fail(p["user"], "otp")
        if r == "locked": PRE.pop(pid, None); session.pop("pre", None); return jsonify(error="Too many wrong codes. Start again.", restart=True), 401
        return jsonify(error="Incorrect code."), 400
    if "totp" in FACTORS[p["role"]]:
        p["stage"] = "totp"; out = dict(stage="totp")
        if DEMO_SHOW_OTP: out["demo_totp"] = demo_totp_hint(p["user"])
        return jsonify(out)
    return _finish(pid, p)
@app.post("/api/auth/totp")
def auth_totp():
    pid, p = _pre()
    if not p or p["stage"] != "totp": return jsonify(error="Your sign-in timed out. Start again.", restart=True), 401
    if check_totp(p["user"], (request.get_json(silent=True) or {}).get("code", "")): return _finish(pid, p)
    p["tries"] = p.get("tries", 0) + 1; register_fail(p["user"], "totp")
    if p["tries"] >= 5: PRE.pop(pid, None); session.pop("pre", None); return jsonify(error="Too many wrong codes. Start again.", restart=True), 401
    return jsonify(error="Incorrect or already-used code."), 400

# ---- forgot password: one-time code to the registered contact (AICTE also needs the authenticator code). Same reply whether or not the account exists.
RST = {}
@app.post("/api/auth/forgot")
def auth_forgot():
    b = request.get_json(silent=True) or {}; role = str(b.get("role")); un = str(b.get("username", "")).strip().lower()[:60]
    if role not in ROLES: return jsonify(error="Choose a role."), 400
    if limited(("forgot", ip()), 8): audit("rate_limited", "forgot", actor="anonymous"); return jsonify(error="Too many attempts. Wait a few minutes."), 429
    if captcha_blocked(): audit("rate_limited", "captcha forgot", actor="anonymous"); return jsonify(error="Too many failed human checks. Wait a few minutes.", captcha=True), 429
    if not captcha_ok(b): audit("captcha_failed", "forgot", actor="anonymous", role=role); return jsonify(error=CAP_FAIL[0], captcha=True), 400
    a, totp = ACCTS.get(un), "totp" in FACTORS[role]
    out = dict(ok=True, needs_totp=totp, expires_in=300, message="If that account exists, we've sent a one-time code to its registered contact.")
    rid = secrets.token_urlsafe(24); real = bool(a and a["role"] == role) and not limited(("forgot_u", un), 3, 3600)
    RST[rid] = dict(user=un if real else None, role=role, t=time.time(), ua=ua_tag(), tries=0); session["rst"] = rid
    code = issue_otp(("reset", rid), a) if real else f"{secrets.randbelow(10**6):06d}"
    if real: audit("reset_requested", role + " u:" + utag(un), actor="anonymous", role=role)
    if DEMO_SHOW_OTP:                                                         # demo shows a code even for unknown accounts, so the reply can't be used to find accounts
        out["demo_otp"] = code
        if totp: out["demo_totp"] = (demo_totp_hint(un) if real else f"{secrets.randbelow(10**6):06d}")
    return jsonify(out)
@app.post("/api/auth/reset")
def auth_reset():
    b = request.get_json(silent=True) or {}; rid = session.get("rst"); rec = RST.get(rid) if rid else None
    if not rec or time.time() - rec["t"] > 600 or rec["ua"] != ua_tag(): RST.pop(rid, None); session.pop("rst", None); return jsonify(error="Your reset request timed out. Start again.", restart=True), 401
    new, u = str(b.get("new_password", ""))[:200], rec["user"]
    pr = pw_problem(new, u or "")
    if pr: return jsonify(error=pr), 400                                      # policy problems say nothing about the account, so they don't use up a try
    ok = bool(u) and check_otp(("reset", rid), b.get("code", ""), burn=False) == "ok"
    tc = match_totp(u, b.get("totp", "")) if ok and "totp" in FACTORS[rec["role"]] else 1
    if not (ok and tc):
        rec["tries"] += 1; audit("reset_failed", "u:" + utag(u or "-"), actor="anonymous", role=rec["role"])
        if rec["tries"] >= 5: RST.pop(rid, None); OTPS.pop(("reset", rid), None); session.pop("rst", None); return jsonify(error="Too many wrong codes. Start again.", restart=True), 401
        return jsonify(error="That code isn't valid or has expired."), 400
    OTPS.pop(("reset", rid), None)
    if "totp" in FACTORS[rec["role"]]: TOTP_LAST[u] = tc
    DB.add("pwchg", dict(username=u, h=hash_pw(new), ts=time.strftime("%Y-%m-%d %H:%M:%S")))
    n = 0
    for sid in [k for k, x in SES.items() if x["user"] == u]: SES.pop(sid, None); n += 1
    LOCKED.pop(u, None); FAILS.pop(u, None); RST.pop(rid, None); session.pop("rst", None); audit("password_reset", f"{rec['role']} u:{utag(u)} {n} session(s) ended", actor="anonymous", role=rec["role"])
    return jsonify(ok=True)
@app.post("/api/auth/cancel")
def auth_cancel(): PRE.pop(session.get("pre"), None); session.pop("pre", None); return jsonify(ok=True)
@app.post("/api/logout")
def logout():
    if g.ses: audit("logout")
    SES.pop(session.get("sid"), None); session.pop("sid", None); session.pop("pre", None); return jsonify(ok=True)
@app.get("/api/me")
def me():
    s = g.ses
    if not s: return jsonify(role=None, demo=DEMO_SHOW_OTP, store=DB.kind, captcha=CAPTCHA_ON)
    p, now = POLICY[s["role"]], time.time()
    return jsonify(role=s["role"], name=s["name"], username=s["user"], inst=s["inst"], store=DB.kind, demo=DEMO_SHOW_OTP, csrf=session.get("csrf"), idle=p["idle"],
                   abs_left=int(p["abs"] - (now - s["t0"])), stepup_ttl=STEPUP_TTL, mfa_age=int(now - s["mfa"]), factors=FACTORS[s["role"]])

# ---- step-up: re-confirm before sensitive actions (institution: email/SMS code, AICTE: authenticator code)
@app.post("/api/stepup/send")
@guard("institution", "aicte")
def stepup_send():
    if limited(("su", g.sid), 6): return jsonify(error="Too many code requests. Wait a few minutes."), 429
    if STEPUP_METHOD[g.ses["role"]] == "totp":                       # AICTE: the code comes from the authenticator app, nothing is sent
        h = demo_totp_hint(g.ses["user"]) if DEMO_SHOW_OTP else None
        return jsonify(method="totp", demo_totp=h, demo_wait=bool(DEMO_SHOW_OTP and not h))
    a = ACCTS[g.ses["user"]]; code = issue_otp(("step", g.sid), a); out = dict(method="otp", masked=mask_dest(a))
    if DEMO_SHOW_OTP: out["demo_otp"] = code
    return jsonify(out)
@app.post("/api/stepup/verify")
@guard("institution", "aicte")
def stepup_verify():
    code, u = (request.get_json(silent=True) or {}).get("code", ""), g.ses["user"]
    if STEPUP_METHOD[g.ses["role"]] == "otp": r = check_otp(("step", g.sid), code)
    else: r = "ok" if check_totp(u, code) else "bad"
    if r == "ok": g.ses["mfa"] = time.time(); g.ses["su_fail"] = 0; audit("stepup_ok"); return jsonify(ok=True)
    g.ses["su_fail"] = g.ses.get("su_fail", 0) + 1; audit("stepup_failed", "u:" + utag(u))
    if r == "locked" or g.ses["su_fail"] >= 5: SES.pop(g.sid, None); session.pop("sid", None); audit("session_terminated", "step-up failures", actor=g.ses["name"], role=g.ses["role"]); return jsonify(error="Too many wrong codes. You were signed out.", expired=True), 401
    return jsonify(error="That code was not accepted." if r != "expired" else "That code has expired. Send a new one."), 400

# ---- account security page
def device_name(ua):
    o = "Android" if "Android" in ua else "iPhone" if "iPhone" in ua else "Windows" if "Windows" in ua else "Mac" if "Mac OS" in ua else "Linux" if "Linux" in ua else "Unknown device"
    b = "Edge" if "Edg/" in ua else "Firefox" if "Firefox" in ua else "Chrome" if "Chrome" in ua else "Safari" if "Safari" in ua else "Browser"
    return f"{b} on {o}"
@app.get("/api/account/security")
@guard()
def acct_security():
    s = g.ses; ago = lambda t: int(time.time() - t); r = s["role"]
    mine = [dict(ref=hm("sid", sid)[:8], device=device_name(x["ua_raw"]), started_ago=ago(x["t0"]), active_ago=ago(x["t"]), current=sid == g.sid) for sid, x in SES.items() if x["user"] == s["user"]]
    return jsonify(role=r, username=s["user"], factors=FACTORS[r], idle=POLICY[r]["idle"], abs=POLICY[r]["abs"], stepup=STEPUP_METHOD.get(r), stepup_ttl=STEPUP_TTL, sessions=mine,
                   mfa_qr=DEMO_SHOW_OTP and "totp" in FACTORS[r], allowlist=bool(ALLOW) and r == "aicte", https=SECURE)
@app.post("/api/account/password")
@guard(fresh=True)
def acct_password():
    b = request.get_json(silent=True) or {}; u = g.ses["user"]; cur, new = str(b.get("current", ""))[:200], str(b.get("new", ""))[:200]
    if not pw_check(u, cur): register_fail(u, "password"); return jsonify(error="Your current password is not correct."), 400
    if new == cur: return jsonify(error="Choose a password different from the current one."), 400
    pr = pw_problem(new, u)
    if pr: return jsonify(error=pr), 400
    DB.add("pwchg", dict(username=u, h=hash_pw(new), ts=time.strftime("%Y-%m-%d %H:%M:%S"))); n = 0
    for sid in [k for k, x in SES.items() if x["user"] == u and k != g.sid]: SES.pop(sid, None); n += 1
    audit("password_changed", f"{n} other session(s) ended"); return jsonify(ok=True, ended=n)
@app.post("/api/account/signout-all")
@guard(fresh=True)
def acct_signout_all():
    u = g.ses["user"]; audit("signout_all"); [SES.pop(k, None) for k in [k for k, x in SES.items() if x["user"] == u]]; session.pop("sid", None); return jsonify(ok=True)
@app.get("/api/account/mfa")
@guard("aicte", fresh=True)
def acct_mfa():
    if not DEMO_SHOW_OTP: return jsonify(error="Authenticator enrolment is handled by your administrator."), 404
    import segno; sec = totp_secret(g.ses["user"]); uri = f"otpauth://totp/NAVS%20(demo):{g.ses['user']}?secret={sec}&issuer=NAVS%20demo&digits=6&period=30"
    buf = io.BytesIO(); segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, dark="#0B1B33")
    audit("mfa_enrol_viewed"); return jsonify(qr="data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode(), secret=sec)

# ---- demo helpers (only when DEMO_SHOW_OTP=1) and the public landing-page numbers
def _demo_accounts():
    first_student = next(iter(u for u, a in ACCTS.items() if a["role"] == "student"))
    return {"student": first_student, "institution": "reg.d0001", "aicte": "aicte.officer", "employer": "acme.hr"}
@app.get("/api/demo")
def demo():
    if not DEMO_SHOW_OTP or limited(("demo", ip()), 90): return jsonify({})
    return jsonify(accounts={r: dict(username=u, password=demo_pw(u), name=ACCTS[u]["name"]) for r, u in _demo_accounts().items()})
@app.get("/api/demo/college/<code>")
def demo_college(code):
    u = "reg." + code.split("-")[-1].lower()
    if not DEMO_SHOW_OTP or limited(("demo", ip()), 90) or u not in ACCTS: return jsonify({}), 404
    return jsonify(username=u, password=demo_pw(u), name=ACCTS[u]["name"])
_PUB = dict(t=0, v=None)
@app.get("/api/public/overview")
def public_overview():
    if limited(("po", ip()), 120): return jsonify(error="Too many requests."), 429
    now = time.time()
    if now - _PUB["t"] > 30:
        rows = analyse(DB.find("students")); c = cnt(rows); insts = DB.find("institutions"); states = {}
        for i in insts: states[i["state"]] = states.get(i["state"], 0) + 1
        _PUB.update(t=now, v=dict(institutions=[dict(code=i["code"], name=i["name"], city=i["city"], state=i["state"]) for i in insts], states=states,
                                 totals=dict(institutions=len(insts), students=len(rows), verified=c["VERIFIED"], attention=c["REVIEW"] + c["FLAGGED"])))
    return jsonify(_PUB["v"])

# ------------------------------------------------------------ reviewer workflow
STATE = {"corrected": "Corrected, re-upload pending", "clarify": "Awaiting student", "escalate": "Escalated to AICTE", "dismiss": "Dismissed", "aicte_upheld": "Upheld by AICTE", "aicte_cleared": "Cleared by AICTE"}
def latest_reviews():
    m = {}
    for r in DB.find("reviews"): m[r["cert_id"]] = r
    return m
def annotate(rows):
    rv = latest_reviews()
    for r in rows:
        x = rv.get(r["cert_id"]); r["state"] = STATE.get(x["decision"], "Open") if x else "Open"
        r["review"] = dict(note=x["note"], by=x["by"], ts=x["ts"], decision=x["decision"]) if x else None
    return rows
# ------------------------------------------------------------ certificates
def cert_payload(s, public=False):
    inst = DB.find("institutions", {"code": s["inst"]})[0]; iss = analyse([s])[0]; lr = latest_reviews().get(s["cert_id"]); ok = iss["status"] != "FLAGGED" or bool(lr and lr["decision"] == "aicte_cleared")
    p = dict(cert_id=s["cert_id"], valid=ok, status="VALID" if ok else "UNDER REVIEW", name=s["name"], apaar=mask(s["apaar"]), roll=s["roll"],
                program=f"{s['program']} ({s['branch']})", admitted=s["year"], institution=inst["name"], aicte_id=inst["code"], city=inst["city"],
                cgpa=s["cgpa"], issued="25 Oct 2026", note="Demo certificate. Not issued by AICTE, DigiLocker or any government body.", issues=iss["issues"], face=s["face"])
    if public:
        for k in ("roll", "cgpa", "issues", "face"): p.pop(k)       # public/QR view: identity + validity only
    return p
def by_cert(cid): return next((s for s in DB.find("students") if s["cert_id"] == cid.upper()), None)
@app.get("/api/verify/<cid>")
def verify(cid):
    if limited(("pv", ip()), 40): return jsonify(error="Too many lookups. Try again shortly."), 429
    s = by_cert(cid[:40]); audit("public_verify", "found" if s else "not found")
    return (jsonify(cert_payload(s, True)) if s else (jsonify(error="No certificate with this ID."), 404))
@app.get("/api/qr/<cid>.svg")
def qr_svg(cid):
    import segno
    base = os.environ.get("PUBLIC_URL") or request.host_url.rstrip("/")
    buf = io.BytesIO(); segno.make(f"{base}/?verify={re.sub('[^A-Za-z0-9-]', '', cid)[:40]}", error="m").save(buf, kind="svg", scale=4, border=2, dark="#10243b")
    return app.response_class(buf.getvalue(), mimetype="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})
@app.get("/api/employer/verify/<cid>")
@guard("employer")
def emp_verify(cid):
    if limited(("ev", g.ses["user"]), 40): return jsonify(error="Too many lookups. Try again shortly."), 429
    s = by_cert(cid[:40])
    if not s: audit("employer_verify", "not found"); return jsonify(error="No certificate with this ID."), 404
    p = cert_payload(s, True); audit("employer_verify", p["cert_id"] + " " + p["status"])
    VERIFIED_LOG.insert(0, dict(by=g.ses["name"], cert=p["cert_id"], status=p["status"], at=time.strftime("%d %b %H:%M")))
    return jsonify(**p, log=[l for l in VERIFIED_LOG if l["by"] == g.ses["name"]][:8])

# ------------------------------------------------------------ role dashboards
@app.get("/api/student/profile")
@guard("student")
def sprofile():
    s = next(x for x in DB.find("students") if x["apaar"] == g.ses["ref"] and x["inst"] == g.ses["inst"])
    p = cert_payload(s)
    return jsonify(institution=next(i for i in DB.find("institutions") if i["code"] == s["inst"]), profile=dict(face=s["face"], name=s["name"], apaar=mask(s["apaar"]), roll=s["roll"], dob=s["dob"], category=s["category"], email=s["email"], phone=s["phone"][:2] + "••••" + s["phone"][-3:]),
                   review=(annotate([analyse([s])[0]])[0]["state"] if p["issues"] else None), certs=[dict(p, kind="Enrolment Verification"), dict(p, kind="Academic Standing", note="Demo CGPA shown for illustration only.")], checks=p["issues"])
@app.get("/api/institution/overview")
@guard("institution")
def inst_overview():
    code = g.ses["inst"]; rows = analyse(DB.find("students", {"inst": code})); i = DB.find("institutions", {"code": code})[0]
    return jsonify(institution=i, counts=cnt(rows), students=annotate(rows), over_intake=max(i["reported"] - i["intake"], 0))
@app.post("/api/institution/review")
@guard("institution", fresh=True)
def inst_review():
    b = request.get_json(silent=True) or {}; d = str(b.get("decision")); note = str(b.get("note", "")).strip()[:300]
    if d not in ("corrected", "clarify", "escalate", "dismiss"): return jsonify(error="Choose a decision."), 400
    if len(note) < 8: return jsonify(error="Add a short reason (at least 8 characters)."), 400
    s = by_cert(str(b.get("cert_id", ""))[:40])
    if not s or s["inst"] != g.ses["inst"]: return jsonify(error="Record not found in your institution."), 404
    row = analyse([s])[0]; codes = {i["code"] for i in row["issues"]}
    if row["status"] == "VERIFIED": return jsonify(error="Nothing to review: this record passed every check."), 400
    if d == "dismiss" and (row["status"] == "FLAGGED" or "DUPLICATE_ACROSS_COLLEGES" in codes):
        return jsonify(error="Flagged records can't be dismissed by the college. Escalate to AICTE or ask the student."), 400
    DB.add("reviews", dict(cert_id=s["cert_id"], inst=s["inst"], decision=d, note=note, by=g.ses["name"], ts=time.strftime("%d %b %Y %H:%M")))
    audit("review_" + d, s["cert_id"]); return jsonify(row=annotate([row])[0])
@app.get("/api/aicte/escalations")
@guard("aicte")
def escalations():
    out = []
    for cid, r in latest_reviews().items():
        if r["decision"] in ("escalate", "aicte_upheld", "aicte_cleared"):
            s = by_cert(cid); row = analyse([s])[0]; out.append({**row, "state": STATE[r["decision"]], "review": dict(note=r["note"], by=r["by"], ts=r["ts"], decision=r["decision"]), "open": r["decision"] == "escalate"})
    return jsonify(items=sorted(out, key=lambda x: not x["open"]))
@app.post("/api/aicte/resolve")
@guard("aicte", fresh=True)
def resolve():
    b = request.get_json(silent=True) or {}; o = str(b.get("outcome")); note = str(b.get("note", "")).strip()[:300]
    if o not in ("upheld", "cleared") or len(note) < 8: return jsonify(error="Choose an outcome and add a reason (8+ characters)."), 400
    cid = str(b.get("cert_id", ""))[:40]; r = latest_reviews().get(cid)
    if not r or r["decision"] != "escalate": return jsonify(error="This record is not awaiting an AICTE decision."), 400
    DB.add("reviews", dict(cert_id=cid, inst=r["inst"], decision="aicte_" + o, note=note, by=g.ses["name"], ts=time.strftime("%d %b %Y %H:%M")))
    audit("aicte_" + o, cid); return jsonify(ok=True)
@app.post("/api/institution/upload")
@guard("institution", fresh=True)
def inst_upload():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"): return jsonify(error="Choose a .csv file."), 400
    raw = f.read()
    try: txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError: txt = raw.decode("cp1252", "replace")
    try: rd = list(csv.DictReader(io.StringIO(txt)))
    except Exception: return jsonify(error="Could not read this file as CSV."), 400
    if rd and any("aadhaar" in (k or "").lower() or "aadhar" in (k or "").lower() for k in rd[0]): return jsonify(error="This system does not accept Aadhaar numbers. Remove that column and upload again."), 400
    need = {"apaar_id", "name", "dob", "roll_no"}
    if not rd or not need <= set(rd[0]): return jsonify(error="CSV needs columns: apaar_id, name, dob, roll_no"), 400
    stu = [dict(apaar=r["apaar_id"].strip(), name=r["name"].strip(), dob=r["dob"].strip(), roll=r["roll_no"].strip(), inst=g.ses["inst"], program=r.get("program", "B.Tech"),
                branch=r.get("branch", "-"), year=2025, cert_id="-") for r in rd[:500]]
    allst = [s for s in DB.find("students") if s["inst"] != g.ses["inst"]] + stu; reg = {r["apaar"]: r for r in DB.find("registry")}; dm = dupmap(allst); rows = []
    for s in stu:
        iss = check(s, reg, dm); rows.append(dict(roll=s["roll"], name=s["name"], apaar=mask(s["apaar"]), status=verdict(iss), issues=[dict(sev=a, code=b, msg=c) for a, b, c in iss]))
    audit("batch_checked", f"{len(rows)} rows"); return jsonify(rows=rows, counts=cnt(rows), note="Preview only: nothing is saved.")
def live_inst_rows(rows=None, dm=None):
    insts, stu = DB.find("institutions"), DB.find("students")
    rows = rows if rows is not None else analyse(stu); dm = dm if dm is not None else dupmap(stu); by, out = {}, []
    for x in rows: by.setdefault(x["inst"], []).append(x)
    for i in insts:
        r = by.get(i["code"], []); c = cnt(r); over = i["reported"] - i["intake"]
        flags = (["OVER_INTAKE"] if over > 0 else []) + (["DUPLICATE_APAAR"] if any(x["code"] == "DUPLICATE_ACROSS_COLLEGES" for y in r for x in y["issues"]) else []) + (["MISMATCHES"] if c["FLAGGED"] else [])
        out.append(dict(i, over=max(over, 0), sample=len(r), **c, flags=flags, risk=min(100, max(over, 0) * 100 // i["intake"] * 2 + c["FLAGGED"] * 12 + c["REVIEW"] * 4), sim=False))
    return out
def all_inst_rows(): return live_inst_rows() + NAT
@app.get("/api/aicte/overview")
@guard("aicte")
def aicte():
    stu = DB.find("students"); rows = analyse(stu); dm = dupmap(stu); live = live_inst_rows(rows, dm); allr = live + NAT
    dups = [dict(apaar=mask(a), colleges=sorted(c)) for a, c in dm.items() if len(c) > 1 and re.fullmatch(r"\d{12}", a)]
    states = {}
    for i in allr: states[i["state"]] = states.get(i["state"], 0) + i["reported"]
    tot = lambda k: sum(i[k] for i in allr); top = sorted(allr, key=lambda i: (-i["risk"], i["code"]))[:5]
    fs = {}
    for i in allr:
        if i["flags"]: fs[i["state"]] = fs.get(i["state"], 0) + 1
    ft = {k: sum(1 for i in allr if k in i["flags"]) for k in ("OVER_INTAKE", "DUPLICATE_APAAR", "MISMATCHES")}
    return jsonify(top=top, duplicates=dups, states=states, flag_states=fs, flag_types=ft, flagged=annotate([r for r in rows if r["status"] == "FLAGGED"]),
                   totals=dict(institutions=len(allr), live=len(live), simulated=len(NAT), reported=tot("reported"), intake=tot("intake"), VERIFIED=tot("VERIFIED"), REVIEW=tot("REVIEW"), FLAGGED=tot("FLAGGED"),
                               flagged_institutions=sum(1 for i in allr if i["flags"]), over_institutions=sum(1 for i in allr if i["over"]), dup_total=len(dups) + sum(i["dups"] for i in NAT), live_flagged=cnt(rows)["FLAGGED"]))
@app.get("/api/aicte/institutions")
@guard("aicte")
def aicte_institutions():
    a = request.args; q = a.get("q", "").strip().lower()[:60]; st = a.get("state", "")[:40]; res = a.get("result", "")[:8]; src = a.get("source", "")[:8]
    try: page, per = max(0, int(a.get("page", 0))), min(max(int(a.get("per", 10)), 1), 3000)
    except ValueError: return jsonify(error="Bad paging values."), 400
    allr = sorted(all_inst_rows(), key=lambda i: (-i["risk"], i["code"])); f = [i for i in allr if (not q or q in (i["name"] + " " + i["city"] + " " + i["code"]).lower()) and (not st or i["state"] == st)
         and (not res or (i["flags"] if res == "flag" else i["over"] if res == "over" else not i["flags"])) and (not src or (i["sim"] if src == "sim" else not i["sim"]))]
    pages = max(1, -(-len(f) // per)); page = min(page, pages - 1)
    if per > 100: audit("institutions_export", f"{len(f)} rows")
    return jsonify(rows=f[page * per:(page + 1) * per], total=len(f), all=len(allr), flagged=sum(1 for i in allr if i["flags"]), page=page, pages=pages, states=sorted({i["state"] for i in allr}))
@app.get("/healthz")
def healthz(): return jsonify(ok=True, store=DB.kind)
@app.get("/api/aicte/audit")
@guard("aicte")
def aicte_audit():
    audit("audit_viewed")
    a, ok, prev = DB.find("audit"), True, "0" * 16
    for e in a:
        if e["prev"] != prev or e["h"] != chain(prev, e): ok = False
        prev = e["h"]
    return jsonify(entries=a[::-1][:150], chain_ok=ok, total=len(a), posture=posture(a))

@app.get("/static/<path:p>")
def static_files(p):
    r = send_from_directory(os.path.join(BASE, "static"), p); r.headers["Cache-Control"] = "public, max-age=3600"; return r
@app.get("/")
def home():
    js = os.path.join(BASE, "static", "app.js"); v = str(int(os.path.getmtime(js))) if os.path.exists(js) else "0"
    with open(os.path.join(BASE, "index.html"), encoding="utf-8") as f: html = f.read().replace("__V__", v)
    return Response(html, mimetype="text/html", headers={"Cache-Control": "no-cache"})
@app.after_request
def hdr(r):
    r.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin", "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": "default-src 'self'; script-src 'self' https://hcaptcha.com https://*.hcaptcha.com; style-src 'self' 'unsafe-inline' https://hcaptcha.com https://*.hcaptcha.com; font-src 'self'; img-src 'self' data: blob: https://hcaptcha.com https://*.hcaptcha.com; frame-src https://hcaptcha.com https://*.hcaptcha.com; connect-src 'self' https://hcaptcha.com https://*.hcaptcha.com; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
    if request.path.startswith("/api/"): r.headers["Cache-Control"] = "no-store"
    if request.is_secure: r.headers["Strict-Transport-Security"] = "max-age=31536000"
    return r
if __name__ == "__main__":
    ctx, host = None, os.environ.get("APAAR_HOST", "127.0.0.1")
    if os.environ.get("APAAR_HTTPS"):
        c, k = os.environ.get("APAAR_CERT", os.path.join(BASE, "certs", "cert.pem")), os.environ.get("APAAR_KEY", os.path.join(BASE, "certs", "key.pem"))
        if not (os.path.exists(c) and os.path.exists(k)): raise SystemExit("HTTPS needs a certificate. Run:  sh make_cert.sh   (or set APAAR_CERT and APAAR_KEY)")
        ctx = (c, k)
    if host not in ("127.0.0.1", "localhost") and not (ctx or os.environ.get("APAAR_PROXY")): print("WARNING: listening beyond this device without HTTPS. Passwords and sessions are not encrypted on the network.")
    if TESTING: print("!!! APAAR_TESTING=1: test mode. Use for automated tests only. !!!")
    if not CAPTCHA_ON: print("!!! CAPTCHA=0: the human check is OFF. Do not run like this on the internet. !!!")
    if CAPTCHA_ON and not HCAPTCHA_SECRET: print("!!! HCAPTCHA_SECRET is not set: nobody can sign in until it is. Export it (see .env.example). !!!")
    print(f"NAVS prototype · {DB.kind} · CAPTCHA: {CAPTCHA_ON} · demo codes on screen: {DEMO_SHOW_OTP} · AICTE network allow-list: {'on' if ALLOW else 'off'}")
    app.run(host=host, port=int(os.environ.get("PORT", 5000)), ssl_context=ctx, debug=False)
