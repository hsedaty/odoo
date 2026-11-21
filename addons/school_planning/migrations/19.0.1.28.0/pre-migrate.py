from odoo.tools.sql import table_exists


def migrate(cr, version):
    cr.execute('SELECT id FROM school_schools ORDER BY id')
    school_ids = [row[0] for row in cr.fetchall()]
    cr.execute('SELECT id, name, percentage FROM school_tax_rules WHERE school_id IS NULL ORDER BY id')
    for tax_id, name, percentage in cr.fetchall():
        assigned = False
        for school_id in school_ids:
            cr.execute('SELECT id FROM school_tax_rules WHERE school_id = %s AND name ILIKE %s AND percentage = %s ORDER BY id LIMIT 1',
                       (school_id, name, percentage))
            existing = cr.fetchone()
            if existing:
                local_id = existing[0]
            elif not assigned:
                cr.execute('UPDATE school_tax_rules SET school_id = %s WHERE id = %s', (school_id, tax_id))
                local_id = tax_id
                assigned = True
            else:
                cr.execute('INSERT INTO school_tax_rules (school_id, name, percentage) VALUES (%s, %s, %s) RETURNING id',
                           (school_id, name, percentage))
                local_id = cr.fetchone()[0]
            if local_id == tax_id:
                continue
            cr.execute('UPDATE school_fee_types SET tax_rule_id = %s WHERE school_id = %s AND tax_rule_id = %s',
                       (local_id, school_id, tax_id))
            if table_exists(cr, 'school_actual_fee_tax_rel'):
                cr.execute('''UPDATE school_actual_fee_tax_rel AS mapping SET tax_rule_id = %s
                              FROM school_fee_values AS fee, school_academic_years AS year
                              WHERE mapping.fee_value_id = fee.id AND fee.academic_year_id = year.id
                                AND year.school_id = %s AND mapping.tax_rule_id = %s''', (local_id, school_id, tax_id))
            if table_exists(cr, 'school_actual_bulk_fee_tax_rel'):
                cr.execute('''UPDATE school_actual_bulk_fee_tax_rel AS mapping SET tax_rule_id = %s
                              FROM school_academic_years AS year
                              WHERE mapping.year_id = year.id AND year.school_id = %s AND mapping.tax_rule_id = %s''',
                           (local_id, school_id, tax_id))
        if not assigned:
            cr.execute("DELETE FROM ir_model_data WHERE model = 'school.tax.rules' AND res_id = %s", (tax_id,))
            cr.execute('DELETE FROM school_tax_rules WHERE id = %s', (tax_id,))