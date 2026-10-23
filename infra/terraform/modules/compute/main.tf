# Cómputo: ECS Fargate con dos servicios (app Streamlit y Keycloak) detrás de un ALB
# con HTTPS. Recursos previstos: aws_ecs_cluster, aws_ecs_task_definition,
# aws_ecs_service, aws_lb (+ listeners 443/80, target groups, reglas por host:
# app.<dominio> y auth.<dominio>), aws_acm_certificate, aws_iam_role (ejecución y
# tarea: lectura de secretos y del bucket), aws_cloudwatch_log_group.
# Keycloak en producción arranca con "start" (no "start-dev") y KC_HOSTNAME=https://auth.<dominio>.
