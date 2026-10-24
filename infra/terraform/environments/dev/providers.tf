provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "billing"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
