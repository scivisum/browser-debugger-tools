import pathlib
from glob import glob

DIR = pathlib.Path(__file__).parent.resolve()

CHROME_EXTENSIONS = glob(f"{DIR}/chromeExtensions/*")
