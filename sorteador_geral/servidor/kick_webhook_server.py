"""Servidor receptor de webhooks da Kick.

Este módulo inicia um servidor HTTP separado na porta 8766 (configurável)
para receber exclusivamente webhooks da Kick.

Ele NÃO expõe:
- Painel administrativo
- Rotas OAuth
- API de gerenciamento
- Overlays OBS
- Banco SQLite

Apenas aceita POST /api/webhooks/kick e repassa para validação.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import queue
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import base64

logger = logging.getLogger(__name__)

# Porta padrão para o receptor de webhooks
from .state import STATE

DEFAULT_WEBHOOK_PORT = 8766

# Fila de processamento
_processing_queue: queue.Queue | None = None
_queue_lock = threading.Lock()
_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_thread: threading.Thread | None = None
_worker_started = threading.Event()
_app_loop = None

def set_app_loop(loop):
    global _app_loop
    _app_loop = loop


# Cache da chave pública
_public_key: str | None = None
_public_key_cached_at: float = 0
_public_key_lock = threading.Lock()


def _get_public_key() -> str | None:
    """Retorna a chave pública cacheada."""
    global _public_key, _public_key_cached_at
    with _public_key_lock:
        now = time.time()
        if _public_key and (now - _public_key_cached_at) < 3600:
            return _public_key
        return None


def _set_public_key(key: str) -> None:
    """Define a chave pública cacheada."""
    global _public_key, _public_key_cached_at
    with _public_key_lock:
        _public_key = key
        _public_key_cached_at = time.time()


def _ensure_worker():
    """Garante que o worker existe e está rodando."""
    global _processing_queue, _worker_loop, _worker_thread

    with _queue_lock:
        if _processing_queue is None:
            _processing_queue = queue.Queue(maxsize=1000)

        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_worker_loop)

            def run():
                asyncio.set_event_loop(_worker_loop)
                _worker_started.set()
                _worker_loop.run_forever()

            _worker_thread = threading.Thread(target=run, daemon=True, name='webhook_worker')
            _worker_thread.start()
            _worker_started.wait(timeout=2.0)


def _verify_signature_sync(message_id: str, timestamp: str, raw_body: bytes, signature_b64: str) -> tuple[bool, str]:
    """Valida a assinatura RSA-SHA256 de forma síncrona.

    Returns:
        (is_valid, error_message)
    """
    if not signature_b64:
        return False, 'Assinatura ausente'

    try:
        signature = base64.b64decode(signature_b64)
    except Exception:
        return False, 'Assinatura invalida (decode)'

    try:
        public_key_pem = _get_public_key()
        if not public_key_pem:
            # Tenta buscar do cache do validador
            from .kick_webhook import get_validator
            validator = get_validator()
            # Acesso síncrono ao cache (pode não existir na primeira chamada)
            if hasattr(validator._public_key_cache, '_key') and validator._public_key_cache._key:
                public_key_pem = validator._public_key_cache._key
            else:
                return False, 'Chave publica indisponivel'

        public_key = serialization.load_pem_public_key(
            public_key_pem.encode('utf-8'),
            backend=default_backend(),
        )

        # Monta dados assinados: message_id.timestamp.raw_body
        message_data = f'{message_id}.{timestamp}.{raw_body.decode("utf-8")}'.encode('utf-8')
        hashed = hashlib.sha256(message_data).digest()

        public_key.verify(
            signature,
            message_data,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

        return True, ''

    except Exception as e:
        return False, f'Assinatura invalida: {e!r}'


async def _process_webhook(headers: dict, raw_body: bytes, start_time: float):
    """Processa um webhook de forma assíncrona."""
    from .kick_webhook import get_validator, verify_broadcaster
    from .kick_chat_auth import get_kick_auth

    try:
        # Valida evento
        validator = get_validator()
        is_valid, error, event = await validator.validate_event(headers, raw_body)

        if not is_valid:
            elapsed = time.time() - start_time
            logger.warning(f'Webhook rejeitado em {elapsed*1000:.1f}ms: {error}')
            return

        elapsed = time.time() - start_time
        logger.info(f'Webhook valido em {elapsed*1000:.1f}ms: type={event.event_type}, msg_id={event.message_id[:16]}...')

        # Verifica broadcaster
        auth = get_kick_auth()
        status = auth.get_status()

        if status.broadcaster_user_id and not verify_broadcaster(event, status.broadcaster_user_id):
            elapsed = time.time() - start_time
            logger.warning(f'Webhook: broadcaster mismatch em {elapsed*1000:.1f}ms')
            return

        # Encaminha para o ChatManager
        if event.event_type == 'chat.message.sent':
            try:
                from .chat_manager import get_chat_manager
                manager = get_chat_manager()
                STATE.last_kick_webhook_ts = time.time()
                STATE.kick_total_messages = getattr(STATE, 'kick_total_messages', 0) + 1
                STATE.last_kick_participant = event.sender_username
                processed = manager.handle_kick_webhook_event(event)

                elapsed = time.time() - start_time
                logger.info(f'Webhook processado em {elapsed*1000:.1f}ms')
            except Exception as e:
                logger.error(f'Erro ao processar webhook: {e!r}')
        else:
            logger.debug(f'Evento nao-processado: {event.event_type}')

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f'Erro no processamento de webhook em {elapsed*1000:.1f}ms: {e!r}')


class KickWebhookOnlyHandler(BaseHTTPRequestHandler):
    """Handler que aceita apenas POST /api/webhooks/kick.

    Responde rapidamente e processa em background.
    """

    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def do_POST(self):
        """Aceita apenas POST /api/webhooks/kick."""
        start_time = time.time()

        parsed = urlparse(self.path)

        if parsed.path != '/api/webhooks/kick':
            self.send_error(404, 'Not Found')
            return

        # Lê corpo
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            self.send_error(400, 'Invalid Content-Length')
            return
        if content_length > 1024 * 1024:  # 1MB max
            self.send_error(413, 'Payload Too Large')
            return
        if content_length <= 0:
            self.send_error(400, 'Bad Request')
            return

        try:
            raw_body = self.rfile.read(content_length)
        except Exception as e:
            logger.warning(f'Falha ao ler corpo: {e!r}')
            self.send_error(400, 'Bad Request')
            return

        # Extrai headers do Kick
        message_id = self.headers.get('Kick-Event-Message-Id', '')
        timestamp = self.headers.get('Kick-Event-Message-Timestamp', '')
        signature = self.headers.get('Kick-Event-Signature', '')

        headers = {
            'Kick-Event-Message-Id': message_id,
            'Kick-Event-Message-Timestamp': timestamp,
            'Kick-Event-Signature': signature,
            'Kick-Event-Type': self.headers.get('Kick-Event-Type', ''),
            'Kick-Event-Version': self.headers.get('Kick-Event-Version', ''),
            'Kick-Event-Subscription-Id': self.headers.get('Kick-Event-Subscription-Id', ''),
        }

        if _app_loop is None or _app_loop.is_closed():
            self.send_error(503, 'Application not ready')
            return
        asyncio.run_coroutine_threadsafe(_process_webhook(headers, raw_body, start_time), _app_loop)
        payload = b'{"ok": true}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        """GET não é aceito."""
        self.send_error(405, 'Method Not Allowed')

    def do_HEAD(self):
        """HEAD não é aceito."""
        self.send_error(405, 'Method Not Allowed')


class WebhookServer:
    """Servidor HTTP dedicado para webhooks da Kick."""

    def __init__(self, port: int = DEFAULT_WEBHOOK_PORT):
        self.port = port
        self.server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_event: threading.Event | None = None

    def start(self) -> bool:
        """Inicia o servidor em thread separada."""
        if self._running:
            return True

        try:
            self.server = HTTPServer(('127.0.0.1', self.port), KickWebhookOnlyHandler)
            self._running = True
            self._stop_event = threading.Event()

            def run():
                logger.info(f'Webhook server iniciado em http://127.0.0.1:{self.port}')
                while self._running and not self._stop_event.is_set():
                    self.server.handle_request()

            self._thread = threading.Thread(target=run, daemon=True)
            self._thread.start()

            return True

        except OSError as e:
            logger.error(f'Falha ao iniciar webhook server: {e!r}')
            return False

    def stop(self):
        """Encerra o servidor."""
        global _processing_queue, _worker_loop, _worker_thread
        self._running = False
        if self._stop_event:
            self._stop_event.set()

        # Envia request para desbloqueiar handle_request
        if self.server:
            try:
                import socket
                s = socket.socket()
                s.settimeout(1)
                s.connect(('127.0.0.1', self.port))
                s.send(b'GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
                s.close()
            except Exception:
                pass

        if self.server:
            try:
                self.server.server_close()
            except Exception:
                pass
            self.server = None
        self._thread = None

        # Para worker
        with _queue_lock:
            if _worker_loop and not _worker_loop.is_closed():
                _worker_loop.call_soon_threadsafe(_worker_loop.stop)
            _worker_loop = None
            _processing_queue = None
            _worker_thread = None

    @property
    def is_running(self) -> bool:
        return self._running


# Instância global
_webhook_server: WebhookServer | None = None


def get_webhook_server() -> WebhookServer:
    """Retorna instância global do servidor de webhook."""
    global _webhook_server
    if _webhook_server is None:
        _webhook_server = WebhookServer()
    return _webhook_server


def start_webhook_server(port: int = DEFAULT_WEBHOOK_PORT) -> bool:
    """Inicia o servidor de webhook."""
    server = get_webhook_server()
    server.port = port
    return server.start()


def stop_webhook_server():
    """Encerra o servidor de webhook."""
    global _webhook_server
    if _webhook_server:
        _webhook_server.stop()
        _webhook_server = None
