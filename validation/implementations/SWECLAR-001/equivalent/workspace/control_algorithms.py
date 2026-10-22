def stable_order(values, key=None):
    rows=[((key(value) if key else value), value) for value in values]
    def merge_sort(items):
        if len(items)<2: return items
        middle=len(items)//2
        left,right=merge_sort(items[:middle]),merge_sort(items[middle:])
        result=[];i=j=0
        while i<len(left) and j<len(right):
            if right[j][0]<left[i][0]: result.append(right[j]);j+=1
            else: result.append(left[i]);i+=1
        return result+left[i:]+right[j:]
    return [row[1] for row in merge_sort(rows)]
