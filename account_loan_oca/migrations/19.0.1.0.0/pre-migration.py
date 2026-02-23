# Migration script to rename models from account.loan* to account.loan.oca*
# This script assumes the old module was installed and tables exist.

import logging

from odoo.upgrade import util

_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("Starting migration of account_loan_oca models")

    # Check if old module is installed
    cr.execute("""
        SELECT state
        FROM ir_module_module
        WHERE name = 'account_loan'
    """)
    result = cr.fetchone()
    if not result or result[0] not in ('installed', 'to upgrade'):
        _logger.info("Old account_loan module not installed, skipping migration")
        return

    _logger.info("Old account_loan module detected, proceeding with migration")

    # Rename models using util.rename_model
    model_renames = [
        ('account.loan', 'account.loan.oca'),
        ('account.loan.line', 'account.loan.line.oca'),
        ('account.loan.generate.wizard', 'account.loan.oca.generate.wizard'),
        ('account.loan.pay.amount', 'account.loan.oca.pay.amount'),
        ('account.loan.post', 'account.loan.oca.post'),
        ('account.loan.increase.amount', 'account.loan.oca.increase.amount'),
    ]

    for old_model, new_model in model_renames:
        util.rename_model(cr, old_model, new_model)
        _logger.info(f"Renamed model {old_model} to {new_model}")

    # Rename tables using util.rename_table
    table_renames = [
        ('account_loan', 'account_loan_oca'),
        ('account_loan_line', 'account_loan_line_oca'),
        ('account_loan_generate_wizard', 'account_loan_oca_generate_wizard'),
        ('account_loan_pay_amount', 'account_loan_oca_pay_amount'),
        ('account_loan_post', 'account_loan_oca_post'),
        ('account_loan_increase_amount', 'account_loan_oca_increase_amount'),
    ]

    for old_table, new_table in table_renames:
        util.rename_table(cr, old_table, new_table)
        _logger.info(f"Renamed table {old_table} to {new_table}")

    # Update ir_model_data for other records
    # Update records from old module
    cr.execute("""
        UPDATE ir_model_data
        SET module = 'account_loan_oca', name = REPLACE(name, 'account_loan.', 'account_loan_oca.')
        WHERE module = 'account_loan'
    """)
    _logger.info("Updated ir_model_data module and names from old module")

    # Update menuitems
    cr.execute("""
        UPDATE ir_model_data
        SET name = REPLACE(name, 'account_loan.', 'account_loan_oca.')
        WHERE module = 'account_loan_oca' AND name LIKE 'account_loan.%'
    """)
    _logger.info("Updated ir_model_data names for menuitems and actions")

    # Update ir_module_module if the old module is installed
    cr.execute("""
        UPDATE ir_module_module
        SET name = 'account_loan_oca'
        WHERE name = 'account_loan'
    """)
    _logger.info("Updated ir_module_module name from account_loan to account_loan_oca")

    _logger.info("Migration completed")
