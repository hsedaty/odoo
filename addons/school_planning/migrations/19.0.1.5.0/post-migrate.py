from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tax_rules = env['school.tax.rules'].with_context(active_test=False).search(
        [], order='id asc'
    )
    canonical_rules = {}

    for rule in tax_rules:
        key = ((rule.name or '').strip().casefold(), float(rule.percentage or 0.0))
        canonical = canonical_rules.get(key)
        if canonical:
            env['school.fee.types'].search([('tax_rule_id', '=', rule.id)]).write({
                'tax_rule_id': canonical.id,
            })
            rule.unlink()
        else:
            canonical_rules[key] = rule

    env['school.tax.rules'].search([('school_id', '!=', False)]).write({
        'school_id': False,
    })