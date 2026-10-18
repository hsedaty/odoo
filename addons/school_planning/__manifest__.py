{
    'name': 'School Budget & Planning System',
    'version': '19.0.1.36.0',
    'category': 'Education',
    'summary': 'Live calculation engine for school budgeting, staffing, asset and room planning',
    'description': """
School Budget & Planning System.

- Master Data (Gold Band): Rarely changes (structure, types, positions).
- Year Data (Blue Band): Re-entered every academic year (inputs).
- Calculated Results (Green Band): Live formulas driven by inputs, never stored.
- Financial Report (Reporting Band): Stored snapshot per academic year powering
  native pivot/graph analysis and Spreadsheet Dashboards (YoY growth, revenue,
  expense and profit charts).
""",
    'author': 'Abdullah Karakuyu',
    'depends': ['base', 'web', 'mail', 'google_gmail'],
    'post_init_hook': 'post_init_hook',
    'data': [
        'security/ir.model.access.csv',
        'data/web_assets.xml',
        'data/grade_presets.xml',
        'data/subject_presets.xml',
        'data/prediction_scenarios.xml',
        'data/prediction_seed_configuration.xml',
        'views/school_planning_frontend_templates.xml',
        'views/school_planning_prediction_templates.xml',
        'views/school_planning_views.xml',
        'views/school_financial_summary_report.xml',
        'views/school_financial_report_views.xml',
        'views/forecast_actual_views.xml',
        'views/efficiency_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}