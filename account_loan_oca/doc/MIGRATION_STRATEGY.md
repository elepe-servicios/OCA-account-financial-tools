# Estrategia de Migración: account_loan_oca v19.0.2.0.0

## Problema

El módulo oficial de Odoo Enterprise `account_loans` tiene `auto_install=True` y
define los modelos `account.loan` y `account.loan.line`. Al actualizar a Odoo 19,
este módulo se instala automáticamente **antes** de que el módulo OCA pueda
migrar sus datos. Esto provocaba que:

1. Las tablas `account_loan` y `account_loan_line` quedasen controladas por el
   módulo oficial.
2. Los campos exclusivos de OCA (rate, rate_type, loan_type, partner_id, etc.)
   se perdieran.
3. La migración anterior (v19.0.1.0.0) intentaba renombrar tablas a `*_oca`,
   lo cual fallaba o producía duplicación de datos cuando el módulo oficial ya
   existía.

## Nueva Estrategia (v19.0.2.0.0)

En vez de definir modelos independientes (`_name = "account.loan.oca"`), el
módulo OCA ahora **extiende** los modelos oficiales mediante herencia:

```python
class AccountLoan(models.Model):
    _inherit = "account.loan"       # antes: _name = "account.loan.oca"

class AccountLoanLine(models.Model):
    _inherit = "account.loan.line"  # antes: _name = "account.loan.line.oca"
```

### Dependencia

```python
"depends": ["account_loans"],  # módulo oficial Enterprise
```

El módulo OCA requiere que `account_loans` esté instalado. Dado que
`account_loans` es `auto_install=True` en Enterprise, siempre estará disponible.

### Ventajas

- **Sin conflicto de tablas**: Ambos módulos comparten las mismas tablas
  (`account_loan`, `account_loan_line`). No hay renombrado de tablas.
- **Sin pérdida de datos**: Los campos oficiales se reutilizan directamente.
  Los campos exclusivos de OCA se agregan a la tabla existente.
- **Compatibilidad**: Los préstamos creados con el flujo oficial siguen
  funcionando. Los préstamos OCA agregan funcionalidad adicional (tipos de
  tasa, amortización con numpy_financial, leasing, etc.).

---

## Mapeo de Campos

### account.loan (OCA antiguo → Oficial)

| Campo OCA (v18)                     | Campo Oficial (v19)       | Acción          |
|--------------------------------------|---------------------------|-----------------|
| `loan_amount`                        | `amount_borrowed`         | Usar oficial    |
| `periods`                            | `duration`                | Usar oficial    |
| `start_date`                         | `date`                    | Usar oficial    |
| `short_term_loan_account_id`         | `short_term_account_id`   | Usar oficial    |
| `long_term_loan_account_id`          | `long_term_account_id`    | Usar oficial    |
| `interest_expenses_account_id`       | `expense_account_id`      | Usar oficial    |
| `state = 'posted'`                   | `state = 'running'`       | Mapear          |
| `partner_id`                         | —                         | Campo OCA nuevo |
| `rate`, `rate_type`, `rate_period`   | —                         | Campo OCA nuevo |
| `loan_type`                          | —                         | Campo OCA nuevo |
| `method_period`                      | —                         | Campo OCA nuevo |
| `residual_amount`                    | —                         | Campo OCA nuevo |
| `is_leasing`, `product_id`, etc.     | —                         | Campo OCA nuevo |

### account.loan.line (OCA antiguo → Oficial)

| Campo OCA (v18)               | Campo Oficial (v19) | Acción              |
|-------------------------------|----------------------|---------------------|
| `interests_amount`            | `interest`           | Usar oficial        |
| `principal_amount`            | `principal`          | Usar oficial        |
| `payment_amount`              | `payment`            | Usar oficial (computed) |
| `move_ids`                    | `generated_move_ids` | Usar oficial        |
| `pending_principal_amount`    | —                    | `oca_pending_principal_amount` |
| `long_term_pending_principal` | —                    | `oca_long_term_pending_principal_amount` |
| `rate`                        | —                    | `oca_rate`          |

### account.move

| Campo OCA (v18)     | Campo Oficial (v19)        | Acción       |
|----------------------|---------------------------|--------------|
| `loan_line_id`       | `generating_loan_line_id` | Usar oficial |
| `loan_id`            | `loan_id` (related)       | Usar oficial |
| `loan_oca_id`        | —                         | Eliminado    |
| `loan_line_oca_id`   | —                         | Eliminado    |

---

## Convención de Nombres

Para evitar conflictos con campos y métodos del módulo oficial, se aplican
estos prefijos:

### Campos exclusivos OCA

Los campos que solo existen en OCA y no tienen equivalente oficial usan el
prefijo `oca_` cuando hay riesgo de colisión:

- `oca_pending_principal_amount`
- `oca_long_term_pending_principal_amount`
- `oca_long_term_principal_amount`
- `oca_final_pending_principal_amount`
- `oca_rate` (en líneas)
- `oca_move_count`

Los campos sin riesgo de colisión conservan su nombre original:
`partner_id`, `rate`, `rate_type`, `loan_type`, `is_leasing`, etc.

### Métodos OCA

Los métodos de negocio que implementan lógica OCA (distinta de la oficial)
usan prefijo `oca_` o `_oca_`:

