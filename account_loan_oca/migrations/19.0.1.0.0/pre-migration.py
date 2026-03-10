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
    # mail_message: update model references (chatter messages)
    if _table_exists(cr, "mail_message"):
        cr.execute(
            "UPDATE mail_message SET model = %s WHERE model = %s",
            (new_model, old_model),
        )
    # mail_followers: update res_model references
    if _table_exists(cr, "mail_followers"):
        cr.execute(
            "UPDATE mail_followers SET res_model = %s WHERE res_model = %s",
            (new_model, old_model),
        )
    # mail_activity: update res_model references
    if _table_exists(cr, "mail_activity"):
        cr.execute(
            "UPDATE mail_activity SET res_model = %s WHERE res_model = %s",
            (new_model, old_model),
        )
    # ir_attachment: update res_model references
    if _table_exists(cr, "ir_attachment"):
        cr.execute(
            "UPDATE ir_attachment SET res_model = %s WHERE res_model = %s",
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

    # Rename unique/check constraints that reference the old table name
    cr.execute(
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = '%s'::regclass
          AND conname LIKE '%%' || '%s' || '%%'
    """
        % (new_table, old_table)
    )
    for (conname,) in cr.fetchall():
        new_conname = conname.replace(old_table, new_table)
        if conname != new_conname:
            cr.execute(
                'ALTER TABLE "%s" RENAME CONSTRAINT "%s" TO "%s"'
                % (new_table, conname, new_conname)
            )
            _logger.info("Renamed constraint %s → %s", conname, new_conname)

    # Rename indexes that reference the old table name
    cr.execute(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = %s AND indexname LIKE '%%' || %s || '%%'
    """,
        (new_table, old_table),
    )
    for (idxname,) in cr.fetchall():
        new_idxname = idxname.replace(old_table, new_table)
        if idxname != new_idxname:
            cr.execute(
                'ALTER INDEX "%s" RENAME TO "%s"' % (idxname, new_idxname)
            )
            _logger.info("Renamed index %s → %s", idxname, new_idxname)

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
# Table copy helper (used when official module owns the shared tables)
# ---------------------------------------------------------------------------


def _copy_table_with_data(cr, src_table, dst_table):
    """Copy a table structure and all data, preserving IDs.

    Used when the official ``account_loans`` module owns the original tables
    and we cannot RENAME them.  Instead we CREATE the new OCA tables and
    INSERT the data so both modules can coexist.
    """
    if not _table_exists(cr, src_table):
        _logger.info("Source table %s does not exist, nothing to copy", src_table)
        return False
    if _table_exists(cr, dst_table):
        _logger.warning(
            "Destination table %s already exists, skipping copy from %s",
            dst_table,
            src_table,
        )
        return False

    # Create new table with same structure and data
    cr.execute(
        'CREATE TABLE "%s" (LIKE "%s" INCLUDING DEFAULTS INCLUDING CONSTRAINTS)'
        % (dst_table, src_table)
    )
    # Copy all rows keeping the same IDs
    cr.execute(
        'INSERT INTO "%s" SELECT * FROM "%s"' % (dst_table, src_table)
    )
    cr.execute('SELECT COUNT(*) FROM "%s"' % dst_table)
    count = cr.fetchone()[0]

    # Ensure we have a proper PK
    cr.execute(
        """
        SELECT 1 FROM pg_constraint
        WHERE conrelid = '%s'::regclass AND contype = 'p'
    """
        % dst_table
    )
    if not cr.fetchone():
        cr.execute('ALTER TABLE "%s" ADD PRIMARY KEY (id)' % dst_table)

    # Set up the id sequence so new records get correct IDs
    seq_name = "%s_id_seq" % dst_table
    cr.execute("SELECT 1 FROM pg_class WHERE relname = %s", (seq_name,))
    if not cr.fetchone():
        cr.execute(
            'CREATE SEQUENCE "%s" OWNED BY "%s".id' % (seq_name, dst_table)
        )
    cr.execute(
        "SELECT setval('%s', COALESCE((SELECT MAX(id) FROM \"%s\"), 1))"
        % (seq_name, dst_table)
    )
    cr.execute(
        "ALTER TABLE \"%s\" ALTER COLUMN id SET DEFAULT nextval('%s')"
        % (dst_table, seq_name)
    )

    _logger.info(
        "Copied %d records from %s → %s (preserving IDs)",
        count,
        src_table,
        dst_table,
    )
    return True


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
# Conflict-aware migration (official account_loans present)
# ---------------------------------------------------------------------------


def _migrate_with_official_conflict(cr):
    """Handle migration when the official ``account_loans`` module owns the
    ``account.loan`` model.

    Scenario (V14 → V18 → V19):
    1. OCA ``account_loan`` was installed in V14 and created the data.
    2. On upgrade to V18, the official ``account_loans`` (auto_install=True)
       was automatically installed.  Since both modules define
       ``_name = "account.loan"``, Odoo merged them into one shared
       model / table.  The data is now "owned" by the official module.
    3. For V19, OCA renames to ``account_loan_oca`` with models ``*.oca``.
       We cannot RENAME the shared tables (the official module needs them),
       so we COPY all data to the new OCA tables and set up the new FK
       columns on ``account.move``.

    After this function runs:
    - ``account_loan_oca`` table has a full copy of ``account_loan`` data
      (same IDs).
    - ``account_loan_line_oca`` has a full copy of ``account_loan_line``.
    - ``account_move.loan_oca_id`` / ``loan_line_oca_id`` are populated.
    - The original tables are **untouched** for the official module.
    - Orphaned ``ir_model_data`` entries for the OCA module are cleaned up.
    """
    _logger.info(
        "Starting conflict-aware migration (official account_loans present)"
    )

    # ----------------------------------------------------------------
    # 1. COPY persistent model tables
    # ----------------------------------------------------------------
    _copy_table_with_data(cr, "account_loan", "account_loan_oca")
    _copy_table_with_data(cr, "account_loan_line", "account_loan_line_oca")

    # Fix the loan_id FK inside account_loan_line_oca — it still points
    # to account_loan.id which works because IDs are the same, but we
    # should also ensure the column name stays "loan_id" (the V19 OCA
    # model defines it as loan_id pointing to account.loan.oca).
    # No column rename needed: the column is already called "loan_id"
    # and the ORM will resolve it to the new comodel at runtime.

    # ----------------------------------------------------------------
    # 2. Handle account_move FK columns
    #    Old fields: loan_id, loan_line_id (shared with official module)
    #    New fields: loan_oca_id, loan_line_oca_id
    #    We CREATE new columns and COPY values (don't touch originals).
    # ----------------------------------------------------------------
    if _column_exists(cr, "account_move", "loan_id"):
        if not _column_exists(cr, "account_move", "loan_oca_id"):
            cr.execute(
                "ALTER TABLE account_move ADD COLUMN loan_oca_id INTEGER"
            )
        # Copy every loan_id that references a record we just copied
        cr.execute(
            """
            UPDATE account_move am
            SET loan_oca_id = am.loan_id
            WHERE am.loan_id IS NOT NULL
              AND am.loan_oca_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM account_loan_oca al
                  WHERE al.id = am.loan_id
              )
        """
        )
        if cr.rowcount:
            _logger.info(
                "Copied %d loan_id values to loan_oca_id on account_move",
                cr.rowcount,
            )

    if _column_exists(cr, "account_move", "loan_line_id"):
        if not _column_exists(cr, "account_move", "loan_line_oca_id"):
            cr.execute(
                "ALTER TABLE account_move "
                "ADD COLUMN loan_line_oca_id INTEGER"
            )
        cr.execute(
            """
            UPDATE account_move am
            SET loan_line_oca_id = am.loan_line_id
            WHERE am.loan_line_id IS NOT NULL
              AND am.loan_line_oca_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM account_loan_line_oca all2
                  WHERE all2.id = am.loan_line_id
              )
        """
        )
        if cr.rowcount:
            _logger.info(
                "Copied %d loan_line_id values to loan_line_oca_id "
                "on account_move",
                cr.rowcount,
            )

    # ----------------------------------------------------------------
    # 3. UPDATE ir.sequence code (only OCA-owned sequence)
    # ----------------------------------------------------------------
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
    if cr.rowcount:
        _logger.info(
            "Updated OCA ir.sequence code: account.loan → account.loan.oca"
        )

    # ----------------------------------------------------------------
    # 4. Clean orphaned ir_model_data entries
    #    hooks.py re-pointed module=account_loan → account_loan_oca,
    #    but the auto-generated model/field entries now reference
    #    ir_model / ir_model_fields records that belong to the
    #    official module.  We must remove them so Odoo can create
    #    fresh entries for the new OCA models.
    # ----------------------------------------------------------------
    # Auto-generated ir.model entries (model_account_loan, etc.)
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model'
          AND name LIKE 'model_account_loan%%'
          AND name NOT LIKE 'model_account_loan_oca%%'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Removed %d orphaned ir_model_data entries (ir.model) "
            "that belong to official module",
            cr.rowcount,
        )

    # Auto-generated ir.model.fields entries
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model.fields'
          AND (
              name LIKE 'field_account_loan__%%'
              OR name LIKE 'field_account_loan_line__%%'
              OR name LIKE 'field_account_loan_generate_wizard__%%'
              OR name LIKE 'field_account_loan_pay_amount__%%'
              OR name LIKE 'field_account_loan_post__%%'
              OR name LIKE 'field_account_loan_increase_amount__%%'
          )
          AND name NOT LIKE '%%_oca%%'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Removed %d orphaned ir_model_data entries (ir.model.fields) "
            "that belong to official module",
            cr.rowcount,
        )

    # Auto-generated ir.model.access entries whose model_id FK points
    # to the official module's ir_model records
    cr.execute(
        """
        DELETE FROM ir_model_data
        WHERE module = 'account_loan_oca'
          AND model = 'ir.model.access'
          AND name LIKE 'access_account_loan%%'
          AND name NOT LIKE '%%_oca%%'
    """
    )
    if cr.rowcount:
        _logger.info(
            "Removed %d orphaned ir_model_data entries (ir.model.access)",
            cr.rowcount,
        )

    # ----------------------------------------------------------------
    # 5. ir_property: update references to the OCA model
    # ----------------------------------------------------------------
    if _table_exists(cr, "ir_property"):
        for old, new in [
            ("account.loan,", "account.loan.oca,"),
            ("account.loan.line,", "account.loan.line.oca,"),
        ]:
            cr.execute(
                """
                UPDATE ir_property
                SET res_id = REPLACE(res_id, %s, %s)
                WHERE res_id LIKE %s
            """,
                (old, new, old + "%"),
            )
            if _column_exists(cr, "ir_property", "value_reference"):
                cr.execute(
                    """
                    UPDATE ir_property
                    SET value_reference = REPLACE(value_reference, %s, %s)
                    WHERE value_reference LIKE %s
                """,
                    (old, new, old + "%"),
                )

    # ----------------------------------------------------------------
    # 6. Log warning about mail thread data
    #    Mail messages / followers will be updated in post-migration
    #    once the new model is registered in the ORM.
    # ----------------------------------------------------------------
    if _table_exists(cr, "mail_message"):
        cr.execute(
            """
            SELECT COUNT(*) FROM mail_message
            WHERE model IN ('account.loan', 'account.loan.line')
        """
        )
        msg_count = cr.fetchone()[0]
        if msg_count:
            _logger.warning(
                "Found %d mail.message records referencing the old "
                "model names (account.loan / account.loan.line). "
                "These will be updated to account.loan.oca / "
                "account.loan.line.oca in the post-migration step.",
                msg_count,
            )

    _logger.info(
        "Conflict-aware pre-migration completed.  Data copied to "
        "account_loan_oca / account_loan_line_oca tables."
    )


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
                "The 'account.loan' model is owned by the official "
                "'account_loans' module.  Cannot RENAME tables — will "
                "COPY data to new OCA tables instead."
            )
            _migrate_with_official_conflict(cr)
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
    # 2. RENAME FIELDS on inherited models (preparation)
    #    Old: account.move.loan_id / account.move.loan_line_id
    #    New: account.move.loan_oca_id / account.move.loan_line_oca_id
    #    The actual rename happens in section 3, which is
    #    conflict-aware when the official account_loans module is present.
    # ================================================================
    field_renames = [
        ("account.move", "account_move", "loan_id", "loan_oca_id"),
        ("account.move", "account_move", "loan_line_id", "loan_line_oca_id"),
    ]

    # ================================================================
    # 3. RENAME FIELDS on account.move — conflict-aware
    #    If the official account_loans module is installed AND also
    #    defines loan_id on account.move, we must NOT rename loan_id
    #    because the official module owns it. Instead we create a new
    #    column loan_oca_id and copy the OCA data to it.
    # ================================================================
    if has_official and _column_exists(cr, "account_move", "loan_id"):
        # Check if the official module also defines loan_id
        cr.execute(
            """
            SELECT 1 FROM ir_model_fields
            WHERE model = 'account.move'
              AND name = 'loan_id'
              AND id IN (
                  SELECT res_id FROM ir_model_data
                  WHERE module = 'account_loans'
                    AND model = 'ir.model.fields'
              )
        """
        )
        official_owns_loan_id = bool(cr.fetchone())
        if official_owns_loan_id:
            _logger.warning(
                "Official 'account_loans' module owns account.move.loan_id. "
                "Will copy data to loan_oca_id instead of renaming."
            )
            # Create the new column if it doesn't exist
            if not _column_exists(cr, "account_move", "loan_oca_id"):
                cr.execute(
                    "ALTER TABLE account_move ADD COLUMN loan_oca_id INTEGER"
                )
            # Copy data: only where loan_id references an OCA loan
            # (i.e., record exists in account_loan_oca table)
            new_loan_table = "account_loan_oca"
            if not _table_exists(cr, new_loan_table):
                new_loan_table = "account_loan"
            cr.execute(
                """
                UPDATE account_move am
                SET loan_oca_id = am.loan_id
                WHERE am.loan_id IS NOT NULL
                  AND am.loan_oca_id IS NULL
                  AND EXISTS (
                      SELECT 1 FROM "%s" al WHERE al.id = am.loan_id
                  )
            """
                % new_loan_table
            )
            if cr.rowcount:
                _logger.info(
                    "Copied %d loan_id values to loan_oca_id on account.move",
                    cr.rowcount,
                )
            # Similarly for loan_line_id → loan_line_oca_id
            if _column_exists(cr, "account_move", "loan_line_id"):
                if not _column_exists(cr, "account_move", "loan_line_oca_id"):
                    cr.execute(
                        "ALTER TABLE account_move ADD COLUMN loan_line_oca_id INTEGER"
                    )
                new_line_table = "account_loan_line_oca"
                if not _table_exists(cr, new_line_table):
                    new_line_table = "account_loan_line"
                cr.execute(
                    """
                    UPDATE account_move am
                    SET loan_line_oca_id = am.loan_line_id
                    WHERE am.loan_line_id IS NOT NULL
                      AND am.loan_line_oca_id IS NULL
                      AND EXISTS (
                          SELECT 1 FROM "%s" all2 WHERE all2.id = am.loan_line_id
                      )
                """
                    % new_line_table
                )
                if cr.rowcount:
                    _logger.info(
                        "Copied %d loan_line_id values to loan_line_oca_id "
                        "on account.move",
                        cr.rowcount,
                    )
            # Update ir_model_fields for the new field names (create entries)
            cr.execute(
                """
                UPDATE ir_model_fields
                SET name = 'loan_oca_id'
                WHERE model = 'account.move'
                  AND name = 'loan_id'
                  AND id IN (
                      SELECT res_id FROM ir_model_data
                      WHERE module = 'account_loan_oca'
                        AND model = 'ir.model.fields'
                  )
            """
            )
            cr.execute(
                """
                UPDATE ir_model_fields
                SET name = 'loan_line_oca_id'
                WHERE model = 'account.move'
                  AND name = 'loan_line_id'
                  AND id IN (
                      SELECT res_id FROM ir_model_data
                      WHERE module = 'account_loan_oca'
                        AND model = 'ir.model.fields'
                  )
            """
            )
        else:
            # Official module doesn't own loan_id, safe to rename
            for model, _table, old_field, new_field in field_renames:
                if _use_util:
                    if _column_exists(cr, _table, old_field):
                        try:
                            util.rename_field(cr, model, old_field, new_field)
                        except Exception as e:
                            _logger.warning(
                                "util.rename_field(%s.%s) failed: %s",
                                model,
                                old_field,
                                e,
                            )
                            _rename_field_sql(cr, model, _table, old_field, new_field)
                else:
                    _rename_field_sql(cr, model, _table, old_field, new_field)
    else:
        # No official module conflict — standard field rename
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
                            "util.rename_field(%s.%s) failed: %s. "
                            "Falling back to SQL.",
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
    # 4. UPDATE ir.sequence CODE
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
    # 5. UPDATE ir_property references (if table exists)
    #    Some Many2one fields may be stored as ir.property in older
    #    versions. We need to update the res_id references.
    # ================================================================
    if _table_exists(cr, "ir_property"):
        # Update res_id references like 'account.loan,123'
        cr.execute(
            """
            UPDATE ir_property
            SET res_id = REPLACE(res_id, 'account.loan,', 'account.loan.oca,')
            WHERE res_id LIKE 'account.loan,%%'
        """
        )
        if cr.rowcount:
            _logger.info(
                "Updated %d ir_property res_id references (account.loan → account.loan.oca)",
                cr.rowcount,
            )
        cr.execute(
            """
            UPDATE ir_property
            SET res_id = REPLACE(res_id, 'account.loan.line,', 'account.loan.line.oca,')
            WHERE res_id LIKE 'account.loan.line,%%'
        """
        )
        if cr.rowcount:
            _logger.info(
                "Updated %d ir_property res_id references "
                "(account.loan.line → account.loan.line.oca)",
                cr.rowcount,
            )
        # Update value_reference column
        if _column_exists(cr, "ir_property", "value_reference"):
            cr.execute(
                """
                UPDATE ir_property
                SET value_reference = REPLACE(
                    value_reference, 'account.loan,', 'account.loan.oca,'
                )
                WHERE value_reference LIKE 'account.loan,%%'
            """
            )
            cr.execute(
                """
                UPDATE ir_property
                SET value_reference = REPLACE(
                    value_reference, 'account.loan.line,', 'account.loan.line.oca,'
                )
                WHERE value_reference LIKE 'account.loan.line,%%'
            """
            )

    # ================================================================
    # 6. UPDATE AUTO-GENERATED XML ID NAMES in ir_model_data
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
            "Updated %d XML ID names for ir.model.fields "
            "(account_loan_line → account_loan_line_oca)",
            cr.rowcount,
        )

    # Update field XML IDs for wizard models
    wizard_field_renames = [
        ("field_account_loan_generate_wizard__", "field_account_loan_oca_generate_wizard__"),
        ("field_account_loan_pay_amount__", "field_account_loan_oca_pay_amount__"),
        ("field_account_loan_post__", "field_account_loan_oca_post__"),
        ("field_account_loan_increase_amount__", "field_account_loan_oca_increase_amount__"),
    ]
    for old_prefix, new_prefix in wizard_field_renames:
        cr.execute(
            """
            UPDATE ir_model_data
            SET name = REPLACE(name, %s, %s)
            WHERE name LIKE %s
              AND module = 'account_loan_oca'
              AND model = 'ir.model.fields'
        """,
            (old_prefix, new_prefix, old_prefix + "%"),
        )
        if cr.rowcount:
            _logger.info(
                "Updated %d XML ID names for wizard fields (%s → %s)",
                cr.rowcount,
                old_prefix,
                new_prefix,
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

    # ================================================================
    # 7. UPDATE ir.model.access: update the model_id FK to point to
    #    the renamed model records
    # ================================================================
    cr.execute(
        """
        UPDATE ir_model_access ima
        SET model_id = im.id
        FROM ir_model im
        WHERE im.model = 'account.loan.oca'
          AND ima.model_id IN (
              SELECT id FROM ir_model WHERE model = 'account.loan'
          )
          AND ima.id IN (
              SELECT res_id FROM ir_model_data
              WHERE module = 'account_loan_oca'
                AND model = 'ir.model.access'
          )
    """
    )
    cr.execute(
        """
        UPDATE ir_model_access ima
        SET model_id = im.id
        FROM ir_model im
        WHERE im.model = 'account.loan.line.oca'
          AND ima.model_id IN (
              SELECT id FROM ir_model WHERE model = 'account.loan.line'
          )
          AND ima.id IN (
              SELECT res_id FROM ir_model_data
              WHERE module = 'account_loan_oca'
                AND model = 'ir.model.access'
          )
    """
    )

    _logger.info("Pre-migration for account_loan_oca completed successfully")

