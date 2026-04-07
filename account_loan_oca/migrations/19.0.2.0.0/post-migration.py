# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
#
# Post-migration script for account_loan_oca v19.0.2.0.0
#
# Runs AFTER the module Python code and data files have been loaded.
# Handles:
#   - Cleanup of orphaned ir_model_data / module entries
#   - Dependency updates for other modules that depended on account_loan
#   - Data integrity verification

import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, table):
    cr.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = %s AND table_schema = 'public'",
        (table,),
    )
    return bool(cr.fetchone())


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = %s AND column_name = %s AND table_schema = 'public'",
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    _logger.info("Starting post-migration for account_loan_oca %s", version)

    # ================================================================
    # 1. Clean up remaining ir_model_data references to old module name
    #    (safety net — hooks.py should have handled this already)
    # ================================================================
    cr.execute(
        """
        UPDATE ir_model_data
        SET module = 'account_loan_oca'
        WHERE module = 'account_loan'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Updated %d remaining ir_model_data entries: "
            "account_loan → account_loan_oca",
            cr.rowcount,
        )

    # ================================================================
    # 2. Remove old module from ir_module_module if still present
    #    (safety net in case pre_init_hook didn't fully clean up)
    # ================================================================
    cr.execute(
        """
        DELETE FROM ir_module_module
        WHERE name = 'account_loan'
          AND state IN ('uninstalled', 'uninstallable')
    """
    )
    if cr.rowcount:
        _logger.info("Removed old 'account_loan' entry from ir_module_module")

    # ================================================================
    # 3. Update dependency references for other modules
    #    Any module that still depends on 'account_loan' must be
    #    updated to depend on 'account_loan_oca'.
    # ================================================================
    cr.execute(
        """
        UPDATE ir_module_module_dependency
        SET name = 'account_loan_oca'
        WHERE name = 'account_loan'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Updated %d dependency references: account_loan → account_loan_oca",
            cr.rowcount,
        )

    # ================================================================
    # 4. Verify data integrity
    # ================================================================

    # 4a. Check that generating_loan_line_id is populated for loan moves
    if _column_exists(cr, "account_move", "generating_loan_line_id"):
        # Count moves that have old loan_line_id but no generating_loan_line_id
        if _column_exists(cr, "account_move", "loan_line_id"):
            cr.execute(
                """
                SELECT COUNT(*) FROM account_move
                WHERE loan_line_id IS NOT NULL
                  AND generating_loan_line_id IS NULL
            """
            )
            orphan_count = cr.fetchone()[0]
            if orphan_count:
                _logger.warning(
                    "%d account.move records have loan_line_id but no "
                    "generating_loan_line_id. Re-copying...",
                    orphan_count,
                )
                cr.execute(
                    """
                    UPDATE account_move
                    SET generating_loan_line_id = loan_line_id
                    WHERE loan_line_id IS NOT NULL
                      AND generating_loan_line_id IS NULL
                """
                )
                _logger.info("Copied %d remaining FK values", cr.rowcount)

    # 4b. Count loan records (informational)
    if _table_exists(cr, "account_loan"):
        cr.execute("SELECT COUNT(*) FROM account_loan")
        count = cr.fetchone()[0]
        _logger.info("Table account_loan has %d records", count)

    if _table_exists(cr, "account_loan_line"):
        cr.execute("SELECT COUNT(*) FROM account_loan_line")
        count = cr.fetchone()[0]
        _logger.info("Table account_loan_line has %d records", count)

    # 4c. Check OCA-specific columns exist (they should after module load)
    oca_columns = [
        ("account_loan", "partner_id"),
        ("account_loan", "rate"),
        ("account_loan", "loan_type"),
        ("account_loan_line", "oca_rate"),
        ("account_loan_line", "oca_pending_principal_amount"),
    ]
    for table, col in oca_columns:
        if _table_exists(cr, table) and not _column_exists(cr, table, col):
            _logger.warning(
                "Expected OCA column %s.%s not found after module load!",
                table,
                col,
            )

    # 4d. Check for orphaned generating_loan_line_id references
    if _column_exists(cr, "account_move", "generating_loan_line_id"):
        cr.execute(
            """
            SELECT COUNT(*) FROM account_move am
            WHERE am.generating_loan_line_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM account_loan_line all2
                  WHERE all2.id = am.generating_loan_line_id
              )
        """
        )
        orphan_count = cr.fetchone()[0]
        if orphan_count:
            _logger.warning(
                "%d account.move records have generating_loan_line_id "
                "pointing to non-existent loan lines. "
                "These may need manual cleanup.",
                orphan_count,
            )

    _logger.info("Post-migration for account_loan_oca completed successfully")
