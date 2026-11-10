"""
CashBot Web Server & PWA Host (Zero-Admin / Zero-Node)
Executa nativamente em Python, serve o app PWA para PC e Celular
e conecta a interface ao robô de trading e às notificações instantâneas.
Segue Object Calisthenics (despacho de rotas sem cadeia de if/else, 1 nível de indentação) e leitura unificada sem N+1.
"""

import os
import sys
import hmac
import hashlib
import json
import time
import socket
import logging
import threading
from typing import Dict, Any, Callable, List, Optional
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
import requests

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(BASE_DIR, "engine")
STATIC_DIR = os.path.join(BASE_DIR, "web", "public")
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(ENGINE_DIR, ".env"), override=True)
sys.path.append(ENGINE_DIR)

from database import Database
from main import TradingEngine
from notifier import TelegramNotifier
from agents.risk import RiskAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("cashbot.web")

_CYCLE_LOCK = threading.Lock()
DEFAULT_RENDER_URL = "https://cashbot-17wi.onrender.com"


class BackgroundScheduler:
    """
    Agendador Nativo 24/7 em Background (15 em 15 minutos cravados + Auto Keep-Alive no Render).
    Garante execução pontual mesmo quando o cron do GitHub Actions atrasa.
    """

    def __init__(self, interval_seconds: int = 900, keepalive_seconds: int = 45):
        self.interval_seconds = interval_seconds
        self.keepalive_seconds = keepalive_seconds
        self.last_cycle_ts = 0.0
        self.last_ping_ts = 0.0

    def start(self) -> None:
        thread = threading.Thread(target=self._run_loop, daemon=True, name="cashbot-15m-scheduler")
        thread.start()
        logger.info("Agendador nativo 15m + Auto Keep-Alive (45s) iniciado em background.")

    def _run_loop(self) -> None:
        time.sleep(10)
        while True:
            self._tick_keepalive()
            self._tick_trading_cycle()
            time.sleep(15)

    def _tick_keepalive(self) -> None:
        now = time.time()
        if (now - self.last_ping_ts) < self.keepalive_seconds:
            return
        self.last_ping_ts = now
        base_url = os.getenv("RENDER_EXTERNAL_URL", DEFAULT_RENDER_URL).rstrip("/")
        try:
            requests.get(f"{base_url}/api/health", timeout=8)
        except Exception:
            return

    def _tick_trading_cycle(self) -> None:
        now = time.time()
        if (now - self.last_cycle_ts) < self.interval_seconds:
            return
        if not _CYCLE_LOCK.acquire(blocking=False):
            return
        try:
            self.last_cycle_ts = time.time()
            logger.info("[SCHEDULER 15M] Disparando ciclo pontual de Day Trade em background...")
            TradingEngine().run_cycle(force_opportunity=False, bypass_cooldown=False)
        except Exception as e:
            logger.error(f"[SCHEDULER 15M] Erro durante ciclo automático: {e}")
        finally:
            _CYCLE_LOCK.release()


