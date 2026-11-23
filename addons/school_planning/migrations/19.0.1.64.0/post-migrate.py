from odoo import api, SUPERUSER_ID
from odoo.tools import SQL


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for model, parent_field, children_field, grade_field in (
        ('school.timetable.line', 'timetable_id', 'line_ids', 'grade_id'),
        ('school.subject.distribution', 'academic_year_id', 'subject_distribution_ids', 'grade_level_id'),
    ):
        rows = env[model].search([('choice_subject_ids', '!=', False)])
        for row in rows:
            if row.elective_group:
                continue
            parent = row[parent_field]
            siblings = parent[children_field].filtered(
                lambda other: other[grade_field] == row[grade_field] and other.curriculum_id == row.curriculum_id
            )
            peers = siblings.filtered(lambda other: set(other.choice_subject_ids.ids) == set(row.choice_subject_ids.ids))
            used = set(siblings.mapped('elective_group'))
            number = 1
            while f'ELCT{number}' in used:
                number += 1
            label = f'ELCT{number}'
            if model == 'school.subject.distribution' and parent.baseline_locked:
                # Label historical slots without rewriting approved subjects or hours.
                cr.execute(SQL('UPDATE %s SET elective_group = %s WHERE id IN %s',
                               SQL.identifier(peers._table), label, tuple(peers.ids)))
                peers.invalidate_recordset(['elective_group'])
                peers.modified(['elective_group'])
                continue
            peers.write({'elective_group': label})
            for subject in row.choice_subject_ids - peers.subject_id:
                row.copy({'subject_id': subject.id, 'elective_group': label})
        if model == 'school.subject.distribution':
            rows = rows.filtered(lambda row: not row.academic_year_id.baseline_locked)
            env.add_to_compute(rows._fields['total_teaching_hours'], rows)
            rows._recompute_recordset(['total_teaching_hours'])
            rows._refresh_year_reports(rows.academic_year_id)