| Método OCA anterior  | Método nuevo               |
|-----------------------|----------------------------|
| `post()`              | `oca_post()`               |
| `compute_lines()`     | `oca_compute_lines()`      |
| `_compute_draft_lines()` | `_oca_compute_draft_lines()` |
| `_generate_move()`    | `_oca_generate_move()`     |
| `_generate_invoice()` | `_oca_generate_invoice()`  |
| `_check_amount()`     | `_oca_check_amount()`      |

---

## Escenarios de Migración

### Escenario 1: Instalación Limpia (sin datos previos)

No se necesita migración. El módulo OCA se instala sobre `account_loans` y
agrega sus campos adicionales a las tablas existentes.

### Escenario 2: Desde V18 OCA (`account_loan` con campos OCA)

Los datos están en la tabla `account_loan` con columnas OCA (loan_amount,
start_date, periods, etc.). El módulo oficial también usa esta tabla.

**Pre-migración**:
1. Copiar datos de columnas OCA a columnas oficiales:
   - `loan_amount` → `amount_borrowed`
   - `start_date` → `date`
   - `periods` → `duration`
   - `short_term_loan_account_id` → `short_term_account_id`
   - `long_term_loan_account_id` → `long_term_account_id`
   - `interest_expenses_account_id` → `expense_account_id`
2. En `account_loan_line`:
   - `interests_amount` → `interest`
   - `principal_amount` → `principal`
3. En `account_move`:
   - `loan_line_id` → `generating_loan_line_id`
4. Mapear estados: `posted` → `running`
5. Renombrar columnas OCA exclusivas con prefijo `oca_`:
   - `pending_principal_amount` → `oca_pending_principal_amount`
   - etc.
6. Limpiar registros de `ir_model_data`, `ir_model_fields` huérfanos.

### Escenario 3: Desde V19 OCA v1 (tablas `account_loan_oca`)

Los datos están en tablas separadas `account_loan_oca` / `account_loan_line_oca`.

**Pre-migración**:
1. Copiar datos de `account_loan_oca` → `account_loan`:
   - Mapear columnas (loan_amount→amount_borrowed, etc.)
   - Preservar IDs
2. Copiar datos de `account_loan_line_oca` → `account_loan_line`:
   - Mapear columnas (interests_amount→interest, etc.)
3. En `account_move`:
   - `loan_oca_id` → copiar a `loan_id` (related via generating_loan_line_id)
   - `loan_line_oca_id` → `generating_loan_line_id`
4. Limpiar tablas y registros obsoletos (`*_oca`).

---

## Estructura de Archivos (post-migración)

```
account_loan_oca/
├── __manifest__.py          # depends: ["account_loans"], version 19.0.2.0.0
├── models/
│   ├── account_loan.py      # _inherit = "account.loan"
│   ├── account_loan_line.py # _inherit = "account.loan.line"
│   ├── account_move.py      # _inherit = "account.move" (override action_post)
│   └── res_partner.py       # _inherit = "res.partner"
├── views/
│   ├── account_loan_view.xml       # inherit_id de vistas oficiales
│   ├── account_loan_lines_view.xml # inherit_id de vistas oficiales
│   ├── account_move_view.xml       # extensión mínima
│   └── res_partner.xml
├── wizards/
│   ├── account_loan_generate_entries.py
│   ├── account_loan_pay_amount.py
│   ├── account_loan_post.py
│   └── account_loan_increase_amount.py
├── migrations/
│   └── 19.0.2.0.0/
│       ├── pre-migration.py
│       └── post-migration.py
└── doc/
    └── MIGRATION_STRATEGY.md  # este archivo
```

---

## Diagrama de Flujo: Decisión en Pre-migración

```
┌─────────────────────────────┐
│ Pre-migration 19.0.2.0.0    │
└──────────────┬──────────────┘
               │
       ┌───────▼────────┐
       │ ¿Existe tabla   │
       │ account_loan_oca│───── SÍ ──── Escenario 3
       │ ?               │              (copiar OCA→oficial)
       └───────┬─────────┘
               │ NO
       ┌───────▼────────┐
       │ ¿Existe columna │
       │ loan_amount en  │───── SÍ ──── Escenario 2
       │ account_loan?   │              (mapear campos OCA→oficial)
       └───────┬─────────┘
               │ NO
       ┌───────▼────────┐
       │ Instalación     │
       │ limpia           │──── Escenario 1 (no hacer nada)
       └─────────────────┘
```

---

## Notas Técnicas

- **numpy_financial**: El módulo OCA sigue requiriendo `numpy_financial` para
  el cálculo de amortización (cuota fija, tasa EAR/NAPR). El módulo oficial
  usa `pyloan`.
- **Estados**: El módulo oficial define: `draft`, `running`, `closed`,
  `cancelled`. OCA usaba `posted` en lugar de `running`. Los métodos OCA
  (`oca_post()`) realizan la transición `draft → running`.
- **Generación de movimientos**: El flujo OCA genera movimientos línea por
  línea (bajo demanda), mientras que el oficial genera todos al confirmar.
  Ambos flujos coexisten: `loan_type` determina si se usa el flujo OCA.
- **Secuencia**: Se mantiene `ir.sequence` con código `account.loan` (mismo
  que el oficial). Ya no se necesita código separado `account.loan.oca`.
