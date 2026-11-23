from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    seed = env.ref('school_planning.prediction_seed_transportation_fee', raise_if_not_found=False)
    if seed and seed.name == 'Transportation Fee':
        seed.unlink()
