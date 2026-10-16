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
    WebAppInfo, BotCommand, MenuButtonCommands, BufferedInputFile,
)

TOKEN = os.environ.get("BOT_TOKEN", "8941827736:AAHTSclOer3V_D2JdcIqMj3dOqfJqo_4jKY")
ADMIN_ID = 8488328091
WEBAPP_URL = "https://yaypanmuzqamoq.netlify.app/"
USERS_FILE = "users.json"
DEBTS_FILE = "debts.json"    # База долгов
ORDERS_FILE = "orders.json"  # База заказов
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

saved_users = load_json(USERS_FILE)
debts_db = load_json(DEBTS_FILE)
orders_db = load_json(ORDERS_FILE)
if not isinstance(orders_db, list):
    orders_db = []

def get_saved_user(user_id):
    return saved_users.get(str(user_id))

def set_saved_user(user_id, name, location, phone):
    saved_users[str(user_id)] = {"name": name, "location": location, "phone": phone}
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

def info_text(name, location, phone):
    return (
        f"👤 <b>Ism:</b> {html.escape(str(name))}\n"
        f"📍 <b>Manzil:</b> {html.escape(str(location))}\n"
        f"📞 <b>Telefon:</b> {html.escape(str(phone))}"
    )

def admin_order_keyboard(user_id, total_price):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚚 Yetkazilmoqda", callback_data=f"deliv_{user_id}")],
        [InlineKeyboardButton(text="💵 Pulni oldim (Qarz yo'q)", callback_data=f"pay_full_{user_id}_{total_price}")],
        [InlineKeyboardButton(text="📝 To'liq qarzga berildi", callback_data=f"pay_debt_{user_id}_{total_price}")],
        [InlineKeyboardButton(text="⚡ Qisman to'landi", callback_data=f"pay_part_{user_id}_{total_price}")],
        [InlineKeyboardButton(text="🖨 Print qilish", callback_data="print_order")],
    ])

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
        await state.update_data(name=saved["name"], location=saved["location"], phone=saved["phone"])
        await message.answer(
            f"Assalomu alaykum, <b>{html.escape(saved['name'])}</b>! 🍦\n"
            f"Buyurtma shu ma'lumotlar bilan yuboriladi:\n\n"
            f"{info_text(saved['name'], saved['location'], saved['phone'])}\n\n"
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
        f"{info_text(data.get('name'), data.get('location'), phone)}\n\n"
        f"💾 Shu ma'lumotlar saqlansinmi?\n"
        f"Saqlansa, keyingi safar qayta so'ralmaydi va buyurtmalar doim shu nomdan boradi.",
        parse_mode="HTML",
        reply_markup=save_keyboard
    )
    await state.set_state(OrderState.waiting_for_save)

