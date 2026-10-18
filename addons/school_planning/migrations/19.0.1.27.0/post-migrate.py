from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'actual_structure_only': True, 'defer_school_financial_refresh': True})
    years = env['school.academic.years'].search([('dataset_type', '=', 'actual')])
    years._prepare_actual_entry_rows()
    for row in years.mapped('fee_value_ids'):
        values = {}
        if not row.actual_tax_rule_ids and row.actual_tax_percent:
            rate = row.actual_tax_percent / 100
            tax = row.fee_type_id.tax_rule_id
            if not tax or abs(tax.percentage - rate) > 0.000001:
                tax = env['school.tax.rules'].search([('school_id', '=', False), ('name', '=', 'Actual Fee Tax'), ('percentage', '=', rate)], limit=1)
                if not tax:
                    tax = env['school.tax.rules'].create({'name': 'Actual Fee Tax', 'percentage': rate})
            values['actual_tax_rule_ids'] = [fields.Command.set(tax.ids)]
        if row.fee_type_id.is_optional and row.actual_applicability == 'all':
            values.update({'actual_applicability': 'selected', 'actual_selected_students': row.enrolled_students if row.amount else 0})
        if values:
            row.write(values)
    env['school.financial.report'].with_context(defer_school_financial_refresh=False)._refresh_for_academic_years(years.ids)