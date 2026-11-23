def migrate(cr, version):
    cr.execute("ALTER TABLE school_academic_years ADD COLUMN IF NOT EXISTS legacy_detailed_tax boolean")
    cr.execute("""
        UPDATE school_academic_years
           SET legacy_detailed_tax = TRUE
         WHERE dataset_type = 'forecast' AND baseline_locked AND detailed_expenses_created
    """)
