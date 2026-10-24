variable "name" {
  description = "Prefijo de los recursos (p. ej. billing-dev)."
  type        = string
}

variable "tags" {
  description = "Etiquetas adicionales."
  type        = map(string)
  default     = {}
}

variable "secret_names" {
  description = "Secretos a crear."
  type        = list(string)
  default     = ["keycloak-client-secret", "keycloak-admin-api-secret", "auth-cookie-secret", "keycloak-admin-password", "anthropic-api-key"]
}
