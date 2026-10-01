import logging, sys, os

os.chdir('/app')
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
from logging import config as lc
lc.fileConfig = lambda *a, **kw: None

from alembic.config import Config
from alembic import command

cfg = Config('/app/alembic.ini')
command.upgrade(cfg, 'head')
print('Migrations complete.')
