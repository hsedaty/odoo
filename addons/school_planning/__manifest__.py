{
    'name': 'School Budget & Planning System',
    'version': '19.0.1.73.0',
    'category': 'Education',
    'summary': 'Live calculation engine for school budgeting, staffing, asset and room planning',
    'description': """
School Budget & Planning System.

- Changing a generated forecast's grade-specific tuition updates the same
  grade and fee in later years from that generation using the saved annual fee
  increase. Later amounts are replaced; approved years cannot be changed.
  Older forecasts without recoverable generation settings are not linked.
- Show Original Forecast Settings displays the inputs saved at the latest
  forecast generation, independently of subsequent edits. Older forecasts
  without a saved snapshot show that the original inputs are unavailable.
- Grade revenue uses gross tuition and grade-assigned per-student income before tax; revenue per student divides
  it by grade enrollment. Grade cost per student sums the selected per-student
  detailed expenses applying to that grade (including participation percentages).
  Grade cost multiplies that rate by grade enrollment. Shared expenses, payroll
  and taxes are excluded. No Details has no grade-assigned per-student costs.
  These grade figures are not total school costs or net profit. Approved
  forecasts retain their per-grade cost rates when frozen.
  Older approved forecasts without grade cost snapshots retain their historical
  net grade revenue and school-wide cost allocation.
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
- Schools can have branches, each with its own subjects, forecasts and Actuals.
  Select a branch for its dashboard, or its parent school for a combined
  dashboard including any existing school-level records and accessible branches.
  Branches must use the parent school's currency. In combined dashboards,
  students are the sum of the latest selected year for each school or branch.
- Report branding: open a school's Report Branding settings to customize school
  and company logos, title, footer and grade detail for PDF and emailed reports.
  PDF amounts use green for inflows/surpluses, red negative amounts for outflows/
  deficits, and neutral zeroes. Signs are presentation-only; calculations do not change.
- Quick Prediction forecasts operating expenses as a percentage of revenue.
  Newly generated revenue-based expenses retain their yearly rates and update
  when revenue changes; existing amounts are not reinterpreted on upgrade.
  The Starting Year is displayed without thousands separators.
  Edit the base percentage and annual percentage-point trend in All Expenses.
  Deleting built-in expense seeds is respected on module upgrades.
  Predictions put the entire annual fee in the Detailed Income tuition seed. Existing
  non-tuition fee rows are retained but excluded from forecast totals; enter
  other income in Detailed Income. Additional existing tuition fee types must
  be reviewed before regenerating; their rows are never deleted automatically.
- The forecast Financial Summary and year workspace offer an optional detailed
  expense list. The checkboxes for each year determine which costs apply,
  including accreditation fees; no payment schedule is required. Costs are shown
  as a separate estimate by default. Each unlocked forecast can select either
  the percentage forecast or the detailed list for financial calculations.
  Detailed expenses must be priced before they can be used in reports.
  The baseline also shows expenses as a share of before- or after-tax revenue.
  Manage detailed categories in Expense Seeds. The dashboard's Expenses by
  category chart uses the selected source per year.
  Administrators can edit or delete unused currencies from the Price Currency picker.
  The former development-only New UI URL now opens the integrated dashboard.
- Detailed income and expense items can be overridden for a single forecast year
  with one amount in school currency or a percentage of revenue before tax.
  The Per Student in % basis uses a per-student amount and participation
  percentage entered for each forecast year in the detailed list.
  Allocated amounts are estimates that may differ from actual results.
  Existing allocated unit budgets and seed prices remain available as defaults.
  A confirmed fixed seed price cannot be changed while used by a forecast.
  Gross revenue is tuition plus selected Detailed Income. Income percentages
  use tuition before tax, avoiding a circular revenue calculation. The general
  tax applies to all forecast revenue unless Detailed expenses are selected.
  Unpriced selected income makes totals provisional and prevents approval.
  Tuition is included automatically from its existing grade fee rows.
  Per Student income shows grade-level amounts and a student-weighted average;
  changing the average resets all applicable grade amounts. Grade revenue includes
  these per-student amounts, but excludes other unallocated Detailed Income.
  Existing inputs remain saved. Approved income breakdowns are frozen.
  Review the Forecast Tuition and Represents Tuition flags for custom or renamed
  legacy entries after upgrading.
  Transportation is configured in detailed income rather than legacy Fee Seeds.
  Existing forecast fee rows are retained and must be reviewed before regeneration.
  Previous detailed categories are archived on upgrade, retaining existing selections.
- Setup / Academic Setup / Timetables holds editable weekly subject-hour seeds,
  one per curriculum. The American timetable uses the supplied KG1-Grade 12
  subjects and hours, including editable zero-hour entries.
  Schools with multiple curricula load all matching active timetables.
  New predictions use seed hours; existing years require a confirmed load in
  Teaching Load. Unrelated rows and other years are preserved.
  Each curriculum uses the grade's class count; enrollment is not split.
  Art/Music (Grades 7-10) and the Grade 11-12 slash-separated choices each
  appear as separate subjects sharing an elective area (ELCT1, ELCT2, etc.).
  Counted Class Hours includes each area once per grade and curriculum,
  using the largest weekly duration if its subjects differ. Both subjects
  retain their full scheduled hours in staffing; no student-choice estimates,
  allocation percentages or extra inputs are required. Areas copy to Actuals.
  The upgrade expands legacy slots in seeds and unlocked years; approved
  forecasts retain their saved subjects, hours and financial baselines.
  Staffing uses the scheduled subject hours and configured teacher load.
  Teaching Load shows weekly teaching hours and rounded-up teacher requirements
  for each subject, summed across grades. The breakdown reconciles to the total.
  Actual entry templates keep hours at zero until entered or explicitly applied.
  Quick Prediction uses the school's configured grades; it creates the default
  grade structure only when no grades have been configured.
  IB, IGCSE and unsupported grades retain their existing distributions unless
  a matching timetable is configured. Seed edits/deletions survive upgrades.
  The 19.0.1.62.0 upgrade replaces only the American timetable seed with the
  supplied tables. Existing yearly loads and other curricula are not rewritten.
  TW retains its supplied label; P.E and PE use the same subject.
  This school-provided timetable is not a Cognia accreditation requirement.
- Expenses shows tax deductions separately, with an editable 0-100% rate for
  each unlocked forecast year using no-details expenses. Choosing detailed
  suspends the saved rate and uses selected expenses, including Official
  Payments. Deleting the list switches back to no-details expenses.
  Actuals retain fee-level tax mappings. Approved forecasts retain their totals.
""",
    'author': 'Abdullah Karakuyu',
    'depends': ['base', 'web', 'mail', 'google_gmail'],
    'post_init_hook': 'post_init_hook',
    'data': [
        'security/ir.model.access.csv',
        'data/web_assets.xml',
        'data/grade_presets.xml',
        'data/subject_presets.xml',
        'data/american_subjects.xml',
        'data/prediction_scenarios.xml',
        'data/prediction_seed_configuration.xml',
        'data/operational_expense_seeds.xml',
        'views/school_planning_frontend_templates.xml',
        'views/school_planning_prediction_templates.xml',
        'views/school_planning_views.xml',
        'views/school_financial_summary_report.xml',
        'views/school_financial_report_views.xml',
        'views/forecast_actual_views.xml',
        'views/timetable_views.xml',
        'views/efficiency_views.xml',
        'views/report_branding_views.xml',
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'school_planning/static/src/js/dismissible_notice.js',
            'school_planning/static/src/xml/dismissible_notice.xml',
            'school_planning/static/src/js/dashboard.js',
            'school_planning/static/src/xml/dashboard.xml',
            'school_planning/static/src/css/dashboard.css',
            'school_planning/static/src/js/detailed_expenses.js',
            'school_planning/static/src/xml/detailed_expenses.xml',
        ],
        'web.assets_unit_tests': [
            'school_planning/static/tests/dashboard.test.js',
            'school_planning/static/tests/income_accordion.test.js',
            'school_planning/static/tests/dismissible_notice.test.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}