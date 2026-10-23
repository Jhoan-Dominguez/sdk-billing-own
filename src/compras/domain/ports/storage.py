from typing import Protocol


class FileStorage(Protocol):
    """Almacén de archivos por clave (p. ej. 'avatars/ab12.png').

    Hoy es el disco local; en AWS puede ser S3 sin cambiar los casos de uso.
    """

    def save(self, key: str, data: bytes) -> None: ...

    def read(self, key: str) -> bytes:
        """Contenido del archivo; FileNotFoundError si no existe."""
        ...

    def delete(self, key: str) -> None:
        """Borra el archivo; no falla si ya no existe."""
        ...
