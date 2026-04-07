# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import models


class AccountMove(models.Model):
    _inherit = "account.move"

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
