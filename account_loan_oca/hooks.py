# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import importlib.util
import logging
import os

_logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations", "19.0.2.0.0")


def _load_migration_script(name):
    """Load a migration script (pre-migration.py / post-migration.py) by name.

    Returns the loaded module so callers can invoke ``module.migrate(cr, version)``.
    Using importlib avoids any issues with the '.' characters in the directory name.
    """
    path = os.path.join(_MIGRATIONS_DIR, f"{name}.py")
    if not os.path.exists(path):
        _logger.warning("Migration script not found: %s", path)
        return None
    spec = importlib.util.spec_from_file_location(
        f"account_loan_oca_migration_{name.replace('-', '_')}", path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


OLD_MODULE = "account_loan"
NEW_MODULE = "account_loan_oca"


def pre_init_hook(env):
    """Handle module rename from account_loan to account_loan_oca.

    If the old module account_loan is installed, we rename it to
    account_loan_oca so that Odoo treats this as an upgrade rather than
    a fresh install.  This ensures migration scripts run properly.

    The new strategy (v19.0.2.0.0) uses ``_inherit = "account.loan"``
    to extend the official ``account_loans`` module.  No model or table
    renames are needed — only the module entry and ir_model_data.module
    references are updated here.  Column-level data migration is handled
    by ``migrations/19.0.2.0.0/pre-migration.py``.

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

    # Log if official Odoo 'account_loans' module is installed
    # (expected — it's a dependency via auto_install=True)
    cr.execute(
        """
        SELECT state FROM ir_module_module
        WHERE name = 'account_loans' AND state IN ('installed', 'to upgrade')
    """
    )
    if cr.fetchone():
        _logger.info(
            "Official Odoo 'account_loans' module is present (expected)."
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

    # -----------------------------------------------------------------------
    # Run pre-migration script directly.
    #
    # When Odoo processes account_loan_oca as a *fresh install* (state was
    # 'to install' when the module graph was built), the engine sets
    # pkg.state = 'to install' in memory.  migration.migrate_module() checks
    # that in-memory state and returns immediately if it is not 'to upgrade'.
    # The DB update above (state = 'to upgrade') is too late — pkg is already
    # constructed.  Calling the script here guarantees it runs regardless.
    # The script is idempotent (checks column/table existence), so running it
    # twice (here + via migration framework on a genuine upgrade) is safe.
    # -----------------------------------------------------------------------
    _logger.info(
        "Running pre-migration script directly from pre_init_hook "
        "(module entered as 'to install', normal migration path skipped)"
    )
    pre_mig = _load_migration_script("pre-migration")
    if pre_mig and hasattr(pre_mig, "migrate"):
        pre_mig.migrate(cr, old_version)
    else:
        _logger.error(
            "pre-migration script could not be loaded — data migration skipped!"
        )


def post_init_hook(env):
    """Run post-migration script after module data is loaded.

    Same timing problem applies to post-migration.py: the script is only
    executed by the migration framework when pkg.state == 'to upgrade'.
    When the module was loaded as 'to install' (rename scenario), this hook
    guarantees the post-migration logic runs after all data files are loaded.

    The script is idempotent, so running it twice on a genuine upgrade is safe.
    """
    cr = env.cr

    # Only execute if we are coming from a rename (old module existed).
    # We detect this by checking whether the old module still exists in
    # ir_model_data (it shouldn't, but the post-migration script handles that)
    # or simply by always calling it — the script guards itself internally.
    _logger.info(
        "post_init_hook: running post-migration script for account_loan_oca"
    )
    post_mig = _load_migration_script("post-migration")
    if post_mig and hasattr(post_mig, "migrate"):
        post_mig.migrate(cr, None)
    else:
        _logger.warning("post-migration script could not be loaded in post_init_hook")
