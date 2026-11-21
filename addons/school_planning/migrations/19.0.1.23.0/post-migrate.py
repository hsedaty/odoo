from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'actual_structure_only': True, 'defer_school_financial_refresh': True})
    years = env['school.academic.years'].search([('baseline_locked', '=', False)])
    for year in years.filtered(lambda record: record.infrastructure_mode == 'new'):
        year._seed_infrastructure()
    plans = years.mapped('room_plan_ids')
    env.add_to_compute(plans._fields['calculated_new_rooms'], plans)
    plans._recompute_recordset()
    env['school.financial.report'].with_context(defer_school_financial_refresh=False)._refresh_for_academic_years(years.ids)