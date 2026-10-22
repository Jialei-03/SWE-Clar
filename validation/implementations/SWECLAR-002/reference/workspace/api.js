let token = '';

export const origin = () => window.location.origin;
export const getToken = () => token;
export const setToken = value => {
  token = typeof value === 'string' ? value : '';
};
export const clearToken = () => {
  token = '';
};

/*
 * The optional third argument lets a caller bind a request to a captured
 * session.  This is important for logout and for reads that can finish after
 * the user has changed identity.
 */
export async function api(path, data, options = {}) {
  const requestToken = Object.prototype.hasOwnProperty.call(options, 'token')
    ? options.token
    : token;
  const headers = {};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  if (requestToken) headers.Authorization = `Bearer ${requestToken}`;

  let response;
  try {
    response = await fetch(origin() + path, {
      method: data === undefined ? 'GET' : 'POST',
      headers,
      body: data === undefined ? undefined : JSON.stringify(data),
      signal: options.signal,
    });
  } catch (error) {
    throw Error(error && error.name === 'AbortError' ? 'request_cancelled' : 'network_error');
  }

  const raw = await response.text();
  let value;
  try {
    value = raw ? JSON.parse(raw) : {};
  } catch (_error) {
    throw Error('invalid_response');
  }
  if (!response.ok) {
    throw Error(value && typeof value.error === 'string' ? value.error : 'request_failed');
  }

  if (path === '/login' && value && typeof value.token === 'string' && value.token) {
    token = value.token;
  }
  if (path === '/logout' && options.clearOnSuccess !== false && requestToken === token) {
    token = '';
  }
  return value;
}
