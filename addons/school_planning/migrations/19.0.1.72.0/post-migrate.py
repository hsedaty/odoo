from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    seeds = env['school.prediction.operational.seed'].search([
        ('active', '=', True), ('replaces_tuition', '=', True),
        ('category_seed_id.catalog_type', '=', 'income'),
    ])
    seeds.write({'basis': 'student'})
    years = env['school.academic.years'].search([('dataset_type', '=', 'forecast')])
    env['school.financial.report']._refresh_for_academic_years(years.ids)
