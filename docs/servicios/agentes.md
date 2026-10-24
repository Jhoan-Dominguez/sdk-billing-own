# Agentes LLM

Un **agente** es una tarea concreta para un modelo de lenguaje: instrucciones (prompt) más
un esquema de salida (pydantic). El agente no sabe qué proveedor lo ejecuta: recibe un
`LLMClient`, y el proveedor y el modelo de cada agente se eligen por configuración, sin
tocar código.

```
application/agents/            ← qué hace cada agente
  base.py        AgentSpec, Agent
  registry.py    AGENTS: invoice, bank_notification
  settings.py    elección de proveedor/modelo por agente (tabla agent_settings)
  prompts/       invoice.md, bank_notification.md
domain/llm.py                  ← tipos neutrales (bloques, capacidades, resultado)
domain/ports/llm.py            ← puerto LLMClient, LLMError, LLMRefusal
infrastructure/llm/            ← cómo se habla con cada proveedor
  anthropic.py   Claude (messages.parse con structured outputs)
  openai.py      OpenAI y APIs compatibles (Ollama, OpenRouter, Groq, Azure, vLLM)
  gemini.py      Google Gemini (google-genai)
  fake.py        respuestas fijas, sin red
  fallback.py    cadena de proveedores
  base.py        utilidades: base64, esquema sin $ref, parseo tolerante, cronómetro
  registry.py    PROVIDERS: catálogo y construcción
```

## El puerto `LLMClient`

```python
class LLMClient(Protocol):
    provider: str
    model: str
    capabilities: Capabilities  # vision: acepta imágenes · pdf: acepta PDFs

    def generate(self, *, system: str, content: list[Block], schema: type[T], max_tokens: int) -> LLMResult[T]: ...
```

- `content` es una lista de bloques neutrales: `TextBlock(text)`, `ImageBlock(media_type, data)`,
  `DocumentBlock(media_type, data, name)`. Cada adaptador los traduce a su formato.
- La salida siempre se **valida contra `schema`**. Si no cumple, se lanza `LLMError`; si el
  modelo se niega, `LLMRefusal`.
- `LLMResult` incluye proveedor, modelo, duración y tokens (`meta()` los devuelve como dict
  para guardarlos en `Attachment.extraction_meta`).

## Proveedores

| Nombre | Adaptador | Se activa con | Modelo por defecto | Capacidades | Salida estructurada |
|---|---|---|---|---|---|
| `anthropic` | `AnthropicClient` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` | imágenes y PDF | `client.beta.messages.parse(output_format=Schema)`, esfuerzo `low`, *fallback* de servidor ante rechazos (`server-side-fallback-2026-07-01`, `fallbacks="default"`) |
| `openai` | `OpenAICompatibleClient` | `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`) | `gpt-5-mini` | imágenes; PDF solo en la API oficial | Chat Completions con `response_format: json_schema` |
| `gemini` | `GeminiClient` | `GEMINI_API_KEY` | `gemini-2.5-flash` | imágenes y PDF | `response_mime_type=application/json` + `response_json_schema` |
| `ollama` | `OpenAICompatibleClient` | Ollama respondiendo en `OLLAMA_BASE_URL` | `qwen3.5:9b` | imágenes (según el modelo); sin PDF | igual que OpenAI; `reasoning_effort` = `OLLAMA_REASONING_EFFORT` |
| `local` | — | siempre | — | — | Sin LLM: solo reglas |

Cada `ProviderSpec` del registro incluye etiqueta, modelos sugeridos, cómo saber si está
configurado (`configured()`), cómo construirlo (`build(model)`) y si puede listar sus modelos
(OpenAI y Ollama: `models.list()`).

Los SDK son **dependencias opcionales** (`pyproject.toml`): `pip install ".[anthropic]"`,
`".[openai]"` (también para Ollama), `".[gemini]"` o `".[llm]"` (todos). La imagen Docker
instala `.[llm]`. Si falta el SDK de un proveedor elegido, `bootstrap.agent()` devuelve
`None` y la extracción usa reglas.

### Proveedor por defecto

`registry.default_provider()`:

1. `BILLING_LLM_PROVIDER` si está definido.
2. Si no, el primero con credenciales entre `anthropic`, `openai` y `gemini`.
3. Si no, `local`.

Ollama no se elige solo (no tiene credenciales): se pide con `BILLING_LLM_PROVIDER=ollama` o
desde la interfaz. `BILLING_LLM_MODEL` fija el modelo del proveedor por defecto.

## Agentes

| Agente | Esquema de salida | Prompt | `max_tokens` | Lo usa |
|---|---|---|---|---|
| `invoice` — Lector de facturas | `InvoiceData` | `prompts/invoice.md` (variables `{categories}`, `{payment_methods}`) | 16000 | `LLMInvoiceExtractor` ([facturas](facturas.md)) |
| `bank_notification` — Notificaciones bancarias | `BankNotification` | `prompts/bank_notification.md` | 4000 | `LLMBankParser` ([correos bancarios](correos-bancarios.md)) |

```python
spec = AGENTS["invoice"]
agent = Agent(spec, llm)  # llm: cualquier LLMClient
result = agent.run(blocks, categories="Supermercado, Otros", payment_methods="Efectivo, …")
result.output  # InvoiceData validado
result.meta()  # {"provider": …, "model": …, "duration_ms": …, …}
```

`Agent.instructions(**variables)` formatea el prompt con `str.format`; `run()` añade
`extra["agent"]` al resultado.

## Elegir o cambiar el agente

En **Configuración → Agentes IA** (solo administradores, `Viewer.manages_agents`):

- Tabla de proveedores con su estado (disponible / sin configurar) y qué variable los activa.
- Por agente: proveedor, modelo (lista de sugeridos + los que devuelve la API; se puede
  escribir cualquier otro), **Guardar**, **Usar el valor por defecto** y **Probar** (ejecuta el
  agente con un ejemplo fijo y muestra la respuesta y el tiempo).

La elección se guarda en `agent_settings` (`application/agents/settings.py`: `resolve`,
`save`, `reset`) y se aplica en la siguiente extracción, sin reiniciar: `bootstrap.agent(name)`
resuelve proveedor y modelo en cada uso y cachea el cliente por `(proveedor, modelo)`.

Las credenciales nunca se guardan en la base: siempre vienen del entorno.

## Cadena de proveedores

`FallbackLLMClient([cliente_a, cliente_b])` prueba cada cliente en orden y devuelve la
primera respuesta válida. Anuncia solo las capacidades que tienen todos y guarda los errores
intermedios en `result.extra["fallback_errors"]`.

## Añadir un proveedor

1. Crear `infrastructure/llm/<proveedor>.py` con una clase que cumpla `LLMClient`: traducir
   los bloques, pedir salida JSON según `inline_schema(schema)` y validar con
   `parse_json(texto, schema)`; convertir los errores del SDK en `LLMError`.
2. Añadir un `ProviderSpec` en `PROVIDERS` (`registry.py`) con su `configured` y `build`.
3. Añadir su SDK como extra en `pyproject.toml`.

No hace falta tocar agentes, casos de uso ni interfaz: el proveedor aparece en
Configuración → Agentes IA.

## Añadir un agente

1. Definir el esquema de salida (pydantic) en `domain/`.
2. Escribir el prompt en `application/agents/prompts/<agente>.md`.
3. Registrar un `AgentSpec` en `AGENTS` y usarlo con `bootstrap.agent("<agente>")`.

## Verificación realizada

Con Ollama local (`qwen3.5:9b`, sin GPU) el agente `bank_notification` leyó una alerta de
Nequi sin plantilla de reglas (importe, comercio, fecha y hora correctos) y descartó un correo
publicitario. Los modelos pequeños en CPU tardan del orden de un minuto por documento; para
imágenes conviene un modelo con visión potente (Claude, GPT o Gemini).
