from cryptography.fernet import Fernet, InvalidToken

from compras.domain.ports.crypto import CipherError


class FernetCipher:
    """AES-128-CBC + HMAC-SHA256 (Fernet) con la clave COMPRAS_SECRET_KEY.

    Cambiar la clave deja ilegibles los secretos guardados: los usuarios tendrían
    que volver a escribir la contraseña de su buzón.
    """

    def __init__(self, key: str) -> None:
        if not key:
            raise CipherError("Falta COMPRAS_SECRET_KEY para cifrar los secretos guardados.")
        try:
            self._fernet = Fernet(key.encode())
        except ValueError as e:
            raise CipherError("COMPRAS_SECRET_KEY no es una clave Fernet válida (32 bytes en base64).") from e

    def encrypt(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as e:
            raise CipherError("No se pudo descifrar el secreto (¿cambió COMPRAS_SECRET_KEY?).") from e
