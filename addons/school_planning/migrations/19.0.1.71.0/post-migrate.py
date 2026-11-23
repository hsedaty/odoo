import json
import math
import uuid

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    years = env['school.academic.years'].search([
        ('dataset_type', '=', 'forecast'),
        ('forecast_fee_growth_batch', '=', False),
        ('original_forecast_settings', '!=', False),
    ])
    groups = {}
    for year in years:
        settings = year.original_forecast_settings
        if not isinstance(settings, list) or len(settings) < 2 or not isinstance(settings[0], dict):
            continue
        values = settings[0].get('values')
        if not isinstance(values, list) or len(values) < 5 or any(
            not isinstance(value, list) or len(value) != 2 for value in values[:5]
        ):
            continue
        start, count, rate = values[0][1], values[1][1], values[4][1]
        if (type(start) is not int or type(count) is not int or count < 1
                or type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0
                or not year.start_date or not start <= year.start_date.year < start + count
                or year.academic_year_name != f'{year.start_date.year}-{year.start_date.year + 1}'):
            continue
        key = (year.school_id.id, json.dumps(settings[:-1], sort_keys=True))
        groups.setdefault(key, []).append((year.id, rate))
    for group in groups.values():
        batch = uuid.uuid4().hex
        for year_id, rate in group:
            cr.execute(
                'UPDATE school_academic_years SET forecast_fee_growth_batch = %s, forecast_fee_growth_percent = %s WHERE id = %s',
                (batch, rate, year_id),
            )
