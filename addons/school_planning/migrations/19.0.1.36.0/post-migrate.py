from odoo import SUPERUSER_ID, api


DEFAULT_PAYROLL = {
    'payroll_start_year_index': 1,
    'payroll_trend': 'revenue_decrease',
    'payroll_base_annual_amount': 50,
    'payroll_annual_change_percent': 3,
}


def _pick_seed(configuration):
    employee = configuration.expense_ids.filtered(lambda row: row.active and row.cost_bucket == 'employee')
    if not employee:
        return False
    salaries = employee.filtered(lambda row: row.name and row.name.strip().casefold() == 'salaries')
    return (salaries or employee).sorted(key=lambda row: (row.display_order, row.id))[0]


def _can_backfill(configuration):
    current = {
        'payroll_start_year_index': configuration.payroll_start_year_index,
        'payroll_trend': configuration.payroll_trend,
        'payroll_base_annual_amount': configuration.payroll_base_annual_amount,
        'payroll_annual_change_percent': configuration.payroll_annual_change_percent,
    }
    return any(not current[name] for name in ('payroll_start_year_index', 'payroll_trend')) or current == DEFAULT_PAYROLL


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    configurations = env['school.prediction.seed.configuration'].search([])
    for configuration in configurations:
        if not _can_backfill(configuration):
            continue
        seed = _pick_seed(configuration)
        if not seed:
            continue
        configuration.write({
            'payroll_start_year_index': seed.start_year_index,
            'payroll_trend': seed.trend,
            'payroll_base_annual_amount': seed.base_annual_amount,
            'payroll_annual_change_percent': seed.annual_change_percent,
        })
