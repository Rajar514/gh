# BIEXC Telegram Store Bot 🚀

Complete Telegram Bot with UPI QR, USDT BEP20 Crypto Deposits, Interactive `/admin` panel, and Sold-Out protections.

## Deployment Instructions (Render.com - 100% Free 24/7)

### Why Render instead of Vercel?
Vercel is a **Serverless** platform designed for stateless web requests (10-15 seconds execution limit). Telegram bots using long polling (`run_polling()`) get killed on Vercel immediately.
**Render** allows running background Python processes 24/7 for free.

### Step-by-Step Setup:

1. **Supabase Setup:**
   - Copy the entire SQL content from `setup_database.sql` and run it in your **Supabase SQL Editor**.

2. **Upload to GitHub:**
   - Create a new GitHub repository (e.g. `biexc-bot`).
   - Upload all files from this archive:
     - `bot.py`
     - `requirements.txt`
     - `Procfile`
     - `setup_database.sql`

3. **Deploy on Render (render.com):**
   - Click **New +** -> **Web Service**.
   - Connect your GitHub repository.
   - Configure:
     - **Runtime:** Python 3
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `python bot.py`
     - **Instance Type:** Free

4. **Add Environment Variables on Render:**
   - `BOT_TOKEN`: Your Telegram Bot Token
   - `DATABASE_URL`: Your Supabase connection string (URI)
   - `ADMIN_ID`: Your Telegram numeric User ID
   - `BOT_USERNAME`: `CARDPACKSBOT` (or your bot's username without @)
   - `UPI_ID`: `navyard@fam`
   - `USDT_ADDRESS`: `0x415c84ea67b273e17b3c03b010e7d5d9b20091d9`
   - `PORT`: `8080`

5. **24/7 Keep-Alive (Optional but recommended):**
   - Go to [cron-job.org](https://cron-job.org) or [uptimerobot.com](https://uptimerobot.com) (free).
   - Set up a monitor targeting your Render URL (e.g. `https://your-bot.onrender.com`) every 5 minutes.
   - This prevents Render's free tier from sleeping!
