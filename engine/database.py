"""
Camada de Persistência do CashBot
Conecta ao Neon PostgreSQL via DATABASE_URL ou chaveia automaticamente
para SQLite local para testes, desenvolvimento e simulação sem atrito.
"""

import os
import sqlite3
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger("cashbot.database")

# Tenta importar psycopg2 para suporte nativo ao PostgreSQL (Neon)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "cashbot.db")

class Database:
    def __init__(self, connection_url: Optional[str] = None):
        self.connection_url = connection_url or os.getenv("DATABASE_URL")
        self.is_postgres = bool(self.connection_url and HAS_PSYCOPG2 and self.connection_url.startswith("postgres"))
        self._init_db()

    def _get_connection(self):
        if self.is_postgres:
            return psycopg2.connect(self.connection_url)
        else:
            conn = sqlite3.connect(SQLITE_PATH)
            conn.row_factory = sqlite3.Row
            return conn

    def _init_db(self):
        """Inicializa as tabelas caso não existam."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            if self.is_postgres:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id SERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        entry_price NUMERIC(18, 8) NOT NULL,
                        exit_price NUMERIC(18, 8),
                        quantity NUMERIC(18, 8) NOT NULL,
                        stop_loss NUMERIC(18, 8) NOT NULL,
                        take_profit NUMERIC(18, 8) NOT NULL,
                        binance_order_list_id BIGINT,
                        status VARCHAR(20) NOT NULL,
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
                        trading_balance NUMERIC(18, 4) NOT NULL,
                        withdrawable_pool NUMERIC(18, 4) NOT NULL,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
            else:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        exit_price REAL,
                        quantity REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        take_profit REAL NOT NULL,
                        binance_order_list_id INTEGER,
                        status TEXT NOT NULL,
                        pnl_usd REAL DEFAULT 0.0,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        closed_at DATETIME
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS consensus_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        technical_score REAL NOT NULL,
                        sentiment_score REAL NOT NULL,
                        final_score REAL NOT NULL,
                        veto_applied INTEGER NOT NULL DEFAULT 0,
                        reasoning_summary TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trading_balance REAL NOT NULL,
                        withdrawable_pool REAL NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                """)

            # Garante linha inicial no portfolio_ledger se estiver vazio
            cur.execute("SELECT COUNT(*) FROM portfolio_ledger")
            count = cur.fetchone()[0]
            if count == 0:
                cur.execute("""
                    INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool)
                    VALUES (1000.00, 0.00)
                """)
            conn.commit()
            mode_str = "Neon PostgreSQL" if self.is_postgres else "SQLite Local"
            logger.info(f"Banco de dados inicializado em modo: {mode_str}")
        finally:
            cur.close()
            conn.close()

    def get_ledger(self) -> Dict[str, float]:
        """Retorna o saldo de giro e o pool para saque."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT trading_balance, withdrawable_pool FROM portfolio_ledger ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return {
                    "trading_balance": float(row[0]),
                    "withdrawable_pool": float(row[1])
                }
            return {"trading_balance": 1000.0, "withdrawable_pool": 0.0}
        finally:
            cur.close()
            conn.close()

    def update_ledger(self, trading_balance: float, withdrawable_pool: float):
        """Atualiza os saldos no ledger contábil."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            now_str = datetime.utcnow().isoformat()
            if self.is_postgres:
                cur.execute("""
                    INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool, updated_at)
                    VALUES (%s, %s, %s)
                """, (trading_balance, withdrawable_pool, now_str))
            else:
                cur.execute("""
                    INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool, updated_at)
                    VALUES (?, ?, ?)
                """, (trading_balance, withdrawable_pool, now_str))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def get_open_trade(self) -> Optional[Dict[str, Any]]:
        """Retorna trade ativo com status 'OPEN_OCO' caso exista."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            query = "SELECT * FROM trades WHERE status = 'OPEN_OCO' ORDER BY id DESC LIMIT 1"
            cur.execute(query)
            row = cur.fetchone()
            if not row:
                return None
            if self.is_postgres:
                cols = [desc[0] for desc in cur.description]
                return dict(zip(cols, row))
            else:
                return dict(row)
        finally:
            cur.close()
            conn.close()

    def save_trade(self, symbol: str, entry_price: float, qty: float, stop_loss: float, take_profit: float, binance_order_list_id: Optional[int], status: str = "OPEN_OCO") -> int:
        """Registra a abertura de um trade."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            if self.is_postgres:
                cur.execute("""
                    INSERT INTO trades (symbol, entry_price, quantity, stop_loss, take_profit, binance_order_list_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (symbol, entry_price, qty, stop_loss, take_profit, binance_order_list_id, status))
                trade_id = cur.fetchone()[0]
            else:
                cur.execute("""
                    INSERT INTO trades (symbol, entry_price, quantity, stop_loss, take_profit, binance_order_list_id, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (symbol, entry_price, qty, stop_loss, take_profit, binance_order_list_id, status))
                trade_id = cur.lastrowid
            conn.commit()
            return trade_id
        finally:
            cur.close()
            conn.close()

    def close_trade(self, trade_id: int, exit_price: float, status: str, pnl_usd: float):
        """Registra o encerramento de um trade com status e PnL apurado."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            now_str = datetime.utcnow().isoformat()
            if self.is_postgres:
                cur.execute("""
                    UPDATE trades
                    SET exit_price = %s, status = %s, pnl_usd = %s, closed_at = %s
                    WHERE id = %s
                """, (exit_price, status, pnl_usd, now_str, trade_id))
            else:
                cur.execute("""
                    UPDATE trades
                    SET exit_price = ?, status = ?, pnl_usd = ?, closed_at = ?
                    WHERE id = ?
                """, (exit_price, status, pnl_usd, now_str, trade_id))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def save_consensus_log(self, symbol: str, tech_score: float, sent_score: float, final_score: float, veto_applied: bool, reasoning_summary: str):
        """Salva a deliberação dos agentes de IA."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            if self.is_postgres:
                cur.execute("""
                    INSERT INTO consensus_logs (symbol, technical_score, sentiment_score, final_score, veto_applied, reasoning_summary)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (symbol, tech_score, sent_score, final_score, veto_applied, reasoning_summary))
            else:
                cur.execute("""
                    INSERT INTO consensus_logs (symbol, technical_score, sentiment_score, final_score, veto_applied, reasoning_summary)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (symbol, tech_score, sent_score, final_score, 1 if veto_applied else 0, reasoning_summary))
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def get_recent_trades(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Busca histórico recente de operações."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            query = f"SELECT * FROM trades ORDER BY id DESC LIMIT {limit}"
            cur.execute(query)
            rows = cur.fetchall()
            if self.is_postgres:
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, r)) for r in rows]
            else:
                return [dict(r) for r in rows]
        finally:
            cur.close()
            conn.close()

    def get_recent_consensus(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Busca histórico recente das notas do comitê."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            query = f"SELECT * FROM consensus_logs ORDER BY id DESC LIMIT {limit}"
            cur.execute(query)
            rows = cur.fetchall()
            if self.is_postgres:
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, r)) for r in rows]
            else:
                return [dict(r) for r in rows]
        finally:
            cur.close()
            conn.close()

