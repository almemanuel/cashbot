"""
CashBot Web Server & PWA Host (Zero-Admin / Zero-Node)
Executa nativamente em Python, serve o app PWA para PC e Celular
e conecta a interface ao robô de trading e às notificações instantâneas.
"""

import os
import sys
import json
import socket
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

# Adiciona o diretório do engine ao sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.path.join(BASE_DIR, "engine")
STATIC_DIR = os.path.join(BASE_DIR, "web", "public")
sys.path.append(ENGINE_DIR)

from database import Database
from main import TradingEngine
from notifier import TelegramNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("cashbot.web")

def get_local_ip():
    """Detecta o IP local na rede Wi-Fi para abrir no celular."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

class CashBotHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def _send_json(self, data, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/overview":
            db = Database()
            ledger = db.get_ledger()
            open_trade = db.get_open_trade()
            recent_trades = db.get_recent_trades(10)
            recent_consensus = db.get_recent_consensus(10)
            self._send_json({
                "ledger": ledger,
                "open_trade": open_trade,
                "recent_trades": recent_trades,
                "recent_consensus": recent_consensus
            })
            return

        # Serve arquivos estáticos do PWA
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""
        payload = {}
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:
                pass

        db = Database()
        notifier = TelegramNotifier()

        # 1. Executar Varredura
        if parsed.path == "/api/run-cycle":
            try:
                engine = TradingEngine(force_simulation=True)
                engine.run_cycle(force_opportunity=False)
                self._send_json({"success": True, "message": "Varredura executada! Veja os logs na aba Comitê IA."})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # 2. Forçar Compra Simulada
        if parsed.path == "/api/simulate-buy":
            try:
                # Se já houver trade aberto, fecha antes para abrir outro
                open_trade = db.get_open_trade()
                if open_trade:
                    db.close_trade(open_trade["id"], float(open_trade["entry_price"]), "CLOSED_SIM", 0.0)

                engine = TradingEngine(force_simulation=True)
                engine.run_cycle(force_opportunity=True)
                self._send_json({"success": True, "message": "Ordem de compra simulada e OCO armada com sucesso!"})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # 3. Simular Fechamento no Take Profit (Lucro)
        if parsed.path == "/api/simulate-tp":
            try:
                open_trade = db.get_open_trade()
                if not open_trade:
                    self._send_json({"success": False, "error": "Nenhum trade aberto para fechar no Take Profit."}, 400)
                    return

                entry = float(open_trade["entry_price"])
                tp = float(open_trade["take_profit"])
                qty = float(open_trade["quantity"])
                pnl = round((tp - entry) * qty, 2)

                db.close_trade(open_trade["id"], tp, "CLOSED_TP", pnl)

                # Divide 50% de lucro para saque Pix e 50% para giro
                to_withdraw = round(pnl * 0.50, 2)
                to_reinvest = round(pnl * 0.50, 2)
                ledger = db.get_ledger()
                new_trading = ledger["trading_balance"] + to_reinvest
                new_pool = ledger["withdrawable_pool"] + to_withdraw
                db.update_ledger(new_trading, new_pool)

                # Notifica no celular
                notifier.notify_order_closed(
                    symbol=open_trade["symbol"],
                    outcome="TP",
                    entry_price=entry,
                    exit_price=tp,
                    pnl_usd=pnl,
                    to_withdraw=to_withdraw,
                    to_reinvest=to_reinvest,
                    is_simulated=True
                )
                self._send_json({
                    "success": True,
                    "message": f"🎯 Take Profit atingido! +${pnl:.2f} de lucro apurado (+${to_withdraw:.2f} no Pool de Saque)."
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # 4. Simular Fechamento no Stop Loss
        if parsed.path == "/api/simulate-sl":
            try:
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

                # Notifica no celular
                notifier.notify_order_closed(
                    symbol=open_trade["symbol"],
                    outcome="SL",
                    entry_price=entry,
                    exit_price=sl,
                    pnl_usd=pnl,
                    to_withdraw=0.0,
                    to_reinvest=0.0,
                    is_simulated=True
                )
                self._send_json({
                    "success": True,
                    "message": f"🛑 Stop Loss executado. Risco contido em ${abs(pnl):.2f}."
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # 5. Testar Notificação Telegram
        if parsed.path == "/api/test-notification":
            if not notifier.is_configured:
                self._send_json({
                    "success": False,
                    "error": "Telegram ainda não configurado. Salve seu Bot Token e Chat ID primeiro."
                }, 400)
                return

            ok = notifier.send_message("📱 <b>CashBot:</b> Teste de notificação recebido com sucesso no seu celular!")
            if ok:
                self._send_json({"success": True, "message": "Notificação enviada! Olhe seu Telegram no celular."})
            else:
                self._send_json({"success": False, "error": "Erro ao enviar mensagem pelo Telegram."}, 500)
            return

        # 6. Salvar Configuração
        if parsed.path == "/api/save-config":
            token = payload.get("TELEGRAM_BOT_TOKEN")
            chat_id = payload.get("TELEGRAM_CHAT_ID")
            env_file = os.path.join(BASE_DIR, ".env")
            
            # Lê .env existente ou cria
            env_lines = []
            if os.path.exists(env_file):
                with open(env_file, "r", encoding="utf-8") as f:
                    env_lines = f.readlines()

            new_lines = []
            token_set = False
            chat_set = False
            for line in env_lines:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    new_lines.append(f"TELEGRAM_BOT_TOKEN={token}\n")
                    token_set = True
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")
                    chat_set = True
                else:
                    new_lines.append(line)

            if not token_set:
                new_lines.append(f"TELEGRAM_BOT_TOKEN={token}\n")
            if not chat_set:
                new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}\n")

            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            # Atualiza no processo atual
            os.environ["TELEGRAM_BOT_TOKEN"] = token
            os.environ["TELEGRAM_CHAT_ID"] = chat_id

            self._send_json({"success": True, "message": "Credenciais salvas com sucesso!"})
            return

        self._send_json({"error": "Endpoint não encontrado"}, 404)

def run_server(port=8080):
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, CashBotHandler)
    local_ip = get_local_ip()

    print("\n" + "="*60)
    print("🚀 CashBot Web App & PWA Server Iniciado com Sucesso!")
    print("="*60)
    print(f"💻 Acesso no PC:     http://localhost:{port}")
    print(f"📱 Acesso no Celular: http://{local_ip}:{port}")
    print("="*60)
    print("👉 Dica no celular: Abra o link acima no Chrome/Safari e toque em")
    print("   'Adicionar à Tela de Início' para instalar como App nativo!")
    print("="*60 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor finalizado pelo usuário.")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)

