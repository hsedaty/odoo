from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    years = env['school.academic.years'].search([
        ('dataset_type', '=', 'forecast'), ('detailed_expenses_created', '=', True), ('baseline_locked', '=', False),
    ])
    years.fee_value_ids._compute_revenue_metrics()
    env['school.financial.report']._refresh_for_academic_years(years.ids)
