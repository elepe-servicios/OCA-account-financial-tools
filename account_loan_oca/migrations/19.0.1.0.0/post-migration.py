# Copyright 2024 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
#
# NO-OP: This migration version used the old strategy (rename models to *.oca).
# That strategy has been replaced in 19.0.2.0.0 with _inherit on official models.
# All migration logic is now in migrations/19.0.2.0.0/.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info(
        "Skipping 19.0.1.0.0 post-migration (superseded by 19.0.2.0.0 strategy)"
    )
