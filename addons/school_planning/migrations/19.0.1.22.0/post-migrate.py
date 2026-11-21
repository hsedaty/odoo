from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['school.academic.years'].search([('dataset_type', '=', 'actual'), ('forecast_year_id', '!=', False)])._ensure_forecast_expense_structure()