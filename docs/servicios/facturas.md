# Reconocimiento de facturas

Convierte una foto, un PDF o un correo de compra en un **borrador** con los datos ya
extraídos, que el usuario revisa en **Importar facturas** antes de guardarlo como compra.

## Formatos aceptados

`domain/files.py` → `classify(filename, content_type)`:

| Tipo | Extensiones | `kind` |
|---|---|---|
| Imagen | `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp` (también la cámara) | `image` |
| PDF | `.pdf` (digital o escaneado) | `pdf` |
| Correo | `.eml` | `email` |

Otro formato → `UnsupportedFile`.

## Flujo

```
imports.store_upload(uow, storage, extractor, nombre, tipo, bytes, owner_id, bank_parser)
  1. classify()                         → kind + content_type
  2. si es correo: bank_parser.parse()  → ¿notificación bancaria? (ver correos-bancarios.md)
  3. si no: extractor.extract(raw, kind, ctype, categories=<categorías del dueño>)
  4. guarda el archivo (FileStorage, clave UUID + extensión)
  5. crea Attachment(purchase_id=None, extracted, extraction_meta, extraction_error, sha256)
```

En Importar, `imports.draft_values(att, categories)` precarga el formulario, descartando la
categoría o el método de pago si no son válidos; `imports.confirm_draft()` crea la `Purchase`
(`source` = `image`/`pdf`/`email`) y vincula el adjunto. `discard_draft()` borra fila y archivo.

## Extractores (`infrastructure/extraction/`)

### `LLMInvoiceExtractor` (por defecto)

1. Pide el agente `invoice` en cada extracción (`bootstrap.agent("invoice")`). Si es `None`
   (proveedor `local` o no disponible), delega en `RegexExtractor`.
2. `documents.to_parts()` normaliza el archivo:
   - imagen o PDF → una parte binaria;
   - correo → cabecera (From, To, Date, Subject), cuerpo (HTML convertido a texto) y los
     adjuntos que sean PDF o imagen.
3. `documents.to_blocks(parts, llm.capabilities)` prepara el contenido según el modelo:

   | Parte | Modelo con soporte | Modelo sin soporte |
   |---|---|---|
   | Texto | `TextBlock` | — |
   | Imagen | `ImageBlock`, orientada según EXIF y reducida a 1568 px de lado mayor (JPEG) | nota «el modelo no lee imágenes» |
   | PDF | `DocumentBlock` | su texto (pypdf) si tiene ≥ 40 caracteres; si es escaneado y el modelo ve imágenes, las 5 primeras páginas renderizadas con pypdfium2 |

4. `agent.run(blocks, categories=…, payment_methods=…)` → `InvoiceData` validado.
5. `meta`: `document_type=invoice`, `method=llm`, agente, proveedor, modelo, duración, tokens y
   avisos. Si el LLM falla (`LLMError`), usa las regex, guarda el error en
   `extraction_error` y `method=rules`: **la subida nunca falla por la extracción**.

### `RegexExtractor` (sin red)

Texto de PDFs digitales y correos (`parts_text`) + expresiones regulares (`regex.py`): total
(última aparición de «Total…»), subtotal, impuestos (IVA/IGV), número de factura, fecha (ISO o
dd/mm/aaaa), moneda (código ISO o €) y comercio (remitente del correo o primera línea).
`parse_amount` interpreta `1.234,56`, `1,234.56`, `45.900` (miles) y `1 234,56`. No lee
imágenes ni PDFs escaneados (deja el aviso `NO_TEXT_ERROR`).

## Instrucciones del agente

`application/agents/prompts/invoice.md`: usar `null` para lo que no aparezca, fecha
`YYYY-MM-DD`, montos sin símbolo ni separador de miles interpretando el separador decimal del
país (`45.900,50` → 45900.50), deducir la moneda por el país o el identificador fiscal (NIT →
COP, RFC → MXN), sumar todos los impuestos, una entrada por línea, y elegir categoría y método
de pago **solo** de las listas recibidas (las categorías del dueño, incluidas las personales).

## Validaciones posteriores

`domain/invoice.py` → `consistency_warnings(data)` (avisos, nunca bloquean):

- la suma de las líneas no coincide con el subtotal (ni con el total);
- subtotal + impuestos ≠ total (tolerancia 0,05);
- fecha inválida, futura o de hace más de dos años;
- moneda que no es un código de 3 letras;
- total negativo.

En el borrador también se avisa de:

- **mismo archivo subido antes** (`find_duplicates`, por SHA-256 y solo del mismo usuario);
- **compra parecida**: mismo total en ±2 días (`similar_purchases`), por ejemplo la factura y
  la alerta del banco del mismo pago.

## Interfaz

`presentation/streamlit/pages/imports.py`: pestañas «Subir archivos» (varios a la vez) y
«Tomar foto»; lista «Pendientes de revisar» con icono de factura o de banco; vista previa del
archivo (`show_attachment`), insignia del tipo de documento, «Leído con proveedor / modelo en
N s» o «reglas locales», avisos, y el formulario de compra. Si el agente `invoice` está en
`local`, la página lo indica y remite a Configuración → Agentes IA.
