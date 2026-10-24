# Despliegue en AWS (Terraform)

`infra/terraform/` es un **esqueleto**: los módulos tienen sus interfaces (variables y
salidas) y cada `main.tf` lista los recursos previstos, pero aún no los crea. Detalle en
[infra/terraform/README.md](../../infra/terraform/README.md).

## Arquitectura objetivo

```
Internet ── ALB (HTTPS, ACM) ──┬── app.<dominio>  → ECS Fargate: app + worker
                               └── auth.<dominio> → ECS Fargate: keycloak
                    subredes privadas: RDS PostgreSQL (compras, keycloak) · S3 · Secrets Manager
ECR (una imagen por servicio) · CloudWatch Logs · Amazon SES (SMTP)
```

| Módulo | Contenido |
|---|---|
| `network` | VPC, subredes, NAT, grupos de seguridad |
| `container_registry` | ECR |
| `database` | RDS PostgreSQL |
| `storage` | Bucket S3 privado y cifrado |
| `secrets` | Secretos (`.env`) en Secrets Manager |
| `compute` | ECS Fargate, ALB, certificados, IAM, logs |

`environments/dev` y `environments/prod` componen los módulos (estado remoto en S3 con
`use_lockfile`). `make tf-validate` valida ambos sin credenciales.

## Qué falta en el código para producción

- Adaptador S3 de `FileStorage` (`BILLING_STORAGE=s3`), registrado en `bootstrap.file_storage()`.
- Keycloak en modo `start` con HTTPS y hostname público; tema de login sin el README.
- Un servicio ECS para el `worker` (misma imagen, comando `python -m billing.worker`).
- SMTP real (SES) en `SMTP_*` para la app y el realm.
- `BILLING_SECRET_KEY`, claves de LLM y secretos de Keycloak desde Secrets Manager.
