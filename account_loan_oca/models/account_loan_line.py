# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)
try:
    import numpy_financial
except (OSError, ImportError) as err:
    _logger.error(err)


class AccountLoanLine(models.Model):
    _inherit = "account.loan.line"

    # ------------------------------------------------------------------
    # OCA-specific fields (not in the official account_loans module)
    # ------------------------------------------------------------------
    name = fields.Char(compute="_compute_oca_name")
    oca_rate = fields.Float(
        string="Rate",
        digits=(8, 6),
    )
    oca_pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        string="Pending Principal",
        help="Pending amount of the loan before the payment",
    )
    oca_long_term_pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        string="Long Term Pending",
        readonly=True,
        help="Pending amount of the loan before the payment that will not be "
        "payed in, at least, 12 months",
    )
    oca_long_term_principal_amount = fields.Monetary(
        currency_field="currency_id",
        string="Long Term Principal",
        readonly=True,
        help="Amount that will reduce the pending loan amount on long term",
    )
    oca_final_pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_oca_final_pending",
        store=True,
        string="Final Pending Principal",
        help="Pending amount of the loan after the payment",
    )
    oca_has_moves = fields.Boolean(compute="_compute_oca_has_moves")
    oca_has_invoices = fields.Boolean(compute="_compute_oca_has_invoices")

    # Related fields from loan for OCA functionality
    oca_partner_id = fields.Many2one(
        "res.partner", related="loan_id.partner_id"
    )
    oca_is_leasing = fields.Boolean(related="loan_id.is_leasing")
    oca_short_term_account_id = fields.Many2one(
        "account.account", related="loan_id.short_term_account_id"
    )
    oca_long_term_account_id = fields.Many2one(
        "account.account", related="loan_id.long_term_account_id"
    )
    oca_expense_account_id = fields.Many2one(
        "account.account", related="loan_id.expense_account_id"
    )
    oca_loan_type = fields.Selection(related="loan_id.loan_type")

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------

    @api.depends("generated_move_ids")
    def _compute_oca_has_moves(self):
        for record in self:
            record.oca_has_moves = bool(record.generated_move_ids)

    @api.depends("generated_move_ids")
    def _compute_oca_has_invoices(self):
        for record in self:
            record.oca_has_invoices = bool(record.generated_move_ids)

    @api.depends("loan_id.name", "sequence")
    def _compute_oca_name(self):
        for record in self:
            record.name = "%s-%d" % (record.loan_id.name or "", record.sequence)

    @api.depends("principal", "interest", "oca_pending_principal_amount")
    def _compute_oca_final_pending(self):
        for rec in self:
            rec.oca_final_pending_principal_amount = (
                rec.oca_pending_principal_amount - rec.principal
            )

    # ------------------------------------------------------------------
    # OCA computation logic
    # ------------------------------------------------------------------

    def _oca_compute_amount(self):
        """Computes the payment amount (principal + interest) for this line."""
        if self.sequence == self.loan_id.duration:
            return (
                self.oca_pending_principal_amount
                + self.interest
                - self.loan_id.residual_amount
            )
        if self.oca_loan_type == "fixed-principal" and self.loan_id.round_on_end:
            return self.loan_id.fixed_amount + self.interest
        if self.oca_loan_type == "fixed-principal":
            return (
                self.oca_pending_principal_amount - self.loan_id.residual_amount
            ) / (self.loan_id.duration - self.sequence + 1) + self.interest
        if self.oca_loan_type == "interest":
            return self.interest
        if self.oca_loan_type == "fixed-annuity" and self.loan_id.round_on_end:
            return self.loan_id.fixed_amount
        if self.oca_loan_type == "fixed-annuity":
            return self.currency_id.round(
                -numpy_financial.pmt(
                    self.loan_id._loan_rate() / 100,
                    self.loan_id.duration - self.sequence + 1,
                    self.oca_pending_principal_amount,
                    -self.loan_id.residual_amount,
                )
            )
        if (
            self.oca_loan_type == "fixed-annuity-begin"
            and self.loan_id.round_on_end
        ):
            return self.loan_id.fixed_amount
        if self.oca_loan_type == "fixed-annuity-begin":
            return self.currency_id.round(
                -numpy_financial.pmt(
                    self.loan_id._loan_rate() / 100,
                    self.loan_id.duration - self.sequence + 1,
                    self.oca_pending_principal_amount,
                    -self.loan_id.residual_amount,
                    when="begin",
                )
            )

    def _oca_check_amount(self):
        """Recompute amounts if the line has not been processed."""
        if self.generated_move_ids:
            raise UserError(
                self.env._(
                    "Amount cannot be recomputed if moves or invoices exists already"
                )
            )
        interest_val = self._oca_compute_interest()
        payment_val = 0.0
        if (
            self.sequence == self.loan_id.duration
            and self.loan_id.round_on_end
            and self.oca_loan_type in ["fixed-annuity", "fixed-annuity-begin"]
        ):
            interest_val = self.currency_id.round(
                self.loan_id.fixed_amount
                - self.oca_pending_principal_amount
                + self.loan_id.residual_amount
            )
            self.interest = interest_val
            payment_val = self.currency_id.round(self._oca_compute_amount())
        elif not self.loan_id.round_on_end:
            interest_val = self.currency_id.round(interest_val)
            self.interest = interest_val
            payment_val = self.currency_id.round(self._oca_compute_amount())
        else:
            self.interest = interest_val
            payment_val = self._oca_compute_amount()
        # principal = payment - interest
        self.principal = payment_val - self.interest

    def _oca_compute_interest(self):
        if self.oca_loan_type == "fixed-annuity-begin":
            return -numpy_financial.ipmt(
                self.loan_id._loan_rate() / 100,
                2,
                self.loan_id.duration - self.sequence + 1,
                self.oca_pending_principal_amount,
                -self.loan_id.residual_amount,
                when="begin",
            )
        return self.oca_pending_principal_amount * self.loan_id._loan_rate() / 100

    def _oca_check_move_amount(self):
        """Update line amounts from posted moves."""
        self.ensure_one()
        interests_moves = self.generated_move_ids.mapped("line_ids").filtered(
            lambda r: r.account_id == self.loan_id.expense_account_id
        )
        short_term_moves = self.generated_move_ids.mapped("line_ids").filtered(
            lambda r: r.account_id == self.loan_id.short_term_account_id
        )
        long_term_moves = self.generated_move_ids.mapped("line_ids").filtered(
            lambda r: r.account_id == self.loan_id.long_term_account_id
        )
        interest_val = sum(interests_moves.mapped("debit")) - sum(
            interests_moves.mapped("credit")
        )
        lt_principal = sum(long_term_moves.mapped("debit")) - sum(
            long_term_moves.mapped("credit")
        )
        payment_val = (
            sum(short_term_moves.mapped("debit"))
            - sum(short_term_moves.mapped("credit"))
            + lt_principal
            + interest_val
        )
        self.interest = interest_val
        self.principal = payment_val - interest_val
        self.oca_long_term_principal_amount = lt_principal

    # ------------------------------------------------------------------
    # Move / Invoice generation (OCA workflow)
    # ------------------------------------------------------------------

    def _oca_move_vals(self, journal=False, account=False):
        return {
            "generating_loan_line_id": self.id,
            "date": self.date,
            "ref": self.name,
            "journal_id": (journal and journal.id) or self.loan_id.journal_id.id,
            "line_ids": [
                Command.create(vals)
                for vals in self._oca_move_line_vals(account=account)
            ],
        }

    def _oca_move_line_vals(self, account=False):
        vals = []
        partner = self.loan_id.partner_id.with_company(self.loan_id.company_id)
        payment_val = self.principal + self.interest
        partner_account = (
            partner.property_account_payable_id
            if payment_val > 0
            else partner.property_account_receivable_id
        )
        vals.append(
            {
                "account_id": (account and account.id) or partner_account.id,
                "partner_id": partner.id,
                "credit": payment_val if payment_val > 0 else 0,
                "debit": -payment_val if payment_val < 0 else 0,
            }
        )
        if self.interest:
            amount = self.interest
            vals.append(
                {
                    "account_id": self.loan_id.expense_account_id.id,
                    "credit": -amount if amount < 0 else 0,
                    "debit": amount if amount > 0 else 0,
                }
            )
        diff_amount = self.principal
        vals.append(
            {
                "account_id": self.loan_id.short_term_account_id.id,
                "credit": -diff_amount if diff_amount < 0 else 0,
                "debit": diff_amount if diff_amount > 0 else 0,
            }
        )
        if (
            self.oca_long_term_account_id
            and self.oca_long_term_principal_amount
        ):
            amount = self.oca_long_term_principal_amount
            vals.append(
                {
                    "account_id": self.loan_id.short_term_account_id.id,
                    "credit": amount if amount > 0 else 0,
                    "debit": -amount if amount < 0 else 0,
                }
            )
            vals.append(
                {
                    "account_id": self.oca_long_term_account_id.id,
                    "credit": -amount if amount < 0 else 0,
                    "debit": amount if amount > 0 else 0,
                }
            )
        return vals

    def _oca_invoice_vals(self):
        return {
            "generating_loan_line_id": self.id,
            "move_type": "in_invoice",
            "partner_id": self.loan_id.partner_id.id,
            "invoice_date": self.date,
            "journal_id": self.loan_id.journal_id.id,
            "company_id": self.loan_id.company_id.id,
            "invoice_line_ids": [
                Command.create(vals) for vals in self._oca_invoice_line_vals()
            ],
        }

    def _oca_invoice_line_vals(self):
        vals = list()
        vals.append(
            {
                "product_id": self.loan_id.product_id.id,
                "name": self.loan_id.product_id.name,
                "quantity": 1,
                "price_unit": self.principal,
                "account_id": self.loan_id.short_term_account_id.id,
            }
        )
        vals.append(
            {
                "product_id": self.loan_id.interests_product_id.id,
                "name": self.loan_id.interests_product_id.name,
                "quantity": 1,
                "price_unit": self.interest,
                "account_id": self.loan_id.expense_account_id.id,
            }
        )
        return vals

    def _oca_generate_move(self, journal=False, account=False):
        """Compute and post the moves of loans."""
        res = []
        for record in self:
            if not record.generated_move_ids:
                if record.loan_id.line_ids.filtered(
                    lambda r, record=record: r.date < record.date
                    and not r.generated_move_ids
                ):
                    raise UserError(
                        self.env._("Some moves must be created first")
                    )
                move = self.env["account.move"].create(
                    record._oca_move_vals(journal=journal, account=account)
                )
                move.action_post()
                res.append(move.id)
        return res

    def _oca_long_term_move_vals(self):
        return {
            "generating_loan_line_id": self.id,
            "date": self.date,
            "ref": self.name,
            "journal_id": self.loan_id.journal_id.id,
            "line_ids": [
                Command.create(vals)
                for vals in self._oca_get_long_term_move_line_vals()
            ],
        }

    def _oca_generate_invoice(self):
        """Compute invoices of leases."""
        res = []
        for record in self:
            if not record.generated_move_ids:
                if record.loan_id.line_ids.filtered(
                    lambda r, rec=record: r.date < rec.date
                    and not r.generated_move_ids
                ):
                    raise UserError(
                        self.env._("Some invoices must be created first")
                    )
                invoice = self.env["account.move"].create(
                    record._oca_invoice_vals()
                )
                res.append(invoice.id)
                for line in invoice.invoice_line_ids:
                    line.tax_ids = line._get_computed_taxes()
                invoice.flush_recordset()
                invoice.filtered(
                    lambda m: m.currency_id.round(m.amount_total) < 0
                ).action_switch_move_type()
                if record.loan_id.post_invoice:
                    invoice.action_post()
                if (
                    record.oca_long_term_account_id
                    and record.oca_long_term_principal_amount != 0
                ):
                    move = self.env["account.move"].create(
                        record._oca_long_term_move_vals()
                    )
                    if record.loan_id.post_invoice:
                        move.action_post()
                    res.append(move.id)
        return res

    def _oca_get_long_term_move_line_vals(self):
        return [
            {
                "account_id": self.loan_id.short_term_account_id.id,
                "credit": self.oca_long_term_principal_amount,
                "debit": 0,
            },
            {
                "account_id": self.oca_long_term_account_id.id,
                "credit": 0,
                "debit": self.oca_long_term_principal_amount,
            },
        ]

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------

    def oca_view_account_values(self):
        """Shows the invoice if it is a leasing or the move if it is a loan."""
        self.ensure_one()
        if self.oca_is_leasing:
            return self.oca_view_account_invoices()
        return self.oca_view_account_moves()

    def oca_view_process_values(self):
        """Process and view the annuity result."""
        self.ensure_one()
        if self.oca_is_leasing:
            self._oca_generate_invoice()
        else:
            self._oca_generate_move()
        return self.oca_view_account_values()

    def oca_view_account_moves(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_line_form"
        )
        result["context"] = {
            "default_generating_loan_line_id": self.id,
        }
        result["domain"] = [("generating_loan_line_id", "=", self.id)]
        if len(self.generated_move_ids) == 1:
            res = self.env.ref("account.view_move_form", False)
            result["views"] = [(res and res.id or False, "form")]
            result["res_id"] = self.generated_move_ids.id
        return result

    def oca_view_account_invoices(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_out_invoice_type"
        )
        result["context"] = {
            "default_generating_loan_line_id": self.id,
        }
        result["domain"] = [("generating_loan_line_id", "=", self.id)]
        if len(self.generated_move_ids) == 1:
            res = self.env.ref("account.view_move_form", False)
            result["views"] = [(res and res.id or False, "form")]
            result["res_id"] = self.generated_move_ids.id
        return result
