# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
#
# Pre-migration script for account_loan → account_loan_oca rename.
#
# This script runs BEFORE the module is loaded and handles:
# - Model renames (account.loan → account.loan.oca, etc.)
# - Table renames (account_loan → account_loan_oca, etc.)
# - Field renames on inherited models (account.move: loan_id → loan_oca_id)
# - ir.sequence code update
# - XML ID name updates for auto-generated model/field entries
# - Conflict checks with official Odoo ``account_loans`` module
#
# The module rename itself (account_loan → account_loan_oca in ir_module_module,
# ir_model_data, and dependencies) is handled by pre_init_hook in hooks.py.
#
# Uses ``odoo.upgrade.util`` when available; falls back to raw SQL otherwise.
# Reference: https://www.odoo.com/documentation/19.0/developer/reference/upgrades/upgrade_utils.html

import logging

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper functions (raw SQL fallback when odoo.upgrade.util is not available)
# ---------------------------------------------------------------------------


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


def _model_exists_in_registry(cr, model):
    cr.execute("SELECT 1 FROM ir_model WHERE model = %s", (model,))
    return bool(cr.fetchone())


def _rename_model_sql(cr, old_model, new_model):
    """Rename a model and all its references using raw SQL."""
    if not _model_exists_in_registry(cr, old_model):
        _logger.info("Model %s does not exist in DB, skipping rename", old_model)
        return

    # ir_model
    cr.execute(
        "UPDATE ir_model SET model = %s WHERE model = %s", (new_model, old_model)
    )
    # ir_model_fields: model column
    cr.execute(
        "UPDATE ir_model_fields SET model = %s WHERE model = %s",
        (new_model, old_model),
    )
    # ir_model_fields: relation (Many2one / One2many / Many2many target)
    cr.execute(
        "UPDATE ir_model_fields SET relation = %s WHERE relation = %s",
        (new_model, old_model),
    )
    # ir_model_data: model column (references to records of this model)
    cr.execute(
        "UPDATE ir_model_data SET model = %s WHERE model = %s",
        (new_model, old_model),
    )
    # ir_model_constraint
    if _table_exists(cr, "ir_model_constraint"):
        cr.execute(
            """
            UPDATE ir_model_constraint
            SET model = subq.id
            FROM (SELECT id FROM ir_model WHERE model = %s) subq
            WHERE ir_model_constraint.model IN (
                SELECT id FROM ir_model WHERE model = %s
            )
        """,
            (new_model, old_model),
        )
    # ir_model_relation
    if _table_exists(cr, "ir_model_relation"):
        cr.execute(
            """
            UPDATE ir_model_relation
            SET model = subq.id
            FROM (SELECT id FROM ir_model WHERE model = %s) subq
            WHERE ir_model_relation.model IN (
                SELECT id FROM ir_model WHERE model = %s
            )
        """,
            (new_model, old_model),
        )
    # ir_rule: update model_id FK
    cr.execute(
        """
        UPDATE ir_rule
        SET model_id = (SELECT id FROM ir_model WHERE model = %s LIMIT 1)
        WHERE model_id IN (SELECT id FROM ir_model WHERE model = %s)
    """,
        (new_model, old_model),
    )
    # ir_act_server
    if _table_exists(cr, "ir_act_server") and _column_exists(
        cr, "ir_act_server", "model_name"
    ):
        cr.execute(
            "UPDATE ir_act_server SET model_name = %s WHERE model_name = %s",
            (new_model, old_model),
        )
    _logger.info("Renamed model %s → %s (via SQL)", old_model, new_model)


