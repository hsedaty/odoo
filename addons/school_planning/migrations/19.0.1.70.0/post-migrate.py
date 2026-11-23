from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    years = env['school.academic.years'].search([('dataset_type', '=', 'forecast')])
    env['school.financial.report']._refresh_for_academic_years(years.ids)
