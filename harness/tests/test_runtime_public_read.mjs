import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {dockerFileOperations} from '../pi/runtime_operations.mjs';

test('actual Docker reader verifies allowed public source bytes and forbids writes', async()=>{
  // Fake only Docker transport: exercise the real path/read/hash implementation.
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),'sweclar-docker-read-'));
  const executable=path.join(temp,'docker');
  await fs.writeFile(executable,'#!/bin/sh\nprintf "reviewed source"\n',{mode:0o755});
  const previous=process.env.PATH;
  process.env.PATH=temp+path.delimiter+previous;
  try{
    const filename='/opt/sweclar/offer_service.py';
    const input={runtime_workspace:'/workspace',runtime_container:'fake-public-read',runtime_uid:1000,
      runtime_public_read_files:{[filename]:createHash('sha256').update('reviewed source').digest('hex')}};
    const operations=dockerFileOperations(input);
    assert.equal(String(await operations.read.readFile(filename)),'reviewed source');
    await assert.rejects(async()=>operations.read.readFile('/opt/sweclar/not-listed.py'));
    await assert.rejects(async()=>operations.read.readFile('/private/tests/answers.py'));
    await assert.rejects(async()=>operations.write.writeFile(filename,'modified'));
    input.runtime_public_read_files[filename]='0'.repeat(64);
    await assert.rejects(()=>operations.read.readFile(filename),/differs from the frozen/);
  }finally{
    process.env.PATH=previous;
    await fs.unlink(executable);
    await fs.rmdir(temp);
  }
});
