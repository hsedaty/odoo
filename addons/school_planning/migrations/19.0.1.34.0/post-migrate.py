import logging

from odoo import SUPERUSER_ID, api


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configuration = env.ref('school_planning.prediction_seed_configuration')
    configuration._merge_legacy_expense_seeds()
    cr.execute('''
        UPDATE school_expense_values AS value
           SET expense_item_id = NULL
          FROM school_expense_items AS item,
               school_expense_categories AS category,
               school_academic_years AS year
         WHERE value.expense_item_id = item.id
           AND item.expense_category_id = category.id
           AND value.academic_year_id = year.id
           AND NOT COALESCE(year.baseline_locked, FALSE)
           AND value.prediction_input_mode IS NOT NULL
           AND lower(trim(item.name)) = lower(trim(category.name))
           AND EXISTS (
               SELECT 1 FROM school_prediction_seed_expense_category AS seed
                WHERE lower(trim(seed.name)) = lower(trim(category.name))
           )
    ''')
    _logger.info('Converted %s generated placeholder expense values to direct categories', cr.rowcount)
    env.invalidate_all()
    years = env['school.academic.years'].search([('dataset_type', '=', 'actual')])
    years._ensure_forecast_expense_structure()
    env['school.financial.report']._refresh_for_academic_years(years.ids)