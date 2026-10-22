import os,sys
sys.path.insert(0,os.getcwd())
from calculator import calculate
r=calculate({'land_area_sqft':10,'site_area_sqft':5,'plot_ratio':1})
assert isinstance(r,dict) and 'converted' in r
print('Public calculation entry point available')
