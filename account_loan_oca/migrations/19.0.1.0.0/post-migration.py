# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
#
# Post-migration script for account_loan → account_loan_oca rename.
#
# Runs AFTER the module and its dependencies are loaded and updated.
# Handles operations that require the ORM or updated registry.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("Starting post-migration for account_loan_oca %s", version)

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
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'account_move'
          AND column_name = 'loan_oca_id'
          AND table_schema = 'public'
    """
    )
    if cr.fetchone():
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
    # 3. Clean up any remaining references to the old module name
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
    # 4. Remove the old module from ir_module_module if it still exists
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

    _logger.info("Post-migration for account_loan_oca completed successfully")
