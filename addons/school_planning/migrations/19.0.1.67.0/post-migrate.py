from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    seed = env.ref('school_planning.prediction_seed_tuition_fee', raise_if_not_found=False)
    names = ['tuition', 'tuition fee']
    if seed:
        names.append(seed.name.strip().casefold())
    fees = env['school.fee.types'].search([]).filtered(lambda fee: fee.name.strip().casefold() in names)
    fees.write({'forecast_tuition': True})
    tuition_items = env['school.prediction.operational.seed'].with_context(active_test=False).search([
        ('name', '=', 'Tuition Fees'), ('category_seed_id.name', '=', 'Incomes'),
        ('category_seed_id.parent_id', '=', False), ('category_seed_id.catalog_type', '=', 'income'),
    ])
    tuition_items.write({'replaces_tuition': True})
    years = env['school.academic.years'].search([('dataset_type', '=', 'forecast')])
    env['school.financial.report']._refresh_for_academic_years(years.ids)
