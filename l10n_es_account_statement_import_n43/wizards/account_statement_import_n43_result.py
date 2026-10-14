# Copyright 2026 Domatix
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class AccountStatementImportN43Result(models.TransientModel):
    _name = "account.statement.import.n43.result"
    _description = "N43 import result"

    statement_ids = fields.Many2many("account.bank.statement")
    line_ids = fields.One2many("account.statement.import.n43.result.line", "wizard_id")

    def action_view_statements(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_bank_statement_tree"
        )
        action["domain"] = [("id", "in", self.statement_ids.ids)]
        return action


class AccountStatementImportN43ResultLine(models.TransientModel):
    _name = "account.statement.import.n43.result.line"
    _description = "N43 import skipped movement"
    _order = "date, id"

    wizard_id = fields.Many2one(
        "account.statement.import.n43.result", required=True, ondelete="cascade"
    )
    date = fields.Date()
    amount = fields.Float(digits=(16, 2))
    payment_ref = fields.Char()
    matched_line_id = fields.Many2one("account.bank.statement.line")
    matched_statement_name = fields.Char(
        related="matched_line_id.statement_id.name", readonly=True
    )
