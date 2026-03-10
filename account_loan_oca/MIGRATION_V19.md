# Migración de account_loan a account_loan_oca — Odoo V19

Este documento resume los cambios realizados y las consideraciones especiales
para la migración del módulo OCA `account_loan` (V18) al nuevo nombre
`account_loan_oca` (V19), evitando conflictos con el módulo oficial de Odoo
`account_loans`.

---

## Motivo del cambio de nombre

Odoo 19 Enterprise incluye un módulo oficial llamado **`account_loans`**
(en plural). Para evitar confusiones y conflictos de nombres de modelos/tablas,
el módulo OCA se renombra a **`account_loan_oca`** y todos sus modelos
incorporan el sufijo `.oca`.

---

## Cambios realizados

### Nombre del módulo
| Antes (V18) | Ahora (V19) |
|---|---|
| `account_loan` | `account_loan_oca` |

### Modelos renombrados
| Modelo antiguo | Modelo nuevo |
|---|---|
| `account.loan` | `account.loan.oca` |
| `account.loan.line` | `account.loan.line.oca` |
| `account.loan.generate.wizard` | `account.loan.oca.generate.wizard` |
| `account.loan.pay.amount` | `account.loan.oca.pay.amount` |
| `account.loan.post` | `account.loan.oca.post` |
| `account.loan.increase.amount` | `account.loan.oca.increase.amount` |

### Tablas renombradas
| Tabla antigua | Tabla nueva |
|---|---|
| `account_loan` | `account_loan_oca` |
| `account_loan_line` | `account_loan_line_oca` |
| (wizard tables follow same pattern) | |

### Campos renombrados en `account.move`
| Campo antiguo | Campo nuevo |
|---|---|
| `loan_id` | `loan_oca_id` |
| `loan_line_id` | `loan_line_oca_id` |

### Secuencia
| Campo | Antes | Ahora |
|---|---|---|
| `ir.sequence` code | `account.loan` | `account.loan.oca` |

### Manifiesto (`__manifest__.py`)
- Versión: `19.0.1.0.0`
- Se añadió `pre_init_hook` para gestionar el renombrado del módulo.
- Se añadió `odoo_version` y se ajustaron metadatos OCA para Odoo 19.

---

## Scripts de migración

### `hooks.py` — `pre_init_hook`
Se ejecuta **antes** de la instalación/actualización del módulo.

Responsabilidades:
1. Detectar si el módulo antiguo `account_loan` está instalado (soporta
   estados `installed`, `to upgrade` y `to install`).
2. Manejar caso especial donde el módulo antiguo está en `uninstalled` sin
   versión (nunca fue realmente instalado) — se elimina limpiamente.
3. Renombrar el módulo en `ir_module_module` para que Odoo lo trate como
   actualización (no instalación nueva) y así los scripts de migración se
   ejecuten correctamente.
4. Si el nuevo módulo ya existe en `ir_module_module` (creado automáticamente
   por `-i account_loan_oca`), transferir datos del módulo antiguo al nuevo.
5. Actualizar `ir_model_data.module` de `account_loan` a `account_loan_oca`.
6. Actualizar las dependencias en `ir_module_module_dependency`.
7. Advertir si el módulo oficial `account_loans` está instalado.

### `migrations/19.0.1.0.0/pre-migration.py`
Se ejecuta **antes** de cargar el módulo (fase `pre`).

Responsabilidades:
1. Renombrar modelos (ej.: `account.loan` → `account.loan.oca`) incluyendo
   todas las referencias en `ir_model`, `ir_model_fields`, `ir_model_data`,
   `ir_rule`, `ir_act_server`, etc.
2. Renombrar tablas, secuencias PK, constraints e índices.
3. Renombrar campos en `account.move` (`loan_id` → `loan_oca_id`, etc.)
   con detección de conflictos si el módulo oficial también define `loan_id`.
4. Actualizar el código de `ir.sequence`.
5. Actualizar referencias en `ir_property` (res_id y value_reference).
6. Actualizar XML IDs auto-generados (model_*, field_*, access_*),
   incluyendo los de los wizards.
