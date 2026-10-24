from typing import Protocol


class CipherError(RuntimeError):
    """Clave ausente o inválida, o texto cifrado con otra clave."""


class SecretCipher(Protocol):
    """Cifrado simétrico de secretos guardados en la base (p. ej. contraseñas IMAP)."""

    def encrypt(self, plain: str) -> str: ...
    def decrypt(self, token: str) -> str: ...
