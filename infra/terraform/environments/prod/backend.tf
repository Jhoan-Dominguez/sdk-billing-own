# Estado remoto en S3 con bloqueo nativo (use_lockfile). El bucket se crea una vez a mano
# o con un stack de "bootstrap"; los valores se pasan al inicializar:
#   terraform init -backend-config=backend.hcl
terraform {
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}
