# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
#
# Pre-migration script for account_loan_oca v19.0.2.0.0
#
# NEW STRATEGY: The OCA module now extends the official ``account_loans``
# module using ``_inherit = "account.loan"`` instead of defining separate
# ``_name = "account.loan.oca"`` models.  Both modules share the same
# tables (``account_loan``, ``account_loan_line``).
#
# SCENARIO: V14/V16/V18 OCA ``account_loan`` → V19
# When this script runs:
#   1. hooks.py pre_init_hook already renamed the module entry
#      (account_loan → account_loan_oca) and updated ir_model_data.
#   2. Official ``account_loans`` (auto_install=True) already installed
#      as a dependency, adding its columns to the existing tables.
#   3. The account_loan / account_loan_line tables have BOTH:
#      - V14 OCA columns (loan_amount, start_date, periods, etc.)  [with data]
#      - Official V19 columns (amount_borrowed, date, duration, etc.) [NULL]
#
# This script:
#   - Copies V14 OCA data into official column names
#   - Renames OCA-only columns to ``oca_`` prefix
#   - Maps state values (posted → running)
#   - Copies account.move FK (loan_line_id → generating_loan_line_id)
#   - Cleans stale ir_model_data entries that conflict with the official module

import logging

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------


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


def _copy_column(cr, table, src, dst):
    """Copy non-NULL values from *src* to *dst* where *dst* IS NULL.

    Safe to call multiple times (idempotent).
    Returns the number of rows updated.
    """
    if not _table_exists(cr, table):
        return 0
    if not _column_exists(cr, table, src):
        _logger.debug("Column %s.%s not found, skipping copy", table, src)
        return 0
    if not _column_exists(cr, table, dst):
        _logger.debug("Column %s.%s not found, skipping copy target", table, dst)
        return 0
    cr.execute(
        'UPDATE "%(t)s" SET "%(d)s" = "%(s)s" '
        'WHERE "%(s)s" IS NOT NULL AND "%(d)s" IS NULL'
        % {"t": table, "s": src, "d": dst}
    )
    if cr.rowcount:
        _logger.info(
            "Copied %d values: %s.%s → %s", cr.rowcount, table, src, dst
        )
    return cr.rowcount


def _rename_column(cr, table, old_col, new_col):
    """Rename a column.  Skips silently if source missing or target exists."""
    if not _table_exists(cr, table):
        return False
    if not _column_exists(cr, table, old_col):
        return False
    if _column_exists(cr, table, new_col):
        _logger.warning(
            "Column %s.%s already exists — cannot rename %s",
            table,
            new_col,
            old_col,
        )
        return False
    cr.execute(
        'ALTER TABLE "%s" RENAME COLUMN "%s" TO "%s"' % (table, old_col, new_col)
    )
    _logger.info("Renamed column %s.%s → %s", table, old_col, new_col)
    return True


# ---------------------------------------------------------------------------
# Loan table migration (account_loan)
# ---------------------------------------------------------------------------


def _migrate_loan_table(cr):
    """Copy V14 OCA column data into official V19 column names."""
    _logger.info("Migrating account_loan columns → official names")

    # Columns where old OCA name differs from official name
    column_map = [
        ("loan_amount", "amount_borrowed"),
        ("start_date", "date"),
        ("periods", "duration"),
        ("short_term_loan_account_id", "short_term_account_id"),
        ("long_term_loan_account_id", "long_term_account_id"),
        ("interest_expenses_account_id", "expense_account_id"),
    ]
    for src, dst in column_map:
        _copy_column(cr, "account_loan", src, dst)

    # Map state values: OCA 'posted' → official 'running'
    if _column_exists(cr, "account_loan", "state"):
        cr.execute(
            "UPDATE account_loan SET state = 'running' WHERE state = 'posted'"
        )
        if cr.rowcount:
            _logger.info("Mapped %d loan states: posted → running", cr.rowcount)


# ---------------------------------------------------------------------------
# Loan-line table migration (account_loan_line)
# ---------------------------------------------------------------------------


def _migrate_loan_line_table(cr):
    """Copy V14 OCA columns to official names and rename OCA-only columns."""
    _logger.info("Migrating account_loan_line columns")

    # 1. Copy to official column names
    column_map = [
        ("interests_amount", "interest"),
        ("principal_amount", "principal"),
        ("payment_amount", "payment"),
    ]
    for src, dst in column_map:
        _copy_column(cr, "account_loan_line", src, dst)

    # 2. Rename OCA-exclusive columns to oca_ prefix.
    #    These columns have no equivalent in the official module; the new
    #    OCA code defines them with the oca_ prefix to avoid future clashes.
    oca_renames = [
        ("pending_principal_amount", "oca_pending_principal_amount"),
        ("long_term_pending_principal_amount", "oca_long_term_pending_principal_amount"),
        ("long_term_principal_amount", "oca_long_term_principal_amount"),
        ("final_pending_principal_amount", "oca_final_pending_principal_amount"),
        ("rate", "oca_rate"),
    ]
    for old, new in oca_renames:
        _rename_column(cr, "account_loan_line", old, new)


