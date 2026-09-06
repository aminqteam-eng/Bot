# -*- coding: utf-8 -*-
"""
💎 ربات قیمت‌گیر ارز دیجیتال — نسخه Neon Royal (تک‌فایل)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
قابلیت‌ها:
- قیمت لحظه‌ای +۶۵۰ ارز از بیت‌پین (تومان/ریال/دلار با نرخ تتر)
- کارت تصویری «Neon Royal»: گرادینت رنگی، گلوی نئون، لوگوی واقعی هر ارز،
  نمودار شیشه‌ای ۲۴ ساعته با افکت درخشش
- مقایسهٔ تصویری هم‌زمان تا ۱۰ ارز در یک عکس رتبه‌بندی‌شده + کپشن کامل
  («تون بیت کوین اتریوم» یا «تون، بیت کوین، اتریوم» یا دستور /compare)
- پاسخگویی خودکار در گروه (بدون دستور)
- مبلغ‌دار: "1000 گرام" | تبدیل: "1000 گرام بیت کوین" | خرید: "1000000 تومان داگز"
- فوتر @AminQTeam روی همه پیام‌ها و عکس‌ها

اجرا:  pip install -r requirements.txt  &&  python bot.py
"""

import os, re, io, json, time, html, random, logging, asyncio, requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ═════════════════════════ تنظیمات ═════════════════════════
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = "@AminQTeam"
API_URL    = "https://api.bitpin.ir/v1/mkt/markets/"
CACHE_TTL  = 20
TOP_COUNT  = 10
MAX_COMPARE = 10  # حداکثر تعداد ارز در یک عکس مقایسه

# آیدی عددی ادمین‌ها، جدا شده با کاما — مثلا: ADMIN_IDS="111111111,222222222"
# آیدی عددی خودت رو با @userinfobot توی تلگرام می‌تونی بگیری.
ADMIN_IDS = {int(p) for p in os.environ.get("ADMIN_IDS", "").split(",") if p.strip().isdigit()}
USERS_FILE = os.environ.get("USERS_FILE", "users.json")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger("bitpin-bot")

_pool    = ThreadPoolExecutor(max_workers=4)   # اجرای توابع سنگین (ساخت عکس) خارج از event loop
_io_pool = ThreadPoolExecutor(max_workers=8)   # فچ موازی لوگو/چارت هر ارز در حالت مقایسه

# ═════════════════════════ کاربران + پنل ادمین ═════════════════════════
def _load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_users = _load_users()          # {"user_id": {"username","first_name","first_seen","last_seen"}}
_users_dirty_count = 0

def _save_users():
    try:
        tmp = USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_users, f, ensure_ascii=False)
        os.replace(tmp, USERS_FILE)
    except Exception as e:
        log.warning("users save error: %s", e)

def record_user(tg_user):
    """هر کاربری که با ربات تعامل داشته (پیام یا دکمه) رو ثبت می‌کنه، برای آمار و پیام همگانی."""
    global _users_dirty_count
    if not tg_user or tg_user.is_bot:
        return
    uid = str(tg_user.id)
    now = time.time()
    is_new = uid not in _users
    entry = _users.setdefault(uid, {})
    entry["username"] = tg_user.username or ""
    entry["first_name"] = tg_user.first_name or ""
    entry["last_seen"] = now
    if is_new:
        entry["first_seen"] = now
    _users_dirty_count += 1
    if is_new or _users_dirty_count >= 20:
        _users_dirty_count = 0
        _save_users()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ═════════════════════════ کش بازار بیت‌پین ═════════════════════════
_cache = {"ts": 0.0, "markets": [], "by_code": {}, "usdt": 0.0}

