# Copyright 2016-2018 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import common
from odoo.tools.misc import file_path


def _build_n43_file(movements):
    """Build a minimal valid N43 file with the given movements.

    Each movement is a dict with keys: fecha (yymmdd string), ref
    (referencia2), amount (float, negative for debits) and concept (free
    text of the concept record).
    """
    header = (
        "11"  # record code
        "2080"  # entidad
        "0646"  # oficina
        + "0" * 10  # cuenta
        + "260801260831"  # fecha_ini + fecha_fin
        + "2"  # saldo_ini sign
        + "0" * 12
        + "00"  # saldo_ini = 0 (skips the group balance check)
        + "978"  # divisa EUR
        + "2"  # modalidad
        + "TEST BUILDER N43".ljust(26)
    )
    lines = [header]
    debit_count = 0
    debit_cents = 0
    credit_count = 0
    credit_cents = 0
    for mov in movements:
        cents = round(abs(mov["amount"]) * 100)
        if mov["amount"] < 0:
            debit_count += 1
            debit_cents += cents
            sign = "1"
        else:
            credit_count += 1
            credit_cents += cents
            sign = "0"
        lines.append(
            "22"
            + " " * 4
            + "0646"  # oficina origen
            + mov["fecha"]  # fecha_oper
            + mov["fecha"]  # fecha_valor
            + "05"  # concepto común
            + "010"  # concepto propio
            + sign
            + f"{cents // 100:012d}{cents % 100:02d}"
            + " " * 10  # num_documento
            + " " * 12  # referencia1
            + mov["ref"]  # referencia2
        )
        lines.append("2301" + mov["concept"].ljust(35))
    lines.append(
        "33"
        + "0" * 18
        + f"{debit_count:05d}"
        + f"{debit_cents // 100:012d}{debit_cents % 100:02d}"
        + f"{credit_count:05d}"
        + f"{credit_cents // 100:012d}{credit_cents % 100:02d}"
        + "2"  # saldo_fin sign
        + "0" * 12
        + "00"  # saldo_fin = 0 (skips the group balance check)
    )
    total = len(lines) + 1  # including this record 88
    lines.append("88" + "9" * 18 + f"{total:06d}")
    return "\n".join(lines)


