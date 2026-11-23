from odoo import api, SUPERUSER_ID
from odoo.tools.convert import convert_file


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # This requested replacement is one-time; later upgrades preserve seed edits.
    convert_file(env, 'school_planning', 'data/american_subjects.xml', {}, mode='init')
    env['school.timetable']._install_american_timetable(replace=True)