def fetch_markets(force=False):
    if not force and time.time() - _cache["ts"] < CACHE_TTL and _cache["markets"]:
        return True
    try:
        r = requests.get(API_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        markets, by_code = [], {}
        for m in r.json().get("results", []):
            if not m.get("code", "").endswith("_IRT"):
                continue
            price = float(m.get("price") or 0)
            if price <= 0:
                continue
            c1, pi = m["currency1"], (m.get("price_info") or {})
            item = {
                "code":    c1["code"],
                "name_en": c1["title"],
                "name_fa": c1.get("title_fa") or c1["title"],
                "toman":   price,
                "change":  float(pi.get("change") or 0),
                "low":     float(pi.get("min") or price),
                "high":    float(pi.get("max") or price),
                "volume":  float(m.get("volume_24h") or 0),
            }
            markets.append(item)
            by_code[item["code"]] = item
        if not markets:
            return False
        if "USDT" in by_code:
            _cache["usdt"] = by_code["USDT"]["toman"]
        _cache.update(markets=markets, by_code=by_code, ts=time.time())
        return True
    except Exception as e:
        log.error("fetch error: %s", e)
        return bool(_cache["markets"])

# ═════════════════════════ ابزار فرمت ═════════════════════════
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def fa(s): return str(s).translate(FA)

def fmt(x, dec=0):
    return f"{x:,.{dec}f}" if dec else f"{int(round(x)):,.0f}"

def smart_toman(t):
    if t >= 10_000: return fmt(t)
    if t >= 100:    return fmt(t, 1)
    if t >= 1:      return fmt(t, 2)
    return fmt(t, 4)

def fmt_usd(u):
    if u >= 1000: return fmt(u, 2)
    if u >= 10:   return fmt(u, 2)
    if u >= 1:    return fmt(u, 4)
    return fmt(u, 6)

def trend(c):
    return "🟢" if c > 0.005 else ("🔴" if c < -0.005 else "⚪️")

def pct(c):
    return (f"+{c:.2f}٪" if c > 0 else f"{c:.2f}٪")

def smart_amount(a):
    if a == int(a): return fmt(a)
    if a >= 1: return fmt(a, 6).rstrip('0').rstrip('.')
    return fmt(a, 8).rstrip('0').rstrip('.')

# ═════════════════════════ تاریخ شمسی ═════════════════════════
def to_jalali(gy, gm, gd):
    gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365*gy + (gy2+3)//4 - (gy2+99)//100 + (gy2+399)//400 + gd + gdm[gm-1]
    jy = -1595 + 33 * (days // 12053); days %= 12053
    jy += 4 * (days // 1461);        days %= 1461
    if days > 365:
        jy += (days-1) // 365; days = (days-1) % 365
    if days < 186:
        jm = 1 + days // 31; jd = 1 + days % 31
    else:
        jm = 7 + (days-186) // 30; jd = 1 + (days-186) % 30
    return jy, jm, jd

def now_fa():
    lt = time.localtime()
    jy, jm, jd = to_jalali(lt.tm_year, lt.tm_mon, lt.tm_mday)
    return fa(f"{jy}/{jm:02d}/{jd:02d} | {lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}")

def now_en():
    """نسخه لاتین برای رندر روی عکس (فونت‌های داخلی از ارقام فارسی پشتیبانی نمی‌کنند)"""
    lt = time.localtime()
    jy, jm, jd = to_jalali(lt.tm_year, lt.tm_mon, lt.tm_mday)
    return f"{jy}/{jm:02d}/{jd:02d}  ·  {lt.tm_hour:02d}:{lt.tm_min:02d}"

# ═════════════════════════ آیکون و نام نمایشی ═════════════════════════
ICONS = {
    "BTC":"₿","ETH":"Ξ","USDT":"💵","GRAM":"💎","TON":"💎","SOL":"◎","XRP":"✕",
    "DOGE":"🐶","BNB":"🟡","TRX":"🔺","ADA":"🔵","SHIB":"🐕","LTC":"Ł",
    "LINK":"🔗","DOT":"⚫️","AVAX":"🗻","XLM":"⭐️","ATOM":"⚛️","NOT":"🖤",
}
def icon(code): return ICONS.get(code, "🪙")

ALIASES = {
    "ton": "GRAM", "toncoin": "GRAM", "تون": "GRAM", "تون کوین": "GRAM", "تونکوین": "GRAM",
    "گرام": "GRAM", "gram": "GRAM",
    "بیت": "BTC", "بیتکوین": "BTC", "بیت کوین": "BTC",
    "اتریوم": "ETH", "اتر": "ETH",
    "دوج": "DOGE", "دوج کوین": "DOGE",
    "شیبا": "SHIB", "شیبا اینو": "SHIB",
    "ترون": "TRX",
    "سولانا": "SOL", "سول": "SOL",
    "ریپل": "XRP",
    "کاردانو": "ADA",
    "لایت کوین": "LTC", "لایتکوین": "LTC",
    "نات": "NOT", "نات کوین": "NOT",
    "همستر": "HMSTR", "همستر کامبت": "HMSTR",
    "داگز": "DOGS", "داگز کوین": "DOGS",
    "کتسی": "CATI", "کتیزن": "CATI",
    "تتر": "USDT",
    "دلار": "USDT", "دلار آمریکا": "USDT",
    "بایننس": "BNB", "بایننس کوین": "BNB",
    "لینک": "LINK", "چین لینک": "LINK",
    "پولکادات": "DOT",
    "استلار": "XLM",
    "کازماس": "ATOM",
}
DISPLAY = {
    "GRAM": ("TON", "تون کوین (Gram)"),
}
def disp(m):
    d = DISPLAY.get(m["code"])
    return (d[0], d[1]) if d else (m["code"], m["name_fa"])

# ═════════════════════════ جستجو ═════════════════════════
def _norm(s): return (s or "").strip().lower().replace("‌", " ").replace("ي", "ی")

def find_coin(q):
    """جستجوی یک ارز. اگر مطمئن (بدون ابهام) پیدا شود sugg خالی برمی‌گردد."""
    q = _norm(q)
    if not q: return None, []
    if q in ALIASES:
        m = _cache["by_code"].get(ALIASES[q])
        if m: return m, []
    for code, m in _cache["by_code"].items():
        if code.lower() == q: return m, []
    for m in _cache["markets"]:
        if _norm(m["name_fa"]) == q or _norm(m["name_en"]) == q: return m, []
    starts = [m for m in _cache["markets"]
              if _norm(m["name_fa"]).startswith(q) or _norm(m["name_en"]).startswith(q)
              or m["code"].lower().startswith(q)]
    if starts: return starts[0], starts[1:6]
    cont = [m for m in _cache["markets"] if q in _norm(m["name_fa"]) or q in _norm(m["name_en"])]
    return None, cont[:6]

# ═════════════════════════ پارسر متن هوشمند ═════════════════════════
def parse_amount(q):
    q = q.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    m = re.match(r'^([\d,.]+)\s*(.*)$', q)
    if m:
        return float(m.group(1).replace(',', '')), m.group(2).strip()
    return None, q

def parse_query(text):
    text = _norm(text)
    amount, rest = parse_amount(text)
    if amount is None:
        amount, rest = 1, text

    toman_mode = False
    words = rest.split()
    if words and words[0] in ('تومان', 'تومن'):
        toman_mode = True
        rest = ' '.join(words[1:]).strip()
    elif words and words[0] == 'ریال':
        toman_mode = True
        amount = amount / 10
        rest = ' '.join(words[1:]).strip()

    if not rest:
        return amount, None, None

    coin, sugg = find_coin(rest)
    if coin and not sugg:
        return amount, coin, ('IRT' if toman_mode else None)

    words = rest.split()
    for i in range(1, len(words)):
        c1, s1 = find_coin(' '.join(words[:i]))
        c2, s2 = find_coin(' '.join(words[i:]))
        if c1 and not s1 and c2 and not s2:
            return amount, c1, c2

    return amount, coin, ('IRT' if toman_mode and coin else None)

# ═════════════════════════ پارسر «مقایسه چند ارز» ═════════════════════════
MAX_PHRASE_WORDS = 3  # طولانی‌ترین نام ارز حداکثر ۳ کلمه‌ست (مثلا «دلار آمریکا»)

def segment_coins(words):
    """کلمات ورودی را به‌صورت حریصانه به دنباله‌ای از ارزهای شناخته‌شده (مطمئن، بدون ابهام) می‌شکند.
    فقط تطبیق‌های دقیق (alias/کد/نام کامل) پذیرفته می‌شود، نه تطبیق حدسی."""
    i, n = 0, len(words)
    coins = []
    leftovers = []
    while i < n:
        matched, matched_len = None, 0
        for L in range(min(MAX_PHRASE_WORDS, n - i), 0, -1):
            phrase = ' '.join(words[i:i + L])
            m, sugg = find_coin(phrase)
            if m and not sugg:
                matched, matched_len = m, L
                break
        if matched:
            coins.append(matched)
            i += matched_len
        else:
            leftovers.append(words[i])
            i += 1
    return coins, leftovers

_SEP_RE = re.compile(r'[,\uFF0C\u060C|/\n]+')          # , ، | / خط‌جدید
_AND_RE = re.compile(r'(?<!\S)و(?!\S)')                 # کلمهٔ مستقل «و»

def try_parse_compare(raw_text):
    """اگر پیام حاوی ۲ تا ۱۰ ارز باشد، لیست ارزها (و کلمات ناشناخته) را برمی‌گرداند، وگرنه None."""
    text = _norm(raw_text)
    if not text:
        return None
    latin = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    if latin[:1].isdigit():
        return None  # پیام‌های مبلغ‌دار برای تبدیل/خرید هستند، نه مقایسه

    had_delim = bool(_SEP_RE.search(text)) or bool(_AND_RE.search(text))
    cleaned = _SEP_RE.sub(' ', text)
    cleaned = _AND_RE.sub(' ', cleaned)
    words = cleaned.split()
    if not words:
        return None

    coins, leftovers = segment_coins(words)
    uniq, seen = [], set()
    for m in coins:
        if m["code"] not in seen:
            seen.add(m["code"]); uniq.append(m)

    need = 2 if had_delim else 3   # بدون جداکننده، حداقل ۳ ارز برای اجتناب از تداخل با «تبدیل»
    if len(uniq) >= need:
        return uniq[:MAX_COMPARE], leftovers
    return None

# ───────────────────── تشخیص «اسم ارز داخل یک جملهٔ عادی» (برای گروه) ─────────────────────
_PUNCT_RE = re.compile(r'[؟!،,.:;()\[\]{}«»"\'/\\+_=*#@~^]+')

def _tokenize_loose(text):
    t = _norm(text)
    t = _PUNCT_RE.sub(' ', t)
    return t.split()

def extract_mentions(text):
    """داخل یک جملهٔ عادی (نه دستور دقیق)، هر اسم/نماد ارزِ شناخته‌شده رو پیدا می‌کنه؛
    بدون نیاز به اینکه کل پیام فقط اسم ارز باشه. برای پاسخگویی هوشمند در گروه استفاده می‌شه
    تا ربات به هر پیام معمولی «پیدا نشد» نگه — فقط وقتی واقعاً اسم یک ارز توش باشه جواب بده."""
    words = _tokenize_loose(text)
    if not words:
        return []
    coins, _leftovers = segment_coins(words)
    uniq, seen = [], set()
    for m in coins:
        if m["code"] not in seen:
            seen.add(m["code"]); uniq.append(m)
    return uniq[:MAX_COMPARE]

# ═════════════════════════ داده‌های بیرونی (CoinGecko: چارت + لوگو) ═════════════════════════
CG_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "USDT": "tether", "GRAM": "the-open-network",
    "SOL": "solana", "XRP": "ripple", "DOGE": "dogecoin", "BNB": "binancecoin",
    "TRX": "tron", "ADA": "cardano", "SHIB": "shiba-inu", "LTC": "litecoin",
    "LINK": "chainlink", "DOT": "polkadot", "AVAX": "avalanche-2", "XLM": "stellar",
    "ATOM": "cosmos", "NOT": "notcoin", "DOGS": "dogs-2", "HMSTR": "hamster-kombat",
    "USDC": "usd-coin", "BCH": "bitcoin-cash", "XMR": "monero", "ZEC": "zcash",
    "SUI": "sui", "HYPE": "hyperliquid", "ARB": "arbitrum", "SEI": "sei-network",
    "NEAR": "near", "APT": "aptos", "FIL": "filecoin", "AAVE": "aave",
    "UNI": "uniswap", "PEPE": "pepe", "WIF": "dogwifcoin", "FET": "fetch-ai",
    "RENDER": "render-token", "INJ": "injective-protocol", "OP": "optimism",
    "TON": "the-open-network", "MATIC": "matic-network", "CATI": "catizen",
}
_cg_series = {"ts": {}, "data": {}}      # {cg_id: (times, values)}  — چارت ۲۴ساعته
_cg_meta   = {"ts": {}, "url": {}}       # {cg_id: image_url}        — بلک/بولک از coins/markets
_logo_img  = {}                          # {cg_id: (ts, PIL.Image)}  — تصویر واقعی لوگو، کش‌شده

def _fetch_prices(cg_id):
    if cg_id in _cg_series["data"] and time.time() - _cg_series["ts"].get(cg_id, 0) < 300:
        return _cg_series["data"][cg_id]
    try:
        r = requests.get(f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart",
                         params={"vs_currency": "usd", "days": "1"},
                         timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if len(prices) < 10:
            return None
        step = max(1, len(prices) // 120)
        pts = prices[::step]
        times  = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in pts]
        values = [p[1] for p in pts]
        _cg_series["data"][cg_id] = (times, values)
        _cg_series["ts"][cg_id] = time.time()
        return times, values
    except Exception as e:
        log.warning("chart data error %s: %s", cg_id, e)
        return None

def _fetch_logo_urls(cg_ids):
    """یک درخواست بولک برای گرفتن URL لوگوی چند ارز هم‌زمان (کاهش تعداد کال به CoinGecko)."""
    need = [c for c in cg_ids if time.time() - _cg_meta["ts"].get(c, 0) > 3600]
    if not need:
        return
    try:
        r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                         params={"vs_currency": "usd", "ids": ",".join(need)},
                         timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        for row in r.json():
            cid = row.get("id")
            if cid and row.get("image"):
                _cg_meta["url"][cid] = row["image"]
                _cg_meta["ts"][cid] = time.time()
    except Exception as e:
        log.warning("logo url fetch error: %s", e)

def get_logo(cg_id):
    """تصویر واقعی لوگوی ارز را برمی‌گرداند (PIL.Image, RGBA) یا None اگر در دسترس نبود."""
    if not cg_id:
        return None
    cached = _logo_img.get(cg_id)
    if cached and time.time() - cached[0] < 6 * 3600:
        return cached[1]
    url = _cg_meta["url"].get(cg_id)
    if not url:
        _fetch_logo_urls([cg_id])
        url = _cg_meta["url"].get(cg_id)
    if not url:
        return None
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        _logo_img[cg_id] = (time.time(), img)
        return img
    except Exception as e:
        log.warning("logo download error %s: %s", cg_id, e)
        return None

# ═════════════════════════ موتور تصویرسازی «Neon Royal» ═════════════════════════
_FONT_DIR = matplotlib.get_data_path() + "/fonts/ttf/"
_FONT_CACHE = {}

def _font(size, weight="bold"):
    key = (size, weight)
    if key not in _FONT_CACHE:
        name = {"bold": "DejaVuSans-Bold.ttf", "regular": "DejaVuSans.ttf"}[weight]
        _FONT_CACHE[key] = ImageFont.truetype(_FONT_DIR + name, size)
    return _FONT_CACHE[key]

BG_TOP, BG_MID, BG_BOTTOM = (14, 8, 36), (30, 12, 58), (8, 10, 30)
NEON_GREEN, NEON_RED = (44, 240, 150), (255, 70, 110)
GOLD, WHITE, GRAY = (255, 205, 90), (245, 246, 250), (150, 155, 175)

def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def _vgrad(w, h, stops):
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]; p1, c1 = stops[i + 1]
            if p0 <= t <= p1:
                col.putpixel((0, y), _lerp(c0, c1, (t - p0) / max(1e-6, p1 - p0)))
                break
        else:
            col.putpixel((0, y), stops[-1][1])
    return col.resize((w, h))

def _glow_blob(canvas, center, radius, color, alpha=70, blur=120):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = center
    d.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(*color, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))

def _glass(canvas, box, radius=28, fill=(255, 255, 255, 16), outline=None, outline_w=2):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=outline_w)
    canvas.alpha_composite(layer)

