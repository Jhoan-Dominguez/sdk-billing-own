# Base de datos: RDS PostgreSQL privada (bases "compras" y "keycloak").
# Recursos previstos: aws_db_subnet_group, aws_db_instance (postgres 17, cifrada,
# backups, Multi-AZ en prod), credenciales gestionadas en Secrets Manager.
# La app no depende del motor: otro adaptador de persistencia tendría su propio módulo.
