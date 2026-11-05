-- CashBot: Database Schema for Neon Serverless PostgreSQL
-- Compatible also with local PostgreSQL or SQLite fallbacks

CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    entry_price NUMERIC(18, 8) NOT NULL,
    exit_price NUMERIC(18, 8),
    quantity NUMERIC(18, 8) NOT NULL,
    stop_loss NUMERIC(18, 8) NOT NULL,
    take_profit NUMERIC(18, 8) NOT NULL,
    binance_order_list_id BIGINT,
    status VARCHAR(20) NOT NULL, -- 'OPEN_OCO', 'CLOSED_TP', 'CLOSED_SL', 'MANUAL_EXIT', 'SIMULATED'
    pnl_usd NUMERIC(18, 4) DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE
);

CREATE TABLE IF NOT EXISTS consensus_logs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    technical_score NUMERIC(5, 2) NOT NULL,
    sentiment_score NUMERIC(5, 2) NOT NULL,
    final_score NUMERIC(5, 2) NOT NULL,
    veto_applied BOOLEAN NOT NULL DEFAULT FALSE,
    reasoning_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio_ledger (
    id SERIAL PRIMARY KEY,
    trading_balance NUMERIC(18, 4) NOT NULL, -- Capital de giro ativo para novas ordens
    withdrawable_pool NUMERIC(18, 4) NOT NULL, -- Lucro retido protegido para saque via Pix
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Seed inicial de saldo caso o ledger esteja vazio
INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool)
SELECT 1000.00, 0.00
WHERE NOT EXISTS (SELECT 1 FROM portfolio_ledger);

