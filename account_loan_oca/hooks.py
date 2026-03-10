# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging

_logger = logging.getLogger(__name__)

OLD_MODULE = "account_loan"
NEW_MODULE = "account_loan_oca"


def pre_init_hook(env):
    """Handle module rename from account_loan to account_loan_oca.

    If the old module account_loan is installed, we rename it to
    account_loan_oca so that Odoo treats this as an upgrade rather than
    a fresh install. This ensures migration scripts run properly.

    Also checks for the official Odoo ``account_loans`` module to
    avoid conflicts.

    Handles migrations from any previous version (V14, V16, V18, etc.).
    """
    cr = env.cr

    # Check if old module is installed (including 'to install' state
    # which can happen if the module was previously uninstalled and
    # is being installed again under the new name)
    cr.execute(
        """
        SELECT id, state, latest_version
        FROM ir_module_module
        WHERE name = %s
          AND state IN ('installed', 'to upgrade', 'to install')
    """,
        (OLD_MODULE,),
    )
    old_module = cr.fetchone()
    if not old_module:
        _logger.info(
            "No installed '%s' module found, proceeding with fresh install of '%s'",
            OLD_MODULE,
            NEW_MODULE,
        )
        return

    old_id, old_state, old_version = old_module

    # Skip if the old module is only 'uninstalled' (never actually installed)
    if old_state == "uninstalled" and not old_version:
        _logger.info(
            "Old module '%s' has state='uninstalled' with no version. "
            "Removing it to allow fresh install of '%s'.",
            OLD_MODULE,
            NEW_MODULE,
        )
        cr.execute(
            "DELETE FROM ir_module_module_dependency WHERE module_id = %s",
            (old_id,),
        )
        cr.execute("DELETE FROM ir_module_module WHERE id = %s", (old_id,))
        return

    _logger.info(
        "Found installed '%s' (id=%s, state=%s, version=%s). "
        "Migrating to '%s'...",
        OLD_MODULE,
        old_id,
        old_state,
        old_version,
        NEW_MODULE,
    )

    # Warn if official Odoo 'account_loans' module is installed
    cr.execute(
        """
        SELECT state FROM ir_module_module
        WHERE name = 'account_loans' AND state IN ('installed', 'to upgrade')
    """
    )
    if cr.fetchone():
        _logger.warning(
            "Official Odoo 'account_loans' module is also installed. "
            "Migration will proceed carefully to avoid conflicts."
        )

    # Check if the new module entry already exists
    # (Odoo auto-creates it when using -i account_loan_oca)
    cr.execute(
        "SELECT id FROM ir_module_module WHERE name = %s",
        (NEW_MODULE,),
    )
    new_module = cr.fetchone()

    if new_module:
        new_id = new_module[0]
        _logger.info(
            "'%s' entry already exists (id=%s). Transferring data from old module...",
            NEW_MODULE,
            new_id,
        )
        # Transfer dependencies from old module to new module
        # (avoid duplicates by excluding already-existing deps)
        cr.execute(
            """
            UPDATE ir_module_module_dependency
            SET module_id = %s
            WHERE module_id = %s
              AND name NOT IN (
                  SELECT name FROM ir_module_module_dependency WHERE module_id = %s
              )
        """,
            (new_id, old_id, new_id),
        )
        # Remove remaining old module deps (already exist in new)
        cr.execute(
            "DELETE FROM ir_module_module_dependency WHERE module_id = %s",
            (old_id,),
        )
        # Set the new module to 'to upgrade' with the old version
        # so that migration scripts will run
        cr.execute(
            """
            UPDATE ir_module_module
            SET state = 'to upgrade', latest_version = %s
            WHERE id = %s
        """,
            (old_version, new_id),
        )
        # Remove the old module entry
        cr.execute(
            "DELETE FROM ir_module_module WHERE id = %s",
            (old_id,),
        )
    else:
        # Simply rename the old module entry
        cr.execute(
            """
            UPDATE ir_module_module
            SET name = %s, state = 'to upgrade'
            WHERE id = %s
        """,
            (NEW_MODULE, old_id),
        )

    # Update ir_model_data module references
    cr.execute(
        """
        UPDATE ir_model_data
        SET module = %s
        WHERE module = %s
    """,
        (NEW_MODULE, OLD_MODULE),
    )

    # Update dependency names in other modules that depend on account_loan
    cr.execute(
        """
        UPDATE ir_module_module_dependency
        SET name = %s
        WHERE name = %s
    """,
        (NEW_MODULE, OLD_MODULE),
    )

    _logger.info(
        "Module rename from '%s' to '%s' completed in pre_init_hook",
        OLD_MODULE,
        NEW_MODULE,
    )