# ---------------------------------------------------------------------------
# Account-move FK migration
# ---------------------------------------------------------------------------


def _migrate_account_move(cr):
    """Copy V14 OCA FK columns to official field names on account_move.

    V14 OCA:  ``loan_line_id``  (Many2one → account.loan.line)
    Official: ``generating_loan_line_id`` (Many2one → account.loan.line)
    The official ``loan_id`` is a related field (non-stored), so no column
    copy is needed for it — it reads from ``generating_loan_line_id.loan_id``.
    """
    _logger.info("Migrating account_move FK columns")
    _copy_column(cr, "account_move", "loan_line_id", "generating_loan_line_id")


# ---------------------------------------------------------------------------
# ir_model_data cleanup
# ---------------------------------------------------------------------------


def _clean_ir_model_data(cr):
    """Remove stale ``ir_model_data`` entries for the OCA module.

    After the module rename (``account_loan`` → ``account_loan_oca`` by
    hooks.py), the OCA module has auto-generated ``ir_model_data`` entries
    for models and fields that now *belong to the official* ``account_loans``
    module.  If left in place, they cause duplicate-XMLID errors.

    We delete them and let Odoo recreate the correct entries:
    - Official fields → owned by ``account_loans``
    - OCA-added fields (via ``_inherit``) → owned by ``account_loan_oca``
    """
    _logger.info("Cleaning stale ir_model_data entries")

    # --- ir.model entries for base models (official owns them) -----------
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model'
          AND name IN ('model_account_loan', 'model_account_loan_line')
    """
    )
    if cr.rowcount:
        _logger.info(
            "Deleted %d stale ir.model entries from ir_model_data", cr.rowcount
        )

    # --- ir.model.fields entries for loan / loan.line / move --------------
    #     The ORM will recreate entries for fields that the OCA module
    #     actually defines via _inherit once the module loads.
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model.fields'
          AND res_id IN (
              SELECT id FROM ir_model_fields
              WHERE model IN (
                  'account.loan',
                  'account.loan.line',
                  'account.move'
              )
          )
    """
    )
    if cr.rowcount:
        _logger.info(
            "Deleted %d stale ir.model.fields entries from ir_model_data",
            cr.rowcount,
        )

    # --- ir.model.access entries for base models -------------------------
    #     Official module provides access rules; OCA now only provides
    #     rules for its own wizard models.
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model.access'
          AND res_id IN (
              SELECT ima.id
              FROM ir_model_access ima
              JOIN ir_model im ON im.id = ima.model_id
              WHERE im.model IN ('account.loan', 'account.loan.line')
          )
    """
    )
    if cr.rowcount:
        _logger.info(
            "Deleted %d stale ir.model.access entries from ir_model_data",
            cr.rowcount,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def migrate(cr, version):
    _logger.info(
        "Starting pre-migration for account_loan_oca %s "
        "(new _inherit strategy)",
        version,
    )

    if not _table_exists(cr, "account_loan"):
        _logger.info(
            "Table account_loan does not exist — fresh install, "
            "nothing to migrate."
        )
        return

    # ------------------------------------------------------------------
    # Detect the source scenario
    # ------------------------------------------------------------------

    # V14/V16/V18 OCA: old column names present (loan_amount, etc.)
    has_oca_columns = _column_exists(cr, "account_loan", "loan_amount")

    # Defunct V19 OCA v1 strategy: tables were renamed to *_oca
    has_v19_oca_v1 = _table_exists(cr, "account_loan_oca")

    if has_v19_oca_v1:
        # Safety net — this should never happen in practice because
        # the 19.0.1.0.0 migration is now a no-op.  If someone DID
        # deploy v1, manual intervention is needed.
        _logger.warning(
            "Detected account_loan_oca table from defunct V19 v1 strategy.  "
            "This requires manual data migration.  Skipping automatic "
            "migration to prevent data loss."
        )
        return

    if not has_oca_columns:
        # The table exists but has no OCA-specific columns.
        # Possible causes:
        #   - Official module created the table on a fresh V19 install
        #   - Prior migration already completed
        _logger.info(
            "No OCA columns found in account_loan (loan_amount missing).  "
            "Nothing to migrate."
        )
        # Still clean ir_model_data in case hooks.py reassigned stale entries
        _clean_ir_model_data(cr)
        return

    _logger.info(
        "Detected OCA loan data (loan_amount column present).  "
        "Migrating to official V19 column names."
    )

    # ------------------------------------------------------------------
    # 1. Copy / rename columns on the shared tables
    # ------------------------------------------------------------------
    _migrate_loan_table(cr)
    _migrate_loan_line_table(cr)
    _migrate_account_move(cr)

    # ------------------------------------------------------------------
    # 2. Clean stale ir_model_data to avoid conflicts with official module
    # ------------------------------------------------------------------
    _clean_ir_model_data(cr)

    _logger.info("Pre-migration for account_loan_oca completed successfully")