7. Actualizar FKs de `ir_model_access` para apuntar a los modelos renombrados.
8. Actualizar referencias de modelo en `mail_message`, `mail_followers`,
   `mail_activity` e `ir_attachment` (mensajes del chatter, seguidores,
   actividades y adjuntos).
9. Detectar conflictos con el módulo oficial `account_loans`:
   - Si el módulo oficial es dueño del modelo `account.loan`, se omite
     el renombrado de modelos/tablas para no dañar datos del módulo oficial.
   - Si el módulo oficial es dueño de `loan_id` en `account.move`, se
     **copia** el dato a `loan_oca_id` en lugar de renombrar la columna,
     para no perder datos de ninguno de los dos módulos.

Utiliza `odoo.upgrade.util` cuando está disponible (`rename_model`,
`rename_field`, `rename_table`). Si no está instalado, recurre a SQL directo
como fallback.

Referencia: https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_utils.html

### `migrations/19.0.1.0.0/post-migration.py`
Se ejecuta **después** de cargar el módulo y sus dependencias (fase `post`).

Responsabilidades:
1. Limpiar entradas huérfanas en `ir_model_data`.
2. Poblar `loan_oca_id` en `account.move` desde `loan_line_oca_id` si falta.
3. Actualizar referencias residuales de modelo antiguo en `mail_message`,
   `mail_followers`, `mail_activity` e `ir_attachment` (red de seguridad
   por si `odoo.upgrade.util` no las cubrió).
4. Limpiar referencias residuales al módulo antiguo `account_loan` en
   `ir_model_data`.
5. Eliminar entrada del módulo antiguo de `ir_module_module` si persiste.
6. Actualizar dependencias residuales en `ir_module_module_dependency`.
7. Verificar integridad de datos: contar registros en las tablas nuevas
   y detectar registros huérfanos en `account.move`.

---

## Conflictos con el módulo oficial `account_loans`

| Aspecto | OCA (`account_loan_oca`) | Oficial (`account_loans`) |
|---|---|---|
| Nombre módulo | `account_loan_oca` | `account_loans` |
| Modelo principal | `account.loan.oca` | `account.loan` (probable) |
| Tabla principal | `account_loan_oca` | `account_loan` (probable) |
| Campos en `account.move` | `loan_oca_id`, `loan_line_oca_id` | `loan_id` (probable) |

Al usar el sufijo `.oca` en los modelos y campos, **no debería haber
conflictos** si ambos módulos están instalados en la misma instancia.

La migración maneja tres escenarios de conflicto:

1. **El módulo oficial es dueño de `account.loan`**: Se **COPIAN** los datos
   a las nuevas tablas OCA en vez de renombrar (ver sección siguiente).
2. **El módulo oficial es dueño de `loan_id` en `account.move`**: Se
   **copia** el dato a `loan_oca_id` en lugar de renombrarlo.
3. **Sin conflicto**: Se renombran modelos, tablas y campos normalmente.

---

## Escenario V14 → V18 → V19 (COPIA de datos)

Este es el escenario más complejo:

1. En **V14**, el módulo OCA `account_loan` estaba instalado y creó todos
   los datos de préstamos (`account_loan`, `account_loan_line`, etc.).
2. Al actualizar a **V18**, el módulo oficial `account_loans` se auto-instaló
   (`auto_install: True`). Como ambos módulos definen `_name = "account.loan"`,
   Odoo los combinó en un solo modelo/tabla. Los datos OCA ahora están en
   tablas "propiedad" del módulo oficial.
3. En **V19**, OCA renombra a `account_loan_oca` con modelos `*.oca`.
   **No podemos RENOMBRAR** las tablas compartidas (el módulo oficial las
   necesita), así que **COPIAMOS** todos los datos.

### Qué hace la migración en este escenario

#### Pre-migración (`pre-migration.py`)
- Detecta que el módulo oficial es dueño de `account.loan` (consulta
  `ir_model_data` buscando `module = 'account_loans'`).
