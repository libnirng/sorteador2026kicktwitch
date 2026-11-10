"""Servidor para o iniciador gráfico, com parada graciosa via stdin.

O controle de parada usa um pipe privado, não um endpoint HTTP público.
O servidor principal continua escutando somente em 127.0.0.1:8777.
"""
from __future__ import annotations

import os
import sys
import threading

import uvicorn


def main() -> int:
    # A porta alternativa existe apenas para testes locais isolados.
    port = int(os.environ.get('SORTEADOR_LAUNCHER_TEST_PORT', '8777'))
    if not 1 <= port <= 65535:
        raise ValueError('Porta inválida.')
    config = uvicorn.Config('servidor.app:app', host='127.0.0.1', port=port,
                            log_level='info', access_log=False)
    server = uvicorn.Server(config)

    def listen_for_stop() -> None:
        try:
            for command in sys.stdin:
                if command.strip().lower() == 'parar':
                    print('Solicitação de encerramento recebida.', flush=True)
                    server.should_exit = True
                    break
        except (OSError, ValueError):
            pass

    threading.Thread(target=listen_for_stop, name='LauncherStop', daemon=True).start()
    server.run()
    return 0 if server.started else 1


if __name__ == '__main__':
    raise SystemExit(main())
