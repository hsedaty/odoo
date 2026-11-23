from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    years = env['school.academic.years'].search([('dataset_type', '=', 'forecast')])
    years.filtered(lambda year: not year.baseline_locked).mapped('fee_value_ids')._compute_revenue_metrics()
    env['school.financial.report']._refresh_for_academic_years(years.ids)
