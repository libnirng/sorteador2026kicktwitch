"""Central gráfica do Sorteador Geral (Tkinter, sem dependências de interface extras).

Inicia o servidor em processo separado, acompanha logs e encerra-o de modo
gracioso ao receber o comando privado no stdin do processo filho.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
HOST = '127.0.0.1'
PORT = 8777
BASE_URL = f'http://{HOST}:{PORT}'
ADMIN_URL = f'{BASE_URL}/admin/'
OBS_URL = f'{BASE_URL}/overlay/sorteio'

BG = '#0B0E18'
CARD = '#121725'
PANEL = '#0F1420'
BORDER = '#2B3448'
FG = '#F4F6FB'
MUTED = '#AAB6CF'
GREEN = '#79E8A4'
RED = '#F07178'
AMBER = '#F7C979'


def service_responds(port: int = PORT) -> bool:
    """Confirma que a porta atende ao health-check do nosso sorteador."""
    try:
        with urlopen(f'http://{HOST}:{port}/api/health', timeout=0.35) as response:
            return response.status == 200 and json.load(response).get('ok') is True
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False


def port_in_use(port: int = PORT) -> bool:
    try:
        with socket.create_connection((HOST, port), timeout=0.25):
            return True
    except OSError:
        return False


def server_python() -> Path:
    if os.name == 'nt':
        return ROOT / '.venv' / 'Scripts' / 'python.exe'
    candidate = ROOT / '.venv' / 'bin' / 'python'
    return candidate if candidate.is_file() else Path(sys.executable)


def worker_command() -> list[str]:
    return [str(server_python()), '-u', '-m', 'servidor.launcher_worker']


class Launcher:
    def __init__(self, root: tk.Tk, *, autostart: bool = False):
        self.root = root
        self.root.title('Sorteador Geral • Central do Servidor')
        self.root.geometry('1020x690')
        self.root.minsize(800, 570)
        self.root.configure(bg=BG)

        self.process: subprocess.Popen[str] | None = None
        self.output: queue.Queue[str] = queue.Queue()
        self.running_since: float | None = None
        self.ready = False
        self.external = False
        self.stopping = False
        self.close_after_stop = False
        self.last_probe = 0.0

        self.auto_open = tk.BooleanVar(value=True)
        self.auto_scroll = tk.BooleanVar(value=True)
        self._build_interface()
        self._set_status('Desligado', MUTED)
        self.root.protocol('WM_DELETE_WINDOW', self._close)
        self.root.after(120, self._tick)
        if autostart:
            self.root.after(400, self.start)

    @staticmethod
    def _button(parent: tk.Widget, text: str, command, *, primary=False, width=15):
        bg = GREEN if primary else PANEL
        fg = BG if primary else FG
        button = tk.Button(parent, text=text, command=command, width=width,
                           font=('Segoe UI', 10, 'bold'), fg=fg, bg=bg,
                           activeforeground=fg, activebackground='#93EFBA' if primary else '#263149',
                           cursor='hand2', relief='flat', bd=0, padx=12, pady=11,
                           disabledforeground='#70809C', highlightthickness=0)
        button.pack(side='left', padx=(0, 10))
        return button

    def _build_interface(self):
        header = tk.Frame(self.root, bg=BG, padx=28, pady=20)
        header.pack(fill='x')
        logo = tk.Label(header, text='S', bg=GREEN, fg=BG,
                        font=('Segoe UI', 20, 'bold'), width=2, height=1)
        logo.pack(side='left', padx=(0, 14))
        title_group = tk.Frame(header, bg=BG)
        title_group.pack(side='left', fill='x', expand=True)
        tk.Label(title_group, text='SORTEADOR GERAL', bg=BG, fg=FG,
                 font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        tk.Label(title_group, text='Central do servidor  •  Twitch, Kick e MegaMu',
                 bg=BG, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w')
        tk.Label(header, text='LOCAL  •  PORTA 8777', bg=PANEL, fg=GREEN,
                 font=('Segoe UI', 9, 'bold'), padx=12, pady=8).pack(side='right')

        body = tk.Frame(self.root, bg=BG, padx=28)
        body.pack(fill='both', expand=True)

        summary = tk.Frame(body, bg=CARD, padx=20, pady=17,
                           highlightbackground=BORDER, highlightthickness=1)
        summary.pack(fill='x', pady=(0, 15))
        status_line = tk.Frame(summary, bg=CARD)
        status_line.pack(fill='x')
        self.indicator = tk.Canvas(status_line, width=18, height=18, bg=CARD,
                                   highlightthickness=0)
        self.dot = self.indicator.create_oval(3, 3, 15, 15, fill=MUTED, outline='')
        self.indicator.pack(side='left', padx=(0, 7))
        self.status_label = tk.Label(status_line, text='Desligado', bg=CARD, fg=FG,
                                      font=('Segoe UI', 14, 'bold'))
        self.status_label.pack(side='left')
        self.uptime_label = tk.Label(status_line, text='Tempo ligado: 00:00:00',
                                      bg=CARD, fg=MUTED, font=('Consolas', 10))
        self.uptime_label.pack(side='right')
        tk.Label(summary, text=ADMIN_URL, bg=CARD, fg=MUTED,
                 font=('Consolas', 10)).pack(anchor='w', pady=(5, 0))

        actions = tk.Frame(body, bg=BG)
        actions.pack(fill='x', pady=(0, 10))
        self.start_button = self._button(actions, '▶  Iniciar servidor', self.start,
                                         primary=True, width=19)
        self.stop_button = self._button(actions, '■  Parar servidor', self.stop, width=18)
        self._button(actions, '↗  Abrir painel', lambda: webbrowser.open(ADMIN_URL), width=16)
        self._button(actions, 'OBS • Sorteio', self.copy_obs_url, width=15)
        self.stop_button.config(state='disabled')

        options = tk.Frame(body, bg=BG)
        options.pack(fill='x', pady=(0, 16))
        for label, variable in [('Abrir painel automaticamente ao iniciar', self.auto_open),
                                ('Rolar logs automaticamente', self.auto_scroll)]:
            tk.Checkbutton(options, text=label, variable=variable,
                           bg=BG, fg=MUTED, selectcolor=PANEL,
                           activebackground=BG, activeforeground=FG,
                           font=('Segoe UI', 9), highlightthickness=0,
                           cursor='hand2').pack(side='left', padx=(0, 26))

        log_card = tk.Frame(body, bg=CARD, padx=16, pady=13,
                            highlightbackground=BORDER, highlightthickness=1)
        log_card.pack(fill='both', expand=True, pady=(0, 14))
        toolbar = tk.Frame(log_card, bg=CARD)
        toolbar.pack(fill='x', pady=(0, 10))
        tk.Label(toolbar, text='LOGS EM TEMPO REAL', bg=CARD, fg=FG,
                 font=('Segoe UI', 11, 'bold')).pack(side='left')
        tk.Button(toolbar, text='Salvar log', command=self.save_log, bg=PANEL,
                  fg=MUTED, relief='flat', cursor='hand2', padx=12, pady=5,
                  font=('Segoe UI', 9)).pack(side='right', padx=(8, 0))
        tk.Button(toolbar, text='Limpar tela', command=self.clear_log, bg=PANEL,
                  fg=MUTED, relief='flat', cursor='hand2', padx=12, pady=5,
                  font=('Segoe UI', 9)).pack(side='right')

        text_area = tk.Frame(log_card, bg=PANEL)
        text_area.pack(fill='both', expand=True)
        scroll = tk.Scrollbar(text_area, orient='vertical')
        scroll.pack(side='right', fill='y')
        self.log_text = tk.Text(text_area, bg=PANEL, fg='#D9E4F5',
                                insertbackground=FG, relief='flat', bd=0,
                                font=('Consolas', 10), padx=13, pady=11,
                                wrap='word', yscrollcommand=scroll.set,
                                state='disabled', spacing2=2)
        self.log_text.pack(fill='both', expand=True)
        scroll.config(command=self.log_text.yview)
        self.log_text.tag_configure('success', foreground=GREEN)
        self.log_text.tag_configure('warning', foreground=AMBER)
        self.log_text.tag_configure('error', foreground=RED)
        self.log_text.tag_configure('info', foreground='#BBD1EB')

        footer = tk.Frame(self.root, bg=BG, padx=28, pady=8)
        footer.pack(fill='x')
        tk.Label(footer, text='O servidor funciona neste computador. Fechar esta janela encerra o servidor iniciado por ela.',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w')
        self._append('Central pronta. Clique em Iniciar servidor.', 'info')

    def _set_status(self, label: str, color: str):
        self.status_label.config(text=label, fg=color)
        self.indicator.itemconfigure(self.dot, fill=color)

    def _append(self, message: str, kind: str | None = None):
        if not message.strip():
            return
        message = message.rstrip('\r\n')
        kind = kind or ('error' if any(x in message.upper() for x in ('ERROR', 'TRACEBACK', 'EXCEPTION'))
                        else 'warning' if 'WARNING' in message.upper() else 'info')
        self.log_text.config(state='normal')
        self.log_text.insert('end', message + '\n', kind)
        # Evita crescimento infinito da memória durante lives longas.
        if int(self.log_text.index('end-1c').split('.')[0]) > 2500:
            self.log_text.delete('1.0', '500.0')
        if self.auto_scroll.get():
            self.log_text.see('end')
        self.log_text.config(state='disabled')

    def _read_output(self, process: subprocess.Popen[str]):
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    self.output.put(line)
        except (OSError, ValueError) as error:
            self.output.put(f'[launcher] Falha ao ler logs: {error}')

    def start(self):
        if self.process and self.process.poll() is None:
            return
        if service_responds():
            self.external = True
            self._set_status('Servidor já está em execução', GREEN)
            self._append('[launcher] Servidor existente detectado na porta 8777. Este iniciador não controla esse processo.', 'warning')
            self.start_button.config(state='disabled')
            self.stop_button.config(state='disabled')
            if self.auto_open.get():
                webbrowser.open(ADMIN_URL)
            return
        if port_in_use():
            self._set_status('Porta 8777 ocupada', RED)
            self._append('[launcher] Outro programa está usando a porta 8777. Feche-o antes de iniciar.', 'error')
            return
        python = server_python()
        if not python.is_file():
            messagebox.showerror('Instalação pendente', 'Execute instalar.bat antes de abrir o sorteador.')
            self._append('[launcher] Python do ambiente .venv não encontrado. Execute instalar.bat.', 'error')
            return
        environment = os.environ.copy()
        environment.update(PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
        try:
            self.process = subprocess.Popen(worker_command(), cwd=ROOT,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, text=True,
                                            encoding='utf-8', errors='replace', bufsize=1,
                                            env=environment,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, ValueError) as error:
            self._set_status('Falha ao iniciar', RED)
            self._append(f'[launcher] Não foi possível iniciar o servidor: {error}', 'error')
            return
        self.external = False
        self.ready = False
        self.stopping = False
        self.running_since = time.monotonic()
        self._set_status('Iniciando servidor…', AMBER)
        self._append(f'[{datetime.now():%H:%M:%S}] Iniciando servidor local na porta 8777…', 'info')
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        threading.Thread(target=self._read_output, args=(self.process,),
                         daemon=True, name='ServerLogs').start()

    def stop(self, *, close_after: bool = False):
        self.close_after_stop = close_after
        if not self.process or self.process.poll() is not None:
            if close_after:
                self.root.destroy()
            return
        if self.stopping:
            return
        self.stopping = True
        self.stop_button.config(state='disabled')
        self._set_status('Encerrando servidor…', AMBER)
        self._append('[launcher] Solicitando parada segura do servidor…', 'warning')
        try:
            if self.process.stdin is not None:
                self.process.stdin.write('parar\n')
                self.process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self.process.terminate()
        self.root.after(10000, self._stop_timeout)

    def _stop_timeout(self):
        if self.process and self.process.poll() is None and self.stopping:
            self._append('[launcher] O servidor não respondeu à parada segura. Encerrando o processo…', 'warning')
            self.process.terminate()

    def _tick(self):
        for _ in range(120):
            try:
                message = self.output.get_nowait()
            except queue.Empty:
                break
            self._append(message)
        now = time.monotonic()
        if self.process and self.process.poll() is None:
            if self.running_since is not None:
                elapsed = max(0, int(now - self.running_since))
                self.uptime_label.config(text=f'Tempo ligado: {elapsed//3600:02}:{elapsed//60%60:02}:{elapsed%60:02}')
            if not self.ready and not self.stopping and now - self.last_probe >= 0.65:
                self.last_probe = now
                if service_responds():
                    self.ready = True
                    self._set_status('Servidor online', GREEN)
                    self._append('[launcher] Servidor ativo. Painel e overlays disponíveis.', 'success')
                    if self.auto_open.get():
                        webbrowser.open(ADMIN_URL)
        elif self.process is not None:
            code = self.process.returncode
            self._set_status('Servidor desligado' if self.stopping or code == 0 else 'Servidor encerrou com erro',
                             MUTED if self.stopping or code == 0 else RED)
            self._append(f'[launcher] Processo finalizado (código {code}).',
                         'info' if code == 0 else 'error')
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None
            self.ready = False
            self.running_since = None
            self.start_button.config(state='normal')
            self.stop_button.config(state='disabled')
            self.uptime_label.config(text='Tempo ligado: 00:00:00')
            if self.close_after_stop:
                self.root.destroy()
                return
        elif self.external and now - self.last_probe >= 2:
            self.last_probe = now
            if not service_responds():
                self.external = False
                self._set_status('Servidor externo desligado', MUTED)
                self.start_button.config(state='normal')
        self.root.after(160, self._tick)

    def copy_obs_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(OBS_URL)
        self._append(f'[launcher] Link do OBS copiado: {OBS_URL}', 'success')

    def clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')

    def save_log(self):
        path = filedialog.asksaveasfilename(title='Salvar log da sessão', defaultextension='.log',
                                            filetypes=[('Arquivo de log', '*.log'), ('Texto', '*.txt')],
                                            initialfile=f'sorteador_{datetime.now():%Y%m%d_%H%M%S}.log')
        if not path:
            return
        try:
            Path(path).write_text(self.log_text.get('1.0', 'end-1c'), encoding='utf-8')
            self._append(f'[launcher] Log salvo em {path}', 'success')
        except OSError as error:
            messagebox.showerror('Erro ao salvar', str(error))

    def _close(self):
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno('Encerrar o Sorteador',
                                       'Fechar esta janela também encerrará o servidor. Deseja continuar?'):
                return
            self.stop(close_after=True)
        else:
            self.root.destroy()


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description='Central gráfica do Sorteador Geral')
    parser.add_argument('--autostart', action='store_true', help='Inicia o servidor ao abrir a janela')
    args = parser.parse_args(argv)
    root = tk.Tk()
    Launcher(root, autostart=args.autostart)
    root.mainloop()


if __name__ == '__main__':
    main()
