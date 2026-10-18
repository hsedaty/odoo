from odoo.tools.sql import column_exists, table_exists


def migrate(cr, version):
    if table_exists(cr, 'school_expense_values') and column_exists(cr, 'school_expense_values', 'expense_category_id'):
        cr.execute('''
            UPDATE school_expense_values AS value
               SET expense_category_id = item.expense_category_id
              FROM school_expense_items AS item
             WHERE value.expense_item_id = item.id
               AND value.expense_category_id IS NULL
        ''')