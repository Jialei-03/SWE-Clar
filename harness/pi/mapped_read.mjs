/* Read-only virtual roots with realpath confinement, including symlink parents. */
import { constants } from 'node:fs';
import { access, readFile, realpath } from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';

export function mappedWorkingDirectory(input) {
  const roots=Array.isArray(input.read_roots)?input.read_roots:[];
  const workspaces=roots.filter(x=>x.workspace===true);
  if(workspaces.length!==1)throw new Error('Mapped sessions require exactly one explicit workspace');
  const workspace=workspaces[0].virtual;
  if(typeof workspace!=='string'||!path.isAbsolute(workspace)||path.resolve(workspace)==='/')
    throw new Error('Invalid mapped workspace');
  return path.resolve(workspace);
}

export function mappedReadOperations(input, imageMime = new Map()) {
  const inline=new Map((Array.isArray(input.read_roots)?input.read_roots:[]).filter(x=>x && typeof x.virtual==='string' && typeof x.content==='string')
    .map(x=>[path.resolve(x.virtual),Buffer.from(x.content)]));
  const roots = (Array.isArray(input.read_roots) ? input.read_roots : [])
    .filter(x => x && typeof x.virtual === 'string' && typeof x.real === 'string')
    .map(x => ({virtual:path.resolve(x.virtual), real:path.resolve(x.real),files:x.files}))
    .sort((a,b) => b.virtual.length-a.virtual.length);
  const inside = (file,root) => file === root || file.startsWith(root+path.sep);
  const translate = async value => {
    const requested=path.resolve(String(value || ''));
    for (const root of roots) {
      if (!inside(requested,root.virtual)) continue;
      const relative=path.relative(root.virtual,requested);
      if (root.files && !Object.hasOwn(root.files,relative)) throw new Error('File is not in frozen manifest');
      const base=await realpath(root.real);
      const resolved=await realpath(path.resolve(base,relative));
      if (!inside(resolved,base)) throw new Error('Read escapes frozen allowlist');
      return {resolved,expected:root.files?.[relative]};
    }
    throw new Error('File is outside the frozen read allowlist');
  };
  return {
    readFile: async value => {
      const memory=inline.get(path.resolve(String(value || '')));
      if(memory)return Buffer.from(memory);
      const {resolved,expected}=await translate(value);
      const data=await readFile(resolved);
      if(expected && createHash('sha256').update(data).digest('hex')!==expected)throw new Error(`Frozen source hash mismatch: ${value}`);
      return data;
    },
    access: async value => {
      if(inline.has(path.resolve(String(value || ''))))return;
      const {resolved}=await translate(value);return access(resolved,constants.R_OK);
    },
    detectImageMimeType: async value => imageMime.get(path.extname(value).toLowerCase()) || null,
  };
}
