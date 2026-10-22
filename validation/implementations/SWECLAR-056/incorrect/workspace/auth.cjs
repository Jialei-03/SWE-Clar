const {createHmac,timingSafeEqual}=require('node:crypto');

function decodeBase64UrlSegment(segment) {
  if(typeof segment!=='string' || segment.length===0) throw new Error('Malformed JWT');
  // Node's base64 decoder is deliberately permissive, so validate the JWT
  // alphabet before decoding it.
  if(!/^[A-Za-z0-9_-]+={0,2}$/.test(segment) || /=[^=]/.test(segment)) {
    throw new Error('Malformed JWT');
  }
  const unpadded=segment.replace(/=+$/,'');
  if(unpadded.length%4===1) throw new Error('Malformed JWT');
  const decoded=Buffer.from(segment,'base64url');
  if(decoded.length===0 || decoded.toString('base64url')!==unpadded) {
    throw new Error('Malformed JWT');
  }
  return decoded;
}

function parseJsonSegment(segment) {
  try { return JSON.parse(decodeBase64UrlSegment(segment).toString('utf8')); }
  catch { throw new Error('Malformed JWT'); }
}

/**
 * Verify a compact JWT signed with the one algorithm supported by the
 * service.  The validation is intentionally kept here rather than delegated
 * to a permissive JWT parser: accepting a different algorithm or an unsigned
 * token would make the WebSocket upgrade unauthenticated.
 */
function verifyToken(token,secret,now) {
  if(typeof token!=='string' || typeof secret!=='string' && !Buffer.isBuffer(secret)) {
    throw new Error('Invalid credentials');
  }

  const parts=token.split('.');
  if(parts.length!==3 || parts.some(part=>part.length===0)) throw new Error('Invalid credentials');

  const header=parseJsonSegment(parts[0]);
  const claims=parseJsonSegment(parts[1]);
  if(!header || typeof header!=='object' || Array.isArray(header) || header.alg!=='HS256') {
    throw new Error('Invalid credentials');
  }
  if(!claims || typeof claims!=='object' || Array.isArray(claims)) {
    throw new Error('Invalid credentials');
  }

  let supplied;
  try { supplied=decodeBase64UrlSegment(parts[2]); }
  catch { throw new Error('Invalid credentials'); }
  const expected=createHmac('sha256',secret).update(`${parts[0]}.${parts[1]}`).digest();
  if(supplied.length!==expected.length || !timingSafeEqual(supplied,expected)) {
    throw new Error('Invalid credentials');
  }

  if(typeof claims.sub!=='string' || claims.sub.length===0 ||
     typeof claims.device_id!=='string' || claims.device_id.length===0 ||
     typeof claims.exp!=='number' || !Number.isFinite(claims.exp) ||
     typeof now!=='number' || !Number.isFinite(now) || claims.exp<=now) {
    throw new Error('Invalid credentials');
  }

  return claims;
}

function bearerToken(value) {
  if(typeof value!=='string') throw new Error('Invalid credentials');
  const match=/^Bearer\s+(\S+)$/i.exec(value);
  if(!match) throw new Error('Invalid credentials');
  return match[1];
}

module.exports={verifyToken,bearerToken};
