variable "environment" {
  description = "Nombre del entorno."
  type        = string
}

variable "region" {
  description = "Región de AWS."
  type        = string
  default     = "us-east-1"
}

variable "domain_name" {
  description = "Dominio base de la app."
  type        = string
}

variable "image_tag" {
  description = "Tag de las imágenes a desplegar (p. ej. el SHA del commit)."
  type        = string
  default     = "latest"
}
