variable "name" {
  description = "Prefijo de los recursos (p. ej. billing-dev)."
  type        = string
}

variable "tags" {
  description = "Etiquetas adicionales."
  type        = map(string)
  default     = {}
}

variable "cidr_block" {
  description = "Rango de la VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "az_count" {
  description = "Zonas de disponibilidad a usar."
  type        = number
  default     = 2
}
