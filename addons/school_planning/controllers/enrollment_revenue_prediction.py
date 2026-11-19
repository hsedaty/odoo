import math

from odoo import http
from odoo.http import request


class SchoolPlanningEnrollmentRevenuePredictionController(http.Controller):
    _FEE_KEYWORDS = {
        'tuition': ('tuition',),
        'admission': ('admission',),
        'activity': ('activity',),
    }

    @http.route(
        '/school_planning/enrollment-revenue-prediction',
        type='http',
        auth='user',
        website=False,
    )
    def enrollment_revenue_prediction(self, **kwargs):
        return request.render('school_planning.enrollment_revenue_prediction_page')

    @http.route(
        '/school_planning/enrollment-revenue-prediction/load',
        type='jsonrpc',
        auth='user',
    )
    def enrollment_revenue_prediction_load(self):
        env = request.env
        years = env['school.academic.years'].search([], order='academic_year_name asc, id asc')
        groups = env['school.grade.groups'].search([], order='display_order asc, id asc')
        levels = env['school.grade.levels'].search([('group_id', 'in', groups.ids)], order='sort_order asc, id asc')

        levels_by_group = {group.id: [] for group in groups}
        for level in levels:
            levels_by_group.setdefault(level.group_id.id, []).append(level)

        enrollments = env['school.grade.enrollment'].search([
            ('academic_year_id', 'in', years.ids),
            ('grade_group_id', 'in', groups.ids),
        ])

        enrollment_by_level = {}
        for enrollment in enrollments:
            year_id = enrollment.academic_year_id.id
            level_id = enrollment.grade_level_id.id
            level_key = (year_id, level_id)
            level_totals = enrollment_by_level.setdefault(level_key, {'classes': 0, 'students': 0})
            level_totals['classes'] += int(enrollment.class_count or 0)
            level_totals['students'] += int(enrollment.student_count or 0)

        fee_types = env['school.fee.types'].search([], order='display_order asc, id asc')
        fee_rows = env['school.fee.values'].search([
            ('academic_year_id', 'in', years.ids),
            ('grade_level_id', 'in', levels.ids),
            ('fee_type_id', 'in', fee_types.ids),
        ])
        fee_amount_index = {
            (row.academic_year_id.id, row.grade_level_id.id, row.fee_type_id.id): float(row.amount or 0)
            for row in fee_rows
        }

        group_payload = []
        for group in groups:
            group_levels = levels_by_group.get(group.id, [])
            group_payload.append({
                'id': group.id,
                'name': group.name,
                'levels': [
                    {
                        'id': level.id,
                        'name': level.name,
                        'sort_order': level.sort_order,
                    }
                    for level in group_levels
                ],
            })

        year_payload = []
        for year in years:
            level_values = {}
            for level in levels:
                fee_amounts = {
                    str(fee_type.id): float(fee_amount_index.get((year.id, level.id, fee_type.id), 0.0))
                    for fee_type in fee_types
                }
                level_values[str(level.id)] = {
                    'classes': int(enrollment_by_level.get((year.id, level.id), {}).get('classes', 0)),
                    'students': int(enrollment_by_level.get((year.id, level.id), {}).get('students', 0)),
                    'fee_amounts': fee_amounts,
                }

            year_payload.append({
                'id': year.id,
                'label': year.display_name,
                'academic_year_name': year.academic_year_name,
                'level_values': level_values,
            })

        return {
            'years': year_payload,
            'groups': group_payload,
            'fee_types': [
                {
                    'id': fee_type.id,
                    'name': fee_type.name,
                }
                for fee_type in fee_types
            ],
        }

    @http.route(
        '/school_planning/enrollment-revenue-prediction/save',
        type='jsonrpc',
        auth='user',
    )
    def enrollment_revenue_prediction_save(self, years=None):
        env = request.env
        years = years or []
        groups = env['school.grade.groups'].search([], order='display_order asc, id asc')
        levels = env['school.grade.levels'].search([('group_id', 'in', groups.ids)], order='sort_order asc, id asc')
        levels_by_id = {level.id: level for level in levels}
        levels_by_group = {group.id: [] for group in groups}
        for level in levels:
            levels_by_group.setdefault(level.group_id.id, []).append(level)

        fee_types = env['school.fee.types'].search([])
        fee_types_by_id = {fee_type.id: fee_type for fee_type in fee_types}
        fee_types_by_key = self._map_fee_types(fee_types)

        for year_block in years:
            year_id = int(year_block.get('year_id') or 0)
            if not year_id:
                continue

            academic_year_name = (year_block.get('academic_year_name') or '').strip()
            if academic_year_name:
                env['school.academic.years'].browse(year_id).write({'academic_year_name': academic_year_name})

            level_values = year_block.get('level_values') or {}
            for level_id_text, value_map in level_values.items():
                level_id = int(level_id_text)
                level = levels_by_id.get(level_id)
                if not level:
                    continue
                self._save_enrollment_level(env, year_id, level, value_map)
                self._save_fee_level(env, year_id, level, value_map, fee_types_by_id, fee_types_by_key)

            # Backward-compatible fallback for older frontend payloads.
            group_values = year_block.get('group_values') or {}
            for group_id_text, value_map in group_values.items():
                group_id = int(group_id_text)
                level_list = levels_by_group.get(group_id, [])
                if not level_list:
                    continue
                level_ids = [level.id for level in level_list]

                self._save_enrollment_group(env, year_id, level_ids, value_map)
                self._save_fee_group(env, year_id, level_ids, value_map, fee_types_by_key)

        return {'ok': True}

    def _save_enrollment_level(self, env, year_id, level, value_map):
        student_count = max(0, int(round(float(value_map.get('students') or 0))))

        enrollment = env['school.grade.enrollment'].search([
            ('academic_year_id', '=', year_id),
            ('grade_level_id', '=', level.id),
        ], limit=1)

        vals = {
            'academic_year_id': year_id,
            'grade_level_id': level.id,
            'student_count': student_count,
        }
        if enrollment:
            enrollment.write(vals)
        else:
            env['school.grade.enrollment'].create(vals)

    def _save_fee_level(self, env, year_id, level, value_map, fee_types_by_id, fee_types_by_key):
        fee_amounts = value_map.get('fee_amounts') or {}
        for fee_type_id_text, raw_amount in fee_amounts.items():
            fee_type = fee_types_by_id.get(int(fee_type_id_text))
            if not fee_type:
                continue
            amount = float(raw_amount or 0)
            row = env['school.fee.values'].search([
                ('academic_year_id', '=', year_id),
                ('grade_level_id', '=', level.id),
                ('fee_type_id', '=', fee_type.id),
            ], limit=1)
            if row:
                row.write({'amount': amount})
            else:
                env['school.fee.values'].create({
                    'academic_year_id': year_id,
                    'grade_level_id': level.id,
                    'fee_type_id': fee_type.id,
                    'amount': amount,
                })

        # Backward compatibility with older frontend keys.
        for fee_key in ('tuition', 'admission', 'activity'):
            fee_type = fee_types_by_key.get(fee_key)
            if not fee_type:
                continue
            if fee_key not in value_map:
                continue
            amount = float(value_map.get(fee_key) or 0)
            row = env['school.fee.values'].search([
                ('academic_year_id', '=', year_id),
                ('grade_level_id', '=', level.id),
                ('fee_type_id', '=', fee_type.id),
            ], limit=1)
            if row:
                row.write({'amount': amount})
            else:
                env['school.fee.values'].create({
                    'academic_year_id': year_id,
                    'grade_level_id': level.id,
                    'fee_type_id': fee_type.id,
                    'amount': amount,
                })

    def _default_max_students_per_class(self, env, level_id):
        level = env['school.grade.levels'].browse(level_id)
        return int(level.max_students_per_class or 0) if level else 0

    @http.route(
        '/school_planning/enrollment-revenue-prediction/add-year',
        type='jsonrpc',
        auth='user',
    )
    def enrollment_revenue_prediction_add_year(self):
        env = request.env
        years = env['school.academic.years'].search([], order='academic_year_name asc, id asc')
        schools = env['school.schools'].search([], limit=1)
        if not schools:
            return {'ok': False, 'error': 'Create at least one school first.'}

        next_label = self._next_academic_year_name(years[-1].academic_year_name if years else '')
        if not next_label:
            next_label = 'New Academic Year'

        env['school.academic.years'].create({
            'school_id': schools.id,
            'academic_year_name': next_label,
        })
        return {'ok': True}

    def _map_fee_types(self, fee_types):
        mapped = {key: False for key in self._FEE_KEYWORDS}
        for fee_type in fee_types:
            name = (fee_type.name or '').strip().lower()
            for key, keywords in self._FEE_KEYWORDS.items():
                if mapped[key]:
                    continue
                if any(keyword in name for keyword in keywords):
                    mapped[key] = fee_type
        return mapped

    def _save_enrollment_group(self, env, year_id, level_ids, value_map):
        target_students = max(0, int(round(float(value_map.get('students') or 0))))
        target_classes = max(0, int(round(float(value_map.get('classes') or 0))))
        if target_students > 0 and target_classes <= 0:
            target_classes = 1

        enrollments = env['school.grade.enrollment'].search([
            ('academic_year_id', '=', year_id),
            ('grade_level_id', 'in', level_ids),
        ])
        enrollment_map = {enrollment.grade_level_id.id: enrollment for enrollment in enrollments}

        existing_student_weights = [int(enrollment_map[level_id].student_count or 0) if level_id in enrollment_map else 0 for level_id in level_ids]
        existing_class_weights = [int(enrollment_map[level_id].class_count or 0) if level_id in enrollment_map else 0 for level_id in level_ids]

        student_alloc = self._distribute_with_weights(target_students, existing_student_weights)
        class_alloc = self._distribute_with_weights(target_classes, existing_class_weights)

        if target_students > 0 and sum(class_alloc) <= 0:
            class_alloc[0] = 1

        for idx, level_id in enumerate(level_ids):
            student_count = student_alloc[idx]
            class_count = class_alloc[idx]
            if student_count > 0 and class_count <= 0:
                class_count = 1
            values = {
                'academic_year_id': year_id,
                'grade_level_id': level_id,
                'student_count': student_count,
            }
            record = enrollment_map.get(level_id)
            if record and int(record.max_students_per_class or 0) > 0:
                max_students_per_class = int(record.max_students_per_class)
            elif class_count > 0 and student_count > 0:
                max_students_per_class = max(1, math.ceil(student_count / class_count))
            else:
                max_students_per_class = self._default_max_students_per_class(env, level_id)
            values['max_students_per_class'] = max_students_per_class
            if record:
                record.write(values)
            else:
                env['school.grade.enrollment'].create(values)

    def _save_fee_group(self, env, year_id, level_ids, value_map, fee_types_by_key):
        for fee_key in ('tuition', 'admission', 'activity'):
            fee_type = fee_types_by_key.get(fee_key)
            if not fee_type:
                continue
            amount = float(value_map.get(fee_key) or 0)
            fee_rows = env['school.fee.values'].search([
                ('academic_year_id', '=', year_id),
                ('grade_level_id', 'in', level_ids),
                ('fee_type_id', '=', fee_type.id),
            ])
            fee_row_map = {row.grade_level_id.id: row for row in fee_rows}

            for level_id in level_ids:
                values = {
                    'academic_year_id': year_id,
                    'grade_level_id': level_id,
                    'fee_type_id': fee_type.id,
                    'amount': amount,
                }
                row = fee_row_map.get(level_id)
                if row:
                    row.write({'amount': amount})
                else:
                    env['school.fee.values'].create(values)

    def _distribute_with_weights(self, total, weights):
        count = len(weights)
        if count == 0:
            return []
        if total <= 0:
            return [0] * count

        usable_weights = [max(0, int(weight or 0)) for weight in weights]
        weight_sum = sum(usable_weights)
        if weight_sum <= 0:
            base = total // count
            rem = total % count
            return [base + (1 if idx < rem else 0) for idx in range(count)]

        raw = [total * weight / weight_sum for weight in usable_weights]
        rounded = [int(math.floor(value)) for value in raw]
        diff = total - sum(rounded)
        if diff > 0:
            remainders = sorted(
                range(count),
                key=lambda idx: raw[idx] - rounded[idx],
                reverse=True,
            )
            for idx in remainders[:diff]:
                rounded[idx] += 1
        return rounded

    def _next_academic_year_name(self, previous_name):
        previous_name = (previous_name or '').strip()
        if not previous_name:
            return ''
        if '-' not in previous_name:
            return ''
        first, second = previous_name.split('-', 1)
        first = first.strip()
        second = second.strip()
        if not (first.isdigit() and second.isdigit()):
            return ''
        first_next = str(int(first) + 1)
        second_next = str(int(second) + 1)
        if len(second) == 2:
            second_next = second_next[-2:]
        return f'{first_next}-{second_next}'
