variable "name" {
  description = "Prefijo de los recursos (p. ej. billing-dev)."
  type        = string
}

variable "tags" {
  description = "Etiquetas adicionales."
  type        = map(string)
  default     = {}
}

variable "subnet_ids" {
  description = "Subredes privadas."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Grupos de seguridad que pueden conectarse."
  type        = list(string)
  default     = []
}

variable "instance_class" {
  description = "Tamaño de la instancia."
  type        = string
  default     = "db.t4g.micro"
}

variable "multi_az" {
  description = "Réplica en otra AZ."
  type        = bool
  default     = false
}
