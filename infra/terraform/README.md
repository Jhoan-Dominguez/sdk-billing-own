# Infraestructura en AWS (Terraform)

Esqueleto listo para desarrollar el despliegue. Los módulos ya tienen su interfaz
(variables y salidas) y cada `main.tf` lista los recursos previstos; falta escribirlos.

## Arquitectura objetivo

```
Internet ── ALB (HTTPS, ACM) ──┬── app.<dominio>  → ECS Fargate: app (imagen infra/docker/app)
                               └── auth.<dominio> → ECS Fargate: keycloak (infra/docker/keycloak)
                                         │
              subredes privadas ─────────┼── RDS PostgreSQL (bases billing y keycloak)
                                         ├── S3 (facturas y avatares: BILLING_STORAGE=s3)
                                         └── Secrets Manager (secretos de .env)
ECR: una imagen por servicio · CloudWatch Logs: logs de las tareas
```

| Módulo | Contenido |
|---|---|
| `modules/network` | VPC, subredes públicas/privadas, NAT, grupos de seguridad |
| `modules/container_registry` | Repositorios ECR |
| `modules/database` | RDS PostgreSQL |
| `modules/storage` | Bucket S3 privado y cifrado |
| `modules/secrets` | Secretos de la app |
| `modules/compute` | ECS Fargate, ALB, certificados, roles IAM, logs |

`environments/dev` y `environments/prod` componen los mismos módulos con distinta
configuración (p. ej. Multi-AZ solo en prod).

## Uso

```bash
cd infra/terraform/environments/dev
cp backend.hcl.example backend.hcl            # bucket del estado remoto
cp terraform.tfvars.example terraform.tfvars
terraform init -backend-config=backend.hcl
terraform plan
```

Para validar sin credenciales: `terraform init -backend=false && terraform validate`.

## Pendiente en la app para AWS

- Adaptador `FileStorage` para S3 en `src/billing/infrastructure/storage/` y su rama en `billing/bootstrap.py`.
- Keycloak en modo `start` con `KC_HOSTNAME=https://auth.<dominio>`.
