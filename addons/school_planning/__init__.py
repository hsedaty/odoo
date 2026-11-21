# -*- coding: utf-8 -*-

from . import controllers
from . import models


def post_init_hook(env):
    env['school.prediction.seed.configuration']._install_planning_catalog()
    env['school.financial.report']._refresh_all()
