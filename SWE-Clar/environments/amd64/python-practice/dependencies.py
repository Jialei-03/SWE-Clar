"""Install checksum-locked public UI packages during manager-side preparation."""
import base64,hashlib,io,json,os,tarfile
from pathlib import Path,PurePosixPath
from urllib.request import urlopen


def install(lock_path,destination):
    packages=json.loads(Path(lock_path).read_text())['packages'];evidence=[]
    for relative,item in packages.items():
        if not relative:continue
        if item.get('os') and 'linux' not in item['os']:continue
        if item.get('cpu') and 'x64' not in item['cpu']:continue
        path=PurePosixPath(relative)
        if path.is_absolute() or '..' in path.parts or path.parts[0]!='node_modules':raise ValueError('Invalid package path')
        url=item['resolved']
        if not url.startswith('https://registry.npmjs.org/'):raise ValueError('Unexpected package registry')
        integrity=item['integrity'];algorithm,expected=integrity.split('-',1)
        if algorithm not in {'sha512','sha256'}:raise ValueError('Unsupported package checksum')
        with urlopen(url,timeout=60) as response:body=response.read()
        if base64.b64encode(hashlib.new(algorithm,body).digest()).decode()!=expected:raise ValueError('Package checksum mismatch')
        target=Path(destination)/relative;target.mkdir(parents=True,exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(body),mode='r:gz') as archive:
            for member in archive.getmembers():
                parts=PurePosixPath(member.name).parts
                if not parts or parts[0]!='package' or '..' in parts or member.issym() or member.islnk():raise ValueError('Unsafe dependency archive')
                file=target.joinpath(*parts[1:])
                if member.isdir():file.mkdir(parents=True,exist_ok=True)
                elif member.isfile():
                    file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(archive.extractfile(member).read());file.chmod(0o755 if member.mode & 0o111 else 0o644)
                else:raise ValueError('Unexpected dependency entry')
        evidence.append({'path':relative,'version':item['version'],'integrity':integrity})
    return evidence