def _text(canvas, pos, txt, f, fill, glow=None, glow_alpha=140, blur=6, anchor="la"):
    if glow:
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(pos, txt, font=f, fill=(*glow, glow_alpha), anchor=anchor)
        canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))
    ImageDraw.Draw(canvas).text(pos, txt, font=f, fill=fill, anchor=anchor)

def _circular(im, size, ring=None, ring_w=4):
    im = im.convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    if ring:
        pad = ring_w * 2
        cv = Image.new("RGBA", (size + pad, size + pad), (0, 0, 0, 0))
        ImageDraw.Draw(cv).ellipse([0, 0, size + pad, size + pad], outline=(*ring, 255), width=ring_w)
        cv.paste(out, (pad // 2, pad // 2), out)
        return cv
    return out

def _placeholder_logo(symbol, color, size=96):
    """اگر دانلود لوگوی واقعی ممکن نبود، یک لوگوی بج‌مانند ساده می‌سازد."""
    im = Image.new("RGBA", (size, size), (*color, 255))
    d = ImageDraw.Draw(im)
    d.text((size / 2, size / 2), (symbol or "?")[0].upper(), font=_font(int(size * 0.46)),
           fill=(255, 255, 255, 255), anchor="mm")
    return im

def _neon_sparkline(values, w, h, color):
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor("none"); ax.axis("off")
    xs = list(range(len(values)))
    c = tuple(v / 255 for v in color)
    for lw, a in [(9, 0.05), (6, 0.10), (3.2, 0.22)]:
        ax.plot(xs, values, color=c, linewidth=lw, alpha=a, solid_capstyle="round")
    ax.plot(xs, values, color=c, linewidth=2.4, solid_capstyle="round")
    vmin, vmax = min(values), max(values)
    pad = (vmax - vmin) * 0.25 or (abs(vmin) * 0.02 + 1)
    ax.set_ylim(vmin - pad, vmax + pad)
    ax.fill_between(xs, values, vmin - pad, color=c, alpha=0.10)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGBA")

def _pct_pill(canvas, change, xy=None, right=None, big=False):
    up = change >= 0
    color = NEON_GREEN if up else NEON_RED
    txt = f"{'▲' if up else '▼'} {abs(change):.2f}%"
    f = _font(26 if big else 20)
    d = ImageDraw.Draw(canvas)
    bbox = d.textbbox((0, 0), txt, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padx, pady = 18, 10
    if right is not None:
        rx, y = right; x = rx - (tw + padx * 2)
    else:
        x, y = xy
    box = [x, y, x + tw + padx * 2, y + th + pady * 2]
    _glass(canvas, box, radius=(th + pady * 2) // 2, fill=(*color, 40), outline=(*color, 220), outline_w=2)
    _text(canvas, (x + padx, y + pady - bbox[1]), txt, f, fill=color, anchor="la")
    return box

def make_chart(code, name_en, change24, toman_price):
    """کارت تصویری تک‌ارزی با طراحی Neon Royal (لوگوی واقعی + چارت شیشه‌ای درخشان)."""
    cg_id = CG_IDS.get(code) or CG_IDS.get(code.upper())
    if not cg_id:
        return None
    data = _fetch_prices(cg_id)
    if not data:
        return None
    times, values = data
    up = change24 > 0
    accent = NEON_GREEN if up else (NEON_RED if change24 < 0 else GRAY)

    W, H = 1200, 1500
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    canvas.paste(_vgrad(W, H, [(0, BG_TOP), (0.5, BG_MID), (1.0, BG_BOTTOM)]), (0, 0))
    _glow_blob(canvas, (W * 0.85, H * 0.08), 260, accent, alpha=70, blur=120)
    _glow_blob(canvas, (W * 0.1, H * 0.95), 300, GOLD, alpha=30, blur=140)

    pad = 60
    sym = "TON" if code == "GRAM" else code
    logo_src = get_logo(cg_id) or _placeholder_logo(sym, (90, 90, 110))
    logo = _circular(logo_src, 108, ring=accent, ring_w=5)
    canvas.paste(logo, (pad, pad), logo)
    tx = pad + logo.width + 26
    _text(canvas, (tx, pad + 8), sym, _font(56), fill=WHITE, glow=accent, blur=10)
    _text(canvas, (tx, pad + 78), f"{name_en}  ·  24H", _font(24, "regular"), fill=GRAY)

    _text(canvas, (W - pad, pad + 10), "AminQTeam", _font(26), fill=GOLD, anchor="ra")
    _text(canvas, (W - pad, pad + 46), f"👑 {CHANNEL_ID}", _font(18, "regular"), fill=GRAY, anchor="ra")

    py = pad + 190
    _text(canvas, (pad, py), f"${_fp(values[-1])}", _font(96), fill=WHITE, glow=accent, blur=14)
    _text(canvas, (pad, py + 110), f"{smart_toman(toman_price)}  Toman", _font(34), fill=GOLD)

    pill_y = py + 175
    box = _pct_pill(canvas, change24, xy=(pad, pill_y), big=True)
    hx = box[2] + 20
    for label, val, col in [("H", _fp(max(values)), NEON_GREEN), ("L", _fp(min(values)), NEON_RED)]:
        txt = f"{label}  {val}"; f = _font(20)
        bb = ImageDraw.Draw(canvas).textbbox((0, 0), txt, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        b = [hx, pill_y, hx + tw + 30, pill_y + th + 20]
        _glass(canvas, b, radius=16, fill=(255, 255, 255, 14), outline=(*col, 160), outline_w=2)
        _text(canvas, (hx + 15, pill_y + 10 - bb[1]), txt, f, fill=col)
        hx = b[2] + 16

    chart_top = pill_y + 90
    chart_box = [pad, chart_top, W - pad, H - 160]
    _glass(canvas, chart_box, radius=36, fill=(255, 255, 255, 10), outline=(255, 255, 255, 30), outline_w=1)
    spark = _neon_sparkline(values, chart_box[2] - chart_box[0] - 60, chart_box[3] - chart_box[1] - 60, accent)
    canvas.alpha_composite(spark, (chart_box[0] + 30, chart_box[1] + 30))

    _text(canvas, (pad, H - 110), "Bitpin Live Price", _font(20, "regular"), fill=GRAY)
    _text(canvas, (W - pad, H - 110), now_en(), _font(20, "regular"), fill=GRAY, anchor="ra")

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()

def _fp(v):
    if v >= 1000: return f"{v:,.0f}"
    if v >= 10:   return f"{v:,.2f}"
    if v >= 1:    return f"{v:,.4f}"
    return f"{v:.6f}"

def make_compare_image(coins):
    """کارت تصویری «Crypto Compare»: رتبه‌بندی تا ۱۰ ارز بر اساس تغییر ۲۴ساعته، با لوگوی واقعی و ریزنمودار."""
    usdt = _cache["usdt"] or 1
    cg_ids = [CG_IDS[m["code"]] for m in coins if m["code"] in CG_IDS]
    _fetch_logo_urls(cg_ids)

    def build_row(m):
        cg_id = CG_IDS.get(m["code"])
        logo_src = (get_logo(cg_id) if cg_id else None)
        series = (_fetch_prices(cg_id) if cg_id else None)
        sym, name_fa = disp(m)
        return {
            "code": m["code"], "symbol": sym, "name_en": m["name_en"], "name_fa": name_fa,
            "change": m["change"], "price_usd": _fp(m["toman"] / usdt),
            "price_toman": smart_toman(m["toman"]),
            "values": (series[1] if series else None),
            "logo": logo_src,
        }

    rows = list(_io_pool.map(build_row, coins))
    rows.sort(key=lambda r: -r["change"])

    W = 1080
    header_h, row_h, footer_h = 230, 168, 90
    H = header_h + row_h * len(rows) + footer_h
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    canvas.paste(_vgrad(W, H, [(0, BG_TOP), (0.45, BG_MID), (1.0, BG_BOTTOM)]), (0, 0))
    _glow_blob(canvas, (W * 0.9, H * 0.03), 260, GOLD, alpha=55, blur=130)
    _glow_blob(canvas, (W * 0.08, H * 0.99), 300, NEON_GREEN, alpha=30, blur=150)

    pad = 44
    _text(canvas, (pad, 46), "CRYPTO COMPARE", _font(52), fill=WHITE, glow=GOLD, blur=12)
    _text(canvas, (pad, 116), f"{len(rows)} Coins  ·  Ranked by 24H performance", _font(22, "regular"), fill=GRAY)
    _text(canvas, (W - pad, 46), "AminQTeam", _font(26), fill=GOLD, anchor="ra")
    _text(canvas, (W - pad, 80), now_en(), _font(18, "regular"), fill=GRAY, anchor="ra")

    rank_colors = {0: (255, 215, 0), 1: (200, 205, 215), 2: (205, 140, 80)}
    y = header_h
    for i, r in enumerate(rows):
        up = r["change"] >= 0
        accent = NEON_GREEN if up else NEON_RED
        row_box = [pad, y + 10, W - pad, y + row_h - 14]
        _glass(canvas, row_box, radius=26, fill=(255, 255, 255, 14), outline=(*accent, 90), outline_w=2)
        cy = y + row_h // 2

        rc = rank_colors.get(i, (120, 126, 148))
        rx = pad + 46
        d = ImageDraw.Draw(canvas)
        d.ellipse([rx - 26, cy - 26, rx + 26, cy + 26], fill=(*rc, 60), outline=(*rc, 255), width=2)
        _text(canvas, (rx, cy), str(i + 1), _font(26), fill=WHITE, anchor="mm")

        lx = rx + 60
        logo_src = r["logo"] or _placeholder_logo(r["symbol"], (90, 90, 110))
        logo = _circular(logo_src, 76, ring=accent, ring_w=3)
        canvas.paste(logo, (lx, cy - logo.height // 2), logo)

        tx = lx + logo.width + 22
        _text(canvas, (tx, cy - 30), r["symbol"], _font(34), fill=WHITE)
        _text(canvas, (tx, cy + 8), r["name_en"], _font(18, "regular"), fill=GRAY)

        sp_w, sp_h = 190, 70
        sp_x = tx + 230
        if r["values"] and len(r["values"]) >= 5:
            spark = _neon_sparkline(r["values"], sp_w, sp_h, accent)
            canvas.alpha_composite(spark, (sp_x, cy - sp_h // 2))

        px = sp_x + sp_w + 30
        _text(canvas, (px, cy - 30), f"${r['price_usd']}", _font(26), fill=WHITE)
        _text(canvas, (px, cy + 6), f"{r['price_toman']} T", _font(18, "regular"), fill=GOLD)

        _pct_pill(canvas, r["change"], right=(W - pad - 24, cy - 23))
        y += row_h

    _text(canvas, (pad, H - 56), f"👑 Bitpin Live  ·  {CHANNEL_ID}", _font(20, "regular"), fill=GRAY)

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), rows

# ═════════════════════════ ساخت پیام‌ها ═════════════════════════
DIV = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def footer():
    return f"👑 {CHANNEL_ID}"

def coin_card(m, amount=1):
    usdt = _cache["usdt"] or 1
    total_toman = m["toman"] * amount
    total_usd = total_toman / usdt
    sym, name_fa = disp(m)
    return (
        f"<blockquote>"
        f"<b>{icon(m['code'])} {smart_amount(amount)} {sym}</b> ⸻ <i>{html.escape(name_fa)}</i>\n"
        f"{DIV}\n"
        f"🇮🇷 <b>Toman</b>      <code>{smart_toman(total_toman)}</code>\n"
        f"💰 <b>Rial</b>        <code>{fmt(total_toman*10)}</code>\n"
        f"💵 <b>USDT</b>       <code>{fmt_usd(total_usd)}</code>\n"
        f"📊 <b>24h</b>        <code>{pct(m['change'])}</code> {trend(m['change'])}\n"
        f"{DIV}\n"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>"
    )

def convert_card(amount, from_m, to_m):
    sym_from, name_from = disp(from_m)
    sym_to, name_to = disp(to_m)
    value_toman = amount * from_m["toman"]
    amount_to = value_toman / to_m["toman"]
    usdt = _cache["usdt"] or 1
    total_usd = value_toman / usdt
    return (
        f"<blockquote>"
        f"<b>🔄 تبدیل ارز</b>\n"
        f"{DIV}\n"
        f"{icon(from_m['code'])} <b>{smart_amount(amount)} {sym_from}</b> ⸻ {html.escape(name_from)}\n"
        f"🔽\n"
        f"{icon(to_m['code'])} <b>{smart_amount(amount_to)} {sym_to}</b> ⸻ {html.escape(name_to)}\n"
        f"{DIV}\n"
        f"💰 <b>ارزش:</b> <code>{smart_toman(value_toman)}</code> تومان\n"
        f"💵 <b>دلاری:</b> <code>{fmt_usd(total_usd)}</code> USDT\n"
        f"{DIV}\n"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>"
    )

def buy_with_toman(toman_amount, coin_m):
    sym, name_fa = disp(coin_m)
    amount = toman_amount / coin_m["toman"]
    usdt = _cache["usdt"] or 1
    usd_value = toman_amount / usdt
    return (
        f"<blockquote>"
        f"<b>💵 خرید با تومان</b>\n"
        f"{DIV}\n"
        f"💰 <b>مبلغ:</b> <code>{fmt(toman_amount)}</code> تومان\n"
        f"🔽\n"
        f"{icon(coin_m['code'])} <b>{smart_amount(amount)} {sym}</b>\n"
        f"<i>{html.escape(name_fa)}</i>\n"
        f"{DIV}\n"
        f"💵 <b>ارزش دلاری:</b> <code>{fmt_usd(usd_value)}</code> USDT\n"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>"
    )

def top_text():
    mkts = sorted(_cache["markets"], key=lambda m: -m["volume"])[:TOP_COUNT]
    lines = ""
    for m in mkts:
        usd = m["toman"] / (_cache["usdt"] or 1)
        sym, _ = disp(m)
        lines += f"{trend(m['change'])} <b>{sym}</b>   <code>${fmt_usd(usd)}</code>   <code>{pct(m['change'])}</code>\n"
    return (
        f"<blockquote>"
        f"<b>🔥 برترین‌های بازار</b>\n"
        f"{DIV}\n"
        f"{lines}"
        f"{DIV}\n"
        f"💵 <b>USDT</b>   <code>{fmt(_cache['usdt'])}</code> تومان\n"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>"
    )

def market_text():
    mkts = _cache["markets"]
    up   = sum(1 for m in mkts if m["change"] > 0)
    down = sum(1 for m in mkts if m["change"] < 0)
    g = sorted(mkts, key=lambda m: -m["change"])[:3]
    l = sorted(mkts, key=lambda m:  m["change"])[:3]
    gs = "\n".join(f"🟢 <b>{disp(m)[0]}</b>   <code>{pct(m['change'])}</code>" for m in g)
    ls = "\n".join(f"🔴 <b>{disp(m)[0]}</b>   <code>{pct(m['change'])}</code>" for m in l)
    return (
        f"<blockquote>"
        f"<b>📊 وضعیت بازار</b>\n"
        f"{DIV}\n"
        f"🟢 صعودی <code>{fa(up)}</code>   🔴 نزولی <code>{fa(down)}</code>\n"
        f"{DIV}\n"
        f"{gs}\n"
        f"{DIV}\n"
        f"{ls}\n"
        f"{DIV}\n"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>"
    )

def compare_caption(rows, leftovers):
    lines = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        rank = medals[i] if i < 3 else f"{i+1}."
        lines += (f"{rank} <b>{r['symbol']}</b> ⸻ {html.escape(r['name_fa'])}\n"
                  f"      💰 <code>{r['price_toman']}</code> تومان   "
                  f"💵 <code>${r['price_usd']}</code>   "
                  f"{trend(r['change'])} <code>{pct(r['change'])}</code>\n")
    warn = ""
    if leftovers:
        warn = f"\n⚠️ شناسایی نشد: {html.escape(' / '.join(leftovers[:6]))}\n"
    return (
        f"<blockquote>"
        f"<b>📊 مقایسه {fa(len(rows))} ارز</b>  <i>(رتبه‌بندی بر اساس ۲۴ساعته)</i>\n"
        f"{DIV}\n"
        f"{lines}"
        f"{DIV}"
        f"{warn}"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>"
    )

# ═════════════════════════ منو ═════════════════════════
def menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 برترین‌ها", callback_data="top"),
         InlineKeyboardButton("💵 تتر",        callback_data="usdt")],
        [InlineKeyboardButton("📊 بازار",      callback_data="market")],
    ])

def coin_kb(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 چارت ۲۴ ساعته", callback_data=f"chart:{code}"),
         InlineKeyboardButton("🔄 بروزرسانی",      callback_data=f"coin:{code}")],
        [InlineKeyboardButton("🔥 برترین‌ها", callback_data="top"),
         InlineKeyboardButton("🏠 منو",       callback_data="menu")],
    ])

_compare_store = {}   # key(str) -> [codes]  — برای دکمهٔ بروزرسانیِ مقایسه (callback_data کوتاه)

def compare_kb(codes):
    key = str(abs(hash(tuple(codes))) % 10**8)
    _compare_store[key] = codes
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی مقایسه", callback_data=f"cmp:{key}")],
        [InlineKeyboardButton("🏠 منو", callback_data="menu")],
    ])

WELCOME = (
    "<blockquote>"
    "<b>💎 Bitpin Price Bot</b>\n"
    f"{DIV}\n"
    "هر چی بنویسی، جواب میدم 👇\n"
    "• <code>BTC</code> یا <code>1000 گرام</code>\n"
    "• <code>1000000 تومان داگز</code>\n"
    "• <code>1000 گرام بیت کوین</code> (تبدیل)\n"
    "• <code>تون، بیت کوین، اتریوم</code> (مقایسهٔ تصویری تا ۱۰ ارز)\n"
    "• یا دستور <code>/compare BTC ETH TON</code>\n"
    f"{DIV}\n"
    f"{footer()}"
    "</blockquote>"
)

# ═════════════════════════ هندلرها ═════════════════════════
async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    record_user(u.effective_user)
    fetch_markets()
    await u.message.reply_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=menu_kb())

