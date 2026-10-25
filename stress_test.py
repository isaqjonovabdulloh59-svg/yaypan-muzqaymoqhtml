"""
YUKLAMA SINOVI: 60 mijoz x 40 buyurtma = 2400 buyurtma, har biri adminda "To'liq qarzga berildi" bosiladi.
2400 ta tugatilgach skript O'ZI TO'XTAYDI va xotira/ma'lumot hisobotini chiqaradi.

ISHLATISH (main.py bilan BIR PAPKADA):
    pip install aiogram aiohttp-cors pillow psutil
    python stress_test.py

Bu skript Telegramga HECH NIMA YUBORMAYDI: botning haqiqiy handlerlari (finish/web_app_data, pay_debt, ...)
ishlaydi, lekin Telegram chaqiruvlari soxta (mock) javob qaytaradi. Ma'lumotlar vaqtinchalik papkaga yoziladi,
sizning haqiqiy users/debts/orders ma'lumotlaringizga TEGMAYDI.

NEON bazani ham sinash (ixtiyoriy) - FAQAT alohida TEST baza/branch bilan (Neon'da "Branch" yarating):
    TEST_DATABASE_URL="postgresql://..." I_CONFIRM_TEST_DB=yes python stress_test.py
"""
import os, sys, re, json, html, time, random, asyncio, tempfile, itertools, logging
from collections import Counter, defaultdict
from datetime import datetime

# ---------------- Sozlamalar ----------------
USERS = int(os.environ.get("USERS", 60))
ORDERS_PER_USER = int(os.environ.get("ORDERS_PER_USER", 40))
MEM_LIMIT_MB = int(os.environ.get("MEM_LIMIT_MB", 512))   # Render bepul tarif ~512 MB
BASE_UID = 7_000_000_000

# ---------------- Xavfsiz muhit (import'dan OLDIN) ----------------
TMP = tempfile.mkdtemp(prefix="stress_")
os.environ["BOT_TOKEN"] = "123456:ABCDEFghijklmnopqrstuvwxyz0123456789"
os.environ["DATA_DIR"] = TMP
test_db = os.environ.get("TEST_DATABASE_URL", "").strip()
if test_db:
    if os.environ.get("I_CONFIRM_TEST_DB") != "yes":
        sys.exit("TEST_DATABASE_URL berilgan. Bu SINOV bazasi ekanini tasdiqlang: I_CONFIRM_TEST_DB=yes")
    os.environ["DATABASE_URL"] = test_db
else:
    os.environ["DATABASE_URL"] = ""   # haqiqiy DATABASE_URL bo'lsa ham ishlatilmaydi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as bm                                    # sizning bot kodingiz
from aiogram import Bot
from aiogram.types import Message, Chat, User, ChatMemberMember

# ---------------- Xotira o'lchash ----------------
def rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1024 / 1024
    except Exception:
        try:
            import resource
            v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return v / 1024 / (1024 if sys.platform == "darwin" else 1)
        except Exception:
            return 0.0

# ---------------- Soxta Telegram ----------------
calls = Counter()
pending = {}                 # uid -> (admin xabar matni, pay_debt callback_data)
_ids = itertools.count(1)
err_count = Counter()

class _ErrCounter(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            err_count[record.getMessage()[:90]] += 1

def _msg(chat_id=1):
    return Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=chat_id, type="private"))

async def fake_call(self, method, request_timeout=None):
    name = type(method).__name__
    calls[name] += 1
    if name == "GetMe":
        return User(id=999, is_bot=True, first_name="TestBot", username="test_bot")
    if name == "GetChatMember":
        return ChatMemberMember(status="member", user=User(id=method.user_id, is_bot=False, first_name="x"))
    if name == "SendMessage" and method.chat_id == bm.ADMIN_ID:
        calls["ADMINGA_XABAR"] += 1
        kb = getattr(method, "reply_markup", None)
        if kb is not None and hasattr(kb, "inline_keyboard"):
            for row in kb.inline_keyboard:
                for b in row:
                    if b.callback_data and b.callback_data.startswith("pay_debt_"):
                        uid = int(b.callback_data.split("_")[2])
                        pending[uid] = (method.text, b.callback_data)
        return _msg(method.chat_id)
    if getattr(method, "__returning__", None) is Message:
        return _msg(getattr(method, "chat_id", 1) if isinstance(getattr(method, "chat_id", 1), int) else 1)
    return True