def _rename_table_sql(cr, old_table, new_table):
    """Rename a table, its PK sequence and PK constraint."""
    if not _table_exists(cr, old_table):
        _logger.info("Table %s does not exist, skipping rename", old_table)
        return
    if _table_exists(cr, new_table):
        _logger.warning(
            "Target table %s already exists, skipping rename of %s",
            new_table,
            old_table,
        )
        return

    cr.execute('ALTER TABLE "%s" RENAME TO "%s"' % (old_table, new_table))

    # Rename PK sequence
    old_seq = "%s_id_seq" % old_table
    new_seq = "%s_id_seq" % new_table
    cr.execute("SELECT 1 FROM pg_class WHERE relname = %s", (old_seq,))
    if cr.fetchone():
        cr.execute('ALTER SEQUENCE "%s" RENAME TO "%s"' % (old_seq, new_seq))

    # Rename PK constraint
    cr.execute(
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = '%s'::regclass AND contype = 'p'
    """
        % new_table
    )
    pk = cr.fetchone()
    if pk:
        old_pk = pk[0]
        new_pk = "%s_pkey" % new_table
        if old_pk != new_pk:
            cr.execute('ALTER INDEX "%s" RENAME TO "%s"' % (old_pk, new_pk))

    _logger.info("Renamed table %s → %s (via SQL)", old_table, new_table)


def _rename_field_sql(cr, model, table, old_field, new_field):
    """Rename a field (column + ir_model_fields entry)."""
    # Rename column
    if _table_exists(cr, table) and _column_exists(cr, table, old_field):
        if _column_exists(cr, table, new_field):
            _logger.warning(
                "Target column %s.%s already exists, skipping rename of %s",
                table,
                new_field,
                old_field,
            )
        else:
            cr.execute(
                'ALTER TABLE "%s" RENAME COLUMN "%s" TO "%s"'
                % (table, old_field, new_field)
            )
            _logger.info(
                "Renamed column %s.%s → %s (via SQL)", table, old_field, new_field
            )
    # Update ir_model_fields
    cr.execute(
        """
        UPDATE ir_model_fields
        SET name = %s
        WHERE model = %s AND name = %s
    """,
        (new_field, model, old_field),
    )
    # Update ir_model_data for the field entry
    old_xmlid_name = "field_%s__%s" % (model.replace(".", "_"), old_field)
    new_xmlid_name = "field_%s__%s" % (model.replace(".", "_"), new_field)
    cr.execute(
        """
        UPDATE ir_model_data
        SET name = %s
        WHERE name = %s AND model = 'ir.model.fields'
    """,
        (new_xmlid_name, old_xmlid_name),
    )
    _logger.info("Renamed field %s.%s → %s (via SQL)", model, old_field, new_field)


# ---------------------------------------------------------------------------
# Conflict detection for official Odoo account_loans module
# ---------------------------------------------------------------------------


def _official_module_owns_model(cr, model_name):
    """Check if a model is owned by the official 'account_loans' module."""
    cr.execute(
        """
        SELECT imd.module
        FROM ir_model_data imd
        JOIN ir_model im ON im.id = imd.res_id
        WHERE imd.model = 'ir.model'
          AND im.model = %s
        ORDER BY imd.id
        LIMIT 1
    """,
        (model_name,),
    )
    row = cr.fetchone()
    return row and row[0] == "account_loans"


# ---------------------------------------------------------------------------
# Main migration function
# ---------------------------------------------------------------------------


def migrate(cr, version):
    _logger.info("Starting pre-migration for account_loan_oca %s", version)

    # --- Detect if old data exists that needs migration ---
    old_model_present = _model_exists_in_registry(cr, "account.loan")
    old_table_present = _table_exists(cr, "account_loan") and not _table_exists(
        cr, "account_loan_oca"
    )

    if not old_model_present and not old_table_present:
        _logger.info(
            "No old account_loan models/tables found. "
            "Nothing to migrate in pre-migration."
        )
        return

    # --- Check for official Odoo account_loans module conflicts ---
    cr.execute(
        """
        SELECT state FROM ir_module_module
        WHERE name = 'account_loans' AND state IN ('installed', 'to upgrade')
    """
    )
    has_official = bool(cr.fetchone())
    if has_official:
        _logger.warning(
            "Official Odoo 'account_loans' module is installed. "
            "Checking model ownership to avoid conflicts..."
        )
        if old_model_present and _official_module_owns_model(cr, "account.loan"):
            _logger.warning(
                "The 'account.loan' model is owned by the official 'account_loans' "
                "module. Skipping model/table renames to avoid conflicts. "
                "The OCA module will create its own 'account.loan.oca' model."
            )
            # Only update sequence code (OCA-specific)
            cr.execute(
                """
                UPDATE ir_sequence
                SET code = 'account.loan.oca'
                WHERE code = 'account.loan'
                  AND id IN (
                      SELECT res_id FROM ir_model_data
                      WHERE module = 'account_loan_oca'
                        AND model = 'ir.sequence'
                  )
            """
            )
            return

    # --- Try to use odoo.upgrade.util if available ---
    _use_util = False
    util = None
    try:
        from odoo.upgrade import util as _util

        util = _util
        _use_util = True
        _logger.info("odoo.upgrade.util is available, will use it for renames")
    except ImportError:
        _logger.info(
            "odoo.upgrade.util not available, using raw SQL for migration"
        )

    # ================================================================
    # 1. RENAME MODELS
    #    rename_model() also renames the table (rename_table=True default)
    #    so we do NOT call rename_table separately when using util.
    # ================================================================
    model_renames = [
        ("account.loan", "account.loan.oca"),
        ("account.loan.line", "account.loan.line.oca"),
        # Transient wizard models
        ("account.loan.generate.wizard", "account.loan.oca.generate.wizard"),
        ("account.loan.pay.amount", "account.loan.oca.pay.amount"),
        ("account.loan.post", "account.loan.oca.post"),
        ("account.loan.increase.amount", "account.loan.oca.increase.amount"),
    ]

    if _use_util:
        for old_model, new_model in model_renames:
            if _model_exists_in_registry(cr, old_model):
                try:
                    util.rename_model(cr, old_model, new_model)
                    _logger.info(
                        "Renamed model %s → %s (via util)", old_model, new_model
                    )
                except Exception as e:
                    _logger.warning(
                        "util.rename_model(%s → %s) failed: %s. Falling back to SQL.",
                        old_model,
                        new_model,
                        e,
                    )
                    _rename_model_sql(cr, old_model, new_model)
                    _rename_table_sql(
                        cr,
                        old_model.replace(".", "_"),
                        new_model.replace(".", "_"),
                    )
            else:
                _logger.info(
                    "Model %s not found in DB, skipping rename", old_model
                )
    else:
        # SQL fallback: rename models first, then tables separately
        for old_model, new_model in model_renames:
            _rename_model_sql(cr, old_model, new_model)

        table_renames = [
            ("account_loan", "account_loan_oca"),
            ("account_loan_line", "account_loan_line_oca"),
            ("account_loan_generate_wizard", "account_loan_oca_generate_wizard"),
            ("account_loan_pay_amount", "account_loan_oca_pay_amount"),
            ("account_loan_post", "account_loan_oca_post"),
            ("account_loan_increase_amount", "account_loan_oca_increase_amount"),
        ]
        for old_table, new_table in table_renames:
            _rename_table_sql(cr, old_table, new_table)

    # ================================================================
    # 2. RENAME FIELDS on inherited models
    #    Old: account.move.loan_id / account.move.loan_line_id
    #    New: account.move.loan_oca_id / account.move.loan_line_oca_id
    # ================================================================
    field_renames = [
        ("account.move", "account_move", "loan_id", "loan_oca_id"),
        ("account.move", "account_move", "loan_line_id", "loan_line_oca_id"),
    ]

    if _use_util:
        for model, _table, old_field, new_field in field_renames:
            if _column_exists(cr, _table, old_field):
                try:
                    util.rename_field(cr, model, old_field, new_field)
                    _logger.info(
                        "Renamed field %s.%s → %s (via util)",
                        model,
                        old_field,
                        new_field,
                    )
                except Exception as e:
                    _logger.warning(
                        "util.rename_field(%s.%s) failed: %s. Falling back to SQL.",
                        model,
                        old_field,
                        e,
                    )
                    _rename_field_sql(cr, model, _table, old_field, new_field)
            else:
                _logger.info(
                    "Column %s.%s not found, skipping field rename",
                    _table,
                    old_field,
                )
    else:
        for model, _table, old_field, new_field in field_renames:
            _rename_field_sql(cr, model, _table, old_field, new_field)

    # ================================================================
    # 3. UPDATE ir.sequence CODE
    #    Old: account.loan → New: account.loan.oca
    # ================================================================
    cr.execute(
        """
        UPDATE ir_sequence
        SET code = 'account.loan.oca'
        WHERE code = 'account.loan'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Updated ir.sequence code: account.loan → account.loan.oca (%d rows)",
            cr.rowcount,
        )

    # ================================================================
    # 4. UPDATE AUTO-GENERATED XML ID NAMES in ir_model_data
    #    The module prefix was already updated by pre_init_hook.
    #    Here we update the *name* part for auto-generated entries like
    #    model_account_loan → model_account_loan_oca
    # ================================================================
    xmlid_name_renames = [
        # ir.model entries
        ("model_account_loan", "model_account_loan_oca"),
        ("model_account_loan_line", "model_account_loan_line_oca"),
        ("model_account_loan_generate_wizard", "model_account_loan_oca_generate_wizard"),
        ("model_account_loan_pay_amount", "model_account_loan_oca_pay_amount"),
        ("model_account_loan_post", "model_account_loan_oca_post"),
        ("model_account_loan_increase_amount", "model_account_loan_oca_increase_amount"),
    ]
    for old_name, new_name in xmlid_name_renames:
        cr.execute(
            """
            UPDATE ir_model_data
            SET name = %s
            WHERE name = %s
              AND module = 'account_loan_oca'
              AND model = 'ir.model'
        """,
            (new_name, old_name),
        )
        if cr.rowcount:
            _logger.info("Renamed XML ID name: %s → %s", old_name, new_name)

    # Update ir.model.fields XML ID names (field_account_loan__* → field_account_loan_oca__*)
    cr.execute(
        """
        UPDATE ir_model_data
        SET name = REPLACE(name, 'field_account_loan__', 'field_account_loan_oca__')
        WHERE name LIKE 'field_account_loan__%%'
          AND module = 'account_loan_oca'
          AND model = 'ir.model.fields'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Updated %d XML ID names for ir.model.fields (account_loan → account_loan_oca)",
            cr.rowcount,
        )

    cr.execute(
        """
        UPDATE ir_model_data
        SET name = REPLACE(name, 'field_account_loan_line__', 'field_account_loan_line_oca__')
        WHERE name LIKE 'field_account_loan_line__%%'
          AND module = 'account_loan_oca'
          AND model = 'ir.model.fields'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Updated %d XML ID names for ir.model.fields (account_loan_line → account_loan_line_oca)",
            cr.rowcount,
        )

    # Update ir.model.access XML ID names
    cr.execute(
        """
        UPDATE ir_model_data
        SET name = REPLACE(name, 'access_account_loan_', 'access_account_loan_oca_')
        WHERE name LIKE 'access_account_loan_%%'
          AND module = 'account_loan_oca'
          AND model = 'ir.model.access'
    """
    )

    _logger.info("Pre-migration for account_loan_oca completed successfully")