async def _send_coin_with_chart(message, m, amount):
    """کارت ارز + تلاش برای چارت (در صورت موجود بودن دیتا)"""
    caption = coin_card(m, amount)
    kb = coin_kb(m["code"])
    png = None
    if amount == 1:  # چارت فقط برای حالت تک‌واحد
        try:
            png = await _run_blocking(make_chart, m["code"], m["name_en"], m["change"], m["toman"])
        except Exception as e:
            log.warning("chart error: %s", e)
    if png:
        await message.reply_photo(photo=io.BytesIO(png), caption=caption,
                                  parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.reply_text(caption, parse_mode=ParseMode.HTML, reply_markup=kb)

async def _run_blocking(fn, *args):
    """اجرای توابع سنگین (شبکه + رندر تصویر) خارج از event loop تا ربات هنگام ساخت عکس بلاک نشود."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool, lambda: fn(*args))

async def _send_compare(message, coins, leftovers):
    status = await message.reply_text("⏳ در حال ساخت تصویر مقایسه...")
    try:
        png, rows = await _run_blocking(make_compare_image, coins)
    except Exception as e:
        log.error("compare image error: %s", e)
        await status.edit_text("⚠️ ساخت تصویر مقایسه با خطا مواجه شد. لطفاً دوباره تلاش کنید.")
        return
    caption = compare_caption(rows, leftovers)
    codes = [r["code"] for r in rows]
    try:
        await status.delete()
    except Exception:
        pass
    await message.reply_photo(photo=io.BytesIO(png), caption=caption,
                              parse_mode=ParseMode.HTML, reply_markup=compare_kb(codes))

async def cmd_compare(u: Update, c: ContextTypes.DEFAULT_TYPE):
    record_user(u.effective_user)
    if not fetch_markets():
        await u.message.reply_text("⚠️ خطا در اتصال. لطفاً چند لحظه بعد تلاش کنید.")
        return
    text = " ".join(c.args) if c.args else ""
    if not text.strip():
        await u.message.reply_text(
            "<blockquote>برای مقایسه، اسم یا نماد ارزها رو بعد از دستور بنویس:\n"
            "<code>/compare BTC ETH TON SOL</code></blockquote>",
            parse_mode=ParseMode.HTML)
        return
    words = _AND_RE.sub(' ', _SEP_RE.sub(' ', _norm(text))).split()
    coins, leftovers = segment_coins(words)
    uniq, seen = [], set()
    for m in coins:
        if m["code"] not in seen:
            seen.add(m["code"]); uniq.append(m)
    if len(uniq) < 2:
        await u.message.reply_text("❌ حداقل ۲ ارز معتبر برای مقایسه لازمه.")
        return
    await _send_compare(u.message, uniq[:MAX_COMPARE], leftovers)

async def on_text(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.message.from_user and u.message.from_user.is_bot:
        return
    text = u.message.text.strip()
    if not text:
        return
    record_user(u.effective_user)

    chat_type = u.effective_chat.type if u.effective_chat else "private"
    is_group = chat_type in ("group", "supergroup")

    if not fetch_markets():
        if not is_group:  # توی گروه، خطای اتصال رو اسپم نکن
            await u.message.reply_text("⚠️ خطا در اتصال. لطفاً چند لحظه بعد تلاش کنید.")
        return

    # ۱) لیست صریح مقایسه («تون، بیت کوین، اتریوم» یا چند ارز پشت‌سرهم)
    compare_result = try_parse_compare(text)
    if compare_result:
        coins, leftovers = compare_result
        await _send_compare(u.message, coins, leftovers)
        return

    # ۲) درخواست دقیق قیمت/تبدیل/خرید («BTC»، «1000 گرام»، «1000 گرام بیت کوین»، «1000000 تومان داگز»)
    amount, coin, target = parse_query(text)
    if coin:
        if target and target != 'IRT':
            await u.message.reply_text(convert_card(amount, coin, target),
                                       parse_mode=ParseMode.HTML,
                                       reply_markup=coin_kb(coin["code"]))
        elif target == 'IRT':
            await u.message.reply_text(buy_with_toman(amount, coin),
                                       parse_mode=ParseMode.HTML,
                                       reply_markup=coin_kb(coin["code"]))
        else:
            await _send_coin_with_chart(u.message, coin, amount)
        return

    # ۳) پیام معمولی که یه اسم ارز جایی توش هست («آقا بیت کوین چند شده؟»)
    #    توی گروه: فقط وقتی واقعاً اسم ارزی توی پیام باشه جواب بده، وگرنه کاملاً سکوت (بدون اسپم «پیدا نشد»).
    #    توی چت خصوصی: بازم اول این حالت رو امتحان کن، وگرنه راهنمایی بده.
    mentioned = extract_mentions(text)
    if mentioned:
        if len(mentioned) == 1:
            await _send_coin_with_chart(u.message, mentioned[0], 1)
        else:
            await _send_compare(u.message, mentioned, [])
        return

    if is_group:
        return  # سکوت کامل — چت عادی گروه، ربطی به ارز نداشته

    await u.message.reply_text(
        f"<blockquote>❌ «{html.escape(text)}» پیدا نشد\n"
        f"نماد یا نام ارز رو بنویس:\n"
        f"<code>BTC</code> • <code>1000 گرام</code> • <code>1000000 تومان داگز</code>\n"
        f"برای مقایسه: <code>تون، بیت کوین، اتریوم</code></blockquote>",
        parse_mode=ParseMode.HTML)

async def on_button(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    record_user(u.effective_user)
    await q.answer()
    fetch_markets(force=True)
    d = q.data or ""
    try:
        if d == "menu":
            await q.edit_message_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=menu_kb())
        elif d in ("top", "usdt", "market"):
            text = {"top": top_text,
                    "usdt": lambda: coin_card(_cache["by_code"].get("USDT", {})),
                    "market": market_text}[d]()
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 بروزرسانی", callback_data=d),
                                        InlineKeyboardButton("🏠 منو", callback_data="menu")]])
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        elif d.startswith("coin:"):
            code = d.split(":", 1)[1]
            m = _cache["by_code"].get(code)
            if m:
                text = coin_card(m, 1)
                kb = coin_kb(code)
                if q.message.photo:
                    await q.edit_message_caption(caption=text,
                                                 parse_mode=ParseMode.HTML, reply_markup=kb)
                else:
                    await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        elif d.startswith("chart:"):
            code = d.split(":", 1)[1]
            m = _cache["by_code"].get(code)
            if m:
                png = await _run_blocking(make_chart, code, m["name_en"], m["change"], m["toman"])
                if png:
                    await q.message.reply_photo(photo=io.BytesIO(png),
                        caption=coin_card(m, 1), parse_mode=ParseMode.HTML,
                        reply_markup=coin_kb(code))
                else:
                    await q.answer("چارت برای این ارز در دسترس نیست", show_alert=True)
        elif d.startswith("cmp:"):
            key = d.split(":", 1)[1]
            codes = _compare_store.get(key)
            if not codes:
                await q.answer("این مقایسه منقضی شده، دوباره درخواست بده.", show_alert=True)
                return
            coins = [_cache["by_code"][c] for c in codes if c in _cache["by_code"]]
            if len(coins) < 2:
                await q.answer("داده کافی برای بروزرسانی موجود نیست.", show_alert=True)
                return
            png, rows = await _run_blocking(make_compare_image, coins)
            await q.message.reply_photo(photo=io.BytesIO(png),
                caption=compare_caption(rows, []), parse_mode=ParseMode.HTML,
                reply_markup=compare_kb([r["code"] for r in rows]))
    except Exception as e:
        if "Message is not modified" not in str(e):
            log.warning("button error: %s", e)

# ═════════════════════════ پنل ادمین ═════════════════════════
async def cmd_myid(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """برای این‌که خودت آیدی عددیت رو بفهمی و توی ADMIN_IDS بذاری."""
    record_user(u.effective_user)
    await u.message.reply_text(f"🆔 آیدی عددی شما: <code>{u.effective_user.id}</code>",
                               parse_mode=ParseMode.HTML)

async def cmd_stats(u: Update, c: ContextTypes.DEFAULT_TYPE):
    record_user(u.effective_user)
    if not is_admin(u.effective_user.id):
        await u.message.reply_text("⛔️ این دستور فقط برای ادمین‌هاست.")
        return
    now = time.time()
    total = len(_users)
    today = sum(1 for v in _users.values() if now - v.get("last_seen", 0) < 86400)
    week  = sum(1 for v in _users.values() if now - v.get("last_seen", 0) < 7 * 86400)
    await u.message.reply_text(
        f"<blockquote>"
        f"<b>📊 آمار ربات</b>\n"
        f"{DIV}\n"
        f"👥 <b>کل کاربران:</b> <code>{fa(total)}</code>\n"
        f"🟢 <b>فعال ۲۴ساعت اخیر:</b> <code>{fa(today)}</code>\n"
        f"🗓 <b>فعال هفتهٔ اخیر:</b> <code>{fa(week)}</code>\n"
        f"{DIV}\n"
        f"⏰ <code>{now_fa()}</code>\n"
        f"{footer()}"
        f"</blockquote>",
        parse_mode=ParseMode.HTML)

async def cmd_broadcast(u: Update, c: ContextTypes.DEFAULT_TYPE):
    record_user(u.effective_user)
    if not is_admin(u.effective_user.id):
        await u.message.reply_text("⛔️ این دستور فقط برای ادمین‌هاست.")
        return
    reply = u.message.reply_to_message
    text = " ".join(c.args) if c.args else ""
    if not text.strip() and not reply:
        await u.message.reply_text(
            "استفاده:\n"
            "<code>/broadcast متن پیام</code>\n"
            "یا روی یک پیام (متن/عکس/...) ریپلای کن و بنویس <code>/broadcast</code>",
            parse_mode=ParseMode.HTML)
        return

    ids = list(_users.keys())
    status = await u.message.reply_text(f"⏳ در حال ارسال به {fa(len(ids))} کاربر...")
    ok = fail = 0
    for uid in ids:
        try:
            if reply:
                await reply.copy(chat_id=int(uid))
            else:
                await c.bot.send_message(chat_id=int(uid), text=text, parse_mode=ParseMode.HTML)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # رعایت محدودیت نرخ ارسال تلگرام
    await status.edit_text(f"✅ ارسال موفق: {fa(ok)}\n❌ ناموفق (بلاک/غیرفعال): {fa(fail)}")

def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "❌ متغیر محیطی BOT_TOKEN ست نشده.\n"
            "توی Railway: تب Variables -> BOT_TOKEN = توکن ربات از BotFather\n"
            "برای اجرای لوکال: export BOT_TOKEN=\"...\""
        )
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("🤖 Bot started (Neon Royal + Compare + Admin)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
