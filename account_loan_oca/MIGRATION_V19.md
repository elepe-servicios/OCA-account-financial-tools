# Migración de account_loan de Odoo V18 a V19

Este documento resume los cambios realizados y consideraciones especiales para la migración del módulo `account_loan` desde Odoo V18 a Odoo V19, siguiendo los lineamientos de la OCA y las mejores prácticas de Odoo.

## Cambios realizados

- Actualización del archivo `__manifest__.py`:
  - Versión incrementada a 19.0.1.0.0.
  - Se añadió el campo `odoo_version` y se ajustaron los metadatos según la plantilla OCA para Odoo 19.
- Revisión de los modelos y wizards:
  - Se verificaron los imports y decoradores para asegurar compatibilidad con Odoo 19.
  - No se detectaron cambios de API incompatibles en los modelos principales.
- Revisión de vistas XML, reglas de seguridad y datos:
  - Estructura y herencias compatibles con Odoo 19.
  - No se requieren cambios en los archivos XML para esta migración.
- Dependencias externas:
  - Se mantienen las dependencias de `numpy` y `numpy-financial`.

## Consideraciones especiales

- El módulo sigue los lineamientos de la OCA para la migración entre versiones: https://github.com/OCA/maintainer-tools/wiki#migration
- Se recomienda ejecutar pruebas funcionales completas tras la migración.
- Revisar posibles cambios en módulos dependientes o integraciones personalizadas.
- Consultar la documentación oficial de Odoo 19 para nuevas mejores prácticas: https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html

## Referencias
- [Guía de migración OCA](https://github.com/OCA/maintainer-tools/wiki#migration)
- [Mejores prácticas de desarrollo Odoo 19](https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html)

---

Si se detectan problemas adicionales durante la instalación o uso, revisar los logs y adaptar el código según los cambios de Odoo 19.

