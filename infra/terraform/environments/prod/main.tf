locals {
  name = "compras-${var.environment}"
}

module "network" {
  source = "../../modules/network"
  name   = local.name
}

module "registry" {
  source = "../../modules/container_registry"
  name   = local.name
}

module "database" {
  source     = "../../modules/database"
  name       = local.name
  subnet_ids = module.network.private_subnet_ids
  multi_az   = true
}

module "storage" {
  source        = "../../modules/storage"
  name          = local.name
  force_destroy = false
}

module "secrets" {
  source = "../../modules/secrets"
  name   = local.name
}

module "compute" {
  source             = "../../modules/compute"
  name               = local.name
  vpc_id             = coalesce(module.network.vpc_id, "pendiente")
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  domain_name        = var.domain_name
  images             = { for repo, url in module.registry.repository_urls : repo => "${url}:${var.image_tag}" }
  database_endpoint  = coalesce(module.database.endpoint, "pendiente")
  bucket_arn         = coalesce(module.storage.bucket_arn, "pendiente")
  secret_arns        = module.secrets.secret_arns
}
