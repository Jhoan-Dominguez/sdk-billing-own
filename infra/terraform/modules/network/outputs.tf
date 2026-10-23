output "vpc_id" {
  description = "ID de la VPC."
  value       = null
}

output "public_subnet_ids" {
  description = "Subredes públicas (ALB)."
  value       = []
}

output "private_subnet_ids" {
  description = "Subredes privadas (ECS, RDS)."
  value       = []
}
