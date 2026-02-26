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
1. Detectar si el módulo antiguo `account_loan` está instalado.
2. Renombrar el módulo en `ir_module_module` para que Odoo lo trate como
   actualización (no instalación nueva) y así los scripts de migración se
   ejecuten correctamente.
3. Actualizar `ir_model_data.module` de `account_loan` a `account_loan_oca`.
4. Actualizar las dependencias en `ir_module_module_dependency`.
5. Advertir si el módulo oficial `account_loans` está instalado.

### `migrations/19.0.1.0.0/pre-migration.py`
Se ejecuta **antes** de cargar el módulo (fase `pre`).

Responsabilidades:
1. Renombrar modelos (ej.: `account.loan` → `account.loan.oca`) incluyendo
   todas las referencias en `ir_model`, `ir_model_fields`, `ir_model_data`,
   `ir_rule`, etc.
2. Renombrar tablas, secuencias PK y constraints.
3. Renombrar campos en `account.move` (`loan_id` → `loan_oca_id`, etc.).
4. Actualizar el código de `ir.sequence`.
5. Actualizar XML IDs auto-generados (model_*, field_*, access_*).
6. Detectar conflictos con el módulo oficial `account_loans`:
   - Si el módulo oficial es dueño del modelo `account.loan`, se omite
     el renombrado de modelos/tablas para no dañar datos del módulo oficial.

Utiliza `odoo.upgrade.util` cuando está disponible (`rename_model`,
`rename_field`, `rename_table`). Si no está instalado, recurre a SQL directo
como fallback.

Referencia: https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_utils.html

### `migrations/19.0.1.0.0/post-migration.py`
Se ejecuta **después** de cargar el módulo y sus dependencias (fase `post`).

Responsabilidades:
1. Limpiar entradas huérfanas en `ir_model_data`.
2. Poblar `loan_oca_id` en `account.move` desde `loan_line_oca_id` si falta.
3. Limpiar referencias residuales al módulo antiguo `account_loan`.
4. Eliminar entrada del módulo antiguo de `ir_module_module` si persiste.

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

La migración verifica si el módulo oficial es dueño del modelo `account.loan`
antes de renombrar, como medida de seguridad.

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


