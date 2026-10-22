import hashlib
from pathlib import Path
def apply(path):
 text=path.read_text()
 assert hashlib.sha256(path.read_bytes()).hexdigest()=='34c2cc84d26f2b5250a30e69106fd346fd3c2778c885f179220096dade7bbdd6'
 needle="    if embeds_scaling == 'K+mean(V) w/ C penalty':"
 text=text.replace(needle,"    # CPU manual-cast UNet queries can be float32 while adapter weights are fp16.\n    ip_k = ip_k.to(dtype=q.dtype)\n    ip_v = ip_v.to(dtype=q.dtype)\n\n"+needle)
 assert hashlib.sha256(text.encode()).hexdigest()=='d4d2badb81124487cc57f19da28cd6228f6a940f59a242bb612938920948fc6a'
 path.write_text(text)
