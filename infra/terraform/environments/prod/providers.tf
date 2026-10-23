provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "compras"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
