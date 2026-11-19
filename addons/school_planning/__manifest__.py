{
    'name': 'School Budget & Planning System',
    'version': '19.0.1.52.0',
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
- Dashboard: live school/dataset/year filters, financial and enrollment charts,
  sortable dynamic report with selectable columns and CSV/PDF export. Forecast
  and Actual are kept separate; unfinished Actual figures are provisional.
  Financial KPIs sum the selected period; Students shows its latest year.
  Select any academic years; Forecast vs Actual follows the same selection.
- Report branding: open a school's Report Branding settings to customize school
  and company logos, title, footer and grade detail for PDF and emailed reports.
  PDF amounts use green for inflows/surpluses, red negative amounts for outflows/
  deficits, and neutral zeroes. Signs are presentation-only; calculations do not change.
- Quick Prediction forecasts operating expenses as a percentage of revenue.
  The Starting Year is displayed without thousands separators.
  Edit the base percentage and annual percentage-point trend in All Expenses.
  Deleting built-in expense seeds is respected on module upgrades.
- The forecast Financial Summary and year workspace offer an optional detailed
  expense list. The checkboxes for each year determine which costs apply,
  including accreditation fees; no payment schedule is required. Costs are shown
  as a separate estimate without changing the existing percentage forecast.
  The baseline also shows expenses as a share of before- or after-tax revenue.
  Manage detailed categories in Expense Seeds. The dashboard's Expenses by
  category chart uses selected, priced details for years with a detailed list
  and percentage forecasts for other years; financial totals are unchanged.
  Administrators can edit or delete unused currencies from the Price Currency picker.
  The former development-only New UI URL now opens the integrated dashboard.
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
        'data/operational_expense_seeds.xml',
        'views/school_planning_frontend_templates.xml',
        'views/school_planning_prediction_templates.xml',
        'views/school_planning_views.xml',
        'views/school_financial_summary_report.xml',
        'views/school_financial_report_views.xml',
        'views/forecast_actual_views.xml',
        'views/efficiency_views.xml',
        'views/report_branding_views.xml',
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'school_planning/static/src/js/dashboard.js',
            'school_planning/static/src/xml/dashboard.xml',
            'school_planning/static/src/css/dashboard.css',
            'school_planning/static/src/js/detailed_expenses.js',
            'school_planning/static/src/xml/detailed_expenses.xml',
        ],
        'web.assets_unit_tests': [
            'school_planning/static/tests/dashboard.test.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}