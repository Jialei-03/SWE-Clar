import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {mappedReadOperations,mappedWorkingDirectory} from '../pi/mapped_read.mjs';

test('mapped cwd is explicit, including nonstandard task workspaces',()=>{
  assert.equal(mappedWorkingDirectory({read_roots:[{virtual:'/task/project',workspace:true}]}),'/task/project');
  assert.throws(()=>mappedWorkingDirectory({read_roots:[]}),/exactly one/);
  assert.throws(()=>mappedWorkingDirectory({read_roots:[{virtual:'/',workspace:true}]}),/Invalid/);
});

test('private read confines paths and symlinks and has no write/exec operations',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'sweclar-read-test-'));
  const root=path.join(temp,'task');await fs.mkdir(root);
  await fs.writeFile(path.join(root,'test.py'),'private test');
  await fs.writeFile(path.join(temp,'secret'),'do not read');
  await fs.symlink(path.join(temp,'secret'),path.join(root,'escape'));
  const read=mappedReadOperations({read_roots:[{virtual:'/private_acceptance',real:root}]});
  assert.equal(String(await read.readFile('/private_acceptance/test.py')),'private test');
  await assert.rejects(()=>read.readFile('/private_acceptance/../secret'));
  await assert.rejects(()=>read.readFile('/private_acceptance/escape'));
  await assert.rejects(()=>read.readFile('/etc/passwd'));
  assert.deepEqual(Object.keys(read).sort(),['access','detectImageMimeType','readFile']);
});

test('frozen manifests reject drift/new files; cards and single files are exact reads',async()=>{
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'sweclar-manifest-test-'));
  const file=path.join(temp,'helper.py');await fs.writeFile(file,'original');
  const hash=createHash('sha256').update('original').digest('hex');
  const read=mappedReadOperations({read_roots:[
    {virtual:'/public_tests',real:temp,files:{'helper.py':hash}},
    {virtual:'/task/request.md',real:file,files:{'':hash}},
    {virtual:'/requirements/001.json',content:'{"content":"private requirement"}'}
  ]});
  assert.equal(String(await read.readFile('/public_tests/helper.py')),'original');
  assert.equal(String(await read.readFile('/task/request.md')),'original');
  assert.equal(JSON.parse(String(await read.readFile('/requirements/001.json'))).content,'private requirement');
  await assert.rejects(()=>read.readFile('/requirements/002.json'));
  await assert.rejects(()=>read.readFile('/requirements/../secret'));
  await assert.rejects(()=>read.readFile('/task/request.md/child'));
  await fs.writeFile(path.join(temp,'new.py'),'unreviewed');
  await assert.rejects(()=>read.readFile('/public_tests/new.py'),/manifest/);
  await fs.writeFile(file,'changed');
  await assert.rejects(()=>read.readFile('/public_tests/helper.py'),/hash mismatch/);
  await assert.rejects(()=>read.readFile('/task/request.md'),/hash mismatch/);
});
