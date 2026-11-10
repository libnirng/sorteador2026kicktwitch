"""Armazenamento seguro de credenciais no Windows.

Suporta:
- Windows Credential Manager (优先)
- DPAPI como fallback

Nunca salva tokens ou secrets em texto puro.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Nome do alvo para Credential Manager
CREDENTIAL_TARGET = 'SorteadorGeral_KickOAuth'


def _is_windows() -> bool:
    """Detecta se está rodando no Windows."""
    return sys.platform == 'win32' or os.name == 'nt'


class SecureStorage:
    """Armazenamento seguro de credenciais."""

    def __init__(self):
        self._use_credential_manager = False
        self._use_dpapi = False

        if _is_windows():
            try:
                # Tenta importar winreg para Credential Manager
                import winreg
                self._use_credential_manager = True
                logger.info('SecureStorage: usando Windows Credential Manager')
            except ImportError:
                logger.warning('SecureStorage: winreg não disponível')

            if not self._use_credential_manager:
                try:
                    # Tenta usar DPAPI via ctypes
                    import ctypes
                    self._use_dpapi = True
                    logger.info('SecureStorage: usando DPAPI')
                except (ImportError, OSError):
                    logger.warning('SecureStorage: DPAPI não disponível')
        else:
            logger.warning('SecureStorage: não é Windows, armazenamento seguro limitado')

    def save_token(
        self,
        access_token: str,
        refresh_token: str = '',
        token_type: str = 'Bearer',
        expires_in: int = 0,
        user_id: str = '',
        username: str = '',
        client_secret: str = '',
        metadata: dict | None = None,
    ) -> bool:
        """Salva token de forma segura.

        Args:
            access_token: Token de acesso
            refresh_token: Token de refresh
            token_type: Tipo do token (ex: Bearer)
            expires_in: Segundos até expirar
            user_id: ID do usuário
            username: Nome de usuário
            client_secret: Secret do OAuth (opcional)

        Returns:
            True se salvou com sucesso
        """
        data = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'token_type': token_type,
            'expires_in': expires_in,
            'user_id': user_id,
            'username': username,
            'client_secret': client_secret,
        }

        data.update(metadata or {})
        json_data = json.dumps(data)

        if self._use_credential_manager:
            return self._save_credential_manager(json_data)
        elif self._use_dpapi:
            return self._save_dpapi(json_data)
        else:
            logger.error('SecureStorage: nenhum método seguro disponível!')
            return False

    def load_token(self) -> Optional[dict]:
        """Carrega token salvo.

        Returns:
            Dicionário com dados do token ou None se não encontrado
        """
        if self._use_credential_manager:
            return self._load_credential_manager()
        elif self._use_dpapi:
            return self._load_dpapi()
        else:
            logger.error('SecureStorage: nenhum método disponível para carregar')
            return None

    def delete_token(self) -> bool:
        """Remove token salvo."""
        if self._use_credential_manager:
            return self._delete_credential_manager()
        elif self._use_dpapi:
            return self._delete_dpapi()
        else:
            logger.error('SecureStorage: nenhum método disponível para deletar')
            return False

    # ======================================================================
    # Windows Credential Manager
    # ======================================================================
    def _save_credential_manager(self, json_data: str) -> bool:
        """Salva usando Windows Credential Manager via winreg."""
        try:
            import winreg

            # Cria chave se não existir
            key_path = r'Software\SorteadorGeral'
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            except OSError:
                logger.error('SecureStorage: não conseguiu criar chave do registro')
                return False

            try:
                # Usa DPAPI para criptografar antes de salvar
                encrypted = self._dpapi_encrypt(json_data.encode('utf-8'))
                if encrypted is None:
                    logger.error('SecureStorage: DPAPI falhou; credenciais não foram gravadas')
                    return False

                winreg.SetValueEx(key, 'KickOAuth', 0, winreg.REG_BINARY, encrypted)
                logger.info('SecureStorage: credenciais salvas com sucesso')
                return True
            finally:
                winreg.CloseKey(key)

        except Exception as e:
            logger.error(f'SecureStorage: erro ao salvar: {e!r}')
            return False

    def _load_credential_manager(self) -> Optional[dict]:
        """Carrega usando Windows Credential Manager via winreg."""
        try:
            import winreg

            key_path = r'Software\SorteadorGeral'
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            try:
                data, reg_type = winreg.QueryValueEx(key, 'KickOAuth')
                winreg.CloseKey(key)

                if reg_type == winreg.REG_BINARY:
                    # Tenta descriptografar com DPAPI
                    decrypted = self._dpapi_decrypt(data)
                    if decrypted:
                        return json.loads(decrypted.decode('utf-8'))

                # Fallback: hex para texto
                try:
                    return json.loads(bytes.fromhex(data.decode('utf-8')).decode('utf-8'))
                except Exception:
                    pass

                return None
            except FileNotFoundError:
                winreg.CloseKey(key)
                return None
            except Exception:
                try:
                    winreg.CloseKey(key)
                except Exception:
                    pass
                return None

        except Exception as e:
            logger.error(f'SecureStorage: erro ao carregar: {e!r}')
            return None

    def _delete_credential_manager(self) -> bool:
        """Remove do Windows Credential Manager."""
        try:
            import winreg

            key_path = r'Software\SorteadorGeral'
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
                try:
                    winreg.DeleteValue(key, 'KickOAuth')
                except FileNotFoundError:
                    pass
                finally:
                    winreg.CloseKey(key)

                logger.info('SecureStorage: credenciais removidas')
                return True
            except FileNotFoundError:
                return True  # Já não existe

        except Exception as e:
            logger.error(f'SecureStorage: erro ao deletar: {e!r}')
            return False

    # ======================================================================
    # DPAPI
    # ======================================================================
    def _dpapi_encrypt(self, data: bytes) -> Optional[bytes]:
        """Criptografa usando DPAPI (CurrentUser)."""
        try:
            import ctypes
            from ctypes import wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [
                    ('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_byte)),
                ]

            crypt32 = ctypes.windll.crypt32

            # Prepara entrada
            input_blob = DATA_BLOB()
            input_blob.cbData = len(data)
            input_blob.pbData = (ctypes.c_byte * len(data)).from_buffer_copy(data)

            # Prepara saída
            output_blob = DATA_BLOB()

            # Chama CryptProtectData
            result = crypt32.CryptProtectData(
                ctypes.byref(input_blob),
                None,  # Descrição (opcional)
                None,  # Entropy (opcional)
                None,  # Reserved
                None,  # Prompt (opcional)
                0,     # Flags (CRYPTPROTECT_UI_FORBIDDEN)
                ctypes.byref(output_blob),
            )

            if not result:
                logger.warning('SecureStorage: CryptProtectData falhou')
                return None

            # Copia dados criptografados
            encrypted = bytes(output_blob.pbData[:output_blob.cbData])

            # Libera memória
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [wintypes.HLOCAL]
            local_free.restype = wintypes.HLOCAL
            local_free(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))

            return encrypted

        except Exception as e:
            logger.warning(f'SecureStorage: DPAPI encrypt falhou: {e!r}')
            return None

    def _dpapi_decrypt(self, data: bytes) -> Optional[bytes]:
        """Descriptografa usando DPAPI."""
        try:
            import ctypes
            from ctypes import wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [
                    ('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_byte)),
                ]

            crypt32 = ctypes.windll.crypt32

            # Prepara entrada
            input_blob = DATA_BLOB()
            input_blob.cbData = len(data)
            input_blob.pbData = (ctypes.c_byte * len(data)).from_buffer_copy(data)

            # Prepara saída
            output_blob = DATA_BLOB()

            # Chama CryptUnprotectData
            result = crypt32.CryptUnprotectData(
                ctypes.byref(input_blob),
                None,  # Descrição (out)
                None,  # Entropy (opcional)
                None,  # Reserved
                None,  # Prompt (opcional)
                0,     # Flags
                ctypes.byref(output_blob),
            )

            if not result:
                logger.warning('SecureStorage: CryptUnprotectData falhou')
                return None

            # Copia dados descriptografados
            decrypted = bytes(output_blob.pbData[:output_blob.cbData])

            # Libera memória
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [wintypes.HLOCAL]
            local_free.restype = wintypes.HLOCAL
            local_free(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))

            return decrypted

        except Exception as e:
            logger.warning(f'SecureStorage: DPAPI decrypt falhou: {e!r}')
            return None

    # ======================================================================
    # Fallback DPAPI (para registro)
    # ======================================================================
    def _save_dpapi(self, json_data: str) -> bool:
        """Salva usando DPAPI (fallback)."""
        try:
            import winreg

            encrypted = self._dpapi_encrypt(json_data.encode('utf-8'))
            if encrypted is None:
                # Último fallback: hex
                encrypted = json_data.encode('utf-8').hex().encode('utf-8')

            key_path = r'Software\SorteadorGeral'
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            except OSError:
                return False

            try:
                winreg.SetValueEx(key, 'KickOAuth', 0, winreg.REG_BINARY, encrypted)
                return True
            finally:
                winreg.CloseKey(key)

        except Exception as e:
            logger.error(f'SecureStorage: DPAPI save falhou: {e!r}')
            return False

    def _load_dpapi(self) -> Optional[dict]:
        """Carrega usando DPAPI (fallback)."""
        try:
            import winreg

            key_path = r'Software\SorteadorGeral'
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
            try:
                data, reg_type = winreg.QueryValueEx(key, 'KickOAuth')
                winreg.CloseKey(key)
            except FileNotFoundError:
                winreg.CloseKey(key)
                return None

            if reg_type == winreg.REG_BINARY:
                decrypted = self._dpapi_decrypt(data)
                if decrypted:
                    return json.loads(decrypted.decode('utf-8'))

            # Fallback hex
            try:
                return json.loads(bytes.fromhex(data.decode('utf-8')).decode('utf-8'))
            except Exception:
                return None

        except Exception as e:
            logger.error(f'SecureStorage: DPAPI load falhou: {e!r}')
            return None

    def _delete_dpapi(self) -> bool:
        """Remove do registro."""
        return self._delete_credential_manager()


# Instância global
_storage: Optional[SecureStorage] = None


def get_storage() -> SecureStorage:
    """Retorna instância global do storage."""
    global _storage
    if _storage is None:
        _storage = SecureStorage()
    return _storage
