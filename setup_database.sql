-- ==============================================
-- BIEXC Telegram Bot Complete Database Schema
-- Run this once in your Supabase SQL Editor
-- ==============================================

-- 1. Users Table
CREATE TABLE IF NOT EXISTS public.tg_users (
    telegram_id BIGINT PRIMARY KEY,
    balance_usd NUMERIC(10, 2) DEFAULT 0.00,
    credits INTEGER DEFAULT 0,
    referred_by BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 2. Transactions Table
CREATE TABLE IF NOT EXISTS public.tg_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    short_id TEXT UNIQUE NOT NULL,
    telegram_id BIGINT NOT NULL,
    type TEXT NOT NULL, -- 'Purchase' or 'Deposit'
    tier TEXT,
    amount_usd NUMERIC(10, 2) NOT NULL,
    credits INTEGER DEFAULT 0,
    method TEXT DEFAULT 'Wallet', -- 'Wallet', 'UPI', 'USDT · BEP20'
    status TEXT DEFAULT 'Pending', -- 'Pending', 'Success', 'Rejected'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

-- 3. Bot Settings Table (Live Config via /admin)
CREATE TABLE IF NOT EXISTS public.bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO public.bot_settings (key, value) VALUES
('tier_1_soldout', 'true'),
('upi_id', 'navyard@fam'),
('usdt_address', '0x415c84ea67b273e17b3c03b010e7d5d9b20091d9'),
('inr_rate', '100')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

-- 4. Atomic Pack Purchase Function (Race-Condition Free)
CREATE OR REPLACE FUNCTION public.tg_buy_pack(
    _telegram_id BIGINT, 
    _tier TEXT, 
    _price NUMERIC, 
    _credits INTEGER,
    _short_id TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    _current_bal NUMERIC;
BEGIN
    SELECT balance_usd INTO _current_bal 
    FROM public.tg_users 
    WHERE telegram_id = _telegram_id 
    FOR UPDATE;

    IF _current_bal IS NULL OR _current_bal < _price THEN
        RETURN FALSE;
    END IF;

    UPDATE public.tg_users 
    SET balance_usd = balance_usd - _price,
        credits = credits + _credits
    WHERE telegram_id = _telegram_id;

    INSERT INTO public.tg_transactions (short_id, telegram_id, type, tier, amount_usd, credits, method, status)
    VALUES (_short_id, _telegram_id, 'Purchase', _tier, _price, _credits, 'Wallet', 'Success');

    RETURN TRUE;
END;
$$;
