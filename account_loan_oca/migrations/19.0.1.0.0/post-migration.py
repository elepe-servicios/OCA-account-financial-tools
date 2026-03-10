# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
#
# Post-migration script for account_loan → account_loan_oca rename.
#
# Runs AFTER the module and its dependencies are loaded and updated.
# Handles operations that require the ORM or updated registry.

import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, table):
    cr.execute(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_name = %s AND table_schema = 'public'
    """,
        (table,),
    )
    return bool(cr.fetchone())


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s AND table_schema = 'public'
    """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    _logger.info("Starting post-migration for account_loan_oca %s", version)

    # ================================================================
    # 0. Detect if official account_loans module is installed
    #    This affects how we handle mail_message / followers migration.
    # ================================================================
    cr.execute(
        """
        SELECT state FROM ir_module_module
        WHERE name = 'account_loans' AND state IN ('installed', 'to upgrade')
    """
    )
    has_official = bool(cr.fetchone())
    if has_official:
        _logger.info(
            "Official 'account_loans' module is present — using "
            "conflict-aware post-migration logic."
        )

    # ================================================================
    # 1. Clean up orphaned ir_model_data entries
    #    After renaming, there may be stale entries that point to
    #    models/tables that no longer exist under the old name.
    # ================================================================
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model'
          AND name IN (
              'model_account_loan',
              'model_account_loan_line',
              'model_account_loan_generate_wizard',
              'model_account_loan_pay_amount',
              'model_account_loan_post',
              'model_account_loan_increase_amount'
          )
          AND NOT EXISTS (
              SELECT 1 FROM ir_model im
              WHERE im.id = ir_model_data.res_id
          )
    """
    )
    if cr.rowcount:
        _logger.info(
            "Cleaned up %d orphaned ir_model_data entries for old model names",
            cr.rowcount,
        )

    # ================================================================
    # 2. Ensure loan_oca_id is populated on account_move
    #    If loan_oca_id is NULL but loan_line_oca_id has a value,
    #    derive the loan from the line (same logic as action_post).
    # ================================================================
    if _column_exists(cr, "account_move", "loan_oca_id"):
        cr.execute(
            """
            UPDATE account_move am
            SET loan_oca_id = allo.loan_id
            FROM account_loan_line_oca allo
            WHERE am.loan_line_oca_id = allo.id
              AND am.loan_oca_id IS NULL
              AND am.loan_line_oca_id IS NOT NULL
        """
        )
        if cr.rowcount:
            _logger.info(
                "Populated loan_oca_id from loan_line_oca_id on %d account.move records",
                cr.rowcount,
            )

    # ================================================================
    # 3. Update model references in mail / chatter tables
    #    When the official module is present, both account.loan and
    #    account.loan.oca tables exist (same data, same IDs).  We only
    #    update records whose res_id has a match in the OCA table to
    #    avoid moving references that the official module might own.
    # ================================================================
    old_to_new_models = [
        ("account.loan", "account.loan.oca", "account_loan_oca"),
        ("account.loan.line", "account.loan.line.oca", "account_loan_line_oca"),
    ]
    for old_model, new_model, oca_table in old_to_new_models:
        # Build an optional WHERE clause to limit scope when official
        # module is present — only touch records whose res_id was copied.
        oca_filter = ""
        if has_official and _table_exists(cr, oca_table):
            oca_filter = (
                " AND res_id IN (SELECT id FROM \"%s\")" % oca_table
            )

        # mail_message
        if _table_exists(cr, "mail_message"):
            cr.execute(
                "UPDATE mail_message SET model = %%s "
                "WHERE model = %%s%s" % oca_filter,
                (new_model, old_model),
            )
            if cr.rowcount:
                _logger.info(
                    "Updated %d mail_message records: %s → %s",
                    cr.rowcount,
                    old_model,
                    new_model,
                )
        # mail_followers
        if _table_exists(cr, "mail_followers"):
            follower_filter = oca_filter.replace("res_id", "res_id")
            cr.execute(
                "UPDATE mail_followers SET res_model = %%s "
                "WHERE res_model = %%s%s" % follower_filter,
                (new_model, old_model),
            )
            if cr.rowcount:
                _logger.info(
                    "Updated %d mail_followers records: %s → %s",
                    cr.rowcount,
                    old_model,
                    new_model,
                )
        # mail_activity
        if _table_exists(cr, "mail_activity"):
            cr.execute(
                "UPDATE mail_activity SET res_model = %%s "
                "WHERE res_model = %%s%s" % oca_filter,
                (new_model, old_model),
            )
            if cr.rowcount:
                _logger.info(
                    "Updated %d mail_activity records: %s → %s",
                    cr.rowcount,
                    old_model,
                    new_model,
                )
        # ir_attachment
        if _table_exists(cr, "ir_attachment"):
            cr.execute(
                "UPDATE ir_attachment SET res_model = %%s "
                "WHERE res_model = %%s%s" % oca_filter,
                (new_model, old_model),
            )
            if cr.rowcount:
                _logger.info(
                    "Updated %d ir_attachment records: %s → %s",
                    cr.rowcount,
                    old_model,
                    new_model,
                )

    # ================================================================
    # 4. Clean up any remaining references to the old module name
    #    in ir_model_data that slipped through.
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
            "Updated %d remaining ir_model_data entries from account_loan to account_loan_oca",
            cr.rowcount,
        )

    # ================================================================
    # 5. Remove the old module from ir_module_module if it still exists
    #    (safety net in case pre_init_hook didn't catch it)
    # ================================================================
    cr.execute(
        """
        DELETE FROM ir_module_module
        WHERE name = 'account_loan'
          AND state IN ('uninstalled', 'uninstallable')
    """
    )
    if cr.rowcount:
        _logger.info(
            "Removed old 'account_loan' entry from ir_module_module"
        )

    # ================================================================
    # 6. Update ir_module_module_dependency references
    #    Any module that still has a dependency on 'account_loan'
    #    should be updated to depend on 'account_loan_oca'.
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
            "Updated %d dependency references from account_loan to account_loan_oca",
            cr.rowcount,
        )

    # ================================================================
    # 7. Verify data integrity — log warnings if anything looks wrong
    # ================================================================
    # Check that the new tables exist
    for table in ("account_loan_oca", "account_loan_line_oca"):
        if _table_exists(cr, table):
            cr.execute("SELECT COUNT(*) FROM \"%s\"" % table)
            count = cr.fetchone()[0]
            _logger.info("Table %s has %d records", table, count)
        else:
            _logger.warning("Expected table %s does not exist!", table)

    # Check for orphaned account.move records that reference
    # non-existent loans (data integrity check)
    if _column_exists(cr, "account_move", "loan_oca_id") and _table_exists(
        cr, "account_loan_oca"
    ):
        cr.execute(
            """
            SELECT COUNT(*) FROM account_move am
            WHERE am.loan_oca_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM account_loan_oca al
                  WHERE al.id = am.loan_oca_id
              )
        """
        )
        orphan_count = cr.fetchone()[0]
        if orphan_count:
            _logger.warning(
                "%d account.move records have loan_oca_id pointing to "
                "non-existent loans. These may need manual cleanup.",
                orphan_count,
            )

    _logger.info("Post-migration for account_loan_oca completed successfully")
