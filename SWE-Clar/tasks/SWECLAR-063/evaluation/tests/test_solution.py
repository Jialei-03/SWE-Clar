import tempfile
from pathlib import Path
from food_contract import App,ru001,ru002,ru003,ru004,ru005

def run(test):
 with tempfile.TemporaryDirectory() as d:
  a=App(Path(d))
  try:test(a)
  finally:a.close()

def test_ru_001_contract():run(ru001)
def test_ru_002_contract():run(ru002)
def test_ru_003_contract():run(ru003)
def test_ru_004_contract():run(ru004)
def test_ru_005_contract():run(ru005)
