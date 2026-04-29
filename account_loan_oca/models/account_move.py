# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    oca_loan_line_id = fields.Many2one(
        comodel_name="account.loan.line",
        string="OCA Loan Line",
        readonly=True,
        ondelete="restrict",
        copy=False,
        help="OCA loan line that generated this entry (migrated from V18).",
    )

    def action_post(self):
        res = super().action_post()
        for record in self:
            loan_line = record.generating_loan_line_id
            if loan_line and loan_line.loan_id.loan_type:
                # OCA workflow: update line amounts and close if last
                loan_line._oca_check_move_amount()
                if loan_line.sequence == loan_line.loan_id.duration:
                    loan_line.loan_id.close()
        return res
