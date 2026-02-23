# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    loan_line_oca_id = fields.Many2one(
        "account.loan.line.oca",
        readonly=True,
        ondelete="restrict",
    )
    loan_oca_id = fields.Many2one(
        "account.loan.oca",
        readonly=True,
        store=True,
        ondelete="restrict",
    )

    def action_post(self):
        res = super().action_post()
        for record in self:
            loan_line_id = record.loan_line_oca_id
            if loan_line_id:
                record.loan_oca_id = loan_line_id.loan_id
                record.loan_line_oca_id._check_move_amount()
                if record.loan_line_oca_id.sequence == record.loan_oca_id.periods:
                    record.loan_oca_id.close()
        return res