def get_local_ip() -> str:
    """Detecta o IP local na rede Wi-Fi para abrir no celular."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class AuthGuard:
    """Valida senha de acesso e emite/verifica token HMAC-SHA256 stateless."""

    @staticmethod
    def _current_password() -> str:
        return os.getenv("APP_PASSWORD", "admin123").strip() or "admin123"

    @classmethod
    def expected_token(cls) -> str:
        secret = cls._current_password().encode("utf-8")
        return hmac.new(secret, b"cashbot-auth-v1", hashlib.sha256).hexdigest()

    @classmethod
    def verify_password(cls, candidate: str) -> Optional[str]:
        expected_pwd = cls._current_password()
        if hmac.compare_digest(candidate.strip(), expected_pwd):
            return cls.expected_token()
        return None

    @classmethod
    def is_authorized(cls, auth_header: str) -> bool:
        if not auth_header.startswith("Bearer "):
            return False
        provided = auth_header[7:].strip()
        return hmac.compare_digest(provided, cls.expected_token())


class EnvConfigUpdater:
    """Encapsula a atualização de chaves no arquivo .env sem aninhamento."""

    def __init__(self, env_path: str):
        self.env_path = env_path

    def update_keys(self, updates: Dict[str, str]) -> None:
        existing_lines = self._read_lines()
        merged_lines = self._merge_lines(existing_lines, updates)
        self._write_lines(merged_lines)
        self._apply_to_process_env(updates)

    def _read_lines(self) -> List[str]:
        if not os.path.exists(self.env_path):
            return []
        with open(self.env_path, "r", encoding="utf-8") as f:
            return f.readlines()

    def _merge_lines(self, lines: List[str], updates: Dict[str, str]) -> List[str]:
        filtered = [line for line in lines if not self._matches_any_key(line, updates)]
        appended = [f"{k}={v}\n" for k, v in updates.items()]
        return filtered + appended

    @staticmethod
    def _matches_any_key(line: str, updates: Dict[str, str]) -> bool:
        return any(line.startswith(f"{k}=") for k in updates)

    def _write_lines(self, lines: List[str]) -> None:
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    @staticmethod
    def _apply_to_process_env(updates: Dict[str, str]) -> None:
        for k, v in updates.items():
            os.environ[k] = v


class CashBotHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_json(self, data: Dict[str, Any], status_code: int = 200) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _require_auth(self) -> bool:
        auth_header = str(self.headers.get("Authorization", ""))
        if AuthGuard.is_authorized(auth_header):
            return True
        self._send_json({"success": False, "error": "Não autorizado. Faça login."}, 401)
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok", "ts": int(time.time())})
            return
        if parsed.path == "/api/overview":
            self._handle_get_overview()
            return

        super().do_GET()

    def _handle_get_overview(self) -> None:
        if not self._require_auth():
            return
        self._execute_route_safely(self._send_overview_payload, {})

    def _send_overview_payload(self, _payload: Dict[str, Any]) -> None:
        db = Database()
        self._send_json(db.get_dashboard_overview(trades_limit=10, consensus_limit=10))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self._read_json_body()

        if parsed.path == "/api/login":
            self._handle_login(payload)
            return

        if not self._require_auth():
            return

        routes = self._post_routes()
        handler = routes.get(parsed.path)

        if handler is None:
            self._send_json({"error": "Endpoint não encontrado"}, 404)
            return

        self._execute_route_safely(handler, payload)

    def _handle_login(self, payload: Dict[str, Any]) -> None:
        password = str(payload.get("password", ""))
        token = AuthGuard.verify_password(password)
        if token is None:
            self._send_json({"success": False, "error": "Senha incorreta."}, 401)
            return
        self._send_json({"success": True, "token": token})

    def _post_routes(self) -> Dict[str, Callable[[Dict[str, Any]], None]]:
        return {
            "/api/run-cycle": self._handle_run_cycle,
            "/api/simulate-buy": self._handle_simulate_buy,
            "/api/simulate-tp": self._handle_simulate_tp,
            "/api/simulate-sl": self._handle_simulate_sl,
            "/api/confirm-withdraw": self._handle_confirm_withdraw,
            "/api/test-notification": self._handle_test_notification,
            "/api/save-config": self._handle_save_config,
            "/api/reset-simulation": self._handle_reset_simulation,
        }

    def _execute_route_safely(
        self,
        handler: Callable[[Dict[str, Any]], None],
        payload: Dict[str, Any]
    ) -> None:
        try:
            handler(payload)
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, 500)

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length)
        return self._parse_json_bytes(body)

    @staticmethod
    def _parse_json_bytes(body: bytes) -> Dict[str, Any]:
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    def _handle_run_cycle(self, _payload: Dict[str, Any]) -> None:
        if not _CYCLE_LOCK.acquire(blocking=False):
            self._send_json({"success": True, "message": "Já existe uma varredura em andamento! Aguarde alguns segundos."})
            return
        try:
            engine = TradingEngine()
            engine.run_cycle(force_opportunity=False, bypass_cooldown=True)
            self._send_json({"success": True, "message": "Varredura executada! Veja os logs na aba Comitê IA."})
        finally:
            _CYCLE_LOCK.release()

    def _handle_simulate_buy(self, _payload: Dict[str, Any]) -> None:
        db = Database()
        open_trade = db.get_open_trade()
        if open_trade:
            db.close_trade(open_trade["id"], float(open_trade["entry_price"]), "CLOSED_SIM", 0.0)

        engine = TradingEngine(force_simulation=True)
        engine.run_cycle(force_opportunity=True)
        self._send_json({"success": True, "message": "Ordem de compra simulada e OCO armada com sucesso!"})

    def _handle_simulate_tp(self, _payload: Dict[str, Any]) -> None:
        db = Database()
        open_trade = db.get_open_trade()
        if not open_trade:
            self._send_json({"success": False, "error": "Nenhum trade aberto para fechar no Take Profit."}, 400)
            return

        entry = float(open_trade["entry_price"])
        tp = float(open_trade["take_profit"])
        qty = float(open_trade["quantity"])
        pnl = round((tp - entry) * qty, 2)

        db.close_trade(open_trade["id"], tp, "CLOSED_TP", pnl)

        ledger = db.get_ledger()
        new_trading, new_pool, to_withdraw, to_reinvest = RiskAgent().allocate_trade_pnl(
            trading_balance=ledger["trading_balance"],
            withdrawable_pool=ledger["withdrawable_pool"],
            pnl_usd=pnl,
        )
        db.update_ledger(new_trading, new_pool)

        TelegramNotifier().notify_order_closed(
            symbol=open_trade["symbol"],
            outcome="TP",
            entry_price=entry,
            exit_price=tp,
            pnl_usd=pnl,
            to_withdraw=to_withdraw,
            to_reinvest=to_reinvest,
            is_simulated=True,
            new_trading_balance=new_trading,
            new_withdrawable_pool=new_pool,
        )
        self._send_json({
            "success": True,
            "message": (
                f"🎯 Take Profit atingido! +${pnl:.2f} de lucro "
                f"(+${to_withdraw:.2f} liberado p/ Saque Pix | Total disponível p/ Saque: ${new_pool:.2f})."
            ),
        })

    def _handle_simulate_sl(self, _payload: Dict[str, Any]) -> None:
        db = Database()
        open_trade = db.get_open_trade()
        if not open_trade:
            self._send_json({"success": False, "error": "Nenhum trade aberto para encerrar no Stop Loss."}, 400)
            return

        entry = float(open_trade["entry_price"])
        sl = float(open_trade["stop_loss"])
        qty = float(open_trade["quantity"])
        pnl = round((sl - entry) * qty, 2)

        db.close_trade(open_trade["id"], sl, "CLOSED_SL", pnl)
        ledger = db.get_ledger()
        new_trading = max(0.0, ledger["trading_balance"] + pnl)
        db.update_ledger(new_trading, ledger["withdrawable_pool"])

        TelegramNotifier().notify_order_closed(
            symbol=open_trade["symbol"],
            outcome="SL",
            entry_price=entry,
            exit_price=sl,
            pnl_usd=pnl,
            to_withdraw=0.0,
            to_reinvest=0.0,
            is_simulated=True,
        )
        self._send_json({
            "success": True,
            "message": f"🛑 Stop Loss executado. Risco contido em ${abs(pnl):.2f}.",
        })

    def _handle_confirm_withdraw(self, _payload: Dict[str, Any]) -> None:
        db = Database()
        ledger = db.get_ledger()
        withdrawn = ledger["withdrawable_pool"]
        if withdrawn <= 0:
            self._send_json({"success": False, "error": "Ainda não há saldo acumulado no Pool de Saque."}, 400)
            return

        db.update_ledger(ledger["trading_balance"], 0.0)
        self._send_json({
            "success": True,
            "message": f"💸 Saque de ${withdrawn:.2f} registrado! Seu Capital de Giro (${ledger['trading_balance']:.2f}) segue intacto.",
        })

    def _handle_test_notification(self, _payload: Dict[str, Any]) -> None:
        notifier = TelegramNotifier()
        if not notifier.is_configured:
            self._send_json({
                "success": False,
                "error": "Telegram ainda não configurado. Salve seu Bot Token e Chat ID primeiro.",
            }, 400)
            return

        ok = notifier.send_message("📱 <b>CashBot:</b> Teste de notificação recebido com sucesso no seu celular!")
        if not ok:
            self._send_json({"success": False, "error": "Erro ao enviar mensagem pelo Telegram."}, 500)
            return

        self._send_json({"success": True, "message": "Notificação enviada! Olhe seu Telegram no celular."})

    def _handle_save_config(self, payload: Dict[str, Any]) -> None:
        token = str(payload.get("TELEGRAM_BOT_TOKEN", "")).strip()
        chat_id = str(payload.get("TELEGRAM_CHAT_ID", "")).strip()
        target_env = os.path.join(ENGINE_DIR, ".env") if os.path.exists(os.path.join(ENGINE_DIR, ".env")) else os.path.join(BASE_DIR, ".env")
        updater = EnvConfigUpdater(target_env)
        updater.update_keys({
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_CHAT_ID": chat_id,
        })
        self._send_json({"success": True, "message": "Credenciais salvas com sucesso!"})

    def _handle_reset_simulation(self, payload: Dict[str, Any]) -> None:
        initial = float(payload.get("initial_capital", 1000.0))
        Database().reset_simulation(initial)
        self._send_json({"success": True, "message": f"Simulação reiniciada com ${initial:,.2f} USD."})


def run_server(port: int = 8080) -> None:
    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, CashBotHandler)
    local_ip = get_local_ip()
    BackgroundScheduler().start()

    print("\n" + "=" * 60)
    print("🚀 CashBot Web App & PWA Server Iniciado com Sucesso!")
    print("=" * 60)
    print(f"💻 Acesso no PC:     http://localhost:{port}")
    print(f"📱 Acesso no Celular: http://{local_ip}:{port}")
    print("=" * 60)
    print("👉 Dica no celular: Abra o link acima no Chrome/Safari e toque em")
    print("   'Adicionar à Tela de Início' para instalar como App nativo!")
    print("=" * 60 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor finalizado pelo usuário.")
        httpd.server_close()


if __name__ == "__main__":
    default_port = int(os.getenv("PORT", "8080"))
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else default_port
    run_server(port_arg)
