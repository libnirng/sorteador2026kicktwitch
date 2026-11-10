"""Gerenciador de túnel ngrok para webhooks.

Este módulo gerencia a conexão ngrok para expor o receptor
de webhooks local para a internet via HTTPS.

O ngrok Free:
- Não requer configuração de DNS ou domínio
- Fornece URL HTTPS aleatória
- Funciona com a conta gratuita
- O domínio é atribuído pela conta ngrok

O usuário precisa:
1. Criar conta em ngrok.com
2. Instalar ngrok no Windows
3. Executar `ngrok config add-authtoken <SEU_TOKEN>` uma vez

O authtoken é configurado LOCALMENTE no ngrok, não neste código.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

# Porta do webhook server
WEBHOOK_PORT = 8766

# Timeout para verificar túnel
TUNNEL_CHECK_INTERVAL = 5  # segundos
TUNNEL_START_TIMEOUT = 30  # segundos


class NgrokManager:
    """Gerenciador do túnel ngrok."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._running = False
        self._ngrok_url: str = ''
        self._last_check = 0.0
        self._check_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        """Retorna True se o túnel está ativo."""
        if not self._running or not self._process:
            return False

        # Verifica se o processo ainda está rodando
        if self._process.poll() is not None:
            self._ngrok_url = ''
            return False

        return bool(self._ngrok_url)

    @property
    def webhook_url(self) -> str:
        """Retorna a URL pública do webhook."""
        return self._ngrok_url

    def start(self) -> tuple[bool, str]:
        """Inicia o túnel ngrok.

        Returns:
            (success, message_or_url)
        """
        if self.is_connected:
            return True, self._ngrok_url

        # Verifica se ngrok está instalado
        if not self._is_ngrok_installed():
            return False, (
                'ngrok não encontrado. Instale o ngrok:\n'
                '1. Baixe em https://ngrok.com/download\n'
                '2. Extraia para uma pasta\n'
                '3. Adicione ao PATH do Windows\n\n'
                'Após instalar, configure seu authtoken:\n'
                'ngrok config add-authtoken <SEU_TOKEN>'
            )

        # Verifica se authtoken está configurado
        if not self._has_authtoken():
            return False, (
                'ngrok sem authtoken configurado.\n\n'
                'Execute este comando uma vez:\n'
                'ngrok config add-authtoken <SEU_TOKEN>\n\n'
                'Encontre seu authtoken em: https://dashboard.ngrok.com/tokens'
            )

        try:
            logger.info('Iniciando ngrok...')

            # Inicia ngrok
            self._process = subprocess.Popen(
                [
                    'ngrok', 'http',
                    '--log', 'stdout',
                    str(WEBHOOK_PORT),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            self._running = True

            # Aguarda URL ser estabelecida
            url = self._wait_for_url(TUNNEL_START_TIMEOUT)

            if url:
                with self._lock:
                    self._ngrok_url = url
                logger.info(f'ngrok conectado: {url}')

                # Inicia thread de verificação
                self._start_check_thread()

                return True, url
            else:
                self.stop()
                return False, 'Timeout ao iniciar ngrok. Verifique sua conexão.'

        except Exception as e:
            logger.error(f'Falha ao iniciar ngrok: {e!r}')
            self.stop()
            return False, f'Erro ao iniciar ngrok: {e!r}'

    def stop(self):
        """Encerra o túnel ngrok."""
        self._running = False

        if self._check_thread:
            try:
                self._check_thread.join(timeout=2)
            except Exception:
                pass
            self._check_thread = None

        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        with self._lock:
            self._ngrok_url = ''

        logger.info('ngrok encerrado')

    def _is_ngrok_installed(self) -> bool:
        """Verifica se ngrok está instalado."""
        try:
            result = subprocess.run(
                ['ngrok', '--version'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _has_authtoken(self) -> bool:
        """Verifica se authtoken está configurado."""
        try:
            result = subprocess.run(
                ['ngrok', 'config', 'check'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Se não houver authtoken, o comando falha
            return result.returncode == 0
        except Exception:
            return False

    def _wait_for_url(self, timeout: float) -> str | None:
        """Aguarda a URL do túnel ser exibida."""
        start = time.time()

        while time.time() - start < timeout:
            if self._process and self._process.poll() is not None:
                # Processo morreu
                return None

            # Lê stdout
            if self._process and self._process.stdout:
                line = self._process.stdout.readline()
                if line:
                    logger.debug(f'ngrok: {line.strip()}')

                    # Procura URL no output
                    if 'https://' in line and '.ngrok' in line:
                        # Extrai URL
                        import re
                        match = re.search(r'https://[a-zA-Z0-9\-]+\.ngrok\.app', line)
                        if match:
                            return match.group(0)

            time.sleep(0.1)

        return None

    def _start_check_thread(self):
        """Inicia thread de verificação de conexão."""
        def check_loop():
            while self._running:
                time.sleep(TUNNEL_CHECK_INTERVAL)

                if not self._running:
                    break

                # Verifica se processo ainda está rodando
                if self._process and self._process.poll() is not None:
                    logger.warning('ngrok desconectado!')
                    with self._lock:
                        self._ngrok_url = ''
                    break

        self._check_thread = threading.Thread(target=check_loop, daemon=True)
        self._check_thread.start()


# Instância global
_ngrok_manager: NgrokManager | None = None


def get_ngrok_manager() -> NgrokManager:
    """Retorna instância global do gerenciador ngrok."""
    global _ngrok_manager
    if _ngrok_manager is None:
        _ngrok_manager = NgrokManager()
    return _ngrok_manager


def start_ngrok() -> tuple[bool, str]:
    """Inicia o túnel ngrok."""
    manager = get_ngrok_manager()
    return manager.start()


def stop_ngrok():
    """Encerra o túnel ngrok."""
    global _ngrok_manager
    if _ngrok_manager:
        _ngrok_manager.stop()
        _ngrok_manager = None


def get_webhook_public_url() -> str:
    """Retorna a URL pública do webhook (se ngrok estiver ativo)."""
    manager = get_ngrok_manager()
    return manager.webhook_url


def is_ngrok_connected() -> bool:
    """Retorna True se ngrok está conectado."""
    manager = get_ngrok_manager()
    return manager.is_connected
