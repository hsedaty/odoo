# -*- coding: utf-8 -*-

from . import controllers
from . import models


def post_init_hook(env):
    env['school.financial.report']._refresh_all()
