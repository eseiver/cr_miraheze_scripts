import logging
import sys

logger = logging.getLogger('cr_wiki')
# logger.setLevel(logging.DEBUG)

fh = logging.StreamHandler(sys.stdout)
fh_formatter = logging.Formatter('%(asctime)s %(levelname)s - %(message)s')
fh.setFormatter(fh_formatter)
logger.addHandler(fh)