from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
import math
FIELDS=('land_area_sqft','site_area_sqft','plot_ratio')
def calculate(values):
    if not isinstance(values,dict):raise ValueError('invalid_input')
    numbers={}
    for key in FIELDS:
        value=values.get(key)
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0:raise ValueError('invalid_input')
        numbers[key]=Decimal(str(value))
    try:
        rounded=lambda x:float(x.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
        converted={key.removesuffix('_sqft')+'_sqm':rounded(numbers[key]*Decimal('0.092903')) for key in FIELDS[:2]}
        result={'gross_floor_area_sqft':rounded((numbers['land_area_sqft'])*numbers['plot_ratio'])}
        if not all(math.isfinite(x) for x in [*converted.values(),*result.values()]):raise ValueError('invalid_input')
    except (InvalidOperation,OverflowError):raise ValueError('invalid_input')
    return {'inputs':{key:values[key] for key in FIELDS},'converted':converted,'result':result,'summary':{**converted,**result}}
