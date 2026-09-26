from odoo import http
from odoo.http import request


class SchoolPlanningFrontendApiController(http.Controller):
    @http.route('/school_planning/new-ui', type='http', auth='user', website=False)
    def school_planning_new_ui(self):
        return request.render('school_planning.school_budgeting_frontend_page')

    @http.route('/school_planning/api/bootstrap', type='jsonrpc', auth='user')
    def school_planning_bootstrap(self):
        env = request.env

        schools = env['school.schools'].search([], order='id asc')
        years = env['school.academic.years'].search([], order='start_date asc, academic_year_name asc, id asc')
        groups = env['school.grade.groups'].search([], order='display_order asc, id asc')
        levels = env['school.grade.levels'].search([], order='sort_order asc, id asc')

        enrollments = env['school.grade.enrollment'].search([], order='academic_year_id asc, grade_level_id asc, id asc')
        fee_types = env['school.fee.types'].search([], order='display_order asc, id asc')
        tax_rules = env['school.tax.rules'].search([], order='id asc')
        fee_values = env['school.fee.values'].search([], order='academic_year_id asc, grade_level_id asc, fee_type_id asc, id asc')

        expense_categories = env['school.expense.categories'].search([], order='display_order asc, id asc')
        expense_items = env['school.expense.items'].search([], order='display_order asc, id asc')
        expense_values = env['school.expense.values'].search([], order='academic_year_id asc, expense_item_id asc, id asc')

        staff_categories = env['school.staff.categories'].search([], order='display_order asc, id asc')
        staff_positions = env['school.staff.positions'].search([], order='display_order asc, id asc')
        staffing_rules = env['school.staffing.rules'].search([], order='display_order asc, id asc')
        salaries = env['school.employment.salaries'].search([], order='academic_year_id asc, staff_position_id asc, id asc')
        subjects = env['school.subjects'].search([], order='display_order asc, id asc')
        subject_distribution = env['school.subject.distribution'].search([], order='academic_year_id asc, grade_level_id asc, subject_id asc, id asc')

        assets = env['school.asset.items'].search([], order='display_order asc, id asc')
        room_types = env['school.room.types'].search([], order='display_order asc, id asc')
        room_templates = env['school.room.templates'].search([], order='display_order asc, id asc')
        room_template_items = env['school.room.template.items'].search([], order='id asc')
        room_plans = env['school.room.plan'].search([], order='academic_year_id asc, room_type_id asc, id asc')
        asset_prices = env['school.asset.prices'].search([], order='academic_year_id asc, asset_item_id asc, id asc')
        asset_transactions = env['school.asset.transactions'].search([], order='academic_year_id asc, transaction_date asc, id asc')

        return {
            'schools': [
                {
                    'id': school.id,
                    'name': school.name,
                    'country': school.country or '',
                    'currency': school.currency or '',
                }
                for school in schools
            ],
            'academicYears': [
                self._serialize_academic_year(year)
                for year in years
            ],
            'gradeGroups': [
                self._serialize_grade_group(group)
                for group in groups
            ],
            'gradeLevels': [
                self._serialize_grade_level(level)
                for level in levels
            ],
            'enrollments': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'gradeId': row.grade_level_id.id,
                    'studentCount': int(row.student_count or 0),
                    'maxStudentsPerClass': int(row.max_students_per_class or 0),
                    'classCount': int(row.class_count or 0),
                }
                for row in enrollments
            ],
            'feeTypes': [
                self._serialize_fee_type(row)
                for row in fee_types
            ],
            'taxRules': [
                self._serialize_tax_rule(row)
                for row in tax_rules
            ],
            'feeValues': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'gradeId': row.grade_level_id.id,
                    'feeTypeId': row.fee_type_id.id,
                    'amount': float(row.amount or 0),
                }
                for row in fee_values
            ],
            'expenseCategories': [
                self._serialize_expense_category(row)
                for row in expense_categories
            ],
            'expenseItems': [
                self._serialize_expense_item(row)
                for row in expense_items
            ],
            'expenseValues': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'itemId': row.expense_item_id.id,
                    'amount': float(row.amount or 0),
                }
                for row in expense_values
            ],
            'staffCategories': [
                self._serialize_staff_category(row)
                for row in staff_categories
            ],
            'staffPositions': [
                self._serialize_staff_position(row)
                for row in staff_positions
            ],
            'staffingRules': [
                self._serialize_staffing_rule(row)
                for row in staffing_rules
            ],
            'subjects': [
                self._serialize_subject(row)
                for row in subjects
            ],
            'subjectDistributions': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'gradeId': row.grade_level_id.id,
                    'subjectId': row.subject_id.id,
                    'weeklyHours': float(row.weekly_hours or 0),
                    'credits': float(row.credits or 0),
                }
                for row in subject_distribution
            ],
            'salaries': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'positionId': row.staff_position_id.id,
                    'employeeCount': int(row.employee_count or 0),
                    'monthlySalary': float(row.monthly_salary or 0),
                    'monthsPaid': int(row.months_paid or 0),
                    'bonus': float(row.bonus or 0),
                }
                for row in salaries
            ],
            'assets': [
                self._serialize_asset_item(row)
                for row in assets
            ],
            'roomTypes': [
                self._serialize_room_type(row)
                for row in room_types
            ],
            'roomTemplates': [
                self._serialize_room_template(row)
                for row in room_templates
            ],
            'roomTemplateItems': [
                self._serialize_room_template_item(row)
                for row in room_template_items
            ],
            'roomPlans': [
                self._serialize_room_plan(row)
                for row in room_plans
            ],
            'assetPrices': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'assetId': row.asset_item_id.id,
                    'ownedQty': int(row.owned_quantity or 0),
                    'unitPrice': float(row.unit_price or 0),
                }
                for row in asset_prices
            ],
            'assetTransactions': [
                {
                    'id': row.id,
                    'yearId': row.academic_year_id.id,
                    'assetId': row.asset_item_id.id,
                    'transactionType': row.transaction_type,
                    'quantity': int(row.quantity or 0),
                    'transactionDate': str(row.transaction_date or ''),
                    'notes': row.notes or '',
                }
                for row in asset_transactions
            ],
        }

    @http.route('/school_planning/api/write', type='jsonrpc', auth='user')
    def school_planning_write(self, resource=None, record_id=None, values=None):
        values = values or {}
        resource_map = {
            'enrollment': {
                'model': 'school.grade.enrollment',
                'fields': {
                    'studentCount': 'student_count',
                },
            },
            'feeValue': {
                'model': 'school.fee.values',
                'fields': {
                    'amount': 'amount',
                },
            },
            'expenseValue': {
                'model': 'school.expense.values',
                'fields': {
                    'amount': 'amount',
                },
            },
            'salary': {
                'model': 'school.employment.salaries',
                'fields': {
                    'monthlySalary': 'monthly_salary',
                    'monthsPaid': 'months_paid',
                    'bonus': 'bonus',
                },
            },
            'expenseValue': {
                'model': 'school.expense.values',
                'fields': {
                    'amount': 'amount',
                },
            },
            'salary': {
                'model': 'school.employment.salaries',
                'fields': {
                    'monthlySalary': 'monthly_salary',
                    'monthsPaid': 'months_paid',
                    'bonus': 'bonus',
                },
            },
            'assetPrice': {
                'model': 'school.asset.prices',
                'fields': {
                    'unitPrice': 'unit_price',
                },
            },
            'assetItem': {
                'model': 'school.asset.items',
                'fields': {
                    'name': 'name',
                    'type': 'asset_type',
                    'unit': 'unit_of_measure',
                },
            },
            'assetTransaction': {
                'model': 'school.asset.transactions',
                'fields': {
                    'yearId': 'academic_year_id',
                    'assetId': 'asset_item_id',
                    'transactionType': 'transaction_type',
                    'quantity': 'quantity',
                    'transactionDate': 'transaction_date',
                    'notes': 'notes',
                },
            },
            'subjectDistribution': {
                'model': 'school.subject.distribution',
                'fields': {
                    'weeklyHours': 'weekly_hours',
                    'credits': 'credits',
                },
            },
            'school': {
                'model': 'school.schools',
                'fields': {
                    'name': 'name',
                    'country': 'country',
                    'currency': 'currency',
                },
            },
            'academicYear': {
                'model': 'school.academic.years',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'academic_year_name',
                    'startDate': 'start_date',
                    'endDate': 'end_date',
                },
            },
            'gradeGroup': {
                'model': 'school.grade.groups',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
            },
            'gradeLevel': {
                'model': 'school.grade.levels',
                'fields': {
                    'groupId': 'group_id',
                    'name': 'name',
                    'maxStudentsOverride': 'max_students_per_class_override',
                },
            },
            'feeType': {
                'model': 'school.fee.types',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                    'isTaxable': 'is_taxable',
                    'taxRuleId': 'tax_rule_id',
                },
            },
            'taxRule': {
                'model': 'school.tax.rules',
                'fields': {
                    'name': 'name',
                    'percentage': 'percentage',
                },
            },
            'expenseCategory': {
                'model': 'school.expense.categories',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
            },
            'expenseItem': {
                'model': 'school.expense.items',
                'fields': {
                    'schoolId': 'school_id',
                    'categoryId': 'expense_category_id',
                    'name': 'name',
                },
            },
            'staffCategory': {
                'model': 'school.staff.categories',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
            },
            'subject': {
                'model': 'school.subjects',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
            },
            'staffPosition': {
                'model': 'school.staff.positions',
                'fields': {
                    'schoolId': 'school_id',
                    'categoryId': 'staff_category_id',
                    'title': 'title',
                },
            },
            'staffingRule': {
                'model': 'school.staffing.rules',
                'fields': {
                    'schoolId': 'school_id',
                    'positionId': 'staff_position_id',
                    'calculationMethod': 'calculation_method',
                    'parameterValue': 'parameter_value',
                },
            },
            'roomType': {
                'model': 'school.room.types',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                    'maxStudentsPerClassDefault': 'max_students_per_class_default',
                },
            },
            'roomTemplate': {
                'model': 'school.room.templates',
                'fields': {
                    'schoolId': 'school_id',
                    'roomTypeId': 'room_type_id',
                    'name': 'name',
                },
            },
            'roomTemplateItem': {
                'model': 'school.room.template.items',
                'fields': {
                    'roomTemplateId': 'room_template_id',
                    'assetId': 'asset_item_id',
                    'quantity': 'quantity',
                },
            },
            'roomPlan': {
                'model': 'school.room.plan',
                'fields': {
                    'existingRooms': 'existing_rooms',
                    'manualNewRooms': 'manual_new_rooms',
                },
            },
        }

        config = resource_map.get(resource or '')
        if not config:
            return {'ok': False, 'error': 'Unsupported resource'}

        if not record_id:
            return {'ok': False, 'error': 'Missing record_id'}

        record = request.env[config['model']].browse(int(record_id)).exists()
        if not record:
            return {'ok': False, 'error': 'Record not found'}

        writable_vals = {}
        for frontend_field, backend_field in config['fields'].items():
            if frontend_field in values:
                writable_vals[backend_field] = values[frontend_field]

        if not writable_vals:
            return {'ok': False, 'error': 'No writable values provided'}

        record.write(writable_vals)
        return {'ok': True}

    @http.route('/school_planning/api/upsert', type='jsonrpc', auth='user')
    def school_planning_upsert(self, resource=None, keys=None, values=None):
        keys = keys or {}
        values = values or {}
        resource_map = {
            'enrollment': {
                'model': 'school.grade.enrollment',
                'key_fields': {
                    'yearId': 'academic_year_id',
                    'gradeId': 'grade_level_id',
                },
                'value_fields': {
                    'studentCount': 'student_count',
                },
                'defaults': {
                    'student_count': 0,
                },
                'serialize': self._serialize_enrollment,
            },
            'feeValue': {
                'model': 'school.fee.values',
                'key_fields': {
                    'yearId': 'academic_year_id',
                    'gradeId': 'grade_level_id',
                    'feeTypeId': 'fee_type_id',
                },
                'value_fields': {
                    'amount': 'amount',
                },
                'defaults': {
                    'amount': 0,
                },
                'serialize': self._serialize_fee_value,
            },
            'subjectDistribution': {
                'model': 'school.subject.distribution',
                'key_fields': {
                    'yearId': 'academic_year_id',
                    'gradeId': 'grade_level_id',
                    'subjectId': 'subject_id',
                },
                'value_fields': {
                    'weeklyHours': 'weekly_hours',
                    'credits': 'credits',
                },
                'defaults': {
                    'weekly_hours': 0,
                    'credits': 0,
                },
                'serialize': self._serialize_subject_distribution,
            },
        }

        config = resource_map.get(resource or '')
        if not config:
            return {'ok': False, 'error': 'Unsupported resource'}

        model = request.env[config['model']]
        domain = []
        create_vals = {}
        for frontend_key, backend_key in config['key_fields'].items():
            if frontend_key not in keys:
                return {'ok': False, 'error': f'Missing key: {frontend_key}'}
            key_value = keys[frontend_key]
            domain.append((backend_key, '=', key_value))
            create_vals[backend_key] = key_value

        write_vals = {}
        for frontend_key, backend_key in config['value_fields'].items():
            if frontend_key in values:
                write_vals[backend_key] = values[frontend_key]

        record = model.search(domain, limit=1)
        if record:
            if write_vals:
                record.write(write_vals)
        else:
            merged = dict(config.get('defaults') or {})
            merged.update(create_vals)
            merged.update(write_vals)
            record = model.create(merged)

        return {
            'ok': True,
            'record': config['serialize'](record),
        }

    @http.route('/school_planning/api/create', type='jsonrpc', auth='user')
    def school_planning_create(self, resource=None, values=None):
        values = values or {}
        resource_map = {
            'school': {
                'model': 'school.schools',
                'fields': {
                    'name': 'name',
                    'country': 'country',
                    'currency': 'currency',
                },
                'defaults': {
                    'currency': 'USD',
                },
                'serialize': self._serialize_school,
            },
            'academicYear': {
                'model': 'school.academic.years',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'academic_year_name',
                    'startDate': 'start_date',
                    'endDate': 'end_date',
                },
                'serialize': self._serialize_academic_year,
                'before_create': self._prepare_academic_year_create_vals,
            },
            'gradeGroup': {
                'model': 'school.grade.groups',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
                'serialize': self._serialize_grade_group,
                'before_create': self._prepare_grade_group_create_vals,
            },
            'gradeLevel': {
                'model': 'school.grade.levels',
                'fields': {
                    'groupId': 'group_id',
                    'name': 'name',
                    'roomTypeId': 'room_type_id',
                    'maxStudentsOverride': 'max_students_per_class_override',
                },
                'serialize': self._serialize_grade_level,
                'before_create': self._prepare_grade_level_create_vals,
            },
            'feeType': {
                'model': 'school.fee.types',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                    'isTaxable': 'is_taxable',
                    'taxRuleId': 'tax_rule_id',
                },
                'defaults': {
                    'is_taxable': False,
                },
                'serialize': self._serialize_fee_type,
                'before_create': self._prepare_fee_type_create_vals,
            },
            'taxRule': {
                'model': 'school.tax.rules',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                    'percentage': 'percentage',
                },
                'defaults': {
                    'percentage': 0,
                },
                'serialize': self._serialize_tax_rule,
                'before_create': self._prepare_tax_rule_create_vals,
            },
            'expenseCategory': {
                'model': 'school.expense.categories',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
                'serialize': self._serialize_expense_category,
                'before_create': self._prepare_expense_category_create_vals,
            },
            'expenseItem': {
                'model': 'school.expense.items',
                'fields': {
                    'schoolId': 'school_id',
                    'categoryId': 'expense_category_id',
                    'name': 'name',
                },
                'serialize': self._serialize_expense_item,
                'before_create': self._prepare_expense_item_create_vals,
            },
            'staffCategory': {
                'model': 'school.staff.categories',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
                'serialize': self._serialize_staff_category,
                'before_create': self._prepare_staff_category_create_vals,
            },
            'subject': {
                'model': 'school.subjects',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                },
                'serialize': self._serialize_subject,
                'before_create': self._prepare_subject_create_vals,
            },
            'staffPosition': {
                'model': 'school.staff.positions',
                'fields': {
                    'schoolId': 'school_id',
                    'categoryId': 'staff_category_id',
                    'title': 'title',
                },
                'serialize': self._serialize_staff_position,
                'before_create': self._prepare_staff_position_create_vals,
            },
            'staffingRule': {
                'model': 'school.staffing.rules',
                'fields': {
                    'schoolId': 'school_id',
                    'positionId': 'staff_position_id',
                    'calculationMethod': 'calculation_method',
                    'parameterValue': 'parameter_value',
                },
                'defaults': {
                    'calculation_method': 'fixed',
                    'parameter_value': 1,
                },
                'serialize': self._serialize_staffing_rule,
                'before_create': self._prepare_staffing_rule_create_vals,
            },
            'roomType': {
                'model': 'school.room.types',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                    'maxStudentsPerClassDefault': 'max_students_per_class_default',
                },
                'defaults': {
                    'max_students_per_class_default': 25,
                },
                'serialize': self._serialize_room_type,
                'before_create': self._prepare_room_type_create_vals,
            },
            'roomTemplate': {
                'model': 'school.room.templates',
                'fields': {
                    'schoolId': 'school_id',
                    'roomTypeId': 'room_type_id',
                    'name': 'name',
                },
                'serialize': self._serialize_room_template,
                'before_create': self._prepare_room_template_create_vals,
            },
            'roomTemplateItem': {
                'model': 'school.room.template.items',
                'fields': {
                    'roomTemplateId': 'room_template_id',
                    'assetId': 'asset_item_id',
                    'quantity': 'quantity',
                },
                'defaults': {
                    'quantity': 1,
                },
                'serialize': self._serialize_room_template_item,
            },
            'roomPlan': {
                'model': 'school.room.plan',
                'fields': {
                    'yearId': 'academic_year_id',
                    'roomTypeId': 'room_type_id',
                    'existingRooms': 'existing_rooms',
                    'manualNewRooms': 'manual_new_rooms',
                },
                'defaults': {
                    'existing_rooms': 0,
                    'manual_new_rooms': 0,
                },
                'serialize': self._serialize_room_plan,
            },
            'expenseValue': {
                'model': 'school.expense.values',
                'fields': {
                    'yearId': 'academic_year_id',
                    'itemId': 'expense_item_id',
                    'amount': 'amount',
                },
                'defaults': {
                    'amount': 0,
                },
                'serialize': self._serialize_expense_value,
            },
            'salary': {
                'model': 'school.employment.salaries',
                'fields': {
                    'yearId': 'academic_year_id',
                    'positionId': 'staff_position_id',
                    'monthlySalary': 'monthly_salary',
                    'monthsPaid': 'months_paid',
                    'bonus': 'bonus',
                },
                'defaults': {
                    'monthly_salary': 0,
                    'months_paid': 12,
                    'bonus': 0,
                },
                'serialize': self._serialize_salary,
            },
            'assetItem': {
                'model': 'school.asset.items',
                'fields': {
                    'schoolId': 'school_id',
                    'name': 'name',
                    'type': 'asset_type',
                    'unit': 'unit_of_measure',
                },
                'defaults': {
                    'asset_type': 'fixed',
                    'unit_of_measure': 'Unit',
                },
                'serialize': self._serialize_asset_item,
                'before_create': self._prepare_asset_item_create_vals,
            },
            'assetPrice': {
                'model': 'school.asset.prices',
                'fields': {
                    'yearId': 'academic_year_id',
                    'assetId': 'asset_item_id',
                    'ownedQty': 'owned_quantity',
                    'unitPrice': 'unit_price',
                },
                'defaults': {
                    'owned_quantity': 0,
                    'unit_price': 0,
                },
                'serialize': self._serialize_asset_price,
            },
            'assetTransaction': {
                'model': 'school.asset.transactions',
                'fields': {
                    'yearId': 'academic_year_id',
                    'assetId': 'asset_item_id',
                    'transactionType': 'transaction_type',
                    'quantity': 'quantity',
                    'transactionDate': 'transaction_date',
                    'notes': 'notes',
                },
                'defaults': {
                    'transaction_type': 'Purchase',
                    'quantity': 0,
                },
                'serialize': self._serialize_asset_transaction,
            },
        }

        config = resource_map.get(resource or '')
        if not config:
            return {'ok': False, 'error': 'Unsupported resource'}

        create_vals = dict(config.get('defaults') or {})
        for frontend_field, backend_field in config['fields'].items():
            if frontend_field in values:
                create_vals[backend_field] = values[frontend_field]

        if config.get('before_create'):
            create_vals = config['before_create'](create_vals)

        record = request.env[config['model']].create(create_vals)
        return {
            'ok': True,
            'record': config['serialize'](record),
        }

    @http.route('/school_planning/api/action', type='jsonrpc', auth='user')
    def school_planning_action(self, resource=None, record_id=None, action=None):
        resource_map = {
            'school': {
                'model': 'school.schools',
                'serialize': self._serialize_school,
                'copy_name_field': 'name',
            },
            'academicYear': {
                'model': 'school.academic.years',
                'serialize': self._serialize_academic_year,
                'copy_name_field': 'academic_year_name',
            },
            'gradeGroup': {
                'model': 'school.grade.groups',
                'serialize': self._serialize_grade_group,
                'copy_name_field': 'name',
            },
            'gradeLevel': {
                'model': 'school.grade.levels',
                'serialize': self._serialize_grade_level,
                'copy_name_field': 'name',
            },
            'feeType': {
                'model': 'school.fee.types',
                'serialize': self._serialize_fee_type,
                'copy_name_field': 'name',
            },
            'subject': {
                'model': 'school.subjects',
                'serialize': self._serialize_subject,
                'copy_name_field': 'name',
            },
            'staffPosition': {
                'model': 'school.staff.positions',
                'serialize': self._serialize_staff_position,
                'copy_name_field': 'title',
            },
            'taxRule': {
                'model': 'school.tax.rules',
                'serialize': self._serialize_tax_rule,
                'copy_name_field': 'name',
            },
            'expenseCategory': {
                'model': 'school.expense.categories',
                'serialize': self._serialize_expense_category,
                'copy_name_field': 'name',
            },
            'expenseItem': {
                'model': 'school.expense.items',
                'serialize': self._serialize_expense_item,
                'copy_name_field': 'name',
            },
            'staffCategory': {
                'model': 'school.staff.categories',
                'serialize': self._serialize_staff_category,
                'copy_name_field': 'name',
            },
            'staffingRule': {
                'model': 'school.staffing.rules',
                'serialize': self._serialize_staffing_rule,
            },
            'roomType': {
                'model': 'school.room.types',
                'serialize': self._serialize_room_type,
                'copy_name_field': 'name',
            },
            'roomTemplate': {
                'model': 'school.room.templates',
                'serialize': self._serialize_room_template,
                'copy_name_field': 'name',
            },
            'roomTemplateItem': {
                'model': 'school.room.template.items',
                'serialize': self._serialize_room_template_item,
            },
            'roomPlan': {
                'model': 'school.room.plan',
                'serialize': self._serialize_room_plan,
            },
            'assetItem': {
                'model': 'school.asset.items',
                'serialize': self._serialize_asset_item,
                'copy_name_field': 'name',
            },
            'assetTransaction': {
                'model': 'school.asset.transactions',
                'serialize': self._serialize_asset_transaction,
            },
            'assetPrice': {
                'model': 'school.asset.prices',
                'serialize': self._serialize_asset_price,
            },
            'expenseValue': {
                'model': 'school.expense.values',
                'serialize': self._serialize_expense_value,
            },
            'salary': {
                'model': 'school.employment.salaries',
                'serialize': self._serialize_salary,
            },
            'feeValue': {
                'model': 'school.fee.values',
                'serialize': self._serialize_fee_value,
            },
            'enrollment': {
                'model': 'school.grade.enrollment',
                'serialize': self._serialize_enrollment,
            },
            'subjectDistribution': {
                'model': 'school.subject.distribution',
                'serialize': self._serialize_subject_distribution,
            },
        }

        config = resource_map.get(resource or '')
        if not config:
            return {'ok': False, 'error': 'Unsupported resource'}

        if not record_id:
            return {'ok': False, 'error': 'Missing record_id'}

        record = request.env[config['model']].browse(int(record_id)).exists()
        if not record:
            return {'ok': False, 'error': 'Record not found'}

        if action == 'duplicate':
            copy_vals = {}
            copy_name_field = config.get('copy_name_field')
            if copy_name_field:
                copy_vals[copy_name_field] = f"{record[copy_name_field]} (Copy)"
            copied = record.copy(copy_vals)
            return {
                'ok': True,
                'record': config['serialize'](copied),
            }

        if action == 'delete':
            try:
                record.unlink()
                return {'ok': True}
            except Exception as error:  # pylint: disable=broad-except
                return {'ok': False, 'error': str(error)}

        return {'ok': False, 'error': 'Unsupported action'}

    def _prepare_asset_item_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if school_id and not create_vals.get('display_order'):
            latest = request.env['school.asset.items'].search([
                ('school_id', '=', school_id),
            ], order='display_order desc, id desc', limit=1)
            create_vals['display_order'] = (latest.display_order if latest else 0) + 10
        return create_vals

    def _next_sequence_value(self, model_name, field_name, domain=None):
        latest = request.env[model_name].search(domain or [], order=f'{field_name} desc, id desc', limit=1)
        return (getattr(latest, field_name, 0) if latest else 0) + 10

    def _prepare_academic_year_create_vals(self, create_vals):
        if not create_vals.get('school_id'):
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            create_vals['school_id'] = school.id if school else False
        return create_vals

    def _prepare_grade_group_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if not school_id:
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            school_id = school.id if school else False
            create_vals['school_id'] = school_id
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.grade.groups',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_grade_level_create_vals(self, create_vals):
        group_id = create_vals.get('group_id')
        if group_id:
            group = request.env['school.grade.groups'].browse(group_id).exists()
            if group and not create_vals.get('school_id'):
                create_vals['school_id'] = group.school_id.id
        if not create_vals.get('sort_order'):
            create_vals['sort_order'] = self._next_sequence_value('school.grade.levels', 'sort_order')
        return create_vals

    def _prepare_fee_type_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if not school_id:
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            school_id = school.id if school else False
            create_vals['school_id'] = school_id
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.fee.types',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_tax_rule_create_vals(self, create_vals):
        create_vals.pop('school_id', None)
        return create_vals

    def _prepare_expense_category_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if not school_id:
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            school_id = school.id if school else False
            create_vals['school_id'] = school_id
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.expense.categories',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_expense_item_create_vals(self, create_vals):
        category_id = create_vals.get('expense_category_id')
        if category_id:
            category = request.env['school.expense.categories'].browse(category_id).exists()
            if category and not create_vals.get('school_id'):
                create_vals['school_id'] = category.school_id.id
        school_id = create_vals.get('school_id')
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.expense.items',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_staff_category_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if not school_id:
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            school_id = school.id if school else False
            create_vals['school_id'] = school_id
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.staff.categories',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_subject_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if not school_id:
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            school_id = school.id if school else False
            create_vals['school_id'] = school_id
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.subjects',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_staff_position_create_vals(self, create_vals):
        category_id = create_vals.get('staff_category_id')
        if category_id:
            category = request.env['school.staff.categories'].browse(category_id).exists()
            if category and not create_vals.get('school_id'):
                create_vals['school_id'] = category.school_id.id
        if not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value('school.staff.positions', 'display_order')
        return create_vals

    def _prepare_staffing_rule_create_vals(self, create_vals):
        position_id = create_vals.get('staff_position_id')
        if position_id:
            position = request.env['school.staff.positions'].browse(position_id).exists()
            if position and not create_vals.get('school_id'):
                create_vals['school_id'] = position.school_id.id
        if not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value('school.staffing.rules', 'display_order')
        return create_vals

    def _prepare_room_type_create_vals(self, create_vals):
        school_id = create_vals.get('school_id')
        if not school_id:
            school = request.env['school.schools'].search([], order='id asc', limit=1)
            school_id = school.id if school else False
            create_vals['school_id'] = school_id
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.room.types',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _prepare_room_template_create_vals(self, create_vals):
        room_type_id = create_vals.get('room_type_id')
        if room_type_id:
            room_type = request.env['school.room.types'].browse(room_type_id).exists()
            if room_type and not create_vals.get('school_id'):
                create_vals['school_id'] = room_type.school_id.id
        school_id = create_vals.get('school_id')
        if school_id and not create_vals.get('display_order'):
            create_vals['display_order'] = self._next_sequence_value(
                'school.room.templates',
                'display_order',
                [('school_id', '=', school_id)],
            )
        return create_vals

    def _serialize_enrollment(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'gradeId': row.grade_level_id.id,
            'studentCount': int(row.student_count or 0),
            'maxStudentsPerClass': int(row.max_students_per_class or 0),
            'classCount': int(row.class_count or 0),
        }

    def _serialize_school(self, row):
        return {
            'id': row.id,
            'name': row.name,
            'country': row.country or '',
            'currency': row.currency or '',
        }

    def _serialize_academic_year(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.academic_year_name,
            'startDate': str(row.start_date or ''),
            'endDate': str(row.end_date or ''),
        }

    def _serialize_grade_group(self, row):
        return {
            'id': row.id,
            'name': row.name,
            'schoolId': row.school_id.id,
        }

    def _serialize_grade_level(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'groupId': row.group_id.id,
            'name': row.name,
            'maxStudentsOverride': int(row.max_students_per_class_override or 0),
            'maxStudents': int(row.max_students_per_class or 0),
        }

    def _serialize_fee_type(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.name,
            'isTaxable': bool(row.is_taxable),
            'taxRuleId': row.tax_rule_id.id if row.tax_rule_id else False,
        }

    def _serialize_tax_rule(self, row):
        return {
            'id': row.id,
            'schoolId': False,
            'name': row.name or '',
            'percentage': float(row.percentage or 0),
        }

    def _serialize_expense_category(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.name,
        }

    def _serialize_expense_item(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'categoryId': row.expense_category_id.id,
            'name': row.name,
        }

    def _serialize_staff_category(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.name,
        }

    def _serialize_subject(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.name,
        }

    def _serialize_staff_position(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'categoryId': row.staff_category_id.id,
            'title': row.title,
        }

    def _serialize_staffing_rule(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'positionId': row.staff_position_id.id,
            'calculationMethod': row.calculation_method,
            'parameterValue': float(row.parameter_value or 0),
        }

    def _serialize_room_type(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.name,
            'maxStudentsPerClassDefault': int(row.max_students_per_class_default or 0),
        }

    def _serialize_room_template(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'roomTypeId': row.room_type_id.id,
            'name': row.name,
        }

    def _serialize_room_template_item(self, row):
        return {
            'id': row.id,
            'schoolId': row.room_template_id.school_id.id,
            'roomTemplateId': row.room_template_id.id,
            'assetId': row.asset_item_id.id,
            'quantity': int(row.quantity or 0),
        }

    def _serialize_room_plan(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'roomTypeId': row.room_type_id.id,
            'existingRooms': int(row.existing_rooms or 0),
            'calculatedNewRooms': int(row.calculated_new_rooms or 0),
            'manualNewRooms': int(row.manual_new_rooms or 0),
            'totalNewRooms': int(row.total_new_rooms or 0),
            'assetCost': float(row.new_rooms_asset_cost or 0),
        }

    def _serialize_fee_value(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'gradeId': row.grade_level_id.id,
            'feeTypeId': row.fee_type_id.id,
            'amount': float(row.amount or 0),
        }

    def _serialize_expense_value(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'itemId': row.expense_item_id.id,
            'amount': float(row.amount or 0),
        }

    def _serialize_salary(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'positionId': row.staff_position_id.id,
            'employeeCount': int(row.employee_count or 0),
            'monthlySalary': float(row.monthly_salary or 0),
            'monthsPaid': int(row.months_paid or 0),
            'bonus': float(row.bonus or 0),
        }

    def _serialize_subject_distribution(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'gradeId': row.grade_level_id.id,
            'subjectId': row.subject_id.id,
            'weeklyHours': float(row.weekly_hours or 0),
            'credits': float(row.credits or 0),
        }

    def _serialize_asset_item(self, row):
        return {
            'id': row.id,
            'schoolId': row.school_id.id,
            'name': row.name,
            'type': row.asset_type,
            'unit': row.unit_of_measure or '',
        }

    def _serialize_asset_price(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'assetId': row.asset_item_id.id,
            'ownedQty': int(row.owned_quantity or 0),
            'unitPrice': float(row.unit_price or 0),
        }

    def _serialize_asset_transaction(self, row):
        return {
            'id': row.id,
            'yearId': row.academic_year_id.id,
            'assetId': row.asset_item_id.id,
            'transactionType': row.transaction_type,
            'quantity': int(row.quantity or 0),
            'transactionDate': str(row.transaction_date or ''),
            'notes': row.notes or '',
        }
