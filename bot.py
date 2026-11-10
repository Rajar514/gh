import os
import io
import random
import string
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import qrcode
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "9219794753:AAFcojyj7G72_WQj_kHVkA8bYm_UsS4sSrI")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "CARDPACKSBOT")
PORT = int(os.getenv("PORT", 8080))

DEFAULT_USDT_ADDRESS = os.getenv("USDT_ADDRESS", "0x415c84ea67b273e17b3c03b010e7d5d9b20091d9")
DEFAULT_UPI_ID = os.getenv("UPI_ID", "navyard@fam")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Render dummy health-check server for 24/7 free tier
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"BIEXC Telegram Bot is running.")

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    server.serve_forever()

def get_db():
    return psycopg2.connect(DATABASE_URL)

def generate_short_id():
    return "BX-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ==================== SETTINGS HELPERS ====================

def get_setting(key, default_val):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM public.bot_settings WHERE key = %s;", (key,))
                row = cur.fetchone()
                return row[0] if row else default_val
    except Exception:
        return default_val

def set_setting(key, value):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.bot_settings (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
                """, (key, str(value)))
                conn.commit()
    except Exception as e:
        logging.error(f"set_setting error: {e}")

def ensure_user(tg_id, referred_by=None):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.tg_users (telegram_id, balance_usd, credits, referred_by)
                    VALUES (%s, 0.00, 0, %s)
                    ON CONFLICT (telegram_id) DO NOTHING;
                """, (tg_id, referred_by))
                conn.commit()
    except Exception as e:
        logging.error(f"ensure_user error: {e}")

def get_user_data(tg_id):
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT balance_usd, credits FROM public.tg_users WHERE telegram_id = %s;", (tg_id,))
                return cur.fetchone()
    except Exception as e:
        logging.error(f"get_user_data error: {e}")
        return None

# ==================== MAIN USER MENUS ====================

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Buy Cards", callback_data="screen_buy_cards")],
        [
            InlineKeyboardButton("💰 Balance", callback_data="screen_balance"),
            InlineKeyboardButton("📥 Deposit", callback_data="screen_deposit_select")
        ],
        [InlineKeyboardButton("📜 Transaction History", callback_data="screen_history")],
        [InlineKeyboardButton("⭐ 🎁 Refer & Earn", callback_data="screen_refer")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    referred_by = None
    if args and args[0].startswith("ref_"):
        try:
            referred_by = int(args[0].split("_")[1])
            if referred_by == user.id:
                referred_by = None
        except ValueError:
            referred_by = None

    ensure_user(user.id, referred_by)
    name = user.first_name if user.first_name else "Anonymous"

    text = (
        "💎 <b>BIEXC · Premium Digital Cards</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Welcome, <b>{name}</b>.\n"
        "Buy gift cards & vouchers in seconds, paid securely in USDT.\n\n"
        "<blockquote>"
        "⚡ <b>Instant delivery</b>\n"
        "🛡️ <b>Secure on-chain payments</b>\n"
        "💬 <b>24/7 priority support</b>"
        "</blockquote>\n\n"
        "Select an option below."
    )
    if update.message:
        await update.message.reply_html(text, reply_markup=main_menu_keyboard())
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")

# ==================== ADMIN PANEL (`/admin`) ====================

def get_admin_dashboard_markup():
    is_soldout = get_setting("tier_1_soldout", "true") == "true"
    soldout_label = "🟢 Set Tier 1 Available" if is_soldout else "🔴 Set Tier 1 Sold Out"

    keyboard = [
        [
            InlineKeyboardButton("📊 Bot Analytics", callback_data="admin_stats"),
            InlineKeyboardButton("⏳ Pending Deposits", callback_data="admin_pending_list")
        ],
        [
            InlineKeyboardButton(soldout_label, callback_data="admin_toggle_soldout"),
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_prompt")
        ],
        [
            InlineKeyboardButton("💳 Change UPI ID", callback_data="admin_update_upi"),
            InlineKeyboardButton("⚡ Change USDT Addr", callback_data="admin_update_usdt")
        ],
        [InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="admin_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Access Denied. Admin only command.")
        return

    upi_id = get_setting("upi_id", DEFAULT_UPI_ID)
    usdt_addr = get_setting("usdt_address", DEFAULT_USDT_ADDRESS)
    is_soldout = get_setting("tier_1_soldout", "true") == "true"

    text = (
        "⚡ <b>BIEXC Control Panel (Admin)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👑 <b>Admin ID:</b> <code>{ADMIN_ID}</code>\n"
        f"💳 <b>UPI ID:</b> <code>{upi_id}</code>\n"
        f"⚡ <b>USDT BEP20:</b> <code>{usdt_addr}</code>\n"
        f"📦 <b>Tier 1 Status:</b> {'❌ SOLD OUT' if is_soldout else '✅ IN STOCK'}\n\n"
        "Niche diye gaye buttons se bot customize karein:"
    )
    if update.message:
        await update.message.reply_html(text, reply_markup=get_admin_dashboard_markup())
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=get_admin_dashboard_markup(), parse_mode="HTML")

# ==================== CALLBACK LOGIC ====================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    tg_id = user.id
    ensure_user(tg_id)
    data = query.data

    # --- ADMIN ACTIONS ---
    if data.startswith("admin_"):
        if tg_id != ADMIN_ID:
            await query.answer("⛔ Access Denied.", show_alert=True)
            return

        if data == "admin_home":
            await admin_panel(update, context)
            await query.answer()
            return

        elif data == "admin_stats":
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM public.tg_users;")
                    total_users = cur.fetchone()[0]

                    cur.execute("SELECT count(*), coalesce(sum(amount_usd), 0) FROM public.tg_transactions WHERE type='Deposit' AND status='Success';")
                    dep_count, dep_vol = cur.fetchone()

                    cur.execute("SELECT count(*), coalesce(sum(amount_usd), 0) FROM public.tg_transactions WHERE type='Purchase' AND status='Success';")
                    pur_count, pur_vol = cur.fetchone()

                    cur.execute("SELECT count(*), coalesce(sum(amount_usd), 0) FROM public.tg_transactions WHERE type='Deposit' AND status='Pending';")
                    pending_count = cur.fetchone()[0]

            stats_text = (
                "📊 <b>Live Bot Analytics</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👥 <b>Total Users:</b> {total_users}\n"
                f"📥 <b>Approved Deposits:</b> {dep_count} (${dep_vol:,.2f})\n"
                f"⏳ <b>Pending Deposits:</b> {pending_count}\n"
                f"🛍️ <b>Orders Delivered:</b> {pur_count} (${pur_vol:,.2f})\n"
            )
            keyboard = [[InlineKeyboardButton("◀️ Back to Admin Panel", callback_data="admin_home")]]
            await query.edit_message_text(stats_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            await query.answer()
            return

        elif data == "admin_toggle_soldout":
            cur_state = get_setting("tier_1_soldout", "true") == "true"
            new_state = "false" if cur_state else "true"
            set_setting("tier_1_soldout", new_state)
            status_str = "AVAILABLE" if new_state == "false" else "SOLD OUT"
            await query.answer(f"✅ Tier 1 is now {status_str}!", show_alert=True)
            await admin_panel(update, context)
            return

        elif data == "admin_pending_list":
            with get_db() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT short_id, telegram_id, method, amount_usd, created_at FROM public.tg_transactions WHERE status='Pending' ORDER BY created_at DESC LIMIT 6;")
                    pendings = cur.fetchall()

            if not pendings:
                await query.answer("Koi pending deposit nahi hai!", show_alert=True)
                return

            text = "⏳ <b>Pending Deposits:</b>\n━━━━━━━━━━━━━━━━━━━━\nSelect an order to Approve or Reject:\n\n"
            keyboard = []
            for p in pendings:
                keyboard.append([
                    InlineKeyboardButton(f"✅ Approve {p['short_id']} (${p['amount_usd']} {p['method']})", callback_data=f"adm_appr_{p['short_id']}"),
                    InlineKeyboardButton(f"❌ Reject", callback_data=f"adm_rej_{p['short_id']}")
                ])
            keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="admin_home")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            await query.answer()
            return

        elif data.startswith("adm_appr_"):
            order_id = data.split("_")[2]
            with get_db() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT * FROM public.tg_transactions WHERE short_id = %s AND status = 'Pending';", (order_id,))
                    order = cur.fetchone()
                    if order:
                        cur.execute("UPDATE public.tg_transactions SET status = 'Success' WHERE short_id = %s;", (order_id,))
                        cur.execute("UPDATE public.tg_users SET balance_usd = balance_usd + %s WHERE telegram_id = %s;", (order["amount_usd"], order["telegram_id"]))
                        conn.commit()

                        await query.answer(f"Order {order_id} Approved! ${order['amount_usd']} credited.", show_alert=True)
                        await context.bot.send_message(
                            chat_id=order["telegram_id"],
                            text=f"✅ <b>Deposit Approved!</b>\n\nOrder <code>{order_id}</code> verified. <b>${order['amount_usd']}</b> added to your wallet.",
                            parse_mode="HTML"
                        )
                        await admin_panel(update, context)
                        return

        elif data.startswith("adm_rej_"):
            order_id = data.split("_")[2]
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE public.tg_transactions SET status = 'Rejected' WHERE short_id = %s;", (order_id,))
                    conn.commit()
            await query.answer(f"Order {order_id} Rejected.", show_alert=True)
            await admin_panel(update, context)
            return

        elif data == "admin_broadcast_prompt":
            context.user_data["awaiting_broadcast"] = True
            await query.edit_message_text(
                "📢 <b>Broadcast Setup</b>\n\nAb agla text message jo aap bhejenge, wo bot ke **sabhi users** ko send ho jayega.\n\nCancel karne ke liye `/cancel` likhein.",
                parse_mode="HTML"
            )
            await query.answer()
            return

        elif data == "admin_update_upi":
            context.user_data["awaiting_upi"] = True
            await query.edit_message_text(
                "💳 <b>Change UPI ID</b>\n\nApna naya UPI ID chat me send karein (e.g. `example@fam`).\n\nCancel karne ke liye `/cancel` likhein.",
                parse_mode="HTML"
            )
            await query.answer()
            return

        elif data == "admin_update_usdt":
            context.user_data["awaiting_usdt"] = True
            await query.edit_message_text(
                "⚡ <b>Change USDT Address (BEP20)</b>\n\nApna naya BSC/BEP20 address chat me paste karein.\n\nCancel karne ke liye `/cancel` likhein.",
                parse_mode="HTML"
            )
            await query.answer()
            return

    # --- USER SCREENS ---
    if data == "screen_main":
        await start(update, context)
        await query.answer()
        return

    # 1. DEPOSIT SELECTION SCREEN
    elif data == "screen_deposit_select":
        text = (
            "📥 <b>Select Deposit Method</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Choose your preferred payment method:\n\n"
            "<blockquote>"
            "🇮🇳 <b>INR · UPI Deposit:</b> Instant via GPay, PhonePe, Paytm (Rate: ₹100 = $1)\n"
            "⚡ <b>Crypto · USDT:</b> Fast deposit via BNB Smart Chain (BEP20)"
            "</blockquote>\n\n"
            "Select an option below:"
        )
        keyboard = [
            [InlineKeyboardButton("🇮🇳 INR · UPI Deposit", callback_data="deposit_method_upi")],
            [InlineKeyboardButton("⚡ USDT · BEP20 (Crypto)", callback_data="deposit_method_crypto")],
            [InlineKeyboardButton("◀️ Main Menu", callback_data="screen_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # 2. UPI AMOUNTS SELECTION
    elif data == "deposit_method_upi":
        rate = get_setting("inr_rate", "100")
        text = (
            "📥 <b>INR · UPI Deposit</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Rate: ₹{rate} = $1</b>\n\n"
            "Choose your wallet top-up amount:"
        )
        keyboard = [
            [InlineKeyboardButton("💰 ₹500 ➔ $5", callback_data="init_upi_500"), InlineKeyboardButton("💰 ₹2000 ➔ $20", callback_data="init_upi_2000")],
            [InlineKeyboardButton("💰 ₹5000 ➔ $50", callback_data="init_upi_5000"), InlineKeyboardButton("💰 ₹10000 ➔ $100", callback_data="init_upi_10000")],
            [InlineKeyboardButton("◀️ Back", callback_data="screen_deposit_select")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # 3. CRYPTO USDT AMOUNTS SELECTION
    elif data == "deposit_method_crypto":
        text = (
            "⚡ <b>USDT · BEP20 Deposit</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Network:</b> BNB Smart Chain (BEP20)\n"
            "<b>Token:</b> USDT\n\n"
            "Choose your top-up amount to generate deposit invoice:"
        )
        keyboard = [
            [InlineKeyboardButton("💵 $5 USDT", callback_data="init_crypto_5"), InlineKeyboardButton("💵 $20 USDT", callback_data="init_crypto_20")],
            [InlineKeyboardButton("💵 $50 USDT", callback_data="init_crypto_50"), InlineKeyboardButton("💵 $100 USDT", callback_data="init_crypto_100")],
            [InlineKeyboardButton("◀️ Back", callback_data="screen_deposit_select")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # 4. GENERATE UPI INVOICE & QR
    elif data.startswith("init_upi_"):
        inr_amt = int(data.split("_")[2])
        usd_amt = inr_amt / float(get_setting("inr_rate", "100"))
        dep_order_id = generate_short_id()
        current_upi = get_setting("upi_id", DEFAULT_UPI_ID)

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO public.tg_transactions (short_id, telegram_id, type, amount_usd, method, status) VALUES (%s, %s, 'Deposit', %s, 'UPI', 'Pending');", (dep_order_id, tg_id, usd_amt))
                conn.commit()

        # UPI URI for QR Code scanning
        upi_intent = f"upi://pay?pa={current_upi}&pn=BIEXC&am={inr_amt}&cu=INR&tn={dep_order_id}"
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(upi_intent)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        bio = io.BytesIO()
        img.save(bio, "PNG")
        bio.seek(0)

        caption = (
            "💎 <b>BIEXC · UPI Checkout</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            f"<b>Pay:</b> ₹{inr_amt}\n"
            f"<b>Wallet top-up:</b> ${usd_amt:.2f}\n"
            f"<b>Order:</b> <code>{dep_order_id}</code>"
            "</blockquote>\n\n"
            f"<b>UPI ID:</b> <code>{current_upi}</code> (Tap to Copy)\n"
            f"<b>Rate: ₹{get_setting('inr_rate', '100')} = $1</b>\n\n"
            "<b>Status: Pending</b>\n\n"
            "<i>Do not pay this expired or completed invoice.</i>"
        )
        keyboard = [
            [InlineKeyboardButton("📥 Deposit Now", callback_data=f"show_upi_guide_{dep_order_id}_{inr_amt}")],
            [InlineKeyboardButton("🔄 Check Status", callback_data=f"chk_dep_{dep_order_id}")],
            [InlineKeyboardButton("◀️ Main Menu", callback_data="screen_main")]
        ]
        await context.bot.send_photo(chat_id=tg_id, photo=bio, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # Pop-up prompt when user clicks "📥 Deposit Now"
    elif data.startswith("show_upi_guide_"):
        parts = data.split("_")
        order_ref = parts[3]
        amt_to_pay = parts[4]
        current_upi = get_setting("upi_id", DEFAULT_UPI_ID)
        await query.answer(
            f"Scan the QR code above or pay ₹{amt_to_pay} to UPI: {current_upi}\nOrder ID: {order_ref}",
            show_alert=True
        )

    # 5. GENERATE CRYPTO USDT INVOICE & QR
    elif data.startswith("init_crypto_"):
        usd_amt = float(data.split("_")[2])
        dep_order_id = generate_short_id()
        usdt_addr = get_setting("usdt_address", DEFAULT_USDT_ADDRESS)

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO public.tg_transactions (short_id, telegram_id, type, amount_usd, method, status) VALUES (%s, %s, 'Deposit', %s, 'USDT · BEP20', 'Pending');", (dep_order_id, tg_id, usd_amt))
                conn.commit()

        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(usdt_addr)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        bio = io.BytesIO()
        img.save(bio, "PNG")
        bio.seek(0)

        caption = (
            "💎 <b>BIEXC · USDT Checkout</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            f"<b>Send Amount:</b> <code>${usd_amt:.2f} USDT</code>\n"
            f"<b>Network:</b> <code>BNB Smart Chain (BEP20)</code>\n"
            f"<b>Order ID:</b> <code>{dep_order_id}</code>"
            "</blockquote>\n\n"
            "<b>Deposit Address (Click to copy):</b>\n"
            f"<code>{usdt_addr}</code>\n\n"
            "<b>Status: Pending</b>\n\n"
            "<blockquote>"
            "⚠️ <b>Important:</b>\n"
            "• Only send <b>USDT</b> via <b>BEP20 (BSC)</b> network.\n"
            "• Sending other coins will result in loss of funds.\n"
            "• System credits balance after network confirmation."
            "</blockquote>"
        )
        keyboard = [
            [InlineKeyboardButton("🔄 Check Status", callback_data=f"chk_dep_{dep_order_id}")],
            [InlineKeyboardButton("◀️ Main Menu", callback_data="screen_main")]
        ]
        await context.bot.send_photo(chat_id=tg_id, photo=bio, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # 6. CHECK DEPOSIT STATUS
    elif data.startswith("chk_dep_"):
        check_id = data.split("_")[2]
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT status FROM public.tg_transactions WHERE short_id = %s;", (check_id,))
                row = cur.fetchone()
                status = row["status"] if row else "Unknown"

        if status == "Success":
            await query.answer("✅ Deposit Verified! Balance credited to wallet.", show_alert=True)
            await start(update, context)
        elif status == "Rejected":
            await query.answer("❌ Order was Rejected or Expired.", show_alert=True)
        else:
            await query.answer(f"⏳ Order {check_id} is still Pending.\nPlease wait for confirmation.", show_alert=True)

    # 7. BUY CARDS SCREEN
    elif data == "screen_buy_cards":
        is_soldout = get_setting("tier_1_soldout", "true") == "true"
        tier_1_btn_text = "⭐ $4 · $500 Value (SOLD OUT)" if is_soldout else "⭐ $4 · $500 Value · 75%"
        tier_1_callback = "buy_tier_1_soldout" if is_soldout else "buy_pack_starter"

        text = (
            "💳 <b>Card Packs</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⭐ <b>Tier 1 · Starter {'(SOLD OUT)' if is_soldout else ''}</b>\n"
            "<blockquote>$4.00 ➔ $500 Value\n"
            "✅ 75% Working</blockquote>\n\n"
            "👑 <b>Tier 2 · Pro — <i>Most popular</i></b>\n"
            "<blockquote>$16.00 ➔ $2K Value\n"
            "✅ 99% Working</blockquote>\n\n"
            "⭐ <b>Tier 3 · Elite</b>\n"
            "<blockquote>$40.00 ➔ $5K Value</blockquote>\n\n"
            "Choose your pack:"
        )
        keyboard = [
            [InlineKeyboardButton(tier_1_btn_text, callback_data=tier_1_callback)],
            [InlineKeyboardButton("👑 $16 · $2K Value · 99%", callback_data="buy_pack_pro")],
            [InlineKeyboardButton("⭐ $40 · $5K Value", callback_data="buy_pack_elite")],
            [InlineKeyboardButton("◀️ Back", callback_data="screen_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    elif data == "buy_tier_1_soldout":
        await query.answer("⚠️ Tier 1 Starter Pack is currently SOLD OUT!\nPlease select Tier 2 Pro or Tier 3 Elite.", show_alert=True)

    # 8. PURCHASE PACK EXECUTION
    elif data in ["buy_pack_starter", "buy_pack_pro", "buy_pack_elite"]:
        tier_map = {
            "buy_pack_starter": ("Tier 1 · Starter", 4.00, "$500 Value", 500, "starter"),
            "buy_pack_pro": ("Tier 2 · Pro", 16.00, "$2K Value", 2000, "pro"),
            "buy_pack_elite": ("Tier 3 · Elite", 40.00, "$5K Value", 5000, "elite")
        }
        pack_title, pack_price, pack_val, pack_credits, tier_code = tier_map[data]

        u_data = get_user_data(tg_id)
        current_bal = float(u_data["balance_usd"]) if u_data else 0.00

        if current_bal < pack_price:
            shortage = pack_price - current_bal
            await query.answer("❌ Insufficient Wallet Balance!", show_alert=True)
            low_text = (
                "⚠️ <b>Insufficient Balance!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Selected Pack: <b>{pack_title}</b>\n"
                f"Pack Price: <b>${pack_price:.2f}</b>\n"
                f"Your Balance: <code>${current_bal:.2f}</code>\n"
                f"Shortage: <b>${shortage:.2f}</b>\n\n"
                "Kharidne ke liye pehle wallet top-up karein:"
            )
            keyboard = [
                [InlineKeyboardButton("📥 Deposit Funds Now", callback_data="screen_deposit_select")],
                [InlineKeyboardButton("◀️ Back to Packs", callback_data="screen_buy_cards")]
            ]
            await query.edit_message_text(low_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            return

        order_short_id = generate_short_id()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT public.tg_buy_pack(%s, %s, %s, %s, %s);", (tg_id, tier_code, pack_price, pack_credits, order_short_id))
                purchase_ok = cur.fetchone()[0]
                conn.commit()

        if not purchase_ok:
            await query.answer("❌ Transaction Failed!", show_alert=True)
            return

        updated_bal = float(get_user_data(tg_id)["balance_usd"])
        msg1 = (
            "✅ <b>Purchase Successful</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "<blockquote>"
            f"<b>{pack_title}</b>\n"
            f"Paid: <b>${pack_price:.2f} from wallet</b>\n"
            f"You got: <b>{pack_val}</b>\n"
            f"Order ID: <code>{order_short_id}</code>"
            "</blockquote>\n\n"
            f"Remaining balance: <b>${updated_bal:,.2f}</b>\n\n"
            "Thank you for choosing BIEXC."
        )
        await query.edit_message_text(msg1, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Main Menu", callback_data="screen_main")]]), parse_mode="HTML")

        msg2 = (
            "🎉 <b>Order Successful!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Thanks user, your purchase is success!\n"
            "Here is your details:\n\n"
            "<blockquote>"
            f"<b>Order ID:</b> <code>{order_short_id}</code>\n"
            "<b>Status:</b> Completed\n\n"
            "<b>Card Details (Click to copy):</b>\n"
            "• Full Format: <code>6489957050811817|12|2027|779</code>\n"
            "• Card Number: <code>6489 9570 5081 1817</code>\n"
            "• Expiry: <code>12/2027</code>\n"
            "• CVV: <code>779</code>"
            "</blockquote>\n\n"
            "Thank you for choosing BIEXC!"
        )
        await context.bot.send_message(chat_id=tg_id, text=msg2, parse_mode="HTML")
        await query.answer()

    # 9. BALANCE SCREEN
    elif data == "screen_balance":
        u_data = get_user_data(tg_id)
        bal = float(u_data["balance_usd"]) if u_data else 0.00
        creds = u_data["credits"] if u_data else 0
        text = (
            "💰 <b>Your Wallet Balance</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Telegram ID: <code>{tg_id}</code>\n"
            f"Available Balance: <b>${bal:,.2f}</b>\n"
            f"Available Credits: <b>{creds}</b>\n"
        )
        keyboard = [
            [InlineKeyboardButton("📥 Deposit Funds", callback_data="screen_deposit_select")],
            [InlineKeyboardButton("💳 Buy Cards", callback_data="screen_buy_cards")],
            [InlineKeyboardButton("◀️ Back", callback_data="screen_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # 10. REFER & EARN
    elif data == "screen_refer":
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{tg_id}"
        text = (
            "🎁 <b>REFER & EARN — FREE $5 CARD PACK!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Invite your friends and get rewarded instantly!\n\n"
            "When your referred friend purchases a <b>$20 Card Pack</b>, you get a <b>$5 Starter Card Pack completely FREE!</b> 💳🔥\n\n"
            "<blockquote>"
            "🔗 <b>Your Unique Referral Link:</b>\n"
            f"<code>{ref_link}</code>"
            "</blockquote>\n\n"
            "<b>How it works:</b>\n"
            "1. Share your unique referral link with your friend.\n"
            "2. Once they purchase the $20 pack, send their Order ID to admin/support.\n"
            "3. As soon as it's verified, you'll receive your <b>$5 Card Pack for FREE!</b>"
        )
        keyboard = [[InlineKeyboardButton("◀️ Main Menu", callback_data="screen_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

    # 11. TRANSACTION HISTORY
    elif data == "screen_history":
        with get_db() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT short_id, type, amount_usd, status FROM public.tg_transactions WHERE telegram_id = %s ORDER BY created_at DESC LIMIT 5;", (tg_id,))
                history = cur.fetchall()

        text = "📜 <b>Recent Transactions</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
        if not history:
            text += "<i>No transaction history found.</i>"
        else:
            for row in history:
                icon = "✅" if row["status"] == "Success" else "⏳" if row["status"] == "Pending" else "❌"
                text += f"{icon} <b>{row['type']}</b> — <code>${row['amount_usd']}</code> | <code>{row['short_id']}</code> ({row['status']})\n"

        keyboard = [[InlineKeyboardButton("◀️ Main Menu", callback_data="screen_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        await query.answer()

# ==================== ADMIN INPUT HANDLER ====================

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    text = update.message.text.strip()
    if text == "/cancel":
        context.user_data.clear()
        await update.message.reply_text("Action cancelled.", reply_markup=get_admin_dashboard_markup())
        return

    # Broadcast handling
    if context.user_data.get("awaiting_broadcast"):
        context.user_data["awaiting_broadcast"] = False
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT telegram_id FROM public.tg_users;")
                users = cur.fetchall()

        count = 0
        for u in users:
            try:
                await context.bot.send_message(chat_id=u[0], text=f"📢 <b>Announcement:</b>\n\n{text}", parse_mode="HTML")
                count += 1
            except Exception:
                pass
        await update.message.reply_text(f"✅ Broadcast successfully sent to {count} users!")
        return

    # UPI update
    if context.user_data.get("awaiting_upi"):
        context.user_data["awaiting_upi"] = False
        set_setting("upi_id", text)
        await update.message.reply_text(f"✅ UPI ID successfully updated to: <code>{text}</code>", parse_mode="HTML")
        return

    # USDT address update
    if context.user_data.get("awaiting_usdt"):
        context.user_data["awaiting_usdt"] = False
        set_setting("usdt_address", text)
        await update.message.reply_text(f"✅ USDT Address successfully updated to: <code>{text}</code>", parse_mode="HTML")
        return

# ==================== MAIN LAUNCHER ====================

def main():
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))

    print("BIEXC Telegram Bot is running smoothly with UPI + USDT BEP20...")
    app.run_polling()

if __name__ == "__main__":
    main()