Bot.__call__ = fake_call
bot = bm.bot
dp = bm.dp

# ---------------- Soxta Telegram yangilanishlari ----------------
_upd = itertools.count(1)
def _plain(text):
    """Telegram HTML'ni olib tashlab, mijoz/admin ko'radigan oddiy matnni beradi."""
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))

def order_update(uid, n, items, total):
    payload = {"name": f"Mijoz {n}", "phone": f"+99890{n:07d}", "location": "Yaypan, sinov manzil",
               "lat": 40.37583, "lon": 70.81556, "items": items, "totalPrice": total}
    return {"update_id": next(_upd), "message": {
        "message_id": next(_ids), "date": int(time.time()),
        "chat": {"id": uid, "type": "private"},
        "from": {"id": uid, "is_bot": False, "first_name": f"Mijoz {n}"},
        "web_app_data": {"data": json.dumps(payload, ensure_ascii=False), "button_text": "Buyurtma"}}}

def admin_cb_update(text, cb_data):
    return {"update_id": next(_upd), "callback_query": {
        "id": str(next(_ids)), "chat_instance": "x", "data": cb_data,
        "from": {"id": bm.ADMIN_ID, "is_bot": False, "first_name": "Admin"},
        "message": {"message_id": next(_ids), "date": int(time.time()),
                    "chat": {"id": bm.ADMIN_ID, "type": "private"},
                    "from": {"id": 999, "is_bot": True, "first_name": "TestBot"},
                    "text": _plain(text)}}}

def make_order():
    keys = random.sample(list(bm.PRODUCTS), random.randint(1, 4))
    items, total = [], 0
    for i, k in enumerate(keys, 1):
        p = bm.PRODUCTS[k]
        qty = random.randint(1, 5) * p["count_in_box"]
        items.append({"name": f"{i}. {p['name']}", "count": qty, "price": p["price"]})
        total += qty * p["price"]
    return items, total

# ---------------- Sinov ----------------
expected = defaultdict(int)
state = {"done": 0, "failed_order": 0, "peak": 0.0}
samples = []

async def customer(i):
    uid = BASE_UID + i
    for _ in range(ORDERS_PER_USER):
        items, total = make_order()
        expected[uid] += total
        await dp.feed_raw_update(bot, order_update(uid, i, items, total))
        got = pending.pop(uid, None)
        if got is None:
            state["failed_order"] += 1       # admin xabari kelmadi = buyurtma qabul qilinmadi
            continue
        await dp.feed_raw_update(bot, admin_cb_update(*got))     # admin "To'liq qarzga berildi" ni bosdi
        state["done"] += 1
        if state["done"] % 50 == 0:
            r = rss_mb(); state["peak"] = max(state["peak"], r)
            samples.append((state["done"], r))
            print(f"  {state['done']:>5}/{USERS*ORDERS_PER_USER}  xotira: {r:7.1f} MB", flush=True)