@dp.callback_query(F.data.in_({"save_yes", "save_no"}), OrderState.waiting_for_save)
async def process_save(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback_query.from_user.id

    if callback_query.data == "save_yes":
        set_saved_user(user_id, data.get("name"), data.get("location"), data.get("phone"))
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

    items_list = data_json.get("items", [])
    total_price = 0
    order_details = ""
    items_summary = []

    if isinstance(items_list, list) and items_list:
        for idx, item in enumerate(items_list, 1):
            title = item.get("name", "Mahsulot")
            qty = int(item.get("count", item.get("quantity", 1)))
            price = int(item.get("price", 0))
            cost = qty * price
            total_price += cost
            order_details += f"• {idx}. {title}: {qty} ta × {price} = {cost} so'm\n"
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
        "status": "Yangi"
    }
    orders_db.append(new_order)
    save_json(ORDERS_FILE, orders_db)

    admin_message = (
        f"📥 <b>Yangi buyurtma keldi! (Mini App)</b>\n\n"
        f"{info_text(user_name, user_loc, user_phone)}\n\n"
        f"🛍 <b>Buyurtma tarkibi:</b>\n{order_details}\n"
        f"💳 <b>Umumiy summa:</b> {total_price} so'm"
    )
    await bot.send_message(
        ADMIN_ID,
        admin_message,
        parse_mode="HTML",
        reply_markup=admin_order_keyboard(user_id, total_price)
    )

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

    # Сохранение заказа для API
    new_order = {
        "id": len(orders_db) + 1,
        "clientName": user_name,
        "phone": user_phone,
        "items": ", ".join(items_summary),
        "totalPrice": total_price,
        "status": "Yangi"
    }
    orders_db.append(new_order)
    save_json(ORDERS_FILE, orders_db)

    admin_message = (
        f"📥 <b>Yangi buyurtma keldi! (bot)</b>\n\n"
        f"{info_text(user_name, data.get('location', '-'), user_phone)}\n\n"
        f"🛍 <b>Buyurtma tarkibi:</b>\n{order_details}\n"
        f"💳 <b>Umumiy summa:</b> {total_price} so'm"
    )
    await bot.send_message(ADMIN_ID, admin_message, parse_mode="HTML", reply_markup=admin_order_keyboard(user_id, total_price))

    user_carts[user_id] = {}
    await message.answer(
        "Buyurtmangiz muvaffaqiyatli yuborildi! ✅ Tez orada siz bilan bog'lanishadi.\n\n"
        "Yangi buyurtma berish uchun /start buyrug'ini bosing.",
        reply_markup=main_menu_keyboard
    )
    await send_sticker_safe(message.chat.id, "🍦", "❤", "👍", "✅")
    await state.clear()

# ---------- Админ Панель Должников ----------
@dp.message(Command("debts"))
async def admin_debts_list(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    if not debts_db:
        await message.answer("Qarzdorlar ro'yxati bo'sh.")
        return

    text = "📋 <b>QARZDORLAR RO'YXATI:</b>\n\n"
    keyboard_buttons = []
    
    for uid, udata in debts_db.items():
        debt = udata.get("debt", 0)
        name = udata.get("name", "Noma'lum")
        phone = udata.get("phone", "-")
        text += f"👤 <b>{html.escape(name)}</b> ({phone})\n💳 Qarz: {debt:,} so'm\n\n"
        keyboard_buttons.append([InlineKeyboardButton(text=f"👤 {name} ({debt:,} so'm)", callback_data=f"manage_debt_{uid}")])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith('manage_debt_'))
async def manage_user_debt(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != ADMIN_ID:
        return
    uid = callback_query.data.split('_')[2]
    u = debts_db.get(uid)
    if not u:
        await callback_query.answer("Mijoz topilmadi.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Qarz qo'shish", callback_data=f"add_debt_{uid}"),
         InlineKeyboardButton(text="➖ Qarzni ayirish / to'lash", callback_data=f"sub_debt_{uid}")],
        [InlineKeyboardButton(text="🔙 Ro'yxatga qaytish", callback_data="back_to_debts")]
    ])
    
    await callback_query.message.edit_text(
        f"👤 <b>Mijoz:</b> {html.escape(u['name'])}\n"
        f"📞 <b>Tel:</b> {u['phone']}\n"
        f"💳 <b>Hozirgi qarzi:</b> {u['debt']:,} so'm\n\n"
        f"Amalni tanlang:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback_query.answer()

@dp.callback_query(F.data == "back_to_debts")
async def back_to_debts_handler(callback_query: types.CallbackQuery):
    await callback_query.message.delete()
    await admin_debts_list(callback_query.message)

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
    await message.answer(f"Mijozga {amount:,} so'm qarz qo'shildi. Umumiy qarzi: {total_debt:,} so'm.")
    
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

    await callback_query.message.reply(f"Mijoz qarziga {total_price} so'm qo'shildi. Umumiy qarzi: {total_debt} so'm.")
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

    await message.answer(msg_text)
    await state.clear()

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

    await setup_bot_menu()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
