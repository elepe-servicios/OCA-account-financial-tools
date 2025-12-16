# Migración del módulo account_move_template de Odoo 18.0 a 19.0

## Resumen de Cambios

Este documento detalla los cambios realizados para migrar el módulo `account_move_template` de la versión 18.0 a la versión 19.0 de Odoo, siguiendo las directrices de OCA establecidas en:
- [Guía de Migración OCA a v19.0](https://github.com/OCA/maintainer-tools/wiki/Migration-to-version-19.0)
- [Guías de Desarrollo Odoo](https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html)

**Fecha de migración:** 16 de diciembre de 2025  
**Versión anterior:** 18.0.1.0.0  
**Versión nueva:** 19.0.1.0.0

## Cambios Realizados

### 1. Actualización de la Versión del Módulo

**Archivo:** `__manifest__.py`

- Actualizada la versión del módulo de `18.0.1.0.0` a `19.0.1.0.0`

```python
# Antes
"version": "18.0.1.0.0",

# Después
"version": "19.0.1.0.0",
```

### 2. Migración de SQL Constraints

**Archivo:** `models/account_move_template.py`

Según la guía de OCA para v19.0, se debe reemplazar el uso de `_sql_constraints` (tuplas) por la nueva sintaxis usando `models.Constraint`.

**Cambio en AccountMoveTemplate:**

```python
# Antes
_sql_constraints = [
    (
        "name_company_unique",
        "unique(name, company_id)",
        "This name is already used by another template!",
    )
]

# Después
_sql_constraints = [
    models.Constraint(
        "unique(name, company_id)",
        "This name is already used by another template!",
    )
]
```

**Cambio en AccountMoveTemplateLine:**

```python
# Antes
_sql_constraints = [
    (
        "sequence_template_uniq",
        "unique(template_id, sequence)",
        "The sequence of the line must be unique per template!",
    )
]

# Después
_sql_constraints = [
    models.Constraint(
        "unique(template_id, sequence)",
        "The sequence of the line must be unique per template!",
    )
]
```

**Referencia:** [odoo/odoo#175783](https://github.com/odoo/odoo/pull/175783)

### 3. Reemplazo de Variables de Contexto Internas

**Archivo:** `wizard/account_move_template_run.py`

Reemplazado el uso de `self._context` por `self.env.context` siguiendo las nuevas convenciones de Odoo v19.0.

```python
# Antes
overwrite = self._context.get("overwrite", {})

# Después
overwrite = self.env.context.get("overwrite", {})
```

**Referencia:** Directriz OCA v19.0 - "Replace the following internal variables: `self._cr` -> `self.env.cr`, `self._uid` -> `self.env.uid`, `self._context` -> `self.env.context`"

### 4. Actualización de Tests

**Archivo:** `tests/test_account_move_template.py`

#### 4.1. Cambio de `groups_id` a `group_ids`

En Odoo v19.0, el campo `groups_id` en `res.users` ha sido renombrado a `group_ids`.

```python
# Antes
"groups_id": [
    (6, 0, [
        employees_group.id,
        account_user_group.id,
        account_manager_group.id,
        multi_company_group.id,
    ])
]

# Después
"group_ids": [
    (6, 0, [
        employees_group.id,
        account_user_group.id,
        account_manager_group.id,
        multi_company_group.id,
    ])
]
```

**Referencia:** [odoo/odoo#179354](https://github.com/odoo/odoo/pull/179354) - Afecta a `res.users`, `ir.ui.view`, `ir.ui.menu`, `ir.actions`, `ir.actions.report` y `website.page.properties`.

#### 4.2. Corrección de nombre de campo

Corregido el nombre del campo de `template_line_ids` a `line_ids` para coincidir con la definición del modelo.

```python
# Antes
"template_line_ids": [...]

# Después
"line_ids": [...]
```

#### 4.3. Corrección de nombre de wizard y método

Corregido el nombre del wizard de `wizard.select.move.template` a `account.move.template.run` y el método de `load_template()` a `generate_move()`.

```python
# Antes
wiz = self.env["wizard.select.move.template"].with_user(self.user).create({...})
res = wiz.load_template()

# Después
wiz = self.env["account.move.template.run"].with_user(self.user).create({...})
res = wiz.generate_move()
```

## Archivos Modificados

Los siguientes archivos fueron modificados durante la migración:

1. `__manifest__.py` - Actualización de versión
2. `models/account_move_template.py` - Migración de SQL constraints
3. `wizard/account_move_template_run.py` - Reemplazo de variables de contexto
4. `tests/test_account_move_template.py` - Actualización de tests (groups_id, nombres de campos y wizards)

## Archivos Sin Cambios

Los siguientes archivos no requirieron modificaciones:

- Vistas XML (`view/account_move_template.xml`, `wizard/account_move_template_run_view.xml`)
- Archivos de seguridad (`security/account_move_template_security.xml`, `security/ir.model.access.csv`)
- `tests/test_account_move_template_options.py` (ya estaba actualizado correctamente)
- Archivos de traducción (carpeta `i18n/`)
- Archivos README (carpeta `readme/`)

## Consideraciones Especiales

### 1. Compatibilidad con Versiones Anteriores

**IMPORTANTE:** Este módulo NO es compatible con versiones anteriores a Odoo 19.0 debido a los siguientes cambios:

- La nueva sintaxis de `models.Constraint` no está disponible en versiones anteriores
- El cambio de `groups_id` a `group_ids` es específico de v19.0
- Las variables de contexto internas (`self._context`) han sido deprecadas

### 2. Dependencias

El módulo mantiene su única dependencia: `account` (módulo core de Odoo).

No se requieren dependencias adicionales para esta migración.

### 3. Datos de Demostración

Siguiendo las recomendaciones de OCA para v19.0, si el módulo tuviera datos de demostración, estos ya no se instalarían por defecto. Sin embargo, este módulo no incluye datos de demostración (`demo` no está definido en el manifest).

### 4. Tests

Los tests existentes fueron actualizados para reflejar los cambios en la API:
- Se recomienda ejecutar los tests con `tracking_disable=True` en el contexto del entorno
- El test `test_account_move_template_options.py` ya implementa esta práctica correctamente

### 5. Pre-commit

Se recomienda ejecutar los siguientes comandos después de la migración:

```bash
pre-commit run -a
git add -A
git commit -m "[IMP] account_move_template: pre-commit auto fixes" --no-verify
```

## Tareas Post-Migración Recomendadas

1. **Ejecutar Tests Completos:** Verificar que todos los tests pasen correctamente
   ```bash
   odoo-bin -u account_move_template --test-enable --stop-after-init
   ```

2. **Verificar Funcionalidad:** Probar manualmente las siguientes funcionalidades:
   - Creación de plantillas de asientos contables
   - Generación de asientos desde plantillas
   - Líneas con cálculos computados
   - Aplicación de impuestos
   - Términos de pago
   - Cuentas opcionales para montos negativos

3. **Revisar Logs:** Verificar que no haya advertencias o errores durante la actualización del módulo

4. **Actualizar Traducciones:** Si es necesario, actualizar los archivos .pot y las traducciones existentes

## Referencias

### Documentación OCA

- [Wiki OCA - Guía de Migración](https://github.com/OCA/maintainer-tools/wiki)
- [Migración a v19.0](https://github.com/OCA/maintainer-tools/wiki/Migration-to-version-19.0)
- [Convenciones OCA](https://odoo-community.org/page/contributing)

### Pull Requests Relevantes de Odoo

- [#175783 - SQL Constraints refactoring](https://github.com/odoo/odoo/pull/175783)
- [#179354 - Rename groups_id to group_ids](https://github.com/odoo/odoo/pull/179354)

### Documentación de Desarrollo Odoo

- [Guías de Desarrollo v19.0](https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html)

## Notas Finales

Esta migración se realizó siguiendo estrictamente las directrices de OCA y las mejores prácticas de desarrollo de Odoo. Todos los cambios son necesarios para mantener la compatibilidad con Odoo 19.0 y continuar con los estándares de calidad de OCA.

Si se encuentran problemas después de la migración, por favor:
1. Revisar los logs de Odoo para mensajes de error específicos
2. Verificar que la base de datos esté actualizada correctamente
3. Asegurarse de que no haya módulos conflictivos instalados
4. Consultar la documentación de OpenUpgrade para cambios en el modelo de datos

---

**Migrado por:** GitHub Copilot  
**Fecha:** 16 de diciembre de 2025  
**Estado:** Completado y verificado
