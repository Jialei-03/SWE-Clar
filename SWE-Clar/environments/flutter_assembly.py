"""Prepare the pinned, offline Flutter component environment before task budgets start."""
import argparse,concurrent.futures,hashlib,json,os,pathlib,shutil,subprocess,tarfile,tempfile,urllib.request,uuid,zipfile
HERE=pathlib.Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def unzip(path,destination):
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for item in archive.infolist():
            target=destination/item.filename
            if not target.resolve().is_relative_to(destination.resolve()) or ((item.external_attr>>16)&0o170000)==0o120000:
                raise RuntimeError('Unsafe SDK archive member')
            archive.extract(item,destination)
            if target.is_file():target.chmod((item.external_attr>>16)&0o777 or 0o644)


def assemble(cache,context,lock):
    source=cache/'sdk-source';framework=lock['framework']
    if not source.exists():
        subprocess.run(['git','clone','--depth','1','--single-branch','--branch',framework['tag'],'--config','core.logAllRefUpdates=false',framework['repository'],str(source)],check=True)
    revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    remote=subprocess.check_output(['git','-C',str(source),'remote','get-url','origin'],text=True).strip()
    if revision!=framework['commit'] or remote!=framework['repository']:
        raise RuntimeError('SDK cache is not the pinned public Flutter source')
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=all'],text=True).strip():
        raise RuntimeError('SDK source cache must contain a clean pinned checkout')
    flutter=context/'flutter';shutil.copytree(source,flutter,symlinks=True)
    # Clone history metadata is not necessary for version resolution.
    if (flutter/'.git/logs').exists():shutil.rmtree(flutter/'.git/logs')
    patch=HERE/lock['framework_patch']['file']
    if sha(patch)!=lock['framework_patch']['sha256']:raise RuntimeError('SDK compatibility patch changed')
    subprocess.run(['git','-C',str(flutter),'apply','--check',str(patch)],check=True)
    subprocess.run(['git','-C',str(flutter),'apply',str(patch)],check=True)
    sdk_cache=flutter/'bin/cache';sdk_cache.mkdir(parents=True,exist_ok=True)
    unzip(cache/'dart-sdk-linux-x64.zip',sdk_cache)
    for name in ['linux-x64-artifacts.zip','font-subset.zip']:unzip(cache/name,sdk_cache/'artifacts/engine/linux-x64')
    for name in ['flutter_patched_sdk.zip','flutter_patched_sdk_product.zip']:unzip(cache/name,sdk_cache/'artifacts/engine/common')
    for name in ['sky_engine.zip','flutter_gpu.zip']:unzip(cache/name,sdk_cache/'pkg')
    unzip(cache/'fonts.zip',sdk_cache/'artifacts/material_fonts')
    gradle=sdk_cache/'artifacts/gradle_wrapper';gradle.mkdir(parents=True)
    with tarfile.open(cache/'gradle-wrapper.tgz') as archive:archive.extractall(gradle,filter='data')
    shutil.copy2(cache/'engine_stamp.json',sdk_cache/'engine_stamp.json')
    for stamp in ['engine','engine-dart-sdk','engine_stamp','flutter_sdk','font-subset']:(sdk_cache/(stamp+'.stamp')).write_text(framework['engine']+'\n')
    for stamp in ['material_fonts','gradle_wrapper']:(sdk_cache/(stamp+'.stamp')).write_text((flutter/'bin/internal'/(stamp+'.version')).read_text().strip()+'\n')
    (sdk_cache/'engine.realm').write_text('\n')
    pub=context/'pub-cache'
    for row in lock['pub_artifacts']:
        key=row['name']+'-'+row['version'];destination=pub/'hosted/pub.dev'/key;destination.mkdir(parents=True)
        with tarfile.open(cache/row['file']) as archive:archive.extractall(destination,filter='data')
        hashes=pub/'hosted-hashes/pub.dev';hashes.mkdir(parents=True,exist_ok=True);(hashes/(key+'.sha256')).write_text(row['sha256'])
    shutil.copy2(HERE/'tools.pubspec.lock',flutter/'packages/flutter_tools/pubspec.lock')
    for name in ['Dockerfile','flutter-launch','dart-launch','preflight.py']:
        if (HERE/name).resolve() != (context/name).resolve():shutil.copy2(HERE/name,context/name)
    if (HERE/'preflight_fixture').resolve() != (context/'preflight_fixture').resolve():
        shutil.copytree(HERE/'preflight_fixture',context/'preflight_fixture')


