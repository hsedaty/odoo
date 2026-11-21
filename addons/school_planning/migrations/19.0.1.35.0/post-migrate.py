from odoo import SUPERUSER_ID, api
from odoo.tools.float_utils import float_compare


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'defer_school_financial_refresh': True})
    years = env['school.academic.years'].search([])
    values = env['school.expense.values'].search([])
    env.add_to_compute(values._fields['total_contribution'], values)
    values._recompute_recordset(['total_contribution'])
    for year in years.filtered(lambda record: not record.baseline_locked and record.payroll_summary_enabled
                               and record.payroll_basis == 'amount'):
        rows = year.payroll_expense_ids
        if rows and float_compare(year.payroll_fixed_amount, sum(rows.mapped('amount')), precision_digits=2) == 0:
            year.payroll_fixed_amount = rows._category_amount_total()
    env['school.financial.report'].with_context(defer_school_financial_refresh=False)._refresh_for_academic_years(years.ids)