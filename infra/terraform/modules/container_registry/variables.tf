variable "name" {
  description = "Prefijo de los recursos (p. ej. billing-dev)."
  type        = string
}

variable "tags" {
  description = "Etiquetas adicionales."
  type        = map(string)
  default     = {}
}

variable "repositories" {
  description = "Imágenes a publicar."
  type        = list(string)
  default     = ["app", "keycloak"]
}