async def run():
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger().addHandler(_ErrCounter())
    total_orders = USERS * ORDERS_PER_USER
    start_mem = rss_mb(); state["peak"] = start_mem
    print(f"\nBoshlandi: {USERS} mijoz x {ORDERS_PER_USER} buyurtma = {total_orders} (hammasi bir vaqtda)")
    print(f"Rejim: {'NEON (test baza)' if bm.DB_ENABLED else 'JSON fayl'} | boshlang'ich xotira: {start_mem:.1f} MB\n")
    t0 = time.time()
    await asyncio.gather(*(customer(i) for i in range(1, USERS + 1)))
    dt = time.time() - t0

    if bm.DB_ENABLED:                       # bazaga yozilib bo'lishini kutamiz
        for _ in range(120):
            if not bm._db_dirty and bm._db_task is None:
                break
            await asyncio.sleep(0.5)
    else:
        await asyncio.sleep(0.2)

    # --- tekshiruvlar ---
    orders = bm.orders_db
    ids = [o["id"] for o in orders]
    exp_total = sum(expected.values())
    act_total = sum(u.get("debt", 0) for u in bm.debts_db.values())
    hist = [len(u.get("history", [])) for u in bm.debts_db.values()]
    end_mem = rss_mb(); state["peak"] = max(state["peak"], end_mem)

    # --- admin ekranlari (/debts, qarzdor kartasi) ---
    t1 = time.time(); admin_err = None
    try:
        png, _, _ = bm.debts_page_content(0)
        uid0 = next(iter(bm.debts_db))
        bm.build_debt_detail_image(uid0, bm.debts_db[uid0])
    except Exception as e:
        admin_err = f"{type(e).__name__}: {e}"
    admin_dt = time.time() - t1
    after_img = rss_mb(); state["peak"] = max(state["peak"], after_img)

    # --- zaxira fayli hajmi (JSON rejimda Telegramga shu yuboriladi) ---
    t2 = time.time(); backup_size = len(bm._backup_payload()) / 1024 / 1024; backup_dt = time.time() - t2
    after_backup = rss_mb(); state["peak"] = max(state["peak"], after_backup)

    db_rows = None
    if bm.DB_ENABLED:
        try:
            c = bm._db_connect(); cur = c.cursor(); cur.execute("SELECT count(*) FROM orders")
            db_rows = cur.fetchone()[0]; c.close()
        except Exception as e:
            db_rows = f"o'qib bo'lmadi: {e}"

    files = {f: os.path.getsize(os.path.join(TMP, f)) / 1024 for f in os.listdir(TMP)} if not bm.DB_ENABLED else {}

    # --- HISOBOT ---
    ok_count = len(orders) == total_orders and len(set(ids)) == len(ids)
    ok_debt = exp_total == act_total
    ok_mem = state["peak"] < MEM_LIMIT_MB * 0.8
    print("\n" + "=" * 62)
    print("NATIJA (sinov o'zi to'xtadi)")
    print("=" * 62)
    print(f"Vaqt: {dt:.1f} s  ({total_orders/dt:.0f} buyurtma/s)")
    print(f"Xotira: boshida {start_mem:.0f} MB -> eng yuqori {state['peak']:.0f} MB -> oxirida {end_mem:.0f} MB "
          f"(o'sish: +{end_mem-start_mem:.0f} MB)")
    print(f"Buyurtmalar: {len(orders)}/{total_orders}  noyob ID: {len(set(ids))}  -> {'OK' if ok_count else 'XATO'}")
    print(f"Qarzdorlar: {len(bm.debts_db)} ta, har birida tarix yozuvi: min {min(hist or [0])} / max {max(hist or [0])}")
    print(f"Qarz yig'indisi: kutilgan {exp_total:,} | haqiqiy {act_total:,}  -> {'OK' if ok_debt else 'XATO (qarz yo`qolgan/ikki marta yozilgan!)'}")
    print(f"Qabul qilinmagan buyurtmalar: {state['failed_order']}")
    if bm.DB_ENABLED:
        print(f"Neon bazadagi buyurtmalar: {db_rows}")
    else:
        print("Fayl hajmlari (KB): " + ", ".join(f"{k}={v:.0f}" for k, v in files.items()))
    print(f"/debts + qarzdor kartasi rasmi: {admin_dt:.2f} s" + (f"  XATO: {admin_err}" if admin_err else "  OK"))
    print(f"Zaxira fayli (backup.json): {backup_size:.2f} MB, {backup_dt:.2f} s")
    print(f"Soxta Telegram chaqiruvlari: adminga xabar {calls['ADMINGA_XABAR']}, jami {sum(calls.values())}")
    if err_count:
        print("\nBot ichidagi XATOLAR (logdan):")
        for k, v in err_count.most_common(8):
            print(f"  {v}x  {k}")
    print("\nXULOSA:")
    print(f"  Xotira ({MEM_LIMIT_MB} MB limitda): {'KO`TARADI' if ok_mem else 'XAVFLI / KO`TARMASLIGI MUMKIN'} "
          f"(eng yuqori {state['peak']:.0f} MB)")
    print(f"  Ma'lumot to'g'riligi: {'OK' if (ok_count and ok_debt) else 'MUAMMO BOR'}")
    print("  ESLATMA: bu sinov Telegram tezlik limitini (adminga ~1 xabar/soniya) HISOBGA OLMAYDI.")
    print("=" * 62)

if __name__ == "__main__":
    asyncio.run(run())
