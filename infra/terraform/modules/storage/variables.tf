variable "name" {
  description = "Prefijo de los recursos (p. ej. billing-dev)."
  type        = string
}

variable "tags" {
  description = "Etiquetas adicionales."
  type        = map(string)
  default     = {}
}

variable "force_destroy" {
  description = "Permitir borrar el bucket con objetos (solo entornos de prueba)."
  type        = bool
  default     = false
}
