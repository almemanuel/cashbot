"""
Camada de Persistência do CashBot
Conecta ao Neon PostgreSQL via DATABASE_URL ou chaveia automaticamente
para SQLite local para testes, desenvolvimento e simulação sem atrito.
Segue Object Calisthenics e evita N+1 com batch insert e leitura unificada em sessão única.
"""

import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple, Sequence
from datetime import datetime

logger = logging.getLogger("cashbot.database")

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "..", "cashbot.db")

POSTGRES_SCHEMA_SQL = [
    """
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
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_ledger (
        id SERIAL PRIMARY KEY,
        trading_balance NUMERIC(18, 4) NOT NULL,
        withdrawable_pool NUMERIC(18, 4) NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """
]

SQLITE_SCHEMA_SQL = [
    """
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
    """,
    """
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
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trading_balance REAL NOT NULL,
        withdrawable_pool REAL NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """
]


class Database:
    _SCHEMA_INITIALIZED = False

    def __init__(self, connection_url: Optional[str] = None):
        self.connection_url = connection_url or os.getenv("DATABASE_URL")
        self.is_postgres = bool(
            self.connection_url and HAS_PSYCOPG2 and self.connection_url.startswith("postgres")
        )
        if not Database._SCHEMA_INITIALIZED:
            self._init_db()
            Database._SCHEMA_INITIALIZED = True

    @contextmanager
    def _session(self):
        """Gerencia conexão e cursor em escopo único com commit automático."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()
            conn.close()

    def _get_connection(self):
        if self.is_postgres:
            return psycopg2.connect(self.connection_url, connect_timeout=10)
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _sql(self, query_with_qmarks: str) -> str:
        """Adapta placeholders '?' para '%s' caso esteja conectado no PostgreSQL."""
        if self.is_postgres:
            return query_with_qmarks.replace("?", "%s")
        return query_with_qmarks

    def _init_db(self) -> None:
        """Inicializa o schema e garante o saldo inicial do portfólio."""
        statements = POSTGRES_SCHEMA_SQL if self.is_postgres else SQLITE_SCHEMA_SQL
        with self._session() as cur:
            self._run_statements(cur, statements)
            self._seed_initial_ledger(cur)
        mode_str = "Neon PostgreSQL" if self.is_postgres else "SQLite Local"
        logger.info(f"Banco de dados inicializado em modo: {mode_str}")

    @staticmethod
    def _run_statements(cur, statements: List[str]) -> None:
        for stmt in statements:
            cur.execute(stmt)

    @staticmethod
    def _seed_initial_ledger(cur) -> None:
        cur.execute("SELECT COUNT(*) FROM portfolio_ledger")
        count = cur.fetchone()[0]
        if count > 0:
            return
        cur.execute(
            "INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool) VALUES (1000.00, 0.00)"
        )

    def reset_simulation(self, initial_capital: float = 1000.0) -> None:
        """Reseta todo o histórico de simulação, zera posições e restaura a banca inicial."""
        with self._session() as cur:
            cur.execute("DELETE FROM trades;")
            cur.execute("DELETE FROM consensus_logs;")
            cur.execute("DELETE FROM portfolio_ledger;")
            insert_sql = self._sql(
                "INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool) VALUES (?, ?)"
            )
            cur.execute(insert_sql, (initial_capital, 0.0))
        logger.info(f"Simulação resetada com sucesso para banca inicial de ${initial_capital:,.2f}!")

    def get_ledger(self) -> Dict[str, float]:
        """Retorna o saldo de giro e o pool para saque."""
        with self._session() as cur:
            return self._fetch_ledger_in_cursor(cur)

    def update_ledger(self, trading_balance: float, withdrawable_pool: float) -> None:
        """Atualiza os saldos no ledger contábil."""
        now_str = datetime.utcnow().isoformat()
        query = self._sql(
            "INSERT INTO portfolio_ledger (trading_balance, withdrawable_pool, updated_at) VALUES (?, ?, ?)"
        )
        with self._session() as cur:
            cur.execute(query, (trading_balance, withdrawable_pool, now_str))

    def get_open_trade(self) -> Optional[Dict[str, Any]]:
        """Retorna trade ativo mais recente com status 'OPEN_OCO' caso exista."""
        with self._session() as cur:
            return self._fetch_open_trade_in_cursor(cur)

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Retorna todas as posições simultâneas abertas ('OPEN_OCO') na carteira."""
        with self._session() as cur:
            return self._fetch_open_trades_in_cursor(cur)

    def save_trade(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        stop_loss: float,
        take_profit: float,
        binance_order_list_id: Optional[int],
        status: str = "OPEN_OCO"
    ) -> int:
        """Registra a abertura de um trade e retorna seu ID."""
        params = (symbol, entry_price, qty, stop_loss, take_profit, binance_order_list_id, status)
        with self._session() as cur:
            return self._insert_trade(cur, params)

    def _insert_trade(self, cur, params: Tuple[Any, ...]) -> int:
        base_query = (
            "INSERT INTO trades (symbol, entry_price, quantity, stop_loss, take_profit, binance_order_list_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        if self.is_postgres:
            cur.execute(self._sql(base_query + " RETURNING id"), params)
            return int(cur.fetchone()[0])
        cur.execute(base_query, params)
        return int(cur.lastrowid)

    def close_trade(self, trade_id: int, exit_price: float, status: str, pnl_usd: float) -> None:
        """Registra o encerramento de um trade com status e PnL apurado."""
        now_str = datetime.utcnow().isoformat()
        query = self._sql(
            "UPDATE trades SET exit_price = ?, status = ?, pnl_usd = ?, closed_at = ? WHERE id = ?"
        )
        with self._session() as cur:
            cur.execute(query, (exit_price, status, pnl_usd, now_str, trade_id))

    def update_trade_take_profit(self, trade_id: int, new_take_profit: float) -> None:
        """Recalibra o Take Profit de uma posição aberta para giro rápido de Day Trade."""
        query = self._sql("UPDATE trades SET take_profit = ? WHERE id = ?")
        with self._session() as cur:
            cur.execute(query, (float(new_take_profit), int(trade_id)))

    def update_trade_stop_loss(self, trade_id: int, new_stop_loss: float) -> None:
        """Recalibra o Stop Loss de Catástrofe (-7.5%) de uma posição aberta."""
        query = self._sql("UPDATE trades SET stop_loss = ? WHERE id = ?")
        with self._session() as cur:
            cur.execute(query, (float(new_stop_loss), int(trade_id)))

    def get_unrecovered_loss_usd(self, exclude_trade_id: int = 0) -> float:
        """
        Calcula o saldo de prejuízo acumulado ainda não recuperado pelos lucros subsequentes
        (High-Water Mark das operações fechadas no ciclo atual, id >= 4).
        """
        query = self._sql(
            "SELECT pnl_usd FROM trades "
            "WHERE status LIKE ? AND id >= 4 AND id != ? "
            "ORDER BY id ASC"
        )
        with self._session() as cur:
            cur.execute(query, ("CLOSED_%", int(exclude_trade_id)))
            rows = cur.fetchall()
            return self._accumulate_drawdown_deficit(rows)

    @staticmethod
    def _accumulate_drawdown_deficit(rows: List[Any]) -> float:
        deficit = 0.0
        for row in rows:
            pnl = float(row[0] or 0.0)
            deficit = max(0.0, round(deficit - pnl, 2))
        return deficit

    def save_consensus_log(
        self,
        symbol: str,
        tech_score: float,
        sent_score: float,
        final_score: float,
        veto_applied: bool,
        reasoning_summary: str
    ) -> None:
        """Salva uma deliberação individual (mantido por compatibilidade)."""
        self.save_consensus_logs_batch([{
            "symbol": symbol,
            "tech_score": tech_score,
            "sent_score": sent_score,
            "final_score": final_score,
            "veto": veto_applied,
            "summary": reasoning_summary,
        }])

    def save_consensus_logs_batch(self, deliberations: Sequence[Dict[str, Any]]) -> None:
        """
        Salva todas as deliberações do ciclo em uma única transação e conexão (Batch Insert),
        eliminando o problema de N+1 conexões/inserts no loop da Watchlist.
        """
        if not deliberations:
            return
        query = self._sql(
            "INSERT INTO consensus_logs "
            "(symbol, technical_score, sentiment_score, final_score, veto_applied, reasoning_summary) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        rows = [self._to_consensus_tuple(d) for d in deliberations]
        with self._session() as cur:
            cur.executemany(query, rows)

    def _to_consensus_tuple(self, item: Dict[str, Any]) -> Tuple[Any, ...]:
        veto_bool = bool(item.get("veto", item.get("veto_applied", False)))
        veto_db = veto_bool if self.is_postgres else (1 if veto_bool else 0)
        return (
            item["symbol"],
            float(item["tech_score"]),
            float(item["sent_score"]),
            float(item["final_score"]),
            veto_db,
            str(item.get("summary", item.get("reasoning_summary", ""))),
        )

    def get_recent_trades(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Busca histórico recente de operações."""
        with self._session() as cur:
            return self._fetch_recent_trades_in_cursor(cur, limit)

    def get_recent_consensus(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Busca histórico recente das notas do comitê."""
        with self._session() as cur:
            return self._fetch_recent_consensus_in_cursor(cur, limit)

    def has_recent_consensus(self, minutes: int = 45) -> bool:
        """Verifica se o Comitê de IA já rodou recentemente para poupar cota em execuções de 15min."""
        with self._session() as cur:
            return self._check_recent_consensus_in_cursor(cur, minutes)

    def _check_recent_consensus_in_cursor(self, cur, minutes: int) -> bool:
        if self.is_postgres:
            cur.execute(
                "SELECT 1 FROM consensus_logs "
                "WHERE symbol NOT LIKE %s AND created_at >= NOW() - (%s * INTERVAL '1 minute') LIMIT 1",
                ("SYSTEM/%", int(minutes)),
            )
            return cur.fetchone() is not None

        cur.execute(
            "SELECT 1 FROM consensus_logs "
            "WHERE symbol NOT LIKE ? AND created_at >= datetime('now', ?) LIMIT 1",
            ("SYSTEM/%", f"-{int(minutes)} minutes"),
        )
        return cur.fetchone() is not None

    def has_system_marker_since(self, marker_symbol: str, minutes: int = 90) -> bool:
        """Verifica se um marcador de sistema (ex: SYSTEM/EOD ou SYSTEM/RESTART) já foi registrado na janela."""
        with self._session() as cur:
            return self._check_system_marker_in_cursor(cur, marker_symbol, minutes)

    def _check_system_marker_in_cursor(self, cur, marker_symbol: str, minutes: int) -> bool:
        if self.is_postgres:
            cur.execute(
                "SELECT 1 FROM consensus_logs "
                "WHERE symbol = %s AND created_at >= NOW() - (%s * INTERVAL '1 minute') LIMIT 1",
                (marker_symbol, int(minutes)),
            )
            return cur.fetchone() is not None

        cur.execute(
            "SELECT 1 FROM consensus_logs "
            "WHERE symbol = ? AND created_at >= datetime('now', ?) LIMIT 1",
            (marker_symbol, f"-{int(minutes)} minutes"),
        )
        return cur.fetchone() is not None

    def save_system_marker(self, marker_symbol: str, note: str) -> None:
        """Grava um marcador de controle (como aviso de fim de dia ou reinício) no banco."""
        self.save_consensus_log(
            symbol=marker_symbol,
            tech_score=100.0,
            sent_score=100.0,
            final_score=100.0,
            veto_applied=False,
            reasoning_summary=note,
        )

    def get_daily_summary_stats(self) -> Dict[str, Any]:
        """Consolida os números das últimas 24h em uma única sessão para o relatório das 22h BRT."""
        with self._session() as cur:
            ledger = self._fetch_ledger_in_cursor(cur)
            open_trades = self._fetch_open_trades_in_cursor(cur)
            recent_trades = self._fetch_recent_trades_in_cursor(cur, limit=50)

            invested_usd = sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)
            current_total = round(float(ledger["trading_balance"]) + float(ledger["withdrawable_pool"]), 2)
            free_cash = max(0.0, round(float(ledger["trading_balance"]) - invested_usd, 2))

            closed_trades = [t for t in recent_trades if str(t.get("status", "")).startswith("CLOSED_")]
            today_pnl = round(sum(float(t.get("pnl_usd", 0.0)) for t in closed_trades), 2)
            start_total = round(current_total - today_pnl, 2)

            return {
                "start_total": start_total,
                "start_of_day_total": start_total,
                "current_total": current_total,
                "end_of_day_total": current_total,
                "trading_balance": round(float(ledger["trading_balance"]), 2),
                "withdrawable_pool": round(float(ledger["withdrawable_pool"]), 2),
                "invested_usd": round(invested_usd, 2),
                "free_cash": free_cash,
                "free_cash_usd": free_cash,
                "open_count": len(open_trades),
                "open_trades_count": len(open_trades),
                "closed_count": len(closed_trades),
                "closed_today_count": len(closed_trades),
                "today_pnl": today_pnl,
                "day_profit_usd": today_pnl,
            }

    def get_dashboard_overview(self, trades_limit: int = 10, consensus_limit: int = 10) -> Dict[str, Any]:
        """
        Carrega todos os dados do painel em uma única conexão ao banco,
        eliminando as conexões separadas por carregamento de tela.
        """
        with self._session() as cur:
            open_trades = self._fetch_open_trades_in_cursor(cur)
            return {
                "db_mode": "Neon PostgreSQL" if self.is_postgres else "SQLite Local",
                "ledger": self._fetch_ledger_in_cursor(cur),
                "ledger_history": self._fetch_ledger_history_in_cursor(cur, limit=30),
                "open_trade": open_trades[0] if open_trades else None,
                "open_trades": open_trades,
                "recent_trades": self._fetch_recent_trades_in_cursor(cur, trades_limit),
                "recent_consensus": self._fetch_recent_consensus_in_cursor(cur, consensus_limit),
            }

    def _fetch_ledger_history_in_cursor(self, cur, limit: int = 30) -> List[Dict[str, Any]]:
        query = self._sql(
            "SELECT id, trading_balance, withdrawable_pool, updated_at "
            "FROM portfolio_ledger ORDER BY id DESC LIMIT ?"
        )
        cur.execute(query, (int(limit),))
        rows = self._rows_to_dicts(cur, cur.fetchall())
        return list(reversed(rows))

    @staticmethod
    def _fetch_ledger_in_cursor(cur) -> Dict[str, float]:
        cur.execute("SELECT trading_balance, withdrawable_pool FROM portfolio_ledger ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return {"trading_balance": 1000.0, "withdrawable_pool": 0.0}
        return {"trading_balance": float(row[0]), "withdrawable_pool": float(row[1])}

    def _fetch_open_trade_in_cursor(self, cur) -> Optional[Dict[str, Any]]:
        trades = self._fetch_open_trades_in_cursor(cur)
        return trades[0] if trades else None

    def _fetch_open_trades_in_cursor(self, cur) -> List[Dict[str, Any]]:
        cur.execute("SELECT * FROM trades WHERE status = 'OPEN_OCO' ORDER BY id DESC")
        return self._rows_to_dicts(cur, cur.fetchall())

    def _fetch_recent_trades_in_cursor(self, cur, limit: int) -> List[Dict[str, Any]]:
        query = self._sql("SELECT * FROM trades ORDER BY id DESC LIMIT ?")
        cur.execute(query, (int(limit),))
        return self._rows_to_dicts(cur, cur.fetchall())

    def _fetch_recent_consensus_in_cursor(self, cur, limit: int) -> List[Dict[str, Any]]:
        query = self._sql(
            "SELECT * FROM consensus_logs WHERE symbol NOT LIKE ? ORDER BY id DESC LIMIT ?"
        )
        cur.execute(query, ("SYSTEM/%", int(limit)))
        return self._rows_to_dicts(cur, cur.fetchall())

    def _rows_to_dicts(self, cur, rows: List[Any]) -> List[Dict[str, Any]]:
        return [self._row_to_dict(cur, r) for r in rows]

    def _row_to_dict(self, cur, row: Any) -> Dict[str, Any]:
        if self.is_postgres:
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))
        return dict(row)
