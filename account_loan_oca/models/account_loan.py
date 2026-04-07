# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging
import math
from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
try:
    import numpy_financial
except (OSError, ImportError) as err:
    _logger.debug(err)


class AccountLoan(models.Model):
    _inherit = "account.loan"

    # ------------------------------------------------------------------
    # OCA-specific fields (not in the official account_loans module)
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        "res.partner",
        string="Lender",
        help="Company or individual that lends the money at an interest rate.",
    )
    rate = fields.Float(
        default=0.0,
        digits=(8, 6),
        help="Currently applied rate",
        tracking=True,
    )
    rate_period = fields.Float(
        compute="_compute_rate_period",
        digits=(8, 6),
        help="Real rate that will be applied on each period",
    )
    rate_type = fields.Selection(
        [("napr", "Nominal APR"), ("ear", "EAR"), ("real", "Real rate")],
        help="Method of computation of the applied rate",
        default="napr",
    )
    loan_type = fields.Selection(
        [
            ("fixed-annuity", "Fixed Annuity"),
            ("fixed-annuity-begin", "Fixed Annuity Begin"),
            ("fixed-principal", "Fixed Principal"),
            ("interest", "Only interest"),
        ],
        help="Method of computation of the period annuity",
        default="fixed-annuity",
    )
    method_period = fields.Integer(
        string="Period Length",
        default=1,
        help="State here the time between 2 depreciations, in months",
    )
    fixed_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_fixed_amount",
    )
    fixed_loan_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
        copy=False,
        default=0,
    )
    fixed_periods = fields.Integer(
        readonly=True,
        copy=False,
        default=0,
    )
    residual_amount = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
        help="Residual amount of the lease that must be payed on the end in "
        "order to acquire the asset",
    )
    round_on_end = fields.Boolean(
        help="When checked, the differences will be applied on the last period"
        ", if it is unchecked, the annuity will be recalculated on each "
        "period.",
    )
    payment_on_first_period = fields.Boolean(
        help="When checked, the first payment will be on start date",
    )
    is_leasing = fields.Boolean()
    leased_asset_account_id = fields.Many2one(
        "account.account",
        domain="[('company_ids', '=', company_id)]",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Loan product",
        help="Product where the amount of the loan will be assigned when the "
        "invoice is created",
    )
    interests_product_id = fields.Many2one(
        "product.product",
        string="Interest product",
        help="Product where the amount of interests will be assigned when the "
        "invoice is created",
    )
    post_invoice = fields.Boolean(
        default=True, help="Invoices will be posted automatically"
    )

    # OCA computed fields
    journal_type = fields.Char(compute="_compute_journal_type")
    oca_pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_oca_total_amounts",
        string="Pending Principal (OCA)",
    )
    oca_payment_amount = fields.Monetary(
        currency_field="currency_id",
        string="Total payed amount",
        compute="_compute_oca_total_amounts",
    )
    oca_interests_amount = fields.Monetary(
        currency_field="currency_id",
        string="Total interests payed",
        compute="_compute_oca_total_amounts",
    )
    oca_move_count = fields.Integer(
        compute="_compute_oca_move_count",
        string="OCA Move Count",
    )

    _sql_constraints = [
        (
            "oca_name_uniq",
            "unique(name, company_id)",
            "Loan name must be unique",
        ),
    ]

    # ------------------------------------------------------------------
    # Onchanges
    # ------------------------------------------------------------------

    @api.onchange("rate")
    def _onchange_rate_warning(self):
        if self.state != "draft":
            return {
                "warning": {
                    "title": self.env._("Rate Change"),
                    "message": self.env._(
                        "You have modified the interest rate. Click the Compute items "
                        "button to update the lines. Please note that if you have "
                        "manually edited these lines, those changes will be lost upon "
                        "computation."
                    ),
                }
            }

    @api.onchange("line_ids")
    def _onchange_line_ids_draft_manual(self):
        self.line_ids = self.line_ids.sorted(key=lambda line: line.sequence)
        previous_pending_principal = 0
        previous_principal_amount = 0
        for line in self.line_ids:
            if line.sequence == 1:
                line.oca_pending_principal_amount = self.amount_borrowed
            else:
                line.oca_pending_principal_amount = (
                    previous_pending_principal - previous_principal_amount
                )
            previous_pending_principal = line.oca_pending_principal_amount
            previous_principal_amount = line.principal

    # ------------------------------------------------------------------
    # Compute methods
    # ------------------------------------------------------------------

    @api.depends("line_ids.generated_move_ids")
    def _compute_oca_move_count(self):
        for item in self:
            item.oca_move_count = len(item.line_ids.generated_move_ids)

    @api.depends("line_ids", "currency_id", "amount_borrowed")
    def _compute_oca_total_amounts(self):
        for record in self:
            lines = record.line_ids.filtered(lambda r: r.generated_move_ids)
            record.oca_payment_amount = sum(lines.mapped("payment")) or 0.0
            record.oca_interests_amount = sum(lines.mapped("interest")) or 0.0
            record.oca_pending_principal_amount = (
                record.amount_borrowed
                - record.oca_payment_amount
                + record.oca_interests_amount
            )

    @api.depends("rate_period", "fixed_loan_amount", "fixed_periods", "currency_id")
    def _compute_fixed_amount(self):
        for record in self:
            if record.loan_type == "fixed-annuity":
                record.fixed_amount = -record.currency_id.round(
                    numpy_financial.pmt(
                        record._loan_rate() / 100,
                        record.fixed_periods,
                        record.fixed_loan_amount,
                        -record.residual_amount,
                    )
                )
            elif record.loan_type == "fixed-annuity-begin":
                record.fixed_amount = -record.currency_id.round(
                    numpy_financial.pmt(
                        record._loan_rate() / 100,
                        record.fixed_periods,
                        record.fixed_loan_amount,
                        -record.residual_amount,
                        when="begin",
                    )
                )
            elif record.loan_type == "fixed-principal":
                record.fixed_amount = record.currency_id.round(
                    (record.fixed_loan_amount - record.residual_amount)
                    / record.fixed_periods
                )
            else:
                record.fixed_amount = 0.0

    @api.model
    def _compute_rate_static(self, rate, rate_type, method_period):
        """Returns the real rate."""
        if rate_type == "napr":
            return rate / 12 * method_period
        if rate_type == "ear":
            return math.pow(1 + rate, method_period / 12) - 1
        return rate

    @api.depends("rate", "method_period", "rate_type")
    def _compute_rate_period(self):
        for record in self:
            record.rate_period = record._loan_rate()

    def _loan_rate(self):
        return self._compute_rate_static(self.rate, self.rate_type, self.method_period)

    @api.depends("is_leasing")
    def _compute_journal_type(self):
        for record in self:
            if record.is_leasing:
                record.journal_type = "purchase"
            else:
                record.journal_type = "general"

    # ------------------------------------------------------------------
    # Onchanges
    # ------------------------------------------------------------------

    @api.onchange("is_leasing")
    def _onchange_is_leasing(self):
        self.journal_id = self.env["account.journal"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("type", "=", "purchase" if self.is_leasing else "general"),
            ],
            limit=1,
        )
        self.residual_amount = 0.0

    @api.onchange("company_id")
    def _onchange_company(self):
        self._onchange_is_leasing()
        self.expense_account_id = self.short_term_account_id = (
            self.long_term_account_id
        ) = False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _get_default_name(self, vals):
        return self.env["ir.sequence"].next_by_code("account.loan.oca") or "/"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self._get_default_name(vals)
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # OCA workflow actions
    # ------------------------------------------------------------------

    def oca_post(self):
        """Post a loan using OCA workflow (state → running)."""
        self.ensure_one()
        if not self.date:
            self.date = fields.Date.today()
        if not self.line_ids:
            self._oca_compute_draft_lines()
        self.write({"state": "running"})

    def close(self):
        self.write({"state": "closed"})

    def oca_compute_lines(self):
        """Compute / recompute loan lines using OCA amortization engine."""
        self.ensure_one()
        if self.state == "draft":
            return self._oca_compute_draft_lines()
        return self._oca_compute_posted_lines()

    def _oca_compute_posted_lines(self):
        """Recompute amortisation of not-yet-processed lines."""
        amount = self.amount_borrowed
        for line in self.line_ids.sorted("sequence"):
            if line.generated_move_ids:
                amount = line.oca_final_pending_principal_amount
            else:
                line.oca_rate = self.rate_period
                line.oca_pending_principal_amount = amount
                line._oca_check_amount()
                amount -= line.payment - line.interest
        if self.long_term_account_id:
            self._oca_check_long_term_principal_amount()

    def _oca_check_long_term_principal_amount(self):
        """Recompute the long term pending principal of unfinished lines."""
        lines = self.line_ids.filtered(lambda r: not r.generated_move_ids)
        amount = 0
        if not lines:
            return
        final_sequence = min(lines.mapped("sequence"))
        for line in lines.sorted("sequence", reverse=True):
            date = line.date + relativedelta(months=12)
            if self.state == "draft" or line.sequence != final_sequence:
                line.oca_long_term_pending_principal_amount = sum(
                    self.line_ids.filtered(
                        lambda r, date=date: r.date >= date
                    ).mapped("principal")
                )
            line.oca_long_term_principal_amount = (
                line.oca_long_term_pending_principal_amount - amount
            )
            amount = line.oca_long_term_pending_principal_amount

    def _oca_new_line_vals(self, sequence, date, amount):
        return {
            "loan_id": self.id,
            "sequence": sequence,
            "date": date,
            "oca_pending_principal_amount": amount,
            "oca_rate": self.rate_period,
        }

    def _oca_compute_draft_lines(self):
        self.ensure_one()
        self.fixed_periods = self.duration
        self.fixed_loan_amount = self.amount_borrowed
        self.line_ids.unlink()
        amount = self.amount_borrowed
        if self.date:
            date = self.date
        else:
            date = datetime.today().date()
        initial_date = date
        delta = relativedelta(months=self.method_period)
        if not self.payment_on_first_period:
            date = initial_date + delta
            initial_date = date
        for i in range(1, self.duration + 1):
            line = self.env["account.loan.line"].create(
                self._oca_new_line_vals(i, date, amount)
            )
            line._oca_check_amount()
            date = initial_date + delta * i
            amount -= line.payment - line.interest
        if self.long_term_account_id:
            self._oca_check_long_term_principal_amount()

    def oca_button_draft(self):
        for item in self:
            if item.state not in ("running", "cancelled") or item.nb_posted_entries > 0:
                raise UserError(
                    self.env._(
                        "It is only possible to change to draft if the status is "
                        "cancelled or running and there are no account moves."
                    )
                )
            item.state = "draft"

    def oca_view_account_moves(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_line_form"
        )
        result["domain"] = [
            ("generating_loan_line_id", "in", self.line_ids.ids),
        ]
        return result

    def oca_view_account_invoices(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_in_invoice_type"
        )
        result["domain"] = [
            ("generating_loan_line_id", "in", self.line_ids.ids),
            ("move_type", "=", "in_invoice"),
        ]
        return result

    @api.model
    def _generate_loan_entries(self, date):
        """Generate the moves of unfinished loans before date."""
        res = []
        for record in self.search(
            [("state", "=", "running"), ("is_leasing", "=", False)]
        ):
            lines = record.line_ids.filtered(
                lambda r: r.date <= date and not r.generated_move_ids
            )
            res += lines._oca_generate_move()
        return res

    @api.model
    def _generate_leasing_entries(self, date):
        res = []
        for record in self.search(
            [("state", "=", "running"), ("is_leasing", "=", True)]
        ):
            res += record.line_ids.filtered(
                lambda r: r.date <= date and not r.generated_move_ids
            )._oca_generate_invoice()
        return res
