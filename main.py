import logging
import asyncio
import os
import json
import html
import re
import io
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from aiohttp import web
import aiohttp_cors
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo, BotCommand, MenuButtonCommands, BufferedInputFile, InputMediaPhoto,
)

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable o'rnatilmagan! Render > Environment bo'limiga qo'shing.")
ADMIN_ID = 8488328091
WEBAPP_URL = "https://yaypanmuzqamoq.netlify.app/"
# Agar Render'da Persistent Disk ulasangiz, DATA_DIR=/data qilib qo'ying
DATA_DIR = os.environ.get("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DEBTS_FILE = os.path.join(DATA_DIR, "debts.json")    # База долгов
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")  # База заказов
CHANNEL = "@YAYPAN_muzqaymoq"
CHANNEL_URL = "https://t.me/YAYPAN_muzqaymoq"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Список продуктов
PRODUCTS = {
    "oilaviy": {"name": "1. Oilaviy (0.5 kg karobka)", "count_in_box": 12, "price": 15000, "photo": "https://t.me/YAYPAN_muzqaymoq/21?single"},
    "zuxro_shoko": {"name": "2. Zuxro shokolad", "count_in_box": 24, "price": 4000, "photo": "https://t.me/YAYPAN_muzqaymoq/19"},
    "flash": {"name": "3. Flash", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/16"},
    "moxitto": {"name": "4. Moxitto", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/13"},
    "sutli": {"name": "5. Sutli", "count_in_box": 54, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/10"},
    "ananas": {"name": "6. Ananas", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/7"},
    "anor": {"name": "7. Anor", "count_in_box": 50, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/6"},
    "jazzi": {"name": "8. Jazzi", "count_in_box": 50, "price": 2300, "photo": "https://t.me/YAYPAN_muzqaymoq/73"},
    "ferero": {"name": "9. Ferero", "count_in_box": 54, "price": 2200, "photo": "https://t.me/YAYPAN_muzqaymoq/74"},
    "anjan_qulupnay": {"name": "10. Anjan qulupnay", "count_in_box": 20, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/75"},
    "shokoland": {"name": "11. Shokoland", "count_in_box": 60, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/76"},
    "ayron": {"name": "12. Ayron", "count_in_box": 70, "price": 800, "photo": "https://t.me/YAYPAN_muzqaymoq/56"},
    "pankie": {"name": "13. Pankie", "count_in_box": 24, "price": 6000, "photo": "https://t.me/YAYPAN_muzqaymoq/55"},
    "labubu": {"name": "14. Labubu", "count_in_box": 24, "price": 8000, "photo": "https://t.me/YAYPAN_muzqaymoq/53"},
    "gold": {"name": "15. Gold", "count_in_box": 28, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/52"},
    "rojok": {"name": "16. Rojok", "count_in_box": 30, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/51"},
    "sendwich": {"name": "17. Sendwich", "count_in_box": 24, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/50"},
    "gazeta": {"name": "18. Gazeta", "count_in_box": 20, "price": 3500, "photo": "https://t.me/YAYPAN_muzqaymoq/49"},
    "stakan": {"name": "19. Stakan", "count_in_box": 48, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/45"},
    "anjan": {"name": "20. Anjan", "count_in_box": 20, "price": 5000, "photo": "https://t.me/YAYPAN_muzqaymoq/44"},
    "banan": {"name": "21. Banan", "count_in_box": 48, "price": 1600, "photo": "https://t.me/YAYPAN_muzqaymoq/34"},
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

# ---------- Операции с JSON-файлами ----------
def load_json(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return [] if filepath.endswith("orders.json") else {}

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка записи в {filepath}: {e}")
    request_backup()

saved_users = load_json(USERS_FILE)
debts_db = load_json(DEBTS_FILE)
orders_db = load_json(ORDERS_FILE)
if not isinstance(orders_db, list):
    orders_db = []

# ---------- Telegram orqali zaxira (Render restart bo'lganda ma'lumot yo'qolmasligi uchun) ----------
# Render bepul tarifida fayllar har restartda o'chib ketadi. Shuning uchun har o'zgarishdan keyin
# barcha ma'lumot bitta backup.json qilib adminga yuboriladi va PIN qilinadi.
# Bot qayta ishga tushganda shu pin qilingan fayldan hammasi tiklanadi.
_backup_scheduled = False
_last_backup_msg_id = None

def request_backup():
    """Ma'lumot o'zgarganda chaqiriladi; 10 soniya ichidagi o'zgarishlarni bitta zaxiraga birlashtiradi."""
    global _backup_scheduled
    if _backup_scheduled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _backup_scheduled = True
    loop.create_task(_do_backup())

def _backup_payload():
    return json.dumps(
        {"users": saved_users, "debts": debts_db, "orders": orders_db},
        ensure_ascii=False, indent=1
    ).encode("utf-8")

async def _do_backup(delay=10):
    global _backup_scheduled, _last_backup_msg_id
    await asyncio.sleep(delay)
    _backup_scheduled = False
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
    if saved_users or debts_db or orders_db:
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
        _last_backup_msg_id = pm.message_id
        # Lokal fayllarga ham yozib qo'yamiz
        for path, obj in ((USERS_FILE, saved_users), (DEBTS_FILE, debts_db), (ORDERS_FILE, orders_db)):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, ensure_ascii=False, indent=2)
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
    await bot.send_message(
        ADMIN_ID, admin_message, parse_mode="HTML",
        reply_markup=admin_order_keyboard(user_id, total_price, geo),
        disable_web_page_preview=True,
    )
    if geo:
        try:
            await bot.send_location(ADMIN_ID, geo["lat"], geo["lon"])
        except Exception as e:
            logging.warning(f"Lokatsiya yuborilmadi: {e}")

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
    if callback_query.from_user.id != ADMIN_ID:
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
        if user is None or user.id == ADMIN_ID or user.id in verified_users:
            return await handler(event, data)
        if isinstance(event, types.Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery) and event.data == "check_sub":
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

# ---------- /start и сценарий ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    if user_id != ADMIN_ID and user_id not in verified_users:
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
    await state.update_data(location=message.text)
    geo_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⏭ O'tkazib yuborish")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "📍 Do'koningiz joylashgan nuqtani xaritada o'zingiz belgilang:\n\n"
        "1️⃣ Chatdagi 📎 (skrepka) tugmasini bosing\n"
        "2️⃣ «Lokatsiya» (Location) ni tanlang\n"
        "3️⃣ Xaritani surib, do'koningiz turgan joyni belgilang yoki qidiruvdan toping\n"
        "4️⃣ «Tanlangan lokatsiyani yuborish» (Send selected location) ni bosing\n\n"
        "⚠️ «Mening joriy joylashuvim» ni emas, aynan do'kon turgan joyni tanlang.",
        reply_markup=geo_kb
    )
    await state.set_state(OrderState.waiting_for_geo)

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
            "Iltimos, 📎 → «Lokatsiya» orqali xaritadan do'koningiz joyini belgilab yuboring "
            "yoki «⏭ O'tkazib yuborish»ni tanlang."
        )
        return
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📞 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Telefon raqamingizni yuboring:", reply_markup=keyboard)
    await state.set_state(OrderState.waiting_for_phone)

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
    for key, prod in PRODUCTS.items():
        box_total = prod['count_in_box'] * prod['price']
        text = (
            f"<b>{prod['name']}</b>\n"
            f"📦 Qutida: {prod['count_in_box']} ta\n"
            f"💰 Dona narxi: {prod['price']} so'm\n"
            f"💵 Jami quti narxi: {box_total} so'm"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Karobkada olish", callback_data=f"box_{key}"),
            InlineKeyboardButton(text="🔢 Dona tanlash", callback_data=f"dona_{key}")
        ]])
        try:
            await message.answer_photo(photo=prod['photo'], caption=text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(F.data.startswith('box_'), OrderState.shopping)
async def add_box_to_cart(callback_query: types.CallbackQuery):
    product_key = callback_query.data.split('_', 1)[1]
    user_id = callback_query.from_user.id
    user_carts.setdefault(user_id, {})
    add_count = PRODUCTS[product_key]['count_in_box']
    user_carts[user_id][product_key] = user_carts[user_id].get(product_key, 0) + add_count
    await callback_query.answer(f"1 karobka ({add_count} ta) savatga qo'shildi! ✅")

@dp.callback_query(F.data.startswith('dona_'), OrderState.shopping)
async def ask_custom_dona(callback_query: types.CallbackQuery, state: FSMContext):
    product_key = callback_query.data.split('_', 1)[1]
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
    if message.from_user.id != ADMIN_ID:
        return
    content = debts_page_content(0)
    if not content:
        await message.answer("Qarzdorlar ro'yxati bo'sh. ✅")
        return
    png, caption, kb = content
    await message.answer_photo(BufferedInputFile(png, filename="qarzdorlar.png"), caption=caption, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith('debts_page_'))
async def debts_page_handler(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
    content = debts_page_content(int(callback_query.data.split('_')[2]))
    await callback_query.answer()
    if not content:
        await callback_query.message.answer("Qarzdorlar ro'yxati bo'sh. ✅")
        return
    await swap_photo(callback_query, *content)

@dp.callback_query(F.data.startswith('manage_debt_'))
async def manage_user_debt(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
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
    if callback_query.from_user.id != ADMIN_ID:
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
    if message.from_user.id != ADMIN_ID or not message.text.isdigit():
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
    if message.from_user.id != ADMIN_ID or not message.text.isdigit():
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
    if callback_query.from_user.id != ADMIN_ID:
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
    if callback_query.from_user.id != ADMIN_ID:
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
    if callback_query.from_user.id != ADMIN_ID:
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
    if callback_query.from_user.id != ADMIN_ID:
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
    if message.from_user.id != ADMIN_ID:
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
    await _do_backup(delay=0)
    await message.answer("✅ Zaxira yuborildi va pin qilindi.")

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
        save_json(USERS_FILE, saved_users)
        save_json(DEBTS_FILE, debts_db)
        save_json(ORDERS_FILE, orders_db)
        await message.answer(
            f"♻️ Fayldan tiklandi:\n👥 Mijozlar: {len(saved_users)}\n"
            f"💳 Qarzdorlar: {len(debts_db)}\n📥 Buyurtmalar: {len(orders_db)}"
        )
    except Exception as e:
        await message.answer(f"❌ Tiklab bo'lmadi: {e}")

# ---------- API (Для мобильного приложения) ----------
async def get_orders_api(request):
    return web.json_response(orders_db)

async def get_debts_api(request):
    return web.json_response(debts_db)

async def handle_ping(request):
    return web.Response(text="Bot va API ishlamoqda!")

async def setup_bot_menu():
    await bot.set_my_commands([
        BotCommand(command="start", description="🍦 Buyurtma berishni boshlash"),
        BotCommand(command="debts", description="📋 Qarzdorlar ro'yxati (Admin)"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

async def main():
    app = web.Application()
    
    # Маршруты HTTP
    app.router.add_get("/", handle_ping)
    app.router.add_get("/api/orders", get_orders_api)
    app.router.add_get("/api/debts", get_debts_api)

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
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
