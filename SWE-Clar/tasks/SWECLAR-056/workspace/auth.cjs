function verifyToken(token) {
  const claims=JSON.parse(Buffer.from(token.split('.')[1] || '', 'base64url').toString());
  return claims;
}
module.exports={verifyToken};
