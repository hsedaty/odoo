from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'actual_structure_only': True, 'defer_school_financial_refresh': True})
    years = env['school.academic.years'].search([('dataset_type', '=', 'actual')])
    years._ensure_forecast_expense_structure()
    years._prepare_actual_entry_rows()
    for year in years:
        if all(year[f'{section}_status'] == 'complete' for section in ('enrollment', 'income', 'expenses', 'payroll', 'assets')):
            year.teaching_status = 'complete'
        elif any(year.subject_distribution_ids.mapped('weekly_hours')):
            year.teaching_status = 'in_progress'
    env['school.financial.report'].with_context(defer_school_financial_refresh=False)._refresh_for_academic_years(years.ids)