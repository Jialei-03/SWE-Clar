import { execFile, spawn } from 'node:child_process';
import path from 'node:path';
import { promisify } from 'node:util';
import { createHash } from 'node:crypto';

const execFileAsync = promisify(execFile);

export function runtimeUserArgs(input) {
  const uid = input.runtime_uid;
  if (uid === null || uid === undefined) return [];
  if (!Number.isInteger(uid) || uid < 1 || uid > 65535) {
    throw new Error('Candidate runtime_uid must be a non-root integer identity');
  }
  return ['--user', `${uid}:${uid}`];
}

export function runtimePath(input, value, { publicRead = false } = {}) {
  const root = path.posix.resolve(input.runtime_workspace || '/workspace/project');
  const candidate = path.posix.resolve(String(value || ''));
  const publicPath =
    publicRead && (candidate === '/public_tests' || candidate.startsWith('/public_tests/'));
  const publicSource = publicRead && candidate.startsWith('/opt/sweclar/') &&
    Object.hasOwn(input.runtime_public_read_files || {}, candidate) &&
    /^[a-f0-9]{64}$/.test(input.runtime_public_read_files[candidate]);
  if (!publicPath && !publicSource && candidate !== root && !candidate.startsWith(`${root}/`)) {
    throw new Error(`Pi tool path escapes the task workspace: ${value}`);
  }
  return candidate;
}

async function dockerExecBuffer(input, argv, maxBuffer = 64 * 1024 * 1024) {
  const result = await execFileAsync(
    'docker',
    ['exec', ...runtimeUserArgs(input), input.runtime_container, ...argv],
    {
      encoding: null,
      maxBuffer,
      windowsHide: true,
    }
  );
  return Buffer.isBuffer(result.stdout) ? result.stdout : Buffer.from(result.stdout || '');
}

function dockerWrite(input, argv, content = null) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      'docker',
      ['exec', '-i', ...runtimeUserArgs(input), input.runtime_container, ...argv],
      {
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      }
    );
    const stderr = [];
    child.stderr.on('data', data => stderr.push(data));
    child.on('error', reject);
    child.on('close', code => {
      if (code === 0) resolve();
      else
        reject(new Error(Buffer.concat(stderr).toString('utf8') || `docker exec exited ${code}`));
    });
    if (content === null) child.stdin.end();
    else child.stdin.end(content, 'utf8');
  });
}

export function dockerBashOperations(input) {
  const container = input.runtime_container;
  const workspace = input.runtime_workspace || '/workspace/project';
  return {
    exec(command, cwd, { onData, signal, timeout }) {
      const requestedTimeout = Number(timeout);
      const timeoutArgs = Number.isFinite(requestedTimeout) && requestedTimeout > 0
        ? ['timeout', '-s', 'TERM', '-k', '5', String(requestedTimeout)] : [];
      const workdir = runtimePath(input, cwd || workspace);
      return new Promise((resolve, reject) => {
        const child = spawn(
          'docker',
          [
            'exec',
            '--workdir',
            workdir,
            ...runtimeUserArgs(input),
            container,
            ...timeoutArgs,
            '/bin/bash',
            '-c',
            command,
          ],
          { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true }
        );
        child.stdout.on('data', onData);
        child.stderr.on('data', onData);
        child.on('error', reject);
        child.on('close', code => resolve({ exitCode: code }));
        const abort = () => child.kill('SIGTERM');
        if (signal?.aborted) abort();
        else signal?.addEventListener('abort', abort, { once: true });
      });
    },
  };
}

export function dockerFileOperations(input, imageMime = new Map()) {
  const container = input.runtime_container;
  const checked = (value, publicRead = false) => runtimePath(input, value, { publicRead });
  const test = async (flag, value, publicRead = false) => {
    await execFileAsync(
      'docker',
      ['exec', ...runtimeUserArgs(input), container, 'test', flag, checked(value, publicRead)],
      {
        windowsHide: true,
      }
    );
  };
  return {
    read: {
      readFile: async value => {
        const target = checked(value, true);
        const data = await dockerExecBuffer(input, ['cat', '--', target]);
        const expected = input.runtime_public_read_files?.[target];
        if (expected && createHash('sha256').update(data).digest('hex') !== expected)
          throw new Error('Runtime public source differs from the frozen environment manifest');
        return data;
      },
      access: value => test('-r', value, true),
      detectImageMimeType: async value => imageMime.get(path.extname(value).toLowerCase()) || null,
    },
    edit: {
      readFile: value => dockerExecBuffer(input, ['cat', '--', checked(value)]),
      access: async value => {
        await test('-r', value);
        await test('-w', value);
      },
      writeFile: (value, content) =>
        dockerWrite(input, ['/bin/sh', '-c', 'cat > "$1"', 'sweclar-write', checked(value)], content),
    },
    write: {
      mkdir: value => dockerWrite(input, ['mkdir', '-p', '--', checked(value)]),
      writeFile: (value, content) =>
        dockerWrite(input, ['/bin/sh', '-c', 'cat > "$1"', 'sweclar-write', checked(value)], content),
    },
  };
}