- Ejecuta `_migrate_with_official_conflict(cr)` en vez del renombrado
  estándar:
  1. **Copia tablas**: `account_loan` → `account_loan_oca`,
     `account_loan_line` → `account_loan_line_oca` (usando
     `CREATE TABLE ... LIKE ... INCLUDING DEFAULTS INCLUDING CONSTRAINTS`
     + `INSERT INTO ... SELECT *`). Los IDs se preservan.
  2. **Copia FKs en `account.move`**: Crea columnas `loan_oca_id` y
     `loan_line_oca_id`, copia valores desde `loan_id` y `loan_line_id`.
     Las columnas originales **no se tocan** (el módulo oficial las usa).
  3. **Actualiza `ir.sequence`**: Solo la secuencia propiedad de OCA.
  4. **Limpia `ir_model_data` huérfanos**: Borra entradas auto-generadas
     (`model_account_loan`, `field_account_loan__*`, `access_account_loan*`)
     que `hooks.py` re-apuntó a `account_loan_oca` pero que realmente
     pertenecen al módulo oficial.
  5. **Actualiza `ir_property`**: Referencias a los nuevos modelos OCA.
  6. **Registra advertencia** sobre mensajes mail pendientes.

#### Post-migración (`post-migration.py`)
- Detecta la presencia del módulo oficial al inicio.
- En **Sección 3** (mail/followers/actividades/adjuntos): solo actualiza
  registros cuyo `res_id` exista en la tabla OCA correspondiente. Esto
  evita mover mensajes de registros creados exclusivamente por el módulo
  oficial.
- El resto de secciones funciona igual que en el caso sin conflicto.

### Resultado final

| Tabla | Contenido | Dueño |
|---|---|---|
| `account_loan` | Datos originales (intactos) | Módulo oficial `account_loans` |
| `account_loan_oca` | **Copia** de los datos | Módulo OCA `account_loan_oca` |
| `account_loan_line` | Datos originales (intactos) | Módulo oficial |
| `account_loan_line_oca` | **Copia** de los datos | Módulo OCA |

| Campo en `account.move` | Apunta a | Dueño |
|---|---|---|
| `loan_id` | `account_loan` | Módulo oficial |
| `loan_oca_id` | `account_loan_oca` | Módulo OCA |
| `loan_line_id` | `account_loan_line` | Módulo oficial |
| `loan_line_oca_id` | `account_loan_line_oca` | Módulo OCA |

> **Nota sobre mensajes del chatter**: Los mensajes (`mail.message`),
> seguidores (`mail.followers`) y actividades (`mail.activity`) se actualizan
> en post-migración para referenciar el nuevo modelo OCA. Solo se afectan
> los registros cuyo `res_id` existe en la tabla OCA.

---

## Instrucciones de instalación/upgrade

### Requisitos previos
- **Recomendado**: instalar `odoo-upgrade` para usar las utilidades oficiales:
  ```
  pip install git+https://github.com/odoo/upgrade-util@master
  ```
- Si no se instala, la migración usa SQL directo como fallback.

### Desde una instancia con `account_loan` (V18) instalado
```bash
# Actualizar el código al nuevo módulo account_loan_oca
# Luego instalar el nuevo módulo (Odoo detectará la migración automáticamente):
./odoo-bin -d MI_BASE -i account_loan_oca --upgrade-path=/path/to/upgrade-util/src
```

### Instalación nueva (sin módulo previo)
```bash
./odoo-bin -d MI_BASE -i account_loan_oca
```

---

## Consideraciones adicionales

- **Respaldo**: Siempre realizar un respaldo de la base de datos antes de la
  migración.
- **Pruebas**: Ejecutar las pruebas del módulo tras la migración:
  ```bash
  ./odoo-bin -d MI_BASE --test-enable --test-tags account_loan_oca -i account_loan_oca --stop-after-init
  ```
- **Módulos dependientes**: Verificar si hay módulos personalizados que dependan
  de `account_loan` y actualizar sus dependencias a `account_loan_oca`.
- **Dependencias Python**: Se mantienen `numpy` y `numpy-financial`.

## Referencias
- [Upgrade utils (Odoo 19)](https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_utils.html)
- [Upgrade scripts (Odoo 19)](https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_scripts.html)
- [Guía de migración OCA](https://github.com/OCA/maintainer-tools/wiki#migration)
- [Coding guidelines Odoo 19](https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html)