class L10nEsAccountStatementImportN43(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test partner N43", "company_id": cls.env.company.id}
        )
        cls.partner_bank = cls.env["res.partner.bank"].create(
            {
                "acc_number": "000000000000000000000000",
                "company_id": cls.env.company.id,
                "partner_id": cls.env.company.partner_id.id,
            }
        )
        cls.partner_bank_01 = cls.env["res.partner.bank"].create(
            {
                "acc_number": "000000000000001000000000",
                "company_id": cls.env.company.id,
                "partner_id": cls.env.company.partner_id.id,
            }
        )
        eur_currency = cls.env.ref("base.EUR")
        eur_currency.write({"active": True})
        cls.journal = cls.env["account.journal"].create(
            {
                "type": "bank",
                "name": "Test N43 bank",
                "code": "BN43",
                "company_id": cls.env.company.id,
                "bank_account_id": cls.partner_bank.id,
                "currency_id": eur_currency.id,
            }
        )
        cls.journal_01 = cls.env["account.journal"].create(
            {
                "type": "bank",
                "name": "Test N43 bank",
                "code": "BN432",
                "company_id": cls.env.company.id,
                "bank_account_id": cls.partner_bank_01.id,
                "currency_id": eur_currency.id,
            }
        )
        n43_file_path = file_path("l10n_es_account_statement_import_n43/tests/test.n43")
        n43_file = base64.b64encode(open(n43_file_path, "rb").read())
        cls.import_wizard = (
            cls.env["account.statement.import"]
            .with_context(journal_id=cls.journal.id)
            .create({"statement_file": n43_file, "statement_filename": "Test"})
        )

    def test_import_n43_multi(self):
        n43_file_path = file_path(
            "l10n_es_account_statement_import_n43/tests/testmulti.n43"
        )
        n43_file = base64.b64encode(open(n43_file_path, "rb").read())
        self.import_wizard.statement_file = n43_file
        action = self.import_wizard.with_context(journal_id=False).import_file_button()
        self.assertTrue(action)
        statements = self.env["account.bank.statement"].search(
            [("journal_id", "=", self.journal.id)]
        )
        self.assertEqual(1, len(statements))
        statements = self.env["account.bank.statement"].search(
            [("journal_id", "=", self.journal_01.id)]
        )
        self.assertEqual(1, len(statements))

    def test_import_n43(self):
        action = self.import_wizard.import_file_button()
        self.assertTrue(action)
        statement_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        statement = statement_lines[2].statement_id
        self.assertEqual(len(statement_lines), 3)
        self.assertTrue(
            statement_lines.filtered(lambda st: str(st.date) == "2016-05-25")
        )
        self.assertTrue(
            statement_lines.filtered(lambda st: str(st.date) == "2016-05-16")
        )
        self.assertTrue(
            statement_lines.filtered(lambda st: str(st.date) == "2016-05-12")
        )
        self.assertEqual(statement_lines[0].date, fields.Date.to_date("2016-05-25"))
        self.assertAlmostEqual(statement.balance_start, 0, 2)
        self.assertAlmostEqual(statement.balance_end, 101.96, 2)
        self.assertEqual(statement_lines[2].partner_id, self.partner)
        self.assertEqual(statement_lines[2].ref, "000975737917")
        self.assertEqual(statement_lines[1].ref, "/")
        self.assertEqual(statement_lines[0].ref, "5540014210128010")

    def test_import_n43_fecha_oper(self):
        self.journal.n43_date_type = "fecha_oper"
        action = self.import_wizard.import_file_button()
        self.assertTrue(action)
        statements = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertEqual(statements[0].date, fields.Date.to_date("2016-05-26"))

    def test_import_n43_excluded_patern(self):
        self.journal.n43_exclude_pattern = r".*TEST PARTNER 2.*"
        self.import_wizard.import_file_button()
        st_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertEqual(len(st_lines), 2)

    def test_import_n43_twice_no_duplicates(self):
        """Reimporting the same file does not create duplicated lines: the
        already imported movements are skipped thanks to unique_import_id."""
        self.import_wizard.import_file_button()
        st_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertEqual(len(st_lines), 3)
        self.assertTrue(all(line.unique_import_id for line in st_lines))
        with self.assertRaises(UserError):
            self.import_wizard.import_file_button()
        st_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertEqual(len(st_lines), 3)

    def test_import_n43_overlapping_files_no_duplicates(self):
        """Movements arriving again in a file with different composition
        (overlapping date ranges) are skipped, whatever their position."""
        movements = [
            {"fecha": "260815", "ref": "REFA", "amount": 100.0, "concept": "CONCEPT A"},
            {
                "fecha": "260816",
                "ref": "REFB",
                "amount": -200.0,
                "concept": "CONCEPT B",
            },
        ]
        self.import_wizard.statement_file = base64.b64encode(
            _build_n43_file(movements).encode()
        )
        self.import_wizard.import_file_button()
        st_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertEqual(len(st_lines), 2)
        line_a = st_lines.filtered(lambda line: line.amount == 100.0)
        # A second file covering a wider range repeats those movements at
        # different positions: only the new ones must be imported
        wider = [
            {"fecha": "260710", "ref": "REFX", "amount": 50.0, "concept": "CONCEPT X"},
            *movements,
            {"fecha": "260901", "ref": "REFC", "amount": 300.0, "concept": "CONCEPT C"},
        ]
        wiz_b = (
            self.env["account.statement.import"]
            .with_context(journal_id=self.journal.id)
            .create(
                {
                    "statement_file": base64.b64encode(_build_n43_file(wider).encode()),
                    "statement_filename": "overlap.n43",
                }
            )
        )
        action = wiz_b.import_file_button()
        # The skipped movements are listed in a result dialog with the
        # existing line each one matches
        self.assertEqual(action["res_model"], "account.statement.import.n43.result")
        result_wizard = self.env["account.statement.import.n43.result"].browse(
            action["res_id"]
        )
        self.assertEqual(len(result_wizard.line_ids), 2)
        self.assertIn(line_a.id, result_wizard.line_ids.matched_line_id.ids)
        statements_action = result_wizard.action_continue()
        self.assertEqual(
            statements_action["domain"],
            [["id", "in", result_wizard.statement_ids.ids]],
        )
        st_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertEqual(len(st_lines), 4)
        self.assertEqual(
            sorted(st_lines.mapped("amount")), [-200.0, 50.0, 100.0, 300.0]
        )

    def test_import_n43_reconcile_button_overlap(self):
        """The "Import and Reconcile" button also opens the result dialog."""
        try:
            self.env["ir.actions.actions"]._for_xml_id(
                "account_reconcile_oca.action_bank_statement_line_reconcile"
            )
        except ValueError:
            self.skipTest("account_reconcile_oca is not installed")
        movements = [
            {"fecha": "260815", "ref": "REFA", "amount": 100.0, "concept": "CONCEPT A"},
        ]
        self.import_wizard.statement_file = base64.b64encode(
            _build_n43_file(movements).encode()
        )
        self.import_wizard.import_file_and_reconcile_button()
        wider = [
            *movements,
            {"fecha": "260901", "ref": "REFC", "amount": 300.0, "concept": "CONCEPT C"},
        ]
        wiz_b = (
            self.env["account.statement.import"]
            .with_context(journal_id=self.journal.id)
            .create(
                {
                    "statement_file": base64.b64encode(_build_n43_file(wider).encode()),
                    "statement_filename": "overlap2.n43",
                }
            )
        )
        action = wiz_b.import_file_and_reconcile_button()
        self.assertEqual(action["res_model"], "account.statement.import.n43.result")
        result_wizard = self.env["account.statement.import.n43.result"].browse(
            action["res_id"]
        )
        self.assertEqual(len(result_wizard.line_ids), 1)
        continue_action = result_wizard.action_continue()
        self.assertEqual(
            continue_action["context"]["default_journal_id"], self.journal.id
        )

    def test_import_n43_identical_movements_rejected(self):
        """A file with two fully identical movements is rejected with a
        clear message instead of crashing on the unique constraint."""
        twin = {
            "fecha": "260815",
            "ref": "REFT",
            "amount": 100.0,
            "concept": "CONCEPT T",
        }
        self.import_wizard.statement_file = base64.b64encode(
            _build_n43_file([twin, dict(twin)]).encode()
        )
        with self.assertRaises(UserError):
            self.import_wizard.import_file_button()
        st_lines = self.env["account.bank.statement.line"].search(
            [("statement_id.journal_id", "=", self.journal.id)]
        )
        self.assertFalse(st_lines)
