import logging
import asyncio
import os
import json
import html
import re
import io
import copy
import hmac
import hashlib
import urllib.parse
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from aiohttp import web
import aiohttp_cors
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo, BotCommand, BotCommandScopeChat, MenuButtonCommands, BufferedInputFile, InputMediaPhoto,
)

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable o'rnatilmagan! Render > Environment bo'limiga qo'shing.")
ADMIN_ID = 8488328091   # ASOSIY admin (zaxira, tiklash va to'liq tozalash faqat unda)

# Qo'shimcha adminlar: ularning Telegram ID raqamini shu yerga vergul bilan yozing, masalan [111111111, 222222222]
# Yoki Render/Netlify Environment variables'da EXTRA_ADMINS="111111111,222222222" deb yozing.
EXTRA_ADMINS = []

ADMIN_IDS = {ADMIN_ID} | {int(x) for x in EXTRA_ADMINS} | {
    int(x) for x in os.environ.get("EXTRA_ADMINS", "").replace(" ", "").split(",") if x.strip().isdigit()
}

def is_admin(uid):
    return uid in ADMIN_IDS
WEBAPP_URL = "https://yaypanmuzqaymoq.netlify.app/"
# Yaypan shahri markazi (mijozlarga xarita sifatida yuboriladi)
YAYPAN_LAT, YAYPAN_LON = 40.37583, 70.81556
# Xaritadan joy tanlash sahifasi: geo.html ni shu netlify saytga (index.html yoniga) yuklang
# Xarita sahifasi botning o'zidan (/geo) beriladi, shuning uchun Netlify'da geo.html bo'lishi shart emas (404 chiqmaydi).
# Botning ochiq manzili (Render). Kerak bo'lsa Render'da BOT_PUBLIC_URL yoki GEO_PICKER_URL o'zgaruvchisini bering.
BOT_PUBLIC_URL = (os.environ.get("BOT_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "https://yaypan-muzqaymoq.onrender.com").rstrip("/")
_geo_base = os.environ.get("GEO_PICKER_URL") or (BOT_PUBLIC_URL + "/geo")
GEO_PICKER_URL = _geo_base + ("&" if "?" in _geo_base else "?") + f"lat={YAYPAN_LAT}&lon={YAYPAN_LON}"
# Agar Render'da Persistent Disk ulasangiz, DATA_DIR=/data qilib qo'ying
DATA_DIR = os.environ.get("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DEBTS_FILE = os.path.join(DATA_DIR, "debts.json")    # База долгов
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")  # База заказов
SUBSCRIBERS_FILE = os.path.join(DATA_DIR, "subscribers.json")  # botga /start bosgan hamma (xabar yuborish uchun)
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.json")  # admin qo'shgan muzqaymoqlar, tugaganlar, "xabar bering" so'rovlari
CHANNEL = "@YAYPAN_muzqaymoq"
CHANNEL_URL = "https://t.me/YAYPAN_muzqaymoq"

logging.basicConfig(level=logging.INFO)
# ================= 💎 PREMIUM EMOJI, RANGLI TUGMALAR VA EFFEKTLAR =================
# Mavjud matnlarga TEGILMAYDI: hamma narsa Telegramga ketayotgan so'rov ustida avtomatik bajariladi.
#  - xabar ichidagi oddiy emoji -> premium (animatsiyali) emoji (agar /emoji orqali o'rgatilgan bo'lsa)
#  - tugmalar rangli bo'ladi (yashil / qizil / ko'k), inline tugmalarning bosh emojisi premium ikonkaga almashadi
#  - muhim xabarlarga animatsiyali effekt (🎉 / ❤️) qo'shiladi
# Xatolik bo'lsa (masalan, egasida Premium yo'q) so'rov eski, oddiy ko'rinishda qayta yuboriladi - bot hech qachon to'xtamaydi.
import time
import aiohttp
from datetime import timedelta, timezone as _tz
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import MessageEntity

PREMIUM_FILE = os.path.join(DATA_DIR, "premium_emoji.json")
premium_emoji = {}   # {oddiy emoji (FE0F siz): custom_emoji_id}

_EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[0-9#*]\uFE0F?\u20E3"
    "|(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\u2190-\u21FF\u2934\u2935"
    "\u3030\u303D\u3297\u3299\u00A9\u00AE\u203C\u2049\u2122\u2139\u24C2\u25AA\u25AB\u25B6\u25C0\u25FB-\u25FE]"
    "[\uFE0F\U0001F3FB-\U0001F3FF]?"
    "(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF\u2640\u2642][\uFE0F\U0001F3FB-\U0001F3FF]?)*))"
)
_LEAD_RE = re.compile(r"^\s*(" + _EMOJI_RE.pattern + r")\s*")

def _enorm(e):
    return (e or "").replace("\uFE0F", "")

def _u16(s):
    return len(s.encode("utf-16-le")) // 2

def _html_emojify(text):
    out, changed = [], False
    for part in re.split(r"(<[^>]*>)", text):
        if part.startswith("<") and part.endswith(">"):
            out.append(part)
            continue
        def rep(m):
            nonlocal changed
            pid = premium_emoji.get(_enorm(m.group(0)))
            if not pid:
                return m.group(0)
            changed = True
            return f'<tg-emoji emoji-id="{pid}">{m.group(0)}</tg-emoji>'
        out.append(_EMOJI_RE.sub(rep, part))
    return "".join(out), changed

def _plain_entities(text):
    ents, pos, off = [], 0, 0
    for m in _EMOJI_RE.finditer(text):
        pid = premium_emoji.get(_enorm(m.group(0)))
        if not pid:
            continue
        off += _u16(text[pos:m.start()])
        ln = _u16(m.group(0))
        ents.append(MessageEntity(type="custom_emoji", offset=off, length=ln, custom_emoji_id=pid))
        off += ln
        pos = m.end()
    return ents

def _auto_style(text, data):
    t, d = (text or "").lower(), (data or "").lower()
    if (d in ("save_no", "bc_cancel", "reset_all_yes") or d.startswith(("remove_", "td_", "ty_", "sub_debt"))
            or any(x in t for x in ("❌", "🗑", "o'chir", "bekor", "to'xtat"))):
        return "danger"
    if (d in ("save_yes", "bc_send", "check_sub", "reset_all_no") or d.startswith(("pay_full", "tr_", "add_debt", "deliv_"))
            or any(x in t for x in ("✅", "yakunla", "tasdiq", "yuborish", "yoqish"))):
        return "success"
    return "primary"

def _style_button(btn, inline):
    upd = {}
    if getattr(btn, "style", None) is None:
        data = getattr(btn, "callback_data", None) if inline else None
        upd["style"] = _auto_style(btn.text, data)
    # Faqat inline tugmalarda bosh emoji premium ikonkaga almashadi (oddiy tugma matni handlerlar uchun o'zgarmaydi)
    if inline and not getattr(btn, "icon_custom_emoji_id", None) and premium_emoji:
        m = _LEAD_RE.match(btn.text or "")
        if m:
            pid = premium_emoji.get(_enorm(m.group(1)))
            rest = (btn.text or "")[m.end():]
            if pid and rest:
                upd["icon_custom_emoji_id"] = pid
                upd["text"] = rest
    return btn.model_copy(update=upd) if upd else btn

def _style_markup(rm):
    if isinstance(rm, InlineKeyboardMarkup):
        rows = [[_style_button(b, True) for b in row] for row in rm.inline_keyboard]
        return rm.model_copy(update={"inline_keyboard": rows})
    if isinstance(rm, ReplyKeyboardMarkup):
        rows = [[_style_button(b, False) if not isinstance(b, str) else b for b in row] for row in rm.keyboard]
        return rm.model_copy(update={"keyboard": rows})
    return rm

_TEXT_FIELDS = {
    "SendMessage": ("text", "entities"), "EditMessageText": ("text", "entities"),
    "SendPhoto": ("caption", "caption_entities"), "SendDocument": ("caption", "caption_entities"),
    "SendVideo": ("caption", "caption_entities"), "SendAnimation": ("caption", "caption_entities"),
    "SendAudio": ("caption", "caption_entities"), "SendVoice": ("caption", "caption_entities"),
    "EditMessageCaption": ("caption", "caption_entities"),
}
# Telegram xabar effektlari (faqat shaxsiy chatlarda ishlaydi)
EFFECTS = {"party": "5046509860389126442", "heart": "5044134455711629726",
           "fire": "5104841245755180586", "like": "5107584321108051014"}

def _premium_method(bot_, method):
    name = type(method).__name__
    upd = {}
    rm = getattr(method, "reply_markup", None)
    if rm is not None:
        new_rm = _style_markup(rm)
        if new_rm is not rm:
            upd["reply_markup"] = new_rm
    tf = _TEXT_FIELDS.get(name)
    if tf and premium_emoji:
        field, ent_field = tf
        text = getattr(method, field, None)
        if isinstance(text, str) and text and not getattr(method, ent_field, None):
            pm = getattr(method, "parse_mode", None)
            if not isinstance(pm, (str, type(None))):
                pm = getattr(getattr(bot_, "default", None), "parse_mode", None)
            pm = str(getattr(pm, "value", pm) or "").upper()
            if pm == "HTML":
                new_text, ch = _html_emojify(text)
                if ch:
                    upd[field] = new_text
            elif pm == "":
                ents = _plain_entities(text)
                if ents:
                    upd[ent_field] = ents
    if name == "SendMessage" and not getattr(method, "message_effect_id", None) \
            and not getattr(method, "business_connection_id", None):
        cid = getattr(method, "chat_id", None)
        txt = (getattr(method, "text", "") or "")
        if isinstance(cid, int) and cid > 0:
            low = txt.lower()
            if "muvaffaqiyatli" in low or "qabul qilindi" in low:
                upd["message_effect_id"] = EFFECTS["party"]
            elif txt.startswith("Assalomu alaykum"):
                upd["message_effect_id"] = EFFECTS["heart"]
    return method.model_copy(update=upd) if upd else None

class PremiumSession(AiohttpSession):
    async def make_request(self, bot, method, timeout=None):
        fancy = None
        try:
            fancy = _premium_method(bot, method)
        except Exception as e:
            logging.warning(f"Premium bezak tayyorlanmadi: {e}")
        if fancy is not None:
            try:
                return await super().make_request(bot, fancy, timeout=timeout)
            except TelegramBadRequest as e:
                logging.info(f"Premium ko'rinish o'tmadi, oddiy yuboriladi: {e}")
        return await super().make_request(bot, method, timeout=timeout)

bot = Bot(token=TOKEN, session=PremiumSession())
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Список продуктов
PRODUCTS = {
    "oilaviy": {"name": "Oilaviy (0.5 kg karobka)", "count_in_box": 12, "price": 15000, "photo": "https://t.me/YAYPAN_muzqaymoq/21?single"},
    "zuxro_shoko": {"name": "Zuxro shokolad", "count_in_box": 24, "price": 4000, "photo": "https://t.me/YAYPAN_muzqaymoq/19"},
    "flash": {"name": "Flash", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/16"},
    "moxitto": {"name": "Moxitto", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/13"},
    "sutli": {"name": "Sutli", "count_in_box": 54, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/10"},
    "ananas": {"name": "Ananas", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/7"},
    "anor": {"name": "Anor", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/6"},
    "jazzi": {"name": "Jazzi", "count_in_box": 50, "price": 2300, "photo": "https://t.me/YAYPAN_muzqaymoq/73"},
    "ferero": {"name": "Ferero", "count_in_box": 54, "price": 2200, "photo": "https://t.me/YAYPAN_muzqaymoq/74"},
    "anjan_qulupnay": {"name": "Anjan qulupnay", "count_in_box": 20, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/75"},
    "shokoland": {"name": "Shokoland", "count_in_box": 60, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/76"},
    "ayron": {"name": "Ayron", "count_in_box": 70, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/56"},
    "pankie": {"name": "Pankie", "count_in_box": 24, "price": 6000, "photo": "https://t.me/YAYPAN_muzqaymoq/55"},
    "labubu": {"name": "Labubu", "count_in_box": 24, "price": 8000, "photo": "https://t.me/YAYPAN_muzqaymoq/53"},
    "gold": {"name": "Gold", "count_in_box": 28, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/52"},
    "rojok": {"name": "Rojok", "count_in_box": 30, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/51"},
    "sendwich": {"name": "Sendwich", "count_in_box": 24, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/50"},
    "gazeta": {"name": "Gazeta", "count_in_box": 20, "price": 3500, "photo": "https://t.me/YAYPAN_muzqaymoq/49"},
    "stakan": {"name": "Stakan", "count_in_box": 48, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/45"},
    "anjan": {"name": "Anjan", "count_in_box": 20, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/44"},
    "banan": {"name": "Banan", "count_in_box": 48, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/34"},
}

class OrderState(StatesGroup):
    waiting_for_name = State()
    waiting_for_location = State()
    waiting_for_geo = State()
    waiting_for_phone = State()
    waiting_for_save = State()
    shopping = State()
    waiting_for_custom_count = State()
    waiting_for_partial_pay = State()
    waiting_for_admin_debt_add = State()
    waiting_for_admin_debt_sub = State()

user_carts = {}

# ---------- Ma'lumotlar bazasi (PostgreSQL: Neon / Supabase) ----------
# DATABASE_URL berilsa, ma'lumot bazada saqlanadi (hajm cheklovi yo'q, qayta ishga tushganda yo'qolmaydi).
# Berilmasa, avvalgidek JSON fayllar ishlatiladi.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_ENABLED = bool(DATABASE_URL)
_db_dirty = {}        # {fayl yo'li: obyekt} - hali bazaga yozilmagan o'zgarishlar
_db_task = None
_orders_saved = {}    # {indeks: json-matn} - bazada allaqachon bor buyurtmalar

def _db_connect():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, connect_timeout=15)

def _db_key(filepath):
    return os.path.basename(filepath)

def _db_init_and_load():
    """Jadvallarni yaratadi va hamma ma'lumotni xotiraga o'qiydi. Ulanmasa, bot ISHGA TUSHMAYDI (bo'sh baza ustiga yozib yubormaslik uchun)."""
    global _orders_saved
    conn = _db_connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value JSONB NOT NULL)")
                cur.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, data JSONB NOT NULL)")
                cur.execute("SELECT key, value FROM kv")
                kv = {k: v for k, v in cur.fetchall()}
                cur.execute("SELECT id, data FROM orders ORDER BY id")
                rows = cur.fetchall()
    finally:
        conn.close()
    orders = [d for _, d in rows]
    _orders_saved = {i: json.dumps(o, ensure_ascii=False) for i, o in enumerate(orders)}
    return kv, orders

def _db_write(snap):
    """snap: {fayl yo'li: json-matn yoki (buyurtmalar uchun) json-matnlar ro'yxati}"""
    from psycopg2.extras import execute_values
    conn = _db_connect()
    new_orders_saved = None
    try:
        with conn:
            with conn.cursor() as cur:
                for path, val in snap.items():
                    if path == ORDERS_FILE:
                        changed = [(i, js) for i, js in enumerate(val) if _orders_saved.get(i) != js]
                        if changed:
                            execute_values(
                                cur,
                                "INSERT INTO orders (id, data) VALUES %s ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
                                changed, template="(%s, %s::jsonb)", page_size=500,
                            )
                        cur.execute("DELETE FROM orders WHERE id >= %s", (len(val),))
                        new_orders_saved = dict(enumerate(val))
                    else:
                        cur.execute(
                            "INSERT INTO kv (key, value) VALUES (%s, %s::jsonb) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                            (_db_key(path), val),
                        )
    finally:
        conn.close()
    if new_orders_saved is not None:
        _orders_saved.clear()
        _orders_saved.update(new_orders_saved)

async def _db_flush_loop():
    global _db_task
    try:
        await asyncio.sleep(1.5)   # qisqa vaqt ichidagi o'zgarishlarni bitta yozuvga birlashtiramiz
        while _db_dirty:
            items = dict(_db_dirty)
            _db_dirty.clear()
            snap = {}
            for path, obj in items.items():
                if path == ORDERS_FILE:
                    snap[path] = [json.dumps(o, ensure_ascii=False) for o in obj]
                else:
                    snap[path] = json.dumps(obj, ensure_ascii=False)
            try:
                await asyncio.to_thread(_db_write, snap)
            except Exception as e:
                logging.error(f"Bazaga yozib bo'lmadi, 10 soniyadan keyin qayta uriniladi: {e}")
                for p, o in items.items():
                    _db_dirty.setdefault(p, o)
                await asyncio.sleep(10)
    finally:
        _db_task = None

def _db_mark(filepath, data):
    """O'zgargan ma'lumotni bazaga yozish uchun navbatga qo'yadi."""
    global _db_task
    _db_dirty[filepath] = data
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # event loop yo'q (masalan, bot ishga tushishidan oldin): darhol yozamiz
        items = dict(_db_dirty)
        _db_dirty.clear()
        snap = {p: ([json.dumps(o, ensure_ascii=False) for o in obj] if p == ORDERS_FILE else json.dumps(obj, ensure_ascii=False))
                for p, obj in items.items()}
        try:
            _db_write(snap)
        except Exception as e:
            logging.error(f"Bazaga yozib bo'lmadi: {e}")
            for p, o in items.items():
                _db_dirty.setdefault(p, o)
        return
    if _db_task is None:
        _db_task = loop.create_task(_db_flush_loop())

_db_kv, _db_orders = _db_init_and_load() if DB_ENABLED else ({}, [])
if DB_ENABLED:
    logging.info(f"Baza ulandi: {len(_db_kv)} ta jadval-kalit, {len(_db_orders)} ta buyurtma")

# ---------- Операции с JSON-файлами ----------
def load_json(filepath):
    if DB_ENABLED:
        if filepath.endswith("orders.json"):
            return _db_orders
        v = _db_kv.get(_db_key(filepath))
        return v if v is not None else {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [] if filepath.endswith("orders.json") else {}

def save_json(filepath, data, backup=True):
    if DB_ENABLED:
        _db_mark(filepath, data)
    else:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка записи в {filepath}: {e}")
    if backup:
        request_backup()

saved_users = load_json(USERS_FILE)
debts_db = load_json(DEBTS_FILE)
orders_db = load_json(ORDERS_FILE)
if not isinstance(orders_db, list):
    orders_db = []
subscribers = load_json(SUBSCRIBERS_FILE)
if not isinstance(subscribers, dict):
    subscribers = {}

def add_subscriber(user):
    uid = str(user.id)
    if uid not in subscribers:
        subscribers[uid] = {"name": user.full_name or "", "username": user.username or ""}
        save_json(SUBSCRIBERS_FILE, subscribers)

# ================= ⏰ SOAT: Telegram Business "Chat bot" orqali ism va bio =================
# Foydalanuvchi botni Telegram > Sozlamalar > Telegram Business > Chat botlar ga qo'shadi.
# Hech qanday telefon raqam, kod yoki 2 bosqichli parol so'ralmaydi: bot ulanishni o'zi qabul qiladi
# va sozlash klaviaturasini o'zi chiqaradi. Ism/bio Bot API (setBusinessAccountName / setBusinessAccountBio) orqali o'zgaradi.
import calendar

CLOCK_FILE = os.path.join(DATA_DIR, "clock.json")
clock_db = load_json(CLOCK_FILE)
if not isinstance(clock_db, dict):
    clock_db = {}
clock_db.setdefault("users", {})
_clock_last = {}     # {uid: {"name": ..., "bio": ...}} - oxirgi yuborilgan qiymatlar (ortiqcha so'rov yubormaslik uchun)
_clock_pause = {}    # {uid: vaqt} - flood limit tugaguncha kutish
_clock_wait = {}     # {uid: (nima kutilyapti, vaqt)}
_clock_http = None

_pd = load_json(PREMIUM_FILE)
if isinstance(_pd, dict) and isinstance(_pd.get("map"), dict):
    premium_emoji.update(_pd["map"])

def save_clock():
    save_json(CLOCK_FILE, clock_db, backup=False)

def save_premium():
    save_json(PREMIUM_FILE, {"map": premium_emoji}, backup=False)

DIGIT_STYLES = [
    ("Oddiy", "0123456789"),
    ("Qalin", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"),
    ("Ikki chiziq", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡"),
    ("Mono", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"),
    ("Kichik", "⁰¹²³⁴⁵⁶⁷⁸⁹"),
    ("Doira", "⓪①②③④⑤⑥⑦⑧⑨"),
]
UZ_DAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
BIO_MODES = ["off", "time", "birthday", "custom"]
BIO_NAMES = {"off": "O'chiq", "time": "Vaqt", "birthday": "Tug'ilgan kun", "custom": "O'z matnim"}

def fmt_time(dt, style):
    digits = DIGIT_STYLES[style % len(DIGIT_STYLES)][1]
    return "".join(digits[int(c)] if c.isdigit() else c for c in dt.strftime("%H:%M"))

def clock_now(u):
    return datetime.now(_tz(timedelta(hours=u.get("tz", 5))))

def birthday_left(now, ddmm):
    """(kun, soat, hafta kuni, bugunmi) - keyingi tug'ilgan kungacha."""
    d, m = [int(x) for x in ddmm.split(".")]
    def mk(y):
        dd = d
        if m == 2 and d == 29 and not calendar.isleap(y):
            dd = 28
        return now.replace(year=y, month=m, day=dd, hour=0, minute=0, second=0, microsecond=0)
    t = mk(now.year)
    if t.date() == now.date():
        return 0, 0, UZ_DAYS[t.weekday()], True
    if t < now:
        t = mk(now.year + 1)
    diff = t - now
    return diff.days, diff.seconds // 3600, UZ_DAYS[t.weekday()], False

def build_bio(u, now):
    mode = u.get("bio_mode", "off")
    t = fmt_time(now, u.get("style", 1))
    if mode == "time":
        return f"⏰ Hozir {t} • {now.strftime('%d.%m.%Y')}"[:140]
    if mode == "birthday" and u.get("birthday"):
        days, hours, wd, today = birthday_left(now, u["birthday"])
        if today:
            return "🎉 Bugun tug'ilgan kunim! 🎂"
        left = f"{days} kun {hours} soat" if days else f"{hours} soat"
        return f"🎂 Tug'ilgan kungacha: {left} ({wd})"[:140]
    if mode == "custom" and u.get("bio_text"):
        s = u["bio_text"].replace("{time}", t).replace("{date}", now.strftime("%d.%m.%Y"))
        if "{left}" in s and u.get("birthday"):
            days, hours, _, _ = birthday_left(now, u["birthday"])
            s = s.replace("{left}", f"{days} kun {hours} soat")
        return s[:140]
    return ""

class ClockApiError(Exception):
    def __init__(self, code, desc, retry=None):
        super().__init__(f"{code}: {desc}")
        self.code, self.desc, self.retry = code, (desc or ""), retry

async def _biz(method, **params):
    """Bot API'ga to'g'ridan-to'g'ri so'rov (aiogram versiyasiga bog'liq emas)."""
    global _clock_http
    if _clock_http is None or _clock_http.closed:
        _clock_http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))
    async with _clock_http.post(f"https://api.telegram.org/bot{TOKEN}/{method}", json=params) as r:
        data = await r.json(content_type=None)
    if data.get("ok"):
        return data.get("result")
    raise ClockApiError(data.get("error_code"), data.get("description", ""), (data.get("parameters") or {}).get("retry_after"))

async def _biz_soft(method, **params):
    try:
        return await _biz(method, **params)
    except ClockApiError as e:
        if "not modified" in e.desc.lower() or "not_modified" in e.desc.lower():
            return None
        raise

def _right(rights, name):
    if rights is None:
        return True
    v = rights.get(name) if isinstance(rights, dict) else getattr(rights, name, None)
    return bool(v)

async def clock_apply(uid, force=False):
    """Bitta foydalanuvchining ismi/biosini hozirgi vaqtga moslaydi. Xato bo'lsa matn qaytaradi."""
    u = clock_db["users"].get(str(uid))
    if not u or not u.get("conn"):
        return "Ulanish topilmadi"
    if _clock_pause.get(str(uid), 0) > time.time():
        return None
    now = clock_now(u)
    last = _clock_last.setdefault(str(uid), {})
    try:
        if u.get("name_on") and u.get("can_name", True):
            t = fmt_time(now, u.get("style", 1))
            base = (u.get("base_first") or "User")[: max(1, 64 - len(t) - 1)]
            first, lastn = f"{base} {t}", u.get("base_last", "")
            if force or last.get("name") != (first, lastn):
                await _biz_soft("setBusinessAccountName", business_connection_id=u["conn"], first_name=first, last_name=lastn)
                last["name"] = (first, lastn)
                if not u.get("t_name"):
                    u["t_name"] = True
                    save_clock()
        if u.get("bio_mode", "off") != "off" and u.get("can_bio", True):
            bio = build_bio(u, now)
            if bio and (force or last.get("bio") != bio):
                await _biz_soft("setBusinessAccountBio", business_connection_id=u["conn"], bio=bio)
                last["bio"] = bio
                if not u.get("t_bio"):
                    u["t_bio"] = True
                    save_clock()
    except ClockApiError as e:
        d = e.desc.lower()
        if e.retry:
            _clock_pause[str(uid)] = time.time() + int(e.retry) + 1
            return f"Telegram limit: {e.retry} soniya kuting"
        if "connection" in d or "rights" in d or "enough" in d:
            u["on"] = False
            save_clock()
            try:
                await bot.send_message(u["chat"], "⚠️ Bot soatni yangilay olmadi (ruxsat yoki ulanish yo'q). "
                                       "Sozlamalar → Telegram Business → Chat botlar bo'limida botga «Ism va bio» ruxsatini bering va /soat ni bosing.")
            except Exception:
                pass
        logging.warning(f"Soat xatosi ({uid}): {e}")
        return e.desc
    return None

async def clock_restore(u, name=True, bio=True):
    if name and u.get("t_name"):
        await _biz_soft("setBusinessAccountName", business_connection_id=u["conn"],
                        first_name=u.get("orig_first") or "User", last_name=u.get("orig_last", ""))
        u["t_name"] = False
    if bio and u.get("t_bio"):
        await _biz_soft("setBusinessAccountBio", business_connection_id=u["conn"], bio=u.get("orig_bio", ""))
        u["t_bio"] = False
    _clock_last.pop(str(u.get("uid")), None)
    save_clock()

async def clock_loop():
    """Har daqiqaning boshida hamma yoqilgan foydalanuvchilarni yangilaydi."""
    await asyncio.sleep(5)
    while True:
        await asyncio.sleep(60 - (time.time() % 60) + 0.5)
        for uid, u in list(clock_db["users"].items()):
            if u.get("on") and u.get("conn"):
                try:
                    await clock_apply(uid)
                except Exception as e:
                    logging.warning(f"Soat tsikli ({uid}): {e}")
                await asyncio.sleep(0.25)

# ---------- Panel (matn + klaviatura) ----------
def clock_panel_text(u):
    now = clock_now(u)
    t = fmt_time(now, u.get("style", 1))
    on = u.get("on")
    name_line = (f"{html.escape(u.get('base_first') or 'User')} {t}" if u.get("name_on") else "o'zgarmaydi")
    bio_preview = build_bio(u, now) if u.get("bio_mode", "off") != "off" else ""
    lines = [
        "<b>⏰ Soat paneli</b>",
        "",
        f"📡 Holat: {'🟢 <b>Ishlayapti</b>' if on else '🔴 <b>To‘xtatilgan</b>'}",
        f"🌍 Vaqt zonasi: <b>UTC{u.get('tz', 5):+d}</b>  •  🕒 <b>{t}</b>",
        f"👤 Ism: <b>{name_line}</b>",
        f"📝 Bio ({BIO_NAMES[u.get('bio_mode', 'off')]}): <b>{html.escape(bio_preview) if bio_preview else '—'}</b>",
        "",
        "Tugmalar orqali hamma narsani sozlang — bot ismingiz va biongizni o'zi yangilab turadi ✨",
    ]
    warn = []
    if not u.get("can_name", True):
        warn.append("Ism")
    if not u.get("can_bio", True):
        warn.append("Bio")
    if warn:
        lines += ["", f"⚠️ Botga <b>{' va '.join(warn)}</b> o'zgartirish ruxsati berilmagan: Sozlamalar → Telegram Business → Chat botlar → botni tanlab ruxsatlarni yoqing."]
    return "\n".join(lines)

def clock_panel_kb(u):
    b = InlineKeyboardButton
    on = u.get("on")
    sample = fmt_time(datetime(2000, 1, 1, 12, 34), u.get("style", 1))
    return InlineKeyboardMarkup(inline_keyboard=[
        [b(text="🔴 To'xtatish va asl holatga qaytarish" if on else "🟢 Soatni yoqish", callback_data="clk:tg")],
        [b(text="👤 Ism: " + ("✅" if u.get("name_on") else "❌"), callback_data="clk:nm"),
         b(text=f"🔢 Shrift: {sample}", callback_data="clk:st")],
        [b(text="➖", callback_data="clk:tz:-"), b(text=f"🌍 UTC{u.get('tz', 5):+d}", callback_data="clk:tzi"),
         b(text="➕", callback_data="clk:tz:+")],
        [b(text=f"📝 Bio: {BIO_NAMES[u.get('bio_mode', 'off')]}", callback_data="clk:bm")],
        [b(text="✏️ Ismni o'zgartirish", callback_data="clk:en"), b(text="🎂 Tug'ilgan kun", callback_data="clk:eb")],
        [b(text="💬 O'z bio matnim", callback_data="clk:ec")],
        [b(text="🔄 Hozir yangilash", callback_data="clk:now")],
    ])

async def clock_send_panel(chat_id, u, effect=True):
    text, kb = clock_panel_text(u), clock_panel_kb(u)
    if effect:
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb, message_effect_id=EFFECTS["party"])
            return
        except Exception as e:
            logging.info(f"Effektli panel yuborilmadi: {e}")
    await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

def clock_how_to_text(bot_username):
    return (
        "<b>⏰ Ismdagi jonli soat</b>\n\n"
        "Botni Telegram akkauntingizga ulang — kod yoki parol <b>kerak emas</b>:\n\n"
        "1️⃣ <b>Sozlamalar</b> → <b>Telegram Business</b>\n"
        "2️⃣ <b>Chat botlar</b> (Chatbots) bo'limini oching\n"
        f"3️⃣ <b>@{bot_username}</b> ni qo'shing\n"
        "4️⃣ Ruxsatlarda <b>Ism</b> va <b>Bio</b> o'zgartirishni yoqing\n\n"
        "Ulangach, sozlash klaviaturasi shu yerning o'zida avtomatik chiqadi 🚀\n"
        "<i>Telegram Business Premium obunasini talab qiladi.</i>"
    )

# ---------- Ulanish (business_connection) ----------
@dp.business_connection()
async def clk_connection(bc: types.BusinessConnection):
    uid = str(bc.user.id)
    u = clock_db["users"].get(uid)
    if not bc.is_enabled:
        if u:
            u["conn"], u["on"] = None, False
            save_clock()
        return
    rights = getattr(bc, "rights", None)
    if rights is None:
        rights = (getattr(bc, "model_extra", None) or {}).get("rights")
    first, last, bio = bc.user.first_name or "", bc.user.last_name or "", ""
    try:
        ch = await bot.get_chat(bc.user_chat_id)
        first, last, bio = ch.first_name or first, ch.last_name or "", getattr(ch, "bio", None) or ""
    except Exception as e:
        logging.info(f"Profil o'qilmadi: {e}")
    if u is None:
        u = {"uid": bc.user.id, "on": False, "tz": 5, "style": 1, "name_on": True, "bio_mode": "time",
             "birthday": "", "bio_text": "", "t_name": False, "t_bio": False,
             "orig_first": first, "orig_last": last, "orig_bio": bio, "base_first": first, "base_last": last}
        clock_db["users"][uid] = u
    elif not u.get("t_name") and not u.get("t_bio"):
        u.update(orig_first=first, orig_last=last, orig_bio=bio)
        u.setdefault("base_first", first)
    u.update(conn=bc.id, chat=bc.user_chat_id,
             can_name=_right(rights, "can_edit_name"), can_bio=_right(rights, "can_edit_bio"))
    save_clock()
    await clock_send_panel(bc.user_chat_id, u)

# ---------- /soat ----------
@dp.message(Command("soat"))
async def cmd_soat(message: types.Message):
    u = clock_db["users"].get(str(message.from_user.id))
    if u and u.get("conn"):
        await clock_send_panel(message.chat.id, u, effect=False)
        return
    me = await bot.me()
    await message.answer(clock_how_to_text(me.username), parse_mode="HTML")

async def _clock_waiting(m: types.Message):
    w = _clock_wait.get(m.from_user.id) if m.from_user else None
    if not w or time.time() - w[1] > 600:
        return False
    return bool(m.text) and not m.text.startswith("/")

@dp.message(_clock_waiting)
async def clk_input(message: types.Message):
    uid = message.from_user.id
    kind, _ = _clock_wait.pop(uid)
    u = clock_db["users"].get(str(uid))
    if not u:
        return
    text = message.text.strip()
    if kind == "name":
        u["base_first"] = text[:50]
    elif kind == "birthday":
        m = re.match(r"^(\d{1,2})[.\-/ ](\d{1,2})(?:[.\-/ ]\d{2,4})?$", text)
        if not m or not (1 <= int(m.group(2)) <= 12) or not (1 <= int(m.group(1)) <= calendar.monthrange(2024, int(m.group(2)))[1]):
            _clock_wait[uid] = ("birthday", time.time())
            await message.answer("❗ Sana noto'g'ri. Masalan: <code>03.12</code> yoki <code>03.12.2013</code>", parse_mode="HTML")
            return
        u["birthday"] = f"{int(m.group(1)):02d}.{int(m.group(2)):02d}"
        u["bio_mode"] = "birthday"
    elif kind == "bio":
        u["bio_text"] = text[:140]
        u["bio_mode"] = "custom"
    save_clock()
    if u.get("on"):
        await clock_apply(uid, force=True)
    await message.answer("✅ Saqlandi!")
    await clock_send_panel(message.chat.id, u, effect=False)

# ---------- Panel tugmalari ----------
async def _clock_redraw(cq: types.CallbackQuery, u):
    try:
        await cq.message.edit_text(clock_panel_text(u), parse_mode="HTML", reply_markup=clock_panel_kb(u))
    except TelegramBadRequest:
        pass

@dp.callback_query(F.data.startswith("clk:"))
async def clk_callback(cq: types.CallbackQuery):
    uid = cq.from_user.id
    u = clock_db["users"].get(str(uid))
    if not u or not u.get("conn"):
        await cq.answer("Avval botni Telegram Business → Chat botlar orqali ulang", show_alert=True)
        return
    parts = cq.data.split(":")
    act = parts[1]
    toast, err = None, None
    try:
        if act == "tg":
            if u.get("on"):
                u["on"] = False
                await clock_restore(u)
                toast = "To'xtatildi, asl ism va bio qaytarildi"
            else:
                u["on"] = True
                err = await clock_apply(uid, force=True)
                toast = "Soat yoqildi ✨"
        elif act == "nm":
            u["name_on"] = not u.get("name_on")
            if u["name_on"]:
                if u.get("on"):
                    err = await clock_apply(uid, force=True)
            else:
                await clock_restore(u, bio=False)
        elif act == "st":
            u["style"] = (u.get("style", 1) + 1) % len(DIGIT_STYLES)
            toast = "Shrift: " + DIGIT_STYLES[u["style"]][0]
            if u.get("on"):
                err = await clock_apply(uid, force=True)
        elif act == "tz":
            u["tz"] = max(-12, min(14, u.get("tz", 5) + (1 if parts[2] == "+" else -1)))
            if u.get("on"):
                err = await clock_apply(uid, force=True)
        elif act == "tzi":
            toast = "Toshkent: UTC+5"
        elif act == "bm":
            nxt = BIO_MODES[(BIO_MODES.index(u.get("bio_mode", "off")) + 1) % len(BIO_MODES)]
            if nxt == "birthday" and not u.get("birthday"):
                _clock_wait[uid] = ("birthday", time.time())
                await cq.message.answer("🎂 Tug'ilgan kuningizni yozing (kun.oy), masalan: <code>03.12</code>", parse_mode="HTML")
                await cq.answer()
                return
            if nxt == "custom" and not u.get("bio_text"):
                _clock_wait[uid] = ("bio", time.time())
                await cq.message.answer("💬 Bio matnini yozing. Ishlatishingiz mumkin: <code>{time}</code> <code>{date}</code> <code>{left}</code>", parse_mode="HTML")
                await cq.answer()
                return
            u["bio_mode"] = nxt
            if nxt == "off":
                await clock_restore(u, name=False)
            elif u.get("on"):
                err = await clock_apply(uid, force=True)
        elif act in ("en", "eb", "ec"):
            kind = {"en": "name", "eb": "birthday", "ec": "bio"}[act]
            ask = {"name": "✏️ Ismda ko'rinadigan yangi ismni yozing (soat uning yoniga qo'shiladi):",
                   "birthday": "🎂 Tug'ilgan kuningizni yozing (kun.oy), masalan: <code>03.12</code>",
                   "bio": "💬 Bio matnini yozing. Ishlatishingiz mumkin: <code>{time}</code> <code>{date}</code> <code>{left}</code>"}[kind]
            _clock_wait[uid] = (kind, time.time())
            await cq.message.answer(ask, parse_mode="HTML")
            await cq.answer()
            return
        elif act == "now":
            err = await clock_apply(uid, force=True)
            toast = "Yangilandi 🔄"
    except ClockApiError as e:
        err = e.desc
    save_clock()
    await cq.answer(("⚠️ " + err[:150]) if err else toast, show_alert=bool(err))
    await _clock_redraw(cq, u)

# ---------- /emoji: premium emojilarni o'rgatish (faqat admin) ----------
_emoji_learning = set()

async def load_emoji_pack(name):
    st = await bot.get_sticker_set(name)
    n = 0
    for s in st.stickers:
        if getattr(s, "custom_emoji_id", None) and s.emoji:
            premium_emoji.setdefault(_enorm(s.emoji), s.custom_emoji_id)
            n += 1
    return n

async def load_emoji_sets_env():
    for name in [x.strip() for x in os.environ.get("PREMIUM_EMOJI_SETS", "").split(",") if x.strip()]:
        try:
            await load_emoji_pack(name)
        except Exception as e:
            logging.warning(f"Emoji to'plami yuklanmadi ({name}): {e}")
    if premium_emoji:
        save_premium()
        logging.info(f"Premium emoji: {len(premium_emoji)} ta")

@dp.message(Command("emoji"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_emoji(message: types.Message):
    _emoji_learning.add(message.from_user.id)
    await message.answer(
        "💎 <b>Premium emoji o'rgatish</b>\n\n"
        "Endi menga <b>premium emojilar yozilgan bitta xabar</b> yuboring — har bir emoji botdagi shu oddiy emoji o'rniga ishlatiladi.\n"
        "Yoki emoji to'plami havolasini yuboring: <code>https://t.me/addemoji/NOM</code>\n\n"
        f"Hozir o'rgatilgan: <b>{len(premium_emoji)}</b> ta.",
        parse_mode="HTML")

async def _learning(m: types.Message):
    return bool(m.from_user) and m.from_user.id in _emoji_learning and not (m.text or "").startswith("/")

@dp.message(_learning)
async def emoji_learn(message: types.Message):
    _emoji_learning.discard(message.from_user.id)
    text = message.text or message.caption or ""
    ents = message.entities or message.caption_entities or []
    raw = text.encode("utf-16-le")
    got = 0
    for e in ents:
        if e.type == "custom_emoji" and e.custom_emoji_id:
            ch = raw[e.offset * 2:(e.offset + e.length) * 2].decode("utf-16-le", "ignore")
            if _enorm(ch):
                premium_emoji[_enorm(ch)] = e.custom_emoji_id
                got += 1
    for name in re.findall(r"t\.me/addemoji/([A-Za-z0-9_]+)", text):
        try:
            got += await load_emoji_pack(name)
        except Exception as e:
            await message.answer(f"To'plam topilmadi: {name}")
    if got:
        save_premium()
        await message.answer(f"✅ {got} ta premium emoji o'rganildi. Jami: {len(premium_emoji)} ta.")
    else:
        await message.answer("Premium emoji topilmadi. /emoji ni bosib, premium emojili xabar yuboring.")

# ---------- Qo'shimcha muzqaymoqlar, "tugadi" holati va "xabar bering" so'rovlari ----------
BASE_PRODUCTS = copy.deepcopy(PRODUCTS)   # kodda yozilgan asl ro'yxat (o'zgarmaydi)
products_state = {}

def apply_products_state():
    """Asl ro'yxat + admin qo'shganlar + tahrirlar - o'chirilganlar = hozirgi PRODUCTS."""
    PRODUCTS.clear()
    for k, p in BASE_PRODUCTS.items():
        PRODUCTS[k] = dict(p)
    for k, p in products_state["custom"].items():
        PRODUCTS[k] = dict(p)
    for k, e in products_state["edits"].items():
        if k in PRODUCTS:
            PRODUCTS[k].update(e)
    for k in products_state["deleted"]:
        PRODUCTS.pop(k, None)

def load_products_state(data):
    products_state.clear()
    if isinstance(data, dict):
        products_state.update(data)
    products_state.setdefault("custom", {})    # admin qo'shgan muzqaymoqlar
    products_state.setdefault("out", [])       # tugagan muzqaymoqlar kalitlari
    products_state.setdefault("waiting", {})   # {mahsulot_kaliti: [user_id, ...]} - kelsa xabar kutayotganlar
    products_state.setdefault("edits", {})     # {kalit: {name/price/count_in_box/photo: yangi qiymat}}
    products_state.setdefault("deleted", [])   # o'chirilgan (asl ro'yxatdagi) muzqaymoqlar kalitlari
    apply_products_state()

load_products_state(load_json(PRODUCTS_FILE))

def save_products():
    save_json(PRODUCTS_FILE, products_state)

def is_in_stock(key):
    return key not in products_state["out"]

def next_custom_key():
    n = 1
    while f"new{n}" in PRODUCTS:
        n += 1
    return f"new{n}"

def add_waiting(key, user_id):
    """Tugagan muzqaymoqni so'ragan odamni ro'yxatga yozadi (kelsa xabar yuboriladi)."""
    lst = products_state["waiting"].setdefault(key, [])
    if user_id not in lst:
        lst.append(user_id)
        save_products()

def out_of_stock_text(key):
    return (
        f"😔 <b>{html.escape(PRODUCTS[key]['name'])}</b> hozircha tugadi.\n"
        f"Agar yetib kelsa, sizga xabar yuboramiz 🔔"
    )

async def reply_out_of_stock(callback_query, key):
    add_waiting(key, callback_query.from_user.id)
    await callback_query.message.answer(out_of_stock_text(key), parse_mode="HTML")
    await callback_query.answer("Bu muzqaymoq tugadi 😔")

async def notify_waiting(key, users):
    """Muzqaymoq yetib kelganda uni so'ragan odamlarga xabar yuboradi. Yuborilganlar sonini qaytaradi."""
    text = (
        f"🍦 Yaxshi xabar! <b>{html.escape(PRODUCTS[key]['name'])}</b> endi mavjud!\n"
        f"Buyurtma berishingiz mumkin 😊 (katalogdan tanlang yoki /start bosing)"
    )
    sent = 0
    for uid in users:
        try:
            try:
                await bot.send_message(int(uid), text, parse_mode="HTML")
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(int(uid), text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            logging.info(f"Xabar yuborilmadi {uid}: {e}")
        await asyncio.sleep(0.05)
    return sent

# ---------- Telegram orqali zaxira ----------
# Har o'zgarishdan keyin barcha ma'lumot backup.json qilib adminga yuboriladi va PIN qilinadi.
# Baza bo'sh bo'lsa, bot ishga tushganda shu pin qilingan fayldan hammasini tiklaydi.
_backup_scheduled = False
_last_backup_msg_id = None

def request_backup():
    """Ma'lumot o'zgarganda chaqiriladi; 10 soniya ichidagi o'zgarishlarni bitta zaxiraga birlashtiradi."""
    global _backup_scheduled
    if DB_ENABLED:
        return   # ma'lumot Neon bazasida saqlanadi, Telegramga zaxira yuborilmaydi
    if _backup_scheduled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _backup_scheduled = True
    loop.create_task(_do_backup())

def _backup_payload():
    orders = list(orders_db)
    while True:
        data = json.dumps(
            {"users": saved_users, "debts": debts_db, "orders": orders, "subscribers": subscribers, "products": products_state},
            ensure_ascii=False, indent=1
        ).encode("utf-8")
        # Telegram'dan yuklab olish chegarasi 20 MB: oshib ketsa, eng eski buyurtmalarni zaxiradan chiqaramiz
        # (baza ishlatilsa, ular bazada baribir saqlanib turadi)
        if len(data) <= 15_000_000 or len(orders) <= 100:
            return data
        orders = orders[len(orders) // 4:]

async def _do_backup(delay=10, force=False):
    global _backup_scheduled, _last_backup_msg_id
    await asyncio.sleep(delay)
    _backup_scheduled = False
    # HIMOYA: ma'lumot butunlay bo'sh bo'lsa, zaxirani yubormaymiz. Aks holda bo'sh zaxira
    # pin qilingan yaxshi zaxiraning o'rniga o'tib, eskisi o'chib ketardi.
    if not force and not (saved_users or debts_db or orders_db):
        logging.info("Ma'lumot bo'sh: zaxira yuborilmadi (eski zaxira saqlab qolindi).")
        return
    try:
        msg = await bot.send_document(
            ADMIN_ID,
            BufferedInputFile(_backup_payload(), filename="backup.json"),
            caption="💾 Avtomatik zaxira (o'chirmang, bot shu fayldan tiklanadi)",
            disable_notification=True,
        )
        await bot.pin_chat_message(ADMIN_ID, msg.message_id, disable_notification=True)
        old_id, _last_backup_msg_id = _last_backup_msg_id, msg.message_id
        if old_id:
            try:
                await bot.delete_message(ADMIN_ID, old_id)
            except Exception:
                pass
    except Exception as e:
        logging.error(f"Zaxira yuborilmadi: {e}")

async def restore_from_telegram():
    """Fayllar bo'sh bo'lsa (yangi restart), adminning pin qilingan backup.json faylidan tiklaydi."""
    global _last_backup_msg_id
    if DB_ENABLED:
        return   # baza ishlatilsa, Telegram zaxirasidan avtomatik tiklash kerak emas
    if saved_users or debts_db or orders_db or subscribers:
        return
    try:
        chat = await bot.get_chat(ADMIN_ID)
        pm = chat.pinned_message
        if not pm or not pm.document:
            logging.info("Tiklash uchun zaxira topilmadi.")
            return
        f = await bot.get_file(pm.document.file_id)
        buf = io.BytesIO()
        await bot.download_file(f.file_path, buf)
        data = json.loads(buf.getvalue().decode("utf-8"))
        saved_users.update(data.get("users", {}))
        debts_db.update(data.get("debts", {}))
        orders_db.extend(data.get("orders", []))
        subscribers.update(data.get("subscribers", {}))
        if data.get("products"):
            load_products_state(data["products"])
        _last_backup_msg_id = pm.message_id
        # Lokal fayllarga ham yozib qo'yamiz
        for path, obj in ((USERS_FILE, saved_users), (DEBTS_FILE, debts_db), (ORDERS_FILE, orders_db), (SUBSCRIBERS_FILE, subscribers), (PRODUCTS_FILE, products_state)):
            save_json(path, obj, backup=False)
        logging.info(f"Zaxiradan tiklandi: {len(saved_users)} mijoz, {len(debts_db)} qarzdor, {len(orders_db)} buyurtma")
        await bot.send_message(
            ADMIN_ID,
            f"♻️ Bot qayta ishga tushdi, ma'lumotlar zaxiradan tiklandi:\n"
            f"👥 Mijozlar: {len(saved_users)}\n💳 Qarzdorlar: {len(debts_db)}\n📥 Buyurtmalar: {len(orders_db)}"
        )
    except Exception as e:
        logging.error(f"Tiklashda xato: {e}")

def maps_link(geo):
    return f"https://www.google.com/maps?q={geo['lat']},{geo['lon']}"

def get_user_debt(user_id):
    return int(debts_db.get(str(user_id), {}).get("debt", 0) or 0)

def get_user_location(user_id):
    s_ = saved_users.get(str(user_id)) or {}
    if s_.get("location"):
        return s_["location"]
    for o in reversed(orders_db):
        if str(o.get("userId")) == str(user_id) and o.get("location") not in (None, "", "-"):
            return o["location"]
    return "-"

def get_user_geo(user_id):
    s_ = saved_users.get(str(user_id)) or {}
    if s_.get("geo"):
        return s_["geo"]
    for o in reversed(orders_db):
        if str(o.get("userId")) == str(user_id) and o.get("geo"):
            return o["geo"]
    return None

def debt_history_text(user_id, limit=8):
    """Mijozning qarz tarixi: sana — mahsulot: summa ... oxirida JAMI QARZ."""
    u = debts_db.get(str(user_id))
    if not u or u.get("debt", 0) <= 0:
        return "📒 <b>Oldingi qarz:</b> yo'q ✅"
    hist = u.get("history", [])
    text = "📒 <b>Mijozning qarz tarixi:</b>\n"
    if len(hist) > limit:
        text += f"... (oldingi {len(hist) - limit} ta yozuv ko'rsatilmadi)\n"
    for h in hist[-limit:]:
        items = str(h.get("items", ""))
        if len(items) > 60:
            items = items[:57] + "..."
        text += f"▫️ {h.get('date', '')} — {html.escape(items)}: {int(h.get('amount', 0)):,} so'm\n"
    text += f"💳 <b>JAMI QARZ: {int(u['debt']):,} so'm</b>"
    return text

def get_saved_user(user_id):
    return saved_users.get(str(user_id))

def set_saved_user(user_id, name, location, phone, geo=None):
    saved_users[str(user_id)] = {"name": name, "location": location, "phone": phone, "geo": geo}
    save_json(USERS_FILE, saved_users)

def delete_saved_user(user_id):
    if str(user_id) in saved_users:
        del saved_users[str(user_id)]
        save_json(USERS_FILE, saved_users)

def add_user_debt(user_id, name, phone, added_amount, items_str=""):
    uid = str(user_id)
    if (not name or name == "-") and uid in saved_users:
        name = saved_users[uid].get("name", "Noma'lum")
    if (not phone or phone == "-") and uid in saved_users:
        phone = saved_users[uid].get("phone", "Noma'lum")

    if uid not in debts_db:
        debts_db[uid] = {"name": name or "Noma'lum", "phone": phone or "Noma'lum", "debt": 0, "history": []}
    
    if "history" not in debts_db[uid]:
        debts_db[uid]["history"] = []

    debts_db[uid]["debt"] += added_amount
    if name and name != "-":
        debts_db[uid]["name"] = name
    if phone and phone != "-":
        debts_db[uid]["phone"] = phone

    if added_amount > 0:
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
        debts_db[uid]["history"].append({
            "date": now_str,
            "items": items_str or "Qarz qo'shildi",
            "amount": added_amount
        })

    save_json(DEBTS_FILE, debts_db)
    return debts_db[uid]["debt"]

def get_formatted_debt_text(user_id):
    uid = str(user_id)
    if uid not in debts_db or debts_db[uid].get("debt", 0) <= 0:
        return "Sizda qarz yo'q! ✅"

    u = debts_db[uid]
    history = u.get("history", [])
    
    text = f"📋 <b>QARZLARINGIZ TARIXI ({html.escape(u.get('name', ''))}):</b>\n\n"
    for i, item in enumerate(history, 1):
        text += f"<b>{i}. {item['date']}</b>\n"
        text += f"🍦 Mahsulot: {item['items']}\n"
        text += f"💰 Qarz: {item['amount']:,} so'm\n"
        text += "-------------------------\n"
    
    text += f"\n💳 <b>JAMI QARZINGIZ: {u['debt']:,} so'm</b>"
    return text

# ---------- Клавиатуры ----------
main_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛒 Savatni ko'rish"), KeyboardButton(text="✅ Buyurtmani yakunlash")],
        [KeyboardButton(text="🍦 Mini App", web_app=WebAppInfo(url=WEBAPP_URL)), KeyboardButton(text="📄 Mening qarzdorligim")],
        [KeyboardButton(text="✏️ Ma'lumotlarni o'zgartirish")]
    ],
    resize_keyboard=True
)

save_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Ha, saqlansin", callback_data="save_yes"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data="save_no"),
    ]
])

def info_text(name, location, phone, geo=None, debt=None):
    t = (
        f"👤 <b>Ism:</b> {html.escape(str(name))}\n"
        f"📍 <b>Manzil:</b> {html.escape(str(location))}\n"
        f"📞 <b>Telefon:</b> {html.escape(str(phone))}"
    )
    if geo:
        t += f"\n🗺 <b>Lokatsiya:</b> <a href=\"{maps_link(geo)}\">Google Mapda ochish</a>"
    if debt is not None:
        t += f"\n💳 <b>Mijozning eski qarzi:</b> {int(debt):,} so'm"
    return t

def admin_order_keyboard(user_id, total_price, geo=None):
    rows = []
    if geo:
        rows.append([InlineKeyboardButton(text="🗺 Google Mapda ko'rish", url=maps_link(geo))])
    return InlineKeyboardMarkup(inline_keyboard=rows + [
        [InlineKeyboardButton(text="🚚 Yetkazilmoqda", callback_data=f"deliv_{user_id}")],
        [InlineKeyboardButton(text="💵 Pulni oldim (Qarz yo'q)", callback_data=f"pay_full_{user_id}_{total_price}")],
        [InlineKeyboardButton(text="📝 To'liq qarzga berildi", callback_data=f"pay_debt_{user_id}_{total_price}")],
        [InlineKeyboardButton(text="⚡ Qisman to'landi", callback_data=f"pay_part_{user_id}_{total_price}")],
        [InlineKeyboardButton(text="🖨 Print qilish", callback_data="print_order")],
    ])

async def send_admin_order(user_id, admin_message, total_price, geo=None):
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(
                admin, admin_message, parse_mode="HTML",
                reply_markup=admin_order_keyboard(user_id, total_price, geo),
                disable_web_page_preview=True,
            )
            if geo:
                await bot.send_location(admin, geo["lat"], geo["lon"])
        except Exception as e:
            logging.warning(f"Adminga ({admin}) buyurtma yuborilmadi: {e}")

def fmt_money(n):
    return f"{int(n):,}".replace(",", " ")

def parse_order_text(text):
    name_match = re.search(r"Ism:\s*(.+)", text)
    phone_match = re.search(r"Telefon:\s*(.+)", text)
    total_match = re.search(r"Umumiy summa:\s*([\d\s]+)", text)
    
    items = []
    items_raw = []
    for m in re.finditer(r"•\s*(.+?):\s*(\d+)\s*ta\s*[×x]\s*(\d+)\s*=\s*(\d+)", text):
        title = re.sub(r"^\d+\.\s*", "", m.group(1).strip())
        items.append((title, int(m.group(2)), int(m.group(3)), int(m.group(4))))
        items_raw.append(f"{title} ({m.group(2)}ta)")
        
    return {
        "name": name_match.group(1).strip() if name_match else "-",
        "phone": phone_match.group(1).strip() if phone_match else "-",
        "items": items,
        "items_summary": ", ".join(items_raw),
        "total": int(re.sub(r"\s", "", total_match.group(1))) if total_match and total_match.group(1).strip() else sum(i[3] for i in items),
    }

# ---------- Генерация чеков ----------
def _load_font(size, bold=False):
    names = (
        ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"] if bold
        else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"]
    )
    dirs = ["", "/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/dejavu/",
            "/usr/share/fonts/truetype/liberation/", "/usr/share/fonts/liberation/",
            "C:/Windows/Fonts/"]
    for d in dirs:
        for n in names:
            try:
                return ImageFont.truetype(d + n, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

def build_receipt_image(order):
    W, M = 800, 40
    f_title, f_b, f_n, f_s = _load_font(44, True), _load_font(30, True), _load_font(28), _load_font(24)
    x_qty, x_price, x_sum = 420, 580, W - M

    rows = order["items"]
    H = 330 + len(rows) * 52 + 140
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def center(text, y, font):
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y), text, font=font, fill="black")

    def right(text, xr, y, font):
        w = d.textlength(text, font=font)
        d.text((xr - w, y), text, font=font, fill="black")

    def fit(text, font, maxw):
        while d.textlength(text, font=font) > maxw and len(text) > 1:
            text = text[:-2] + "…"
        return text

    y = 25
    center("YAYPAN MUZQAYMOQ", y, f_title); y += 62
    center(datetime.now().strftime("%d.%m.%Y %H:%M"), y, f_s); y += 50
    d.text((M, y), "Ism:", font=f_b, fill="black")
    d.text((M + 90, y), fit(order["name"], f_n, W - 2 * M - 90), font=f_n, fill="black"); y += 46
    d.text((M, y), "Telefon:", font=f_b, fill="black")
    d.text((M + 150, y), fit(order["phone"], f_n, W - 2 * M - 150), font=f_n, fill="black"); y += 60

    d.line((M, y, W - M, y), fill="black", width=3); y += 10
    d.text((M, y), "Mahsulot", font=f_b, fill="black")
    right("Soni", x_qty, y, f_b)
    right("Narxi", x_price, y, f_b)
    right("Summa", x_sum, y, f_b); y += 48
    d.line((M, y, W - M, y), fill="black", width=3); y += 10

    for title, qty, price, cost in rows:
        d.text((M, y), fit(title, f_n, 285), font=f_n, fill="black")
        right(str(qty), x_qty, y, f_n)
        right(fmt_money(price), x_price, y, f_n)
        right(fmt_money(cost), x_sum, y, f_n)
        y += 46
        d.line((M, y, W - M, y), fill="gray", width=1); y += 6

    y += 14
    d.line((M, y, W - M, y), fill="black", width=3); y += 16
    d.text((M, y), "JAMI:", font=f_title, fill="black")
    right(f"{fmt_money(order['total'])} so'm", W - M, y, f_title)

    buf = io.BytesIO()
    img.crop((0, 0, W, y + 80)).save(buf, format="PNG")
    return buf.getvalue()

def _img_tools(d):
    def center(text, y, font, W):
        w = d.textlength(text, font=font)
        d.text(((W - w) / 2, y), text, font=font, fill="black")
    def right(text, xr, y, font):
        w = d.textlength(text, font=font)
        d.text((xr - w, y), text, font=font, fill="black")
    def fit(text, font, maxw):
        while d.textlength(text, font=font) > maxw and len(text) > 1:
            text = text[:-2] + "…"
        return text
    def wrap(text, font, maxw, max_lines=2):
        words, lines, cur = str(text).split(), [], ""
        for w_ in words:
            t = (cur + " " + w_).strip()
            if d.textlength(t, font=font) <= maxw:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w_
        if cur:
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = fit(lines[-1] + "…", font, maxw)
        return lines or [""]
    return center, right, fit, wrap

def build_debts_list_image(rows, page, pages, grand_total, start=0):
    """Qarzdorlar ro'yxati: Ism, Manzil, Telefon, Qarz, Sana."""
    W, M = 900, 36
    f_t, f_b, f_n = _load_font(42, True), _load_font(30, True), _load_font(26)
    f_s = _load_font(22)
    img = Image.new("RGB", (W, 260 + len(rows) * 180), "white")
    d = ImageDraw.Draw(img)
    center, right, fit, wrap = _img_tools(d)

    y = 24
    center("QARZDORLAR RO'YXATI", y, f_t, W); y += 60
    center(f"{datetime.now().strftime('%d.%m.%Y %H:%M')}   |   {page + 1}/{pages}-sahifa", y, f_s, W); y += 44
    d.line((M, y, W - M, y), fill="black", width=3); y += 14

    for i, (uid, u) in enumerate(rows, start + 1):
        hist = u.get("history", [])
        first = hist[0].get("date", "-") if hist else "-"
        last = hist[-1].get("date", "-") if hist else "-"
        d.text((M, y), fit(f"{i}. {u.get('name', 'Noma`lum')}", f_b, 520), font=f_b, fill="black")
        right(f"{fmt_money(u.get('debt', 0))} so'm", W - M, y, f_b); y += 42
        d.text((M, y), fit("Manzil: " + str(get_user_location(uid)), f_n, W - 2 * M), font=f_n, fill="black"); y += 36
        d.text((M, y), "Telefon: " + str(u.get("phone", "-")), font=f_n, fill="black"); y += 36
        when = f"Qarz sanasi: {first}" if first == last else f"Qarz sanasi: {first}  (oxirgi: {last})"
        d.text((M, y), fit(when, f_n, W - 2 * M), font=f_n, fill="black"); y += 40
        d.line((M, y, W - M, y), fill="gray", width=1); y += 14

    y += 6
    d.line((M, y, W - M, y), fill="black", width=3); y += 14
    d.text((M, y), "JAMI QARZ:", font=f_t, fill="black")
    right(f"{fmt_money(grand_total)} so'm", W - M, y, f_t); y += 70

    buf = io.BytesIO()
    img.crop((0, 0, W, y)).save(buf, format="PNG")
    return buf.getvalue()

def build_debt_detail_image(uid, u):
    """Bitta mijoz: ma'lumotlari + qaysi kuni nima olgani + oxirida jami qarz."""
    W, M = 900, 36
    f_t, f_b, f_n = _load_font(42, True), _load_font(30, True), _load_font(26)
    f_s = _load_font(22)
    hist = u.get("history", [])
    shown = hist[-20:]
    img = Image.new("RGB", (W, 700 + len(shown) * 120), "white")
    d = ImageDraw.Draw(img)
    center, right, fit, wrap = _img_tools(d)

    y = 24
    center("MIJOZ QARZI", y, f_t, W); y += 66
    d.text((M, y), "Ism:", font=f_b, fill="black")
    d.text((M + 90, y), fit(str(u.get("name", "-")), f_n, W - 2 * M - 90), font=f_n, fill="black"); y += 44
    d.text((M, y), "Manzil:", font=f_b, fill="black")
    d.text((M + 140, y), fit(str(get_user_location(uid)), f_n, W - 2 * M - 140), font=f_n, fill="black"); y += 44
    d.text((M, y), "Telefon:", font=f_b, fill="black")
    d.text((M + 150, y), str(u.get("phone", "-")), font=f_n, fill="black"); y += 56

    d.line((M, y, W - M, y), fill="black", width=3); y += 8
    d.text((M, y), "Sana", font=f_b, fill="black")
    d.text((M + 270, y), "Mahsulot", font=f_b, fill="black")
    right("Summa", W - M, y, f_b); y += 44
    d.line((M, y, W - M, y), fill="black", width=3); y += 8

    if len(hist) > len(shown):
        d.text((M, y), f"... oldingi {len(hist) - len(shown)} ta yozuv ko'rsatilmadi", font=f_s, fill="gray"); y += 34
    for h in shown:
        lines = wrap(h.get("items", ""), f_n, W - 2 * M - 270 - 170)
        d.text((M, y), str(h.get("date", "")), font=f_s, fill="black")
        for ln in lines:
            d.text((M + 270, y), ln, font=f_n, fill="black"); y += 34
        right(fmt_money(h.get("amount", 0)), W - M, y - 34 * len(lines), f_n)
        y += 8
        d.line((M, y, W - M, y), fill="gray", width=1); y += 8

    paid = sum(int(h.get("amount", 0)) for h in hist) - int(u.get("debt", 0))
    if paid > 0:
        y += 6
        d.text((M, y), "To'langan / ayirilgan:", font=f_n, fill="black")
        right(f"- {fmt_money(paid)} so'm", W - M, y, f_n); y += 42

    y += 6
    d.line((M, y, W - M, y), fill="black", width=3); y += 14
    d.text((M, y), "JAMI QARZ:", font=f_t, fill="black")
    right(f"{fmt_money(u.get('debt', 0))} so'm", W - M, y, f_t); y += 70

    buf = io.BytesIO()
    img.crop((0, 0, W, y)).save(buf, format="PNG")
    return buf.getvalue()

@dp.callback_query(F.data == "print_order")
async def print_order(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Bu tugma faqat admin uchun!", show_alert=True)
        return
    order = parse_order_text(callback_query.message.text or callback_query.message.caption or "")
    if not order["items"]:
        await callback_query.answer("Buyurtma tarkibini o'qib bo'lmadi.", show_alert=True)
        return
    png = build_receipt_image(order)
    await callback_query.message.answer_photo(BufferedInputFile(png, filename="chek.png"))
    await callback_query.answer("Chek yuborildi ✅")

# ---------- Обязательная подписка ----------
verified_users = set()
_admin_warned = False

async def is_subscribed(user_id):
    global _admin_warned
    try:
        m = await bot.get_chat_member(CHANNEL, user_id)
        return m.status in ("member", "administrator", "creator") or (
            m.status == "restricted" and getattr(m, "is_member", False)
        )
    except Exception as e:
        logging.warning(f"Obunani tekshirib bo'lmadi: {e}")
        if not _admin_warned:
            _admin_warned = True
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️️ Obunani tekshirib bo'lmadi. Botni {CHANNEL} kanaliga ADMIN qilib qo'shing.\nXato: {e}"
                )
            except Exception:
                pass
        return True

def subscribe_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="check_sub")],
    ])

async def send_subscribe_prompt(message: types.Message):
    await send_sticker_safe(message.chat.id, "📢", "👋", "🙏")
    await message.answer(
        "Assalomu alaykum! 🍦\n\n"
        f"Botdan foydalanish uchun avval rasmiy kanalimizga obuna bo'ling:\n👉 {CHANNEL}\n\n"
        "Obuna bo'lgach, «✅ Obuna bo'ldim» tugmasini bosing.",
        reply_markup=subscribe_keyboard()
    )

class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is None or is_admin(user.id) or user.id in verified_users:
            return await handler(event, data)
        if isinstance(event, types.Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery) and (event.data or "").startswith("clk:"):
            return await handler(event, data)
        if isinstance(event, types.Message) and ((event.text or "").startswith("/soat") or user.id in _clock_wait):
            return await handler(event, data)
        if await is_subscribed(user.id):
            verified_users.add(user.id)
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery):
            await event.answer("Avval kanalga obuna bo'ling!", show_alert=True)
            if event.message:
                await send_subscribe_prompt(event.message)
        elif isinstance(event, types.Message):
            await send_subscribe_prompt(event)
        return

dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())

@dp.callback_query(F.data == "check_sub")
async def check_sub(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if not await is_subscribed(user_id):
        await callback_query.answer("❌ Siz hali obuna bo'lmagansiz. Avval kanalga obuna bo'ling.", show_alert=True)
        return
    verified_users.add(user_id)
    await callback_query.answer("✅ Obuna tasdiqlandi!")
    try:
        await callback_query.message.delete()
    except Exception:
        pass
    await send_sticker_safe(callback_query.message.chat.id, "🎉", "🥳", "👏")
    await begin_flow(callback_query.message, state, user_id)

# ---------- Анимационные стикеры ----------
STICKER_SETS = ["AnimatedEmojies", "animatedemoji", "HotCherry", "TheFoods", "BananaFun"]
_sticker_cache = {}

def _norm(e):
    return (e or "").replace("\ufe0f", "")

async def pick_sticker(*emojis):
    for set_name in STICKER_SETS:
        if set_name not in _sticker_cache:
            try:
                st = await bot.get_sticker_set(set_name)
                _sticker_cache[set_name] = [(_norm(x.emoji), x.file_id) for x in st.stickers]
            except Exception:
                _sticker_cache[set_name] = []
        for e in emojis:
            for emo, fid in _sticker_cache[set_name]:
                if emo == _norm(e):
                    return fid
    return None

async def send_sticker_safe(chat_id, *emojis):
    try:
        fid = await pick_sticker(*emojis)
        if fid:
            await bot.send_sticker(chat_id, fid)
    except Exception as e:
        logging.info(f"Stiker yuborilmadi: {e}")

# ---------- Hamma foydalanuvchilarga xabar yuborish (faqat admin) ----------
class BroadcastState(StatesGroup):
    waiting_for_message = State()

def broadcast_recipients():
    ids = set(subscribers.keys()) | set(saved_users.keys())
    for a in ADMIN_IDS:
        ids.discard(str(a))
    return sorted(ids)

@dp.message(Command("xabar"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer(
        f"📣 Xabar yuboriladigan odamlar: <b>{len(broadcast_recipients())}</b> ta\n\n"
        "Yubormoqchi bo'lgan xabaringizni yozing (matn, rasm, video, havola, hammasi bo'ladi).\n"
        "Bekor qilish uchun /start bosing.",
        parse_mode="HTML"
    )

@dp.message(BroadcastState.waiting_for_message, ~F.text.startswith("/"))
async def broadcast_preview(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(src_chat=message.chat.id, src_msg=message.message_id)
    await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    await message.answer(
        f"☝️ Mana shu xabar <b>{len(broadcast_recipients())}</b> ta odamga yuboriladi. Yuboraymi?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Yuborish", callback_data="bc_send"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bc_cancel"),
        ]])
    )

@dp.callback_query(F.data == "bc_cancel")
async def broadcast_cancel(callback_query: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        return
    await state.clear()
    await callback_query.message.edit_text("❌ Bekor qilindi.")
    await callback_query.answer()

@dp.callback_query(F.data == "bc_send")
async def broadcast_send(callback_query: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        return
    data = await state.get_data()
    src_chat, src_msg = data.get("src_chat"), data.get("src_msg")
    await state.clear()
    if not src_msg:
        await callback_query.answer("Xabar topilmadi, /xabar dan qayta boshlang.", show_alert=True)
        return
    await callback_query.answer()
    ids = broadcast_recipients()
    status = await callback_query.message.edit_text(f"⏳ Yuborilmoqda... 0/{len(ids)}")
    ok = blocked = failed = 0
    for i, uid in enumerate(ids, 1):
        try:
            try:
                await bot.copy_message(int(uid), src_chat, src_msg)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await bot.copy_message(int(uid), src_chat, src_msg)
            ok += 1
        except TelegramForbiddenError:
            blocked += 1   # foydalanuvchi botni bloklagan
        except (TelegramBadRequest, Exception) as e:
            failed += 1
            logging.info(f"Xabar yuborilmadi {uid}: {e}")
        if i % 25 == 0:
            try:
                await status.edit_text(f"⏳ Yuborilmoqda... {i}/{len(ids)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)   # Telegram limiti: soniyasiga ~30 ta
    await status.edit_text(
        f"✅ Tayyor!\n\n📨 Yetkazildi: {ok}\n🚫 Botni bloklaganlar: {blocked}\n⚠️ Boshqa xato: {failed}"
    )

# ---------- Muzqaymoq qo'shish va "bor / tugadi" holati (faqat admin) ----------
class ProductAdminState(StatesGroup):
    name = State()
    count = State()
    price = State()
    photo = State()

@dp.message(Command("yangi"))
async def cmd_new_product(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(ProductAdminState.name)
    await message.answer(
        "🍦 Yangi muzqaymoq nomini yozing (masalan: Pistali).\nBekor qilish uchun /start bosing.",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(ProductAdminState.name, F.text, ~F.text.startswith("/"))
async def new_product_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(p_name=message.text.strip()[:60])
    await state.set_state(ProductAdminState.count)
    await message.answer("📦 Bitta qutida nechta dona bor? Raqam yozing (masalan: 50):")

@dp.message(ProductAdminState.count, F.text, ~F.text.startswith("/"))
async def new_product_count(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    t = message.text.replace(" ", "")
    if not t.isdigit() or int(t) <= 0:
        await message.answer("Iltimos, faqat raqam kiriting (masalan: 50):")
        return
    await state.update_data(p_count=int(t))
    await state.set_state(ProductAdminState.price)
    await message.answer("💰 Bitta dona narxi necha so'm? (masalan: 1600):")

@dp.message(ProductAdminState.price, F.text, ~F.text.startswith("/"))
async def new_product_price(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    t = message.text.replace(" ", "")
    if not t.isdigit() or int(t) <= 0:
        await message.answer("Iltimos, faqat raqam kiriting (masalan: 1600):")
        return
    await state.update_data(p_price=int(t))
    await state.set_state(ProductAdminState.photo)
    await message.answer(
        "📷 Muzqaymoq rasmini yuboring (yoki rasm havolasini yozing).\nRasm kerak bo'lmasa «⏭ O'tkazib yuborish» ni bosing.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏭ O'tkazib yuborish")]], resize_keyboard=True)
    )

async def _finish_new_product(message: types.Message, state: FSMContext, photo):
    data = await state.get_data()
    key = next_custom_key()
    prod = {"name": data["p_name"], "count_in_box": data["p_count"], "price": data["p_price"], "photo": photo}
    products_state["custom"][key] = prod
    apply_products_state()
    save_products()
    await state.clear()
    await message.answer(
        f"✅ <b>{html.escape(prod['name'])}</b> qo'shildi!\n"
        f"📦 Qutida: {prod['count_in_box']} ta\n💰 Dona narxi: {prod['price']} so'm\n\n"
        "Mijozlar /start bosganda katalogda ko'radi.\n"
        "Bor/tugadi holatini o'zgartirish: /holat",
        parse_mode="HTML", reply_markup=main_menu_keyboard
    )

@dp.message(ProductAdminState.photo, F.photo)
async def new_product_photo(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await _finish_new_product(message, state, message.photo[-1].file_id)

@dp.message(ProductAdminState.photo, F.text, ~F.text.startswith("/"))
async def new_product_photo_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    t = message.text.strip()
    if t.startswith("⏭"):
        await _finish_new_product(message, state, None)
    elif t.startswith("http"):
        await _finish_new_product(message, state, t)
    else:
        await message.answer("Rasm yuboring yoki «⏭ O'tkazib yuborish» ni bosing.")

def stock_panel_text():
    return (
        "📦 <b>Muzqaymoqlar holati</b>\n"
        "✅ — bor, ❌ — tugagan. Bosib holatini o'zgartiring.\n"
        "Tugagan muzqaymoq «bor» qilinsa, uni so'raganlarga avtomatik xabar ketadi (🔔 — kutayotganlar soni)."
    )

def stock_keyboard():
    rows = []
    for key, prod in PRODUCTS.items():
        if is_in_stock(key):
            label = f"✅ {prod['name']}"
        else:
            n = len(products_state["waiting"].get(key, []))
            label = f"❌ {prod['name']}" + (f" (🔔 {n})" if n else "")
        rows.append([InlineKeyboardButton(text=label, callback_data=f"stk_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(Command("holat"))
async def cmd_stock(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(stock_panel_text(), parse_mode="HTML", reply_markup=stock_keyboard())

@dp.callback_query(F.data.startswith("stk_"))
async def toggle_stock(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    key = callback_query.data.split("_", 1)[1]
    prod = PRODUCTS.get(key)
    if not prod:
        await callback_query.answer("Muzqaymoq topilmadi.", show_alert=True)
        return
    users = []
    if is_in_stock(key):
        products_state["out"].append(key)
        note = f"❌ {prod['name']} — tugadi deb belgilandi"
    else:
        products_state["out"].remove(key)
        users = products_state["waiting"].pop(key, [])
        note = f"✅ {prod['name']} — mavjud deb belgilandi"
    save_products()
    await callback_query.answer(note)
    try:
        await callback_query.message.edit_reply_markup(reply_markup=stock_keyboard())
    except Exception:
        pass
    if users:
        sent = await notify_waiting(key, users)
        await callback_query.message.answer(
            f"📨 «{prod['name']}» mavjud ekani haqida {sent}/{len(users)} ta odamga xabar yuborildi."
        )

# ---------- Muzqaymoqni tahrirlash va o'chirish (faqat admin) ----------
class ProductEditState(StatesGroup):
    value = State()

EDIT_FIELDS = {  # callback nomi: (mahsulotdagi kalit, so'rov matni)
    "name": ("name", "✏️ Yangi nomini yozing:"),
    "price": ("price", "✏️ Yangi dona narxini yozing (so'm, masalan 1600):"),
    "count": ("count_in_box", "✏️ Qutida nechta dona borligini yozing (masalan 50):"),
    "photo": ("photo", "🖼 Yangi rasmni yuboring (yoki rasm havolasini yozing):"),
}

def product_card_text(key):
    p = PRODUCTS[key]
    return (
        f"🍦 <b>{html.escape(p['name'])}</b>\n"
        f"📦 Qutida: {p['count_in_box']} ta\n"
        f"💰 Dona narxi: {p['price']} so'm\n"
        f"🖼 Rasm: {'bor' if p.get('photo') else 'yoq'}\n"
        f"{'✅ Mavjud' if is_in_stock(key) else '❌ Tugagan'}"
    )

def edit_menu_keyboard(key):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Nomi", callback_data=f"tf_name_{key}"),
         InlineKeyboardButton(text="💰 Narxi", callback_data=f"tf_price_{key}")],
        [InlineKeyboardButton(text="📦 Qutidagi soni", callback_data=f"tf_count_{key}"),
         InlineKeyboardButton(text="🖼 Rasmi", callback_data=f"tf_photo_{key}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"td_{key}")],
        [InlineKeyboardButton(text="🔙 Ro'yxatga qaytish", callback_data="tback")],
    ])

def edit_list_keyboard():
    rows = [[InlineKeyboardButton(text=p['name'], callback_data=f"te_{k}")] for k, p in PRODUCTS.items()]
    gone = [k for k in products_state["deleted"] if k in BASE_PRODUCTS]
    if gone:
        rows.append([InlineKeyboardButton(text=f"♻️ O'chirilganlar ({len(gone)})", callback_data="tdl")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

EDIT_LIST_TEXT = "✏️ Qaysi muzqaymoqni tahrirlash yoki o'chirmoqchisiz?"

async def _edit_msg(callback_query, text, kb):
    try:
        await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass

@dp.message(Command("tahrir"))
async def cmd_edit_products(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(EDIT_LIST_TEXT, reply_markup=edit_list_keyboard())

@dp.callback_query(F.data == "tback")
async def edit_back(callback_query: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    await state.clear()
    await callback_query.answer()
    await _edit_msg(callback_query, EDIT_LIST_TEXT, edit_list_keyboard())

@dp.callback_query(F.data.startswith("te_"))
async def edit_open(callback_query: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    key = callback_query.data.split("_", 1)[1]
    if key not in PRODUCTS:
        await callback_query.answer("Muzqaymoq topilmadi.", show_alert=True)
        return
    await state.clear()
    await callback_query.answer()
    await _edit_msg(callback_query, product_card_text(key), edit_menu_keyboard(key))

@dp.callback_query(F.data.startswith("tf_"))
async def edit_field_ask(callback_query: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    _, field, key = callback_query.data.split("_", 2)
    if key not in PRODUCTS or field not in EDIT_FIELDS:
        await callback_query.answer("Muzqaymoq topilmadi.", show_alert=True)
        return
    await state.clear()
    await state.set_state(ProductEditState.value)
    await state.update_data(edit_key=key, edit_field=field)
    await callback_query.answer()
    await callback_query.message.answer(EDIT_FIELDS[field][1] + "\n(Bekor qilish: /tahrir)")

async def _apply_edit(message: types.Message, state: FSMContext, value):
    data = await state.get_data()
    key, field = data.get("edit_key"), data.get("edit_field")
    if key not in PRODUCTS or field not in EDIT_FIELDS:
        await state.clear()
        await message.answer("Muzqaymoq topilmadi. /tahrir dan qayta boshlang.")
        return
    products_state["edits"].setdefault(key, {})[EDIT_FIELDS[field][0]] = value
    apply_products_state()
    save_products()
    await state.clear()
    await message.answer("✅ Saqlandi!\n\n" + product_card_text(key), parse_mode="HTML", reply_markup=edit_menu_keyboard(key))

@dp.message(ProductEditState.value, F.photo)
async def edit_value_photo(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if (await state.get_data()).get("edit_field") != "photo":
        await message.answer("Bu yerga rasm emas, matn yoki raqam yuboring.")
        return
    await _apply_edit(message, state, message.photo[-1].file_id)

@dp.message(ProductEditState.value, F.text, ~F.text.startswith("/"))
async def edit_value_text(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    field = (await state.get_data()).get("edit_field")
    t = message.text.strip()
    if field == "name":
        if not t:
            await message.answer("Nom bo'sh bo'lmasin:")
            return
        await _apply_edit(message, state, t[:60])
    elif field in ("price", "count"):
        t = t.replace(" ", "")
        if not t.isdigit() or int(t) <= 0:
            await message.answer("Iltimos, 0 dan katta raqam kiriting:")
            return
        await _apply_edit(message, state, int(t))
    elif field == "photo":
        if not t.startswith("http"):
            await message.answer("Rasm yuboring yoki https:// bilan boshlanadigan havola yozing:")
            return
        await _apply_edit(message, state, t)

@dp.callback_query(F.data.startswith("td_"))
async def edit_delete_ask(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    key = callback_query.data.split("_", 1)[1]
    if key not in PRODUCTS:
        await callback_query.answer("Muzqaymoq topilmadi.", show_alert=True)
        return
    await callback_query.answer()
    await _edit_msg(
        callback_query,
        f"🗑 <b>{html.escape(PRODUCTS[key]['name'])}</b> o'chirilsinmi?\nU katalogdan va Mini App'dan olib tashlanadi.",
        InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Ha, o'chirish", callback_data=f"ty_{key}"),
            InlineKeyboardButton(text="❌ Yo'q", callback_data=f"te_{key}"),
        ]])
    )

@dp.callback_query(F.data.startswith("ty_"))
async def edit_delete_do(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    key = callback_query.data.split("_", 1)[1]
    if key not in PRODUCTS:
        await callback_query.answer("Muzqaymoq topilmadi.", show_alert=True)
        return
    name = PRODUCTS[key]["name"]
    if key in products_state["custom"]:
        del products_state["custom"][key]          # admin qo'shgani: butunlay o'chadi
        products_state["edits"].pop(key, None)
    elif key not in products_state["deleted"]:
        products_state["deleted"].append(key)      # asl ro'yxatdagisi: yashiriladi (qaytarish mumkin)
    if key in products_state["out"]:
        products_state["out"].remove(key)
    products_state["waiting"].pop(key, None)
    apply_products_state()
    save_products()
    await callback_query.answer("O'chirildi 🗑")
    await _edit_msg(callback_query, f"🗑 <b>{html.escape(name)}</b> o'chirildi.\n\n" + EDIT_LIST_TEXT, edit_list_keyboard())

@dp.callback_query(F.data == "tdl")
async def edit_deleted_list(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    rows = [[InlineKeyboardButton(text=f"♻️ {BASE_PRODUCTS[k]['name']}", callback_data=f"tr_{k}")]
            for k in products_state["deleted"] if k in BASE_PRODUCTS]
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="tback")])
    await callback_query.answer()
    await _edit_msg(callback_query, "♻️ Qaytarmoqchi bo'lgan muzqaymoqni tanlang:", InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("tr_"))
async def edit_restore(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer()
        return
    key = callback_query.data.split("_", 1)[1]
    if key in products_state["deleted"]:
        products_state["deleted"].remove(key)
        apply_products_state()
        save_products()
    await callback_query.answer("Qaytarildi ♻️")
    await _edit_msg(callback_query, EDIT_LIST_TEXT, edit_list_keyboard())

# ---------- /start и сценарий ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    add_subscriber(message.from_user)
    if is_admin(user_id):
        await set_admin_menu(user_id)
    if not is_admin(user_id) and user_id not in verified_users:
        if not await is_subscribed(user_id):
            await message.answer("👋", reply_markup=types.ReplyKeyboardRemove())
            await send_subscribe_prompt(message)
            return
        verified_users.add(user_id)
    await begin_flow(message, state, user_id)

async def begin_flow(message: types.Message, state: FSMContext, user_id: int):
    user_carts[user_id] = {}
    await state.clear()

    saved = get_saved_user(user_id)
    if saved:
        await state.update_data(name=saved["name"], location=saved["location"], phone=saved["phone"], geo=saved.get("geo"))
        await message.answer(
            f"Assalomu alaykum, <b>{html.escape(saved['name'])}</b>! 🍦\n"
            f"Buyurtma shu ma'lumotlar bilan yuboriladi:\n\n"
            f"{info_text(saved['name'], saved['location'], saved['phone'], saved.get('geo'))}\n\n"
            f"O'zgartirish uchun «✏️ Ma'lumotlarni o'zgartirish» tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard
        )
        await show_catalog(message)
        await state.set_state(OrderState.shopping)
        return

    await message.answer(
        "Assalomu alaykum! Muzqaymoq buyurtma berish botiga xush kelibsiz.\n"
        "Iltimos, Ism va Familiyangizni kiriting:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(OrderState.waiting_for_name)

@dp.message(F.text == "✏️ Ma'lumotlarni o'zgartirish")
async def change_info(message: types.Message, state: FSMContext):
    delete_saved_user(message.from_user.id)
    await state.clear()
    user_carts.setdefault(message.from_user.id, {})
    await message.answer("Yangi Ism va Familiyangizni kiriting:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(OrderState.waiting_for_name)

@dp.message(F.text == "📄 Mening qarzdorligim")
async def my_debt_handler(message: types.Message):
    debt_text = get_formatted_debt_text(message.from_user.id)
    await message.answer(debt_text, parse_mode="HTML")

@dp.message(OrderState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Endi manzilingizni (qaysi joyda ekaningizni) yozib yuboring:")
    await state.set_state(OrderState.waiting_for_location)

@dp.message(OrderState.waiting_for_location)
async def process_location(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Iltimos, manzilingizni matn ko'rinishida yozib yuboring:")
        return
    await state.update_data(location=message.text)
    geo_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Lokatsiyani belgilash", web_app=WebAppInfo(url=GEO_PICKER_URL))],
            [KeyboardButton(text="📡 Hozirgi joylashuvim", request_location=True)],
            [KeyboardButton(text="⏭ O'tkazib yuborish")],
        ],
        resize_keyboard=True
    )
    await message.answer(
        "📍 Pastdagi «Lokatsiyani belgilash» tugmasini bosing. Xarita Yaypandan ochiladi, "
        "uni surib do'koningiz turgan joyni belgilang va «Tasdiqlash» ni bosing.\n\n"
        "Yoki «📡 Hozirgi joylashuvim» ni bosing. Boshqa joyni tanlash uchun 📎 (qisqich) → «Lokatsiya» "
        "orqali xaritadan nuqtani tanlab yuborishingiz ham mumkin.",
        reply_markup=geo_kb
    )
    await state.set_state(OrderState.waiting_for_geo)

async def _ask_phone(message: types.Message, state: FSMContext):
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Telefon raqamingizni yuboring:", reply_markup=keyboard)
    await state.set_state(OrderState.waiting_for_phone)

@dp.message(OrderState.waiting_for_geo, F.web_app_data)
async def process_geo_picker(message: types.Message, state: FSMContext):
    try:
        d = json.loads(message.web_app_data.data)
        lat, lon = float(d["lat"]), float(d["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except Exception:
        await message.answer("❌ Lokatsiya olinmadi, qaytadan «📍 Lokatsiyani belgilash» tugmasini bosing.")
        return
    await state.update_data(geo={"lat": lat, "lon": lon})
    await message.answer("✅ Lokatsiya belgilandi.", reply_markup=types.ReplyKeyboardRemove())
    await _ask_phone(message, state)

@dp.message(OrderState.waiting_for_geo)
async def process_geo(message: types.Message, state: FSMContext):
    loc = message.location or (message.venue.location if message.venue else None)
    if loc:
        if message.location and getattr(message.location, "live_period", None):
            await message.answer("Iltimos, jonli (live) lokatsiya emas, xaritadan do'kon joylashgan nuqtani tanlab yuboring.")
            return
        await state.update_data(geo={"lat": loc.latitude, "lon": loc.longitude})
    elif message.text and message.text.startswith("⏭"):
        await state.update_data(geo=None)
    else:
        await message.answer(
            "Iltimos, «📍 Lokatsiyani belgilash» tugmasini bosib xaritadan joyni belgilang "
            "yoki «⏭ O'tkazib yuborish»ni tanlang."
        )
        return
    await _ask_phone(message, state)

@dp.message(OrderState.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)
    data = await state.get_data()

    await message.answer("Rahmat! ✅", reply_markup=types.ReplyKeyboardRemove())
    await message.answer(
        f"{info_text(data.get('name'), data.get('location'), phone, data.get('geo'))}\n\n"
        f"💾 Shu ma'lumotlar saqlansinmi?\n"
        f"Saqlansa, keyingi safar qayta so'ralmaydi va buyurtmalar doim shu nomdan boradi.",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=save_keyboard
    )
    await state.set_state(OrderState.waiting_for_save)

@dp.callback_query(F.data.in_({"save_yes", "save_no"}), OrderState.waiting_for_save)
async def process_save(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback_query.from_user.id

    if callback_query.data == "save_yes":
        set_saved_user(user_id, data.get("name"), data.get("location"), data.get("phone"), data.get("geo"))
        result = "💾 Ma'lumotlaringiz saqlandi!"
    else:
        result = "Ma'lumotlar saqlanmadi (faqat shu buyurtma uchun ishlatiladi)."

    await callback_query.message.edit_reply_markup(reply_markup=None)
    await callback_query.answer()
    await callback_query.message.answer(
        f"{result}\n\nQuyidagi mahsulotlar ro'yxatidan tanlang:",
        reply_markup=main_menu_keyboard
    )
    await show_catalog(callback_query.message)
    await state.set_state(OrderState.shopping)

# ---------- Обработка данных из WebApp (Mini App) ----------
@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message):
    user_id = message.from_user.id
    raw_data = message.web_app_data.data

    try:
        data_json = json.loads(raw_data)
    except Exception:
        data_json = {}

    # Faqat xaritadan tanlangan nuqta keldi (buyurtma emas), lekin bot holati yo'qolgan (masalan, qayta ishga tushgan)
    if (isinstance(data_json, dict) and "lat" in data_json and "lon" in data_json
            and not data_json.get("items") and "totalPrice" not in data_json):
        await message.answer(
            "⚠️ Lokatsiya qabul qilinmadi, chunki jarayon uzilib qoldi. Iltimos, /start ni bosib qaytadan boshlang.",
            reply_markup=types.ReplyKeyboardRemove()
        )
        return

    user_saved_info = saved_users.get(str(user_id)) or {}
    user_name = data_json.get("name") or user_saved_info.get("name") or message.from_user.full_name
    user_phone = data_json.get("phone") or user_saved_info.get("phone") or "-"
    user_loc = data_json.get("location") or user_saved_info.get("location") or "-"
    geo = user_saved_info.get("geo")
    try:
        if data_json.get("lat") is not None and data_json.get("lon") is not None:
            geo = {"lat": float(data_json["lat"]), "lon": float(data_json["lon"])}
    except Exception:
        pass

    items_list = data_json.get("items", [])

    # Mini App'da tanlangan muzqaymoq tugagan bo'lsa (nomi bo'yicha tekshiramiz), buyurtma qabul qilinmaydi
    if isinstance(items_list, list):
        gone = {}
        for item in items_list:
            if not isinstance(item, dict):
                continue
            t = re.sub(r"^\s*\d+\s*[.)\-]\s*", "", str(item.get("name", ""))).strip().lower()
            for k, p in PRODUCTS.items():
                if p["name"].strip().lower() == t and not is_in_stock(k):
                    gone[k] = p["name"]
        if gone:
            for k in gone:
                add_waiting(k, user_id)
            await message.answer(
                "😔 Quyidagi muzqaymoq(lar) hozircha tugagan: <b>" + html.escape(", ".join(gone.values())) + "</b>\n"
                "Ularsiz buyurtmani qaytadan yuboring. Agar yetib kelsa, sizga xabar yuboramiz 🔔",
                parse_mode="HTML", reply_markup=main_menu_keyboard
            )
            return

    total_price = 0
    order_details = ""
    items_summary = []

    if isinstance(items_list, list) and items_list:
        for idx, item in enumerate(items_list, 1):
            title = str(item.get("name", "Mahsulot"))
            title = re.sub(r"^\s*\d+\s*[.)\-]\s*", "", title).strip() or "Mahsulot"  # "17. Banan" -> "Banan"
            qty = int(item.get("count", item.get("quantity", 1)))
            price = int(item.get("price", 0))
            cost = qty * price
            total_price += cost
            order_details += f"• {title}: {qty} ta × {price} = {cost} so'm\n"
            items_summary.append(f"{title} ({qty}ta)")
    else:
        # Текстовый резерв
        order_details = str(raw_data)
        total_price = int(data_json.get("totalPrice", 0))

    if not total_price and "totalPrice" in data_json:
        total_price = int(data_json.get("totalPrice", 0))

    new_order = {
        "id": len(orders_db) + 1,
        "clientName": user_name,
        "phone": user_phone,
        "items": ", ".join(items_summary) if items_summary else order_details,
        "totalPrice": total_price,
        "userId": user_id,
        "location": user_loc,
        "geo": geo,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "status": "Yangi"
    }
    orders_db.append(new_order)
    save_json(ORDERS_FILE, orders_db)

    admin_message = (
        f"📥 <b>Yangi buyurtma keldi! (Mini App)</b>\n\n"
        f"{info_text(user_name, user_loc, user_phone, geo)}\n\n{debt_history_text(user_id)}\n\n"
        f"🛍 <b>Buyurtma tarkibi:</b>\n{order_details}\n"
        f"💳 <b>Umumiy summa:</b> {total_price} so'm"
    )
    await send_admin_order(user_id, admin_message, total_price, geo)

    await message.answer(
        "Buyurtmangiz Mini App orqali muvaffaqiyatli qabul qilindi! ✅ Tez orada siz bilan bog'lanishadi.",
        reply_markup=main_menu_keyboard
    )
    await send_sticker_safe(message.chat.id, "🍦", "❤", "👍", "✅")

# ---------- Каталог ----------
async def show_catalog(message: types.Message):
    for key, prod in list(PRODUCTS.items()):
        box_total = prod['count_in_box'] * prod['price']
        text = (
            f"<b>{prod['name']}</b>\n"
            f"📦 Qutida: {prod['count_in_box']} ta\n"
            f"💰 Dona narxi: {prod['price']} so'm\n"
            f"💵 Jami quti narxi: {box_total} so'm"
        )
        if not is_in_stock(key):
            text += "\n\n❌ <b>Hozircha tugagan.</b> Tanlasangiz, yetib kelganda xabar beramiz 🔔"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Karobkada olish", callback_data=f"box_{key}"),
            InlineKeyboardButton(text="🔢 Dona tanlash", callback_data=f"dona_{key}")
        ]])
        try:
            if not prod.get('photo'):
                raise ValueError("rasm yo'q")
            await message.answer_photo(photo=prod['photo'], caption=text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data.startswith('box_'), OrderState.shopping)
async def add_box_to_cart(callback_query: types.CallbackQuery):
    product_key = callback_query.data.split('_', 1)[1]
    user_id = callback_query.from_user.id
    if product_key not in PRODUCTS:
        await callback_query.answer("Bu muzqaymoq endi sotuvda yo'q.", show_alert=True)
        return
    if not is_in_stock(product_key):
        await reply_out_of_stock(callback_query, product_key)
        return
    user_carts.setdefault(user_id, {})
    add_count = PRODUCTS[product_key]['count_in_box']
    user_carts[user_id][product_key] = user_carts[user_id].get(product_key, 0) + add_count
    await callback_query.answer(f"1 karobka ({add_count} ta) savatga qo'shildi! ✅")

@dp.callback_query(F.data.startswith('dona_'), OrderState.shopping)
async def ask_custom_dona(callback_query: types.CallbackQuery, state: FSMContext):
    product_key = callback_query.data.split('_', 1)[1]
    if product_key not in PRODUCTS:
        await callback_query.answer("Bu muzqaymoq endi sotuvda yo'q.", show_alert=True)
        return
    if not is_in_stock(product_key):
        await reply_out_of_stock(callback_query, product_key)
        return
    prod = PRODUCTS[product_key]
    await state.update_data(selected_product=product_key)
    await callback_query.message.answer(
        f"<b>{prod['name']}</b> uchun nechta dona olishni xohlaysiz? Raqamni kiriting (masalan: 70):",
        parse_mode="HTML"
    )
    await state.set_state(OrderState.waiting_for_custom_count)
    await callback_query.answer()

@dp.message(OrderState.waiting_for_custom_count)
async def process_custom_dona(message: types.Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("Iltimos, faqat raqam kiriting (masalan: 50):")
        return
    count = int(message.text)
    data = await state.get_data()
    product_key = data.get('selected_product')
    user_id = message.from_user.id
    if product_key not in PRODUCTS:
        await message.answer("Bu muzqaymoq endi sotuvda yo'q.", reply_markup=main_menu_keyboard)
        await state.set_state(OrderState.shopping)
        return
    if not is_in_stock(product_key):
        add_waiting(product_key, user_id)
        await message.answer(out_of_stock_text(product_key), parse_mode="HTML", reply_markup=main_menu_keyboard)
        await state.set_state(OrderState.shopping)
        return
    user_carts.setdefault(user_id, {})
    user_carts[user_id][product_key] = user_carts[user_id].get(product_key, 0) + count
    await message.answer(f"Savatga {count} dona qo'shildi! ✅", reply_markup=main_menu_keyboard)
    await state.set_state(OrderState.shopping)

# ---------- Корзина ----------
def build_cart(cart):
    text = "🛒 <b>Sizning savatingiz:</b>\n\n"
    total_price = 0
    inline_kb = []
    for prod_key, total_items in cart.items():
        if prod_key in PRODUCTS:
            prod = PRODUCTS[prod_key]
            cost = total_items * prod['price']
            total_price += cost
            text += f"• {prod['name']}: {total_items} ta dona - {cost} so'm\n"
            inline_kb.append([InlineKeyboardButton(text=f"❌ O'chirish: {prod['name']}", callback_data=f"remove_{prod_key}")])
    text += f"\n💳 <b>Umumiy summa:</b> {total_price} so'm"
    return text, InlineKeyboardMarkup(inline_keyboard=inline_kb)

@dp.message(F.text == "🛒 Savatni ko'rish", OrderState.shopping)
async def show_cart(message: types.Message):
    cart = user_carts.get(message.from_user.id, {})
    if not cart:
        await message.answer("Savatingiz hozircha bo'sh. 📭", reply_markup=main_menu_keyboard)
        return
    text, kb = build_cart(cart)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith('remove_'), OrderState.shopping)
async def remove_from_cart(callback_query: types.CallbackQuery):
    product_key = callback_query.data.split('_', 1)[1]
    user_id = callback_query.from_user.id
    if user_id in user_carts and product_key in user_carts[user_id]:
        del user_carts[user_id][product_key]
        await callback_query.answer("Savatdan olib tashlandi! 🗑")
        cart = user_carts[user_id]
        if not cart:
            await callback_query.message.edit_text("Savatingiz bo'shadi. 📭")
        else:
            text, kb = build_cart(cart)
            await callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

# ---------- Завершение заказа из Telegram ----------
@dp.message(F.text == "✅ Buyurtmani yakunlash", OrderState.shopping)
async def finish_order(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    cart = user_carts.get(user_id, {})
    if not cart:
        await message.answer("Savatingiz bo'sh! Avval mahsulot tanlang.", reply_markup=main_menu_keyboard)
        return

    # Savatga qo'shilgandan keyin tugab qolgan muzqaymoqlarni olib tashlaymiz
    removed = [k for k in list(cart) if k not in PRODUCTS]
    if removed:
        for k in removed:
            cart.pop(k, None)
        await message.answer(
            "😔 Savatingizdagi ba'zi muzqaymoqlar endi sotuvda yo'q va savatdan olib tashlandi.\n"
            "Savatni tekshirib, buyurtmani qayta yakunlang.",
            reply_markup=main_menu_keyboard
        )
        return
    gone = [k for k in list(cart) if k in PRODUCTS and not is_in_stock(k)]
    if gone:
        for k in gone:
            cart.pop(k, None)
            add_waiting(k, user_id)
        names = ", ".join(html.escape(PRODUCTS[k]['name']) for k in gone)
        await message.answer(
            f"😔 Savatingizdagi quyidagi muzqaymoq(lar) tugab qolibdi va savatdan olib tashlandi: <b>{names}</b>\n"
            "Agar yetib kelsa, sizga xabar yuboramiz 🔔\n\n"
            "Savatni tekshirib, buyurtmani qayta yakunlang.",
            parse_mode="HTML", reply_markup=main_menu_keyboard
        )
        return

    data = await state.get_data()
    total_price = 0
    order_details = ""
    items_summary = []

    for prod_key, total_items in cart.items():
        if prod_key in PRODUCTS:
            prod = PRODUCTS[prod_key]
            cost = total_items * prod['price']
            total_price += cost
            order_details += f"• {prod['name']}: {total_items} ta × {prod['price']} = {cost} so'm\n"
            items_summary.append(f"{prod['name']} ({total_items}ta)")

    user_saved_info = saved_users.get(str(user_id)) or {}
    user_name = data.get('name') or user_saved_info.get('name') or "Noma’lum"
    user_phone = data.get('phone') or user_saved_info.get('phone') or "-"
    geo = data.get('geo') or user_saved_info.get('geo')

    # Сохранение заказа для API
    new_order = {
        "id": len(orders_db) + 1,
        "clientName": user_name,
        "phone": user_phone,
        "items": ", ".join(items_summary),
        "totalPrice": total_price,
        "userId": user_id,
        "location": data.get('location') or user_saved_info.get('location') or "-",
        "geo": geo,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "status": "Yangi"
    }
    orders_db.append(new_order)
    save_json(ORDERS_FILE, orders_db)

    admin_message = (
        f"📥 <b>Yangi buyurtma keldi! (bot)</b>\n\n"
        f"{info_text(user_name, data.get('location') or user_saved_info.get('location') or '-', user_phone, geo)}\n\n{debt_history_text(user_id)}\n\n"
        f"🛍 <b>Buyurtma tarkibi:</b>\n{order_details}\n"
        f"💳 <b>Umumiy summa:</b> {total_price} so'm"
    )
    await send_admin_order(user_id, admin_message, total_price, geo)

    user_carts[user_id] = {}
    await message.answer(
        "Buyurtmangiz muvaffaqiyatli yuborildi! ✅ Tez orada siz bilan bog'lanishadi.\n\n"
        "Yangi buyurtma berish uchun /start buyrug'ini bosing.",
        reply_markup=main_menu_keyboard
    )
    await send_sticker_safe(message.chat.id, "🍦", "❤", "👍", "✅")
    await state.clear()

# ---------- Админ Панель Должников ----------
DEBTS_PAGE_SIZE = 8

def _active_debtors():
    items = [(uid, u) for uid, u in debts_db.items() if u.get("debt", 0) > 0]
    items.sort(key=lambda x: x[1].get("debt", 0), reverse=True)
    return items

def debts_page_content(page):
    items = _active_debtors()
    if not items:
        return None
    pages = max(1, (len(items) + DEBTS_PAGE_SIZE - 1) // DEBTS_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * DEBTS_PAGE_SIZE
    chunk = items[start:start + DEBTS_PAGE_SIZE]
    grand = sum(u.get("debt", 0) for _, u in items)
    png = build_debts_list_image(chunk, page, pages, grand, start=start)
    rows = [[InlineKeyboardButton(text=f"👤 {u.get('name', '?')} — {u.get('debt', 0):,} so'm", callback_data=f"manage_debt_{uid}")]
            for uid, u in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Oldingi", callback_data=f"debts_page_{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="Keyingi ▶️", callback_data=f"debts_page_{page + 1}"))
    if nav:
        rows.append(nav)
    caption = f"💳 <b>Jami qarz: {grand:,} so'm</b>\n👥 Qarzdorlar: {len(items)} ta"
    return png, caption, InlineKeyboardMarkup(inline_keyboard=rows)

async def swap_photo(callback_query, png, caption, kb):
    """Yangi xabar ochmasdan, bor xabardagi rasmni almashtiradi."""
    try:
        media = InputMediaPhoto(media=BufferedInputFile(png, filename="qarz.png"), caption=caption, parse_mode="HTML")
        await callback_query.message.edit_media(media=media, reply_markup=kb)
    except Exception:
        try:
            await callback_query.message.delete()
        except Exception:
            pass
        await callback_query.message.answer_photo(
            BufferedInputFile(png, filename="qarz.png"), caption=caption, parse_mode="HTML", reply_markup=kb
        )

@dp.message(Command("debts"))
async def admin_debts_list(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    content = debts_page_content(0)
    if not content:
        await message.answer("Qarzdorlar ro'yxati bo'sh. ✅")
        return
    png, caption, kb = content
    await message.answer_photo(BufferedInputFile(png, filename="qarzdorlar.png"), caption=caption, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith('debts_page_'))
async def debts_page_handler(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    content = debts_page_content(int(callback_query.data.split('_')[2]))
    await callback_query.answer()
    if not content:
        await callback_query.message.answer("Qarzdorlar ro'yxati bo'sh. ✅")
        return
    await swap_photo(callback_query, *content)

@dp.callback_query(F.data.startswith('manage_debt_'))
async def manage_user_debt(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    uid = callback_query.data.split('_')[2]
    u = debts_db.get(uid)
    if not u:
        await callback_query.answer("Mijoz topilmadi.", show_alert=True)
        return

    rows = [[InlineKeyboardButton(text="➕ Qarz qo'shish", callback_data=f"add_debt_{uid}"),
             InlineKeyboardButton(text="➖ Qarzni ayirish / to'lash", callback_data=f"sub_debt_{uid}")]]
    geo = get_user_geo(uid)
    if geo:
        rows.append([InlineKeyboardButton(text="🗺 Google Mapda ko'rish", url=maps_link(geo))])
    rows.append([InlineKeyboardButton(text="🔙 Ro'yxatga qaytish", callback_data="back_to_debts")])

    caption = (
        f"👤 <b>{html.escape(str(u.get('name', '')))}</b>\n"
        f"📞 {html.escape(str(u.get('phone', '-')))}\n"
        f"💳 <b>Jami qarz: {u.get('debt', 0):,} so'm</b>"
    )
    await callback_query.answer()
    await swap_photo(callback_query, build_debt_detail_image(uid, u), caption, InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data == "back_to_debts")
async def back_to_debts_handler(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    await callback_query.answer()
    content = debts_page_content(0)
    if not content:
        await callback_query.message.answer("Qarzdorlar ro'yxati bo'sh. ✅")
        return
    await swap_photo(callback_query, *content)

@dp.callback_query(F.data.startswith('add_debt_'))
async def start_add_debt(callback_query: types.CallbackQuery, state: FSMContext):
    uid = callback_query.data.split('_')[2]
    await state.update_data(target_uid=uid)
    await callback_query.message.answer("Qancha qarz qo'shmoqchisiz? Summani kiriting:")
    await state.set_state(OrderState.waiting_for_admin_debt_add)
    await callback_query.answer()

@dp.message(OrderState.waiting_for_admin_debt_add)
async def process_admin_add_debt(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id) or not message.text.isdigit():
        await message.answer("Faqat raqam kiriting:")
        return
    amount = int(message.text)
    data = await state.get_data()
    uid = data['target_uid']
    
    total_debt = add_user_debt(uid, "-", "-", amount, items_str="Admin tomonidan qo'shildi")
    await message.answer(f"Mijozga {amount:,} so'm qarz qo'shildi.\n\n" + debt_history_text(uid), parse_mode="HTML")
    
    try:
        await bot.send_message(int(uid), f"Qarzingizga {amount:,} so'm qo'shildi.\n\n" + get_formatted_debt_text(uid), parse_mode="HTML")
    except Exception:
        pass
    await state.clear()

@dp.callback_query(F.data.startswith('sub_debt_'))
async def start_sub_debt(callback_query: types.CallbackQuery, state: FSMContext):
    uid = callback_query.data.split('_')[2]
    await state.update_data(target_uid=uid)
    await callback_query.message.answer("Qancha summani ayirmoqchisiz (to'ladi)? Summani kiriting:")
    await state.set_state(OrderState.waiting_for_admin_debt_sub)
    await callback_query.answer()

@dp.message(OrderState.waiting_for_admin_debt_sub)
async def process_admin_sub_debt(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id) or not message.text.isdigit():
        await message.answer("Faqat raqam kiriting:")
        return
    amount = int(message.text)
    data = await state.get_data()
    uid = data['target_uid']
    
    if uid in debts_db:
        debts_db[uid]["debt"] = max(0, debts_db[uid]["debt"] - amount)
        save_json(DEBTS_FILE, debts_db)
        total_debt = debts_db[uid]["debt"]
        await message.answer(f"Qarz {amount:,} so'mga kamaytirildi. Qolgan qarz: {total_debt:,} so'm.")
        
        try:
            await bot.send_message(int(uid), f"Qarzingizdan {amount:,} so'm to'landi va olib tashlandi.\n\n" + get_formatted_debt_text(uid), parse_mode="HTML")
        except Exception:
            pass
    await state.clear()

# ---------- Yetkazilmoqda ----------
@dp.callback_query(F.data.startswith('deliv_'))
async def process_delivering(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    target_user_id = callback_query.data.split('_')[1]
    try:
        await bot.send_message(int(target_user_id), "🚚 Buyurtmangiz yetkazilmoqda! Tez orada yetib boradi. Rahmat! 🍦")
        note = "🚚 Mijozga «yetkazilmoqda» xabari yuborildi ✅"
    except Exception as e:
        note = f"⚠️ Mijozga xabar yuborib bo'lmadi: {e}"
    for o in reversed(orders_db):
        if str(o.get("userId")) == str(target_user_id) and o.get("status") == "Yangi":
            o["status"] = "Yetkazilmoqda"
            save_json(ORDERS_FILE, orders_db)
            break
    await callback_query.message.reply(note)
    await callback_query.answer("Yuborildi ✅")

# ---------- Оплата и долги при заказе (Админ) ----------
@dp.callback_query(F.data.startswith('pay_full_'))
async def process_pay_full(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    _, _, target_user_id, total_price = callback_query.data.split('_')
    
    try:
        await bot.send_message(int(target_user_id), f"Buyurtmangiz uchun to'lov qabul qilindi. Rahmat! ✅")
    except Exception:
        pass

    await callback_query.message.reply(f"To'lov to'liq qabul qilindi. Mijozga qarz yozilmadi. ✅")
    await callback_query.answer()

@dp.callback_query(F.data.startswith('pay_debt_'))
async def process_pay_debt(callback_query: types.CallbackQuery):
    if not is_admin(callback_query.from_user.id):
        return
    _, _, target_user_id, total_price = callback_query.data.split('_')
    
    order_info = parse_order_text(callback_query.message.text or callback_query.message.caption or "")
    total_debt = add_user_debt(target_user_id, order_info['name'], order_info['phone'], int(total_price), items_str=order_info['items_summary'])

    try:
        debt_msg = f"Buyurtmangiz qarzga rasmiylashtirildi.\n\n" + get_formatted_debt_text(target_user_id)
        await bot.send_message(int(target_user_id), debt_msg, parse_mode="HTML")
    except Exception:
        pass

    await callback_query.message.reply(
        f"Mijoz qarziga {int(total_price):,} so'm qo'shildi.\n\n" + debt_history_text(target_user_id),
        parse_mode="HTML"
    )
    await callback_query.answer()

@dp.callback_query(F.data.startswith('pay_part_'))
async def process_pay_part(callback_query: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback_query.from_user.id):
        return
    _, _, target_user_id, total_price = callback_query.data.split('_')
    
    await state.update_data(
        target_user_id=target_user_id, 
        total_price=int(total_price), 
        msg_text=callback_query.message.text or callback_query.message.caption or ""
    )
    await callback_query.message.reply("Olingan summani kiriting (masalan 20000):")
    await state.set_state(OrderState.waiting_for_partial_pay)
    await callback_query.answer()

@dp.message(OrderState.waiting_for_partial_pay)
async def process_partial_pay_input(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text or not message.text.isdigit():
        await message.answer("Iltimos, faqat raqam kiriting:")
        return

    paid = int(message.text)
    data = await state.get_data()
    target_user_id = data['target_user_id']
    total_price = data['total_price']
    
    debt_to_add = total_price - paid
    order_info = parse_order_text(data.get('msg_text', ''))
    
    if debt_to_add > 0:
        total_debt = add_user_debt(target_user_id, order_info['name'], order_info['phone'], debt_to_add, items_str=order_info['items_summary'])
        msg_text = f"Qolgan {debt_to_add} so'm qarzga yozildi. Umumiy qarzi: {total_debt} so'm."
        try:
            debt_msg = f"Siz {paid} so'm to'ladingiz. Qolgan {debt_to_add} so'm qarzga yozildi.\n\n" + get_formatted_debt_text(target_user_id)
            await bot.send_message(int(target_user_id), debt_msg, parse_mode="HTML")
        except Exception:
            pass
    else:
        msg_text = "To'lov to'liq qoplandi, qarz yozilmadi."

    if debt_to_add > 0:
        msg_text += "\n\n" + debt_history_text(target_user_id)
    await message.answer(msg_text, parse_mode="HTML")
    await state.clear()

@dp.message(Command("backup"))
async def cmd_backup(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await _do_backup(delay=0, force=True)
    await message.answer(
        f"✅ Zaxira yuborildi.\n\n👥 Mijozlar: {len(saved_users)}\n📋 Qarzdorlar: {len(debts_db)}\n📦 Buyurtmalar: {len(orders_db)}"
    )

@dp.message(Command("reset_all"))
async def cmd_reset_all(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Ha, hammasini o'chirish", callback_data="reset_all_yes"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="reset_all_no"),
    ]])
    await message.answer(
        "⚠️ <b>DIQQAT!</b> Barcha mijozlar, qarzlar, buyurtmalar va savatlar o'chiriladi.\n"
        f"👥 Mijozlar: {len(saved_users)}\n💳 Qarzdorlar: {len(debts_db)}\n📥 Buyurtmalar: {len(orders_db)}\n\n"
        "Oldin joriy holatning nusxasi sizga fayl qilib yuboriladi. Davom etasizmi?",
        parse_mode="HTML", reply_markup=kb
    )

@dp.callback_query(F.data.in_({"reset_all_yes", "reset_all_no"}))
async def reset_all_confirm(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer()
        return
    await callback_query.message.edit_reply_markup(reply_markup=None)
    if callback_query.data == "reset_all_no":
        await callback_query.answer("Bekor qilindi")
        await callback_query.message.answer("Bekor qilindi, ma'lumotlar joyida.")
        return
    await callback_query.answer()
    try:
        # 1) Xavfsizlik uchun eski holatning nusxasini yuboramiz (pin qilinmaydi)
        await bot.send_document(
            ADMIN_ID,
            BufferedInputFile(_backup_payload(), filename="backup_OLD_before_reset.json"),
            caption="🗂 Tozalashdan oldingi nusxa (kerak bo'lsa shu faylni botga yuborsangiz tiklanadi)",
            disable_notification=True,
        )
    except Exception as e:
        await callback_query.message.answer(f"❌ Nusxa yuborilmadi, tozalash to'xtatildi: {e}")
        return
    # 2) Xotiradagi hamma narsani tozalaymiz
    saved_users.clear()
    debts_db.clear()
    orders_db.clear()
    user_carts.clear()
    verified_users.clear()
    # 3) Fayllarni / bazani bo'shatamiz
    for path, obj in ((USERS_FILE, saved_users), (DEBTS_FILE, debts_db), (ORDERS_FILE, orders_db)):
        try:
            save_json(path, obj, backup=False)
        except Exception as e:
            logging.error(f"Tozalashda xato {path}: {e}")
    # 4) Eski pin qilingan backup'ni olib tashlab, bo'sh yangisini pin qilamiz
    try:
        await bot.unpin_all_chat_messages(ADMIN_ID)
    except Exception as e:
        logging.error(f"Unpin xato: {e}")
    await _do_backup(delay=0)
    await callback_query.message.answer(
        "✅ Hamma ma'lumot tozalandi: mijozlar, qarzlar, buyurtmalar va savatlar.\n"
        "Endi har bir mijoz /start bosganda yangidan ro'yxatdan o'tadi."
    )

@dp.message(F.document, F.from_user.id == ADMIN_ID)
async def admin_restore_from_file(message: types.Message):
    """Admin backup.json faylini botga yuborsa, ma'lumotlar shundan tiklanadi."""
    doc = message.document
    if not (doc.file_name or "").lower().endswith(".json"):
        return
    try:
        f = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(f.file_path, buf)
        data = json.loads(buf.getvalue().decode("utf-8"))
        if not isinstance(data, dict) or not ({"users", "debts", "orders"} & set(data.keys())):
            await message.answer("❌ Bu zaxira (backup.json) fayliga o'xshamaydi.")
            return
        saved_users.clear(); saved_users.update(data.get("users", {}))
        debts_db.clear(); debts_db.update(data.get("debts", {}))
        orders_db[:] = data.get("orders", [])
        if "products" in data:
            load_products_state(data["products"])
            save_json(PRODUCTS_FILE, products_state)
        save_json(USERS_FILE, saved_users)
        save_json(DEBTS_FILE, debts_db)
        save_json(ORDERS_FILE, orders_db)
        await message.answer(
            f"♻️ Fayldan tiklandi:\n👥 Mijozlar: {len(saved_users)}\n"
            f"💳 Qarzdorlar: {len(debts_db)}\n📥 Buyurtmalar: {len(orders_db)}"
        )
    except Exception as e:
        await message.answer(f"❌ Tiklab bo'lmadi: {e}")

GEO_HTML = r'''<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<title>Lokatsiyani belgilash</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  html, body { margin:0; height:100%; font-family:-apple-system,Roboto,Arial,sans-serif; background:#fff; }
  #map { position:absolute; inset:0; }
  .pin { position:absolute; left:50%; top:50%; width:0; height:0; z-index:1000; pointer-events:none; }
  .pin span { position:absolute; left:-18px; top:-44px; font-size:36px; line-height:1; filter:drop-shadow(0 3px 3px rgba(0,0,0,.35)); }
  .pin i { position:absolute; left:-4px; top:-4px; width:8px; height:8px; border-radius:50%; background:rgba(0,0,0,.35); }
  .top { position:absolute; z-index:1000; top:10px; left:10px; right:10px; display:flex; gap:8px; }
  .top input { flex:1; min-width:0; padding:12px 14px; border:0; border-radius:14px; font-size:15px; box-shadow:0 2px 10px rgba(0,0,0,.25); outline:none; }
  .top button, .fab { border:0; background:#fff; border-radius:14px; width:46px; font-size:20px; box-shadow:0 2px 10px rgba(0,0,0,.25); cursor:pointer; }
  .fabs { position:absolute; z-index:1000; right:10px; bottom:110px; display:flex; flex-direction:column; gap:8px; }
  .fab { height:46px; }
  .bottom { position:absolute; z-index:1000; left:10px; right:10px; bottom:calc(10px + env(safe-area-inset-bottom,0px)); }
  #ok { width:100%; padding:15px; border:0; border-radius:16px; background:linear-gradient(90deg,#6366f1,#a855f7); color:#fff; font-size:17px; font-weight:700; box-shadow:0 4px 14px rgba(0,0,0,.3); cursor:pointer; }
  #addr { background:#fff; border-radius:12px; padding:8px 12px; margin-bottom:8px; font-size:13px; color:#333; box-shadow:0 2px 10px rgba(0,0,0,.2); display:none; }
</style>
</head>
<body>
<div id="map"></div>
<div class="pin"><span>📍</span><i></i></div>
<form class="top" id="sform"><input id="q" placeholder="Manzil qidirish..." autocomplete="off"><button type="submit">🔍</button></form>
<div class="fabs">
  <button class="fab" id="sat" type="button" title="Sputnik">🛰</button>
  <button class="fab" id="me" type="button" title="Mening joyim">🎯</button>
</div>
<div class="bottom"><div id="addr"></div><button id="ok" type="button">✅ Tasdiqlash</button></div>
<script>
(function () {
  // Google Maps API kalitini shu yerga qo'ying. Bo'sh qolsa oddiy (OpenStreetMap) xarita ochiladi.
  var GOOGLE_KEY = "";

  var tg = window.Telegram && Telegram.WebApp;
  if (tg) { tg.ready(); tg.expand(); }
  var p = new URLSearchParams(location.search);
  var lat = parseFloat(p.get('lat')), lon = parseFloat(p.get('lon'));
  if (!isFinite(lat) || !isFinite(lon)) { lat = 40.37583; lon = 70.81556; }

  var M = null; // {getCenter, setCenter, toggleSat, onIdle}
  var addr = document.getElementById('addr'), t;

  function initLeaflet() {
    document.getElementById('map').innerHTML = '';
    var map = L.map('map', { zoomControl:false, maxZoom:21 }).setView([lat, lon], 17);
    var street = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxNativeZoom:19, maxZoom:21, referrerPolicy:'origin', attribution:'© OpenStreetMap' });
    var sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom:18, maxZoom:21, attribution:'Esri' });
    var lbl = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', { maxNativeZoom:18, maxZoom:21 });
    var isSat = false; street.addTo(map);
    M = {
      getCenter: function () { var c = map.getCenter(); return { lat:c.lat, lon:c.lng }; },
      setCenter: function (la, lo, z) { map.setView([la, lo], z || 18); },
      toggleSat: function () { if (isSat) { map.removeLayer(sat); map.removeLayer(lbl); street.addTo(map); } else { map.removeLayer(street); sat.addTo(map); lbl.addTo(map); } isSat = !isSat; },
      onIdle: function (f) { map.on('moveend', f); },
      search: function (q, cb) {
        fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=uz&q=' + encodeURIComponent(q))
          .then(function (r) { return r.json(); }).then(function (a) { cb(a[0] ? { lat:+a[0].lat, lon:+a[0].lon } : null); })
          .catch(function () { cb(null); });
      }
    };
    M.onIdle(updateAddr); updateAddr();
  }

  function initGoogle() {
    var gm = new google.maps.Map(document.getElementById('map'), {
      center: { lat:lat, lng:lon }, zoom: 18, mapTypeId: 'roadmap',
      disableDefaultUI: true, zoomControl: true, gestureHandling: 'greedy', clickableIcons: false, keyboardShortcuts: false
    });
    var geocoder = new google.maps.Geocoder(), sat = false;
    M = {
      getCenter: function () { var c = gm.getCenter(); return { lat:c.lat(), lon:c.lng() }; },
      setCenter: function (la, lo, z) { gm.setCenter({ lat:la, lng:lo }); gm.setZoom(z || 18); },
      toggleSat: function () { sat = !sat; gm.setMapTypeId(sat ? 'hybrid' : 'roadmap'); },
      onIdle: function (f) { gm.addListener('idle', f); },
      search: function (q, cb) {
        geocoder.geocode({ address: q, region: 'uz' }, function (res, st) {
          if (st === 'OK' && res[0]) { var l = res[0].geometry.location; cb({ lat:l.lat(), lon:l.lng() }); } else cb(null);
        });
      },
      geocoder: geocoder
    };
    M.onIdle(updateAddr); updateAddr();
  }

  function updateAddr() {
    clearTimeout(t);
    t = setTimeout(function () {
      var c = M.getCenter();
      fetch('https://nominatim.openstreetmap.org/reverse?format=json&zoom=18&accept-language=uz,ru&lat=' + c.lat + '&lon=' + c.lon)
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d && d.display_name) { addr.textContent = d.display_name; addr.style.display = 'block'; } })
        .catch(function () {});
    }, 500);
  }

  window.gm_authFailure = function () { initLeaflet(); };
  if (GOOGLE_KEY) {
    window.__gmInit = initGoogle;
    var sc = document.createElement('script');
    sc.src = 'https://maps.googleapis.com/maps/api/js?key=' + encodeURIComponent(GOOGLE_KEY) + '&language=uz&region=UZ&callback=__gmInit';
    sc.onerror = initLeaflet;
    document.head.appendChild(sc);
  } else initLeaflet();

  document.getElementById('sat').onclick = function () { if (M) M.toggleSat(); };
  document.getElementById('me').onclick = function () {
    if (!navigator.geolocation || !M) return;
    navigator.geolocation.getCurrentPosition(function (pos) {
      M.setCenter(pos.coords.latitude, pos.coords.longitude, 18);
    }, function () { alert("Joylashuvni aniqlab bo'lmadi. Xaritani surib belgilang."); }, { enableHighAccuracy:true, timeout:10000 });
  };
  document.getElementById('sform').onsubmit = function (e) {
    e.preventDefault();
    var q = document.getElementById('q').value.trim(); if (!q || !M) return;
    M.search(q, function (r) { if (r) M.setCenter(r.lat, r.lon, 18); else alert('Topilmadi'); });
  };
  document.getElementById('ok').onclick = function () {
    if (!M) return;
    var c = M.getCenter();
    var data = JSON.stringify({ lat: +c.lat.toFixed(6), lon: +c.lon.toFixed(6) });
    if (tg && tg.platform && tg.platform !== 'unknown') { tg.sendData(data); }
    else alert("Tasdiqlash faqat Telegram bot ichida ishlaydi. Botdagi «📍 Lokatsiyani belgilash» tugmasi orqali oching.\n\nTanlangan nuqta: " + data);
  };
})();
</script>
</body>
</html>
'''

async def get_geo_page(request):
    return web.Response(text=GEO_HTML, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-cache"})

# ---------- API (Для мобильного приложения) ----------
async def get_orders_api(request):
    return web.json_response(orders_db)

async def get_debts_api(request):
    return web.json_response(debts_db)

def verify_init_data(init_data):
    """Telegram Mini App initData imzosini tekshiradi; to'g'ri bo'lsa foydalanuvchi ID sini qaytaradi."""
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        got_hash = pairs.pop("hash")
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got_hash):
            return None
        return int(json.loads(pairs["user"])["id"])
    except Exception:
        return None

async def get_products_api(request):
    out = {}
    for k, p in list(PRODUCTS.items()):
        photo = p.get("photo") or ""
        is_url = photo.startswith("http")
        out[k] = {
            "name": p["name"], "count_in_box": p["count_in_box"], "price": p["price"],
            "in_stock": is_in_stock(k),
            "custom": k in products_state["custom"],
            "edited": list(products_state["edits"].get(k, {}).keys()),
            "photo": photo if is_url else "",
            "photo_path": f"/api/photo/{k}?v={hashlib.md5(photo.encode()).hexdigest()[:8]}" if photo and not is_url else "",
        }
    return web.json_response(out)

_photo_cache = {}

async def get_photo_api(request):
    """Telegram'ga yuklangan (file_id) rasmni Mini App ko'rsata olishi uchun."""
    p = PRODUCTS.get(request.match_info["key"]) or {}
    fid = p.get("photo") or ""
    if not fid or fid.startswith("http"):
        raise web.HTTPNotFound()
    data = _photo_cache.get(fid)
    if data is None:
        try:
            f = await bot.get_file(fid)
            buf = io.BytesIO()
            await bot.download_file(f.file_path, buf)
            data = buf.getvalue()
        except Exception:
            raise web.HTTPNotFound()
        if len(_photo_cache) > 50:
            _photo_cache.clear()
        _photo_cache[fid] = data
    return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

async def post_notify_api(request):
    """Mini App'da tugagan muzqaymoq uchun «kelsa xabar bering» so'rovi."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    uid = verify_init_data(str(body.get("initData", "")))
    if not uid:
        return web.json_response({"ok": False, "error": "auth"}, status=403)
    key = str(body.get("key", ""))
    if key not in PRODUCTS or is_in_stock(key):
        return web.json_response({"ok": False, "error": "not_out"})
    add_waiting(key, uid)
    return web.json_response({"ok": True})

async def handle_ping(request):
    return web.Response(text="Bot va API ishlamoqda!")

async def set_admin_menu(chat_id):
    """Adminning o'ziga to'liq buyruqlar menyusini o'rnatadi."""
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🍦 Buyurtma berishni boshlash"),
            BotCommand(command="soat", description="⏰ Ismdagi jonli soat"),
            BotCommand(command="emoji", description="💎 Premium emoji o'rgatish"),
            BotCommand(command="debts", description="📋 Qarzdorlar ro'yxati"),
            BotCommand(command="xabar", description="📣 Hammaga xabar yuborish"),
            BotCommand(command="yangi", description="➕ Yangi muzqaymoq qo'shish"),
            BotCommand(command="holat", description="📦 Muzqaymoq bor / tugadi"),
            BotCommand(command="tahrir", description="✏️ Muzqaymoqni tahrirlash / o'chirish"),
        ], scope=BotCommandScopeChat(chat_id=chat_id))
        await bot.set_chat_menu_button(chat_id=chat_id, menu_button=MenuButtonCommands())
    except Exception as e:
        logging.warning(f"Admin menyusi ({chat_id}): {e}")

async def setup_bot_menu():
    await bot.set_my_commands([
        BotCommand(command="start", description="🍦 Buyurtma berishni boshlash"),
        BotCommand(command="soat", description="⏰ Ismdagi jonli soat"),
    ])
    for _adm in ADMIN_IDS:
        await set_admin_menu(_adm)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def main():
    app = web.Application()
    
    # Маршруты HTTP
    app.router.add_get("/", handle_ping)
    app.router.add_get("/geo", get_geo_page)
    app.router.add_get("/geo.html", get_geo_page)
    app.router.add_get("/api/orders", get_orders_api)
    app.router.add_get("/api/debts", get_debts_api)
    app.router.add_get("/api/products", get_products_api)
    app.router.add_get("/api/photo/{key}", get_photo_api)
    app.router.add_post("/api/notify", post_notify_api)

    # Настройка CORS
    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    for route in list(app.router.routes()):
        cors.add(route)

    port = int(os.environ.get("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await restore_from_telegram()
    await setup_bot_menu()
    await load_emoji_sets_env()
    asyncio.create_task(clock_loop())
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
