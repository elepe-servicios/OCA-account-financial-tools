# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models
from odoo.exceptions import UserError


class AccountLoanPayAmount(models.TransientModel):
    _name = "account.loan.oca.pay.amount"
    _description = "Loan pay amount"

    loan_id = fields.Many2one(
        "account.loan",
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="loan_id.currency_id", readonly=True
    )
    cancel_loan = fields.Boolean(
        default=False,
    )
    date = fields.Date(required=True, default=fields.Date.today())
    amount = fields.Monetary(
        currency_field="currency_id",
        string="Amount to reduce from Principal",
    )
    fees = fields.Monetary(currency_field="currency_id", string="Bank fees")

    @api.onchange("cancel_loan")
    def _onchange_cancel_loan(self):
        if self.cancel_loan:
            self.amount = max(
                self.loan_id.line_ids.filtered(lambda r: not r.generated_move_ids).mapped(
                    "oca_pending_principal_amount"
                )
            )

    def new_line_vals(self, sequence):
        return {
            "loan_id": self.loan_id.id,
            "sequence": sequence,
            "principal": self.amount,
            "interest": self.fees,
            "oca_rate": 0,
            "date": self.date,
        }

    def run(self):
        self.ensure_one()
        if self.loan_id.is_leasing:
            if self.loan_id.line_ids.filtered(
                lambda r: r.date <= self.date and not r.generated_move_ids
            ):
                raise UserError(self.env._("Some invoices are not created"))
            if self.loan_id.line_ids.filtered(
                lambda r: r.date > self.date and r.generated_move_ids
            ):
                raise UserError(self.env._("Some future invoices already exists"))
        else:
            if self.loan_id.line_ids.filtered(
                lambda r: r.date < self.date and not r.generated_move_ids
            ):
                raise UserError(self.env._("Some moves are not created"))
            if self.loan_id.line_ids.filtered(
                lambda r: r.date > self.date and r.generated_move_ids
            ):
                raise UserError(self.env._("Some future moves already exists"))
        lines = self.loan_id.line_ids.filtered(lambda r: r.date > self.date).sorted(
            "sequence", reverse=True
        )
        sequence = min(lines.mapped("sequence"))
        for line in lines:
            line.sequence += 1
            line.flush_recordset()
        old_line = lines.filtered(lambda r: r.sequence == sequence + 1)
        pending = old_line.oca_pending_principal_amount
        if self.loan_id.currency_id.compare_amounts(self.amount, pending) == 1:
            raise UserError(self.env._("Amount cannot be bigger than debt"))
        if self.loan_id.currency_id.compare_amounts(self.amount, 0) <= 0:
            raise UserError(self.env._("Amount cannot be less than zero"))
        self.loan_id.duration += 1
        self.loan_id.fixed_periods = self.loan_id.duration - sequence
        self.loan_id.fixed_loan_amount = pending - self.amount
        new_line = self.env["account.loan.line"].create(self.new_line_vals(sequence))
        new_line.oca_long_term_pending_principal_amount = (
            old_line.oca_long_term_pending_principal_amount
        )
        amount = self.loan_id.amount_borrowed
        for line in self.loan_id.line_ids.sorted("sequence"):
            if line.generated_move_ids:
                amount = line.oca_final_pending_principal_amount
            else:
                line.oca_pending_principal_amount = amount
                if line.sequence != sequence:
                    line.oca_rate = self.loan_id.rate_period
                    line._oca_check_amount()
                amount -= line.principal
        if self.loan_id.long_term_account_id:
            self.loan_id._oca_check_long_term_principal_amount()
        if self.loan_id.currency_id.compare_amounts(pending, self.amount) == 0:
            self.loan_id.write({"state": "cancelled"})
        return new_line.oca_view_process_values()
