from odoo.tools.sql import column_exists


def migrate(cr, version):
    for table, column in (
        ('school_academic_years', 'infrastructure_mode'),
        ('school_schools', 'default_infrastructure'),
        ('school_prediction_seed_configuration', 'infrastructure_mode'),
        ('school_prediction_quick_setup_wizard', 'infrastructure_mode'),
    ):
        if column_exists(cr, table, column):
            cr.execute(f"UPDATE {table} SET {column} = %s WHERE {column} = %s", ('new', 'none'))