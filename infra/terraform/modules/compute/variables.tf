variable "name" {
  description = "Prefijo de los recursos (p. ej. billing-dev)."
  type        = string
}

variable "tags" {
  description = "Etiquetas adicionales."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "VPC."
  type        = string
}

variable "public_subnet_ids" {
  description = "Subredes del ALB."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Subredes de las tareas."
  type        = list(string)
}

variable "domain_name" {
  description = "Dominio base (app.<dominio>, auth.<dominio>)."
  type        = string
}

variable "images" {
  description = "Imagen (URL:tag) por servicio: app, keycloak."
  type        = map(string)
}

variable "database_endpoint" {
  description = "Host:puerto de PostgreSQL."
  type        = string
}

variable "bucket_arn" {
  description = "Bucket de archivos."
  type        = string
}

variable "secret_arns" {
  description = "Secretos que se inyectan como variables de entorno."
  type        = map(string)
}

variable "app_desired_count" {
  description = "Tareas de la app."
  type        = number
  default     = 1
}
