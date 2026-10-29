"""Administración de cuentas: acciones auditadas y formato de exportación de un usuario."""

# Acciones que quedan en la auditoría (AuditEntry.action).
BLOCK_USER = "block_user"
UNBLOCK_USER = "unblock_user"
DELETE_USER = "delete_user"
EXPORT_USER = "export_user"
RESTORE_USER = "restore_user"
CHANGE_ROLE = "change_role"
LOGOUT_USER = "logout_user"
FORCE_PASSWORD_CHANGE = "force_password_change"
REMOVE_OTP = "remove_otp"
RESEND_VERIFICATION = "resend_verification"
INVITE_USER = "invite_user"
PURGE_DRAFTS = "purge_drafts"
TRAIN_MODELS = "train_models"

ACTION_LABELS = {
    BLOCK_USER: "Bloquear cuenta",
    UNBLOCK_USER: "Desbloquear cuenta",
    DELETE_USER: "Eliminar cuenta",
    EXPORT_USER: "Exportar datos",
    RESTORE_USER: "Restaurar cuenta",
    CHANGE_ROLE: "Cambiar rol",
    LOGOUT_USER: "Cerrar sesiones",
    FORCE_PASSWORD_CHANGE: "Forzar cambio de contraseña",
    REMOVE_OTP: "Quitar verificación en dos pasos",
    RESEND_VERIFICATION: "Reenviar verificación de correo",
    INVITE_USER: "Invitar usuario",
    PURGE_DRAFTS: "Purgar borradores antiguos",
    TRAIN_MODELS: "Entrenar modelos de predicción",
}

# Exportación de un usuario (ZIP): manifest.json + data.json + archivos. `EXPORT_VERSION`
# cambia cuando cambia la forma de data.json; la restauración rechaza versiones que no conoce.
EXPORT_FORMAT = "billing-user-export"
EXPORT_VERSION = 1
