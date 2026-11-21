from odoo import api, SUPERUSER_ID
from odoo.tools.convert import convert_file


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    convert_file(env, 'school_planning', 'data/american_subjects.xml', {}, mode='init', noupdate=True)
