const fs = require('node:fs');
const http = require('node:http');
const req = require('node:module').createRequire(process.env.SWECLAR_NODE_REQUIRE_ROOT || __filename);
const { WebSocketServer, WebSocket } = req('ws');

const config = JSON.parse(fs.readFileSync(process.env.SHOP_CONFIG, 'utf8'));
const users = config && config.users && typeof config.users === 'object' ? config.users : {};
const sessions = config && config.sessions && typeof config.sessions === 'object' ? config.sessions : {};
const products = config && config.products && typeof config.products === 'object' ? config.products : {};

// All state below is indexed by the authenticated user id.  Nothing in an
// action payload is used as an identity.
const subscriptions = new Map();
const inboxes = new Map();
const carts = new Map();
const notifications = new Map();
const sockets = new Map();

const hasOwn = (object, key) =>
  object !== null && object !== undefined &&
  (typeof object === 'object' || typeof object === 'function') &&
  Object.prototype.hasOwnProperty.call(object, key);

class ShopError extends Error {
  constructor(code, status = 400) {
    super(code);
    this.name = 'ShopError';
    this.code = code;
    this.status = status;
  }
}

function authenticatedUser(authorization) {
  if (typeof authorization !== 'string' || !authorization.startsWith('Bearer ')) return null;
  const token = authorization.slice('Bearer '.length);
  if (!token || !hasOwn(sessions, token)) return null;
  const userId = sessions[token];
  return typeof userId === 'string' && userRecord(userId) ? userId : null;
}

function userRecord(userId) {
  return hasOwn(users, userId) && users[userId] && typeof users[userId] === 'object'
    ? users[userId]
    : null;
}

function productRecord(productId) {
  if (typeof productId !== 'string' ||
      !hasOwn(products, productId) ||
      !products[productId] ||
      typeof products[productId] !== 'object') {
    throw new ShopError('unknown_product');
  }
  return products[productId];
}

function productPrice(productId) {
  const product = productRecord(productId);
  // Products are part of the trusted fixture, but refusing an invalid price is
  // preferable to allowing an unsafe value into a user's cart.
  if (!Number.isSafeInteger(product.price_cents) || product.price_cents < 0) {
    throw new ShopError('invalid_product_price');
  }
  return product.price_cents;
}

function validNonemptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function validQuantity(value) {
  // Number.isSafeInteger also rejects booleans, strings, fractions, Infinity,
  // and numbers outside JavaScript's exact integer range.
  return Number.isSafeInteger(value) && value > 0;
}

function cartFor(userId) {
  const rows = [];
  let total = 0;
  const lines = carts.get(userId) || new Map();

  for (const [productId, quantity] of lines) {
    if (!Number.isSafeInteger(quantity) || quantity <= 0) {
      throw new ShopError('invalid_quantity');
    }
    const price = productPrice(productId);
    const lineTotal = quantity * price;
    if (!Number.isSafeInteger(lineTotal)) throw new ShopError('invalid_quantity');
    const nextTotal = total + lineTotal;
    if (!Number.isSafeInteger(nextTotal)) throw new ShopError('invalid_quantity');
    total = nextTotal;
    rows.push({
      product_id: productId,
      quantity,
      price_cents: price,
      line_total_cents: lineTotal,
    });
  }

  return { lines: rows, total_cents: total };
}

function publish(userId, input) {
  const currentUser = userRecord(userId);
  if (!currentUser || currentUser.role !== 'manager') throw new ShopError('forbidden', 403);

  const { id, channel, title } = input;
  if (!validNonemptyString(id) || !validNonemptyString(channel) || !validNonemptyString(title)) {
    throw new ShopError('invalid_notification');
  }

  const record = { id, channel, title };
  const existing = notifications.get(id);
  if (existing) {
    if (existing.id === record.id && existing.channel === record.channel && existing.title === record.title) {
      return { duplicate: true };
    }
    throw new ShopError('notification_conflict');
  }

  // Take the recipient decision before changing any inbox.  JavaScript runs
  // this action synchronously, so this is the complete subscription snapshot
  // for the publication.
  const recipients = [];
  for (const [recipient, channels] of subscriptions) {
    if (channels.has(channel)) recipients.push(recipient);
  }

  notifications.set(id, record);
  for (const recipient of recipients) {
    const rows = inboxes.get(recipient) || [];
    rows.push({ ...record });
    inboxes.set(recipient, rows);

    // A user may have more than one authenticated connection.  A failed send
    // on an already-closing socket must not undo the durable in-memory inbox
    // delivery or affect the other connections.
    const active = sockets.get(recipient);
    if (!active) continue;
    for (const socket of [...active]) {
      if (socket.readyState !== WebSocket.OPEN) continue;
      try {
        socket.send(JSON.stringify(record));
      } catch (_) {
        // The close event removes the socket from the active set.  There is no
        // useful action for a send that loses a race with that close.
      }
    }
  }

  return { duplicate: false };
}

function changeCart(userId, input) {
  const productId = input.product_id;
  const quantity = input.quantity;
  // Validate every input before making a candidate state.  In particular,
  // price_cents supplied by a caller is intentionally ignored.
  productPrice(productId);
  if (!validQuantity(quantity)) throw new ShopError('invalid_quantity');

  const previous = carts.get(userId) || new Map();
  const next = new Map(previous);
  const oldQuantity = next.get(productId) || 0;

  let nextQuantity;
  if (input.type === 'add') {
    nextQuantity = oldQuantity + quantity;
    if (!Number.isSafeInteger(nextQuantity)) throw new ShopError('invalid_quantity');
    next.set(productId, nextQuantity);
  } else {
    nextQuantity = oldQuantity - quantity;
    if (nextQuantity > 0) {
      // oldQuantity and quantity are safe positive integers, so a positive
      // subtraction is safe as well.
      next.set(productId, nextQuantity);
    } else {
      next.delete(productId);
    }
  }

  // Calculate the entire candidate cart before committing it.  This makes an
  // overflow (or a malformed existing fixture) a no-op.
  const oldCart = carts.get(userId);
  carts.set(userId, next);
  try {
    const result = cartFor(userId);
    return result;
  } catch (error) {
    if (oldCart) carts.set(userId, oldCart);
    else carts.delete(userId);
    throw error;
  }
}

function performAction(userId, input) {
  const type = input.type;

  if (type === 'subscribe' || type === 'unsubscribe') {
    const channel = input.channel;
    if (!validNonemptyString(channel)) throw new ShopError('invalid_channel');

    // Work on a copy so a future validation or failure cannot partially alter
    // an existing subscription set.
    const next = new Set(subscriptions.get(userId) || []);
    if (type === 'subscribe') next.add(channel);
    else next.delete(channel);
    subscriptions.set(userId, next);
    return { channels: [...next].sort() };
  }

  if (type === 'publish') return publish(userId, input);
  if (type === 'add' || type === 'remove') return changeCart(userId, input);
  throw new ShopError('unknown_action');
}

function catalog() {
  return Object.entries(products).map(([id, product]) => ({
    ...(product && typeof product === 'object' ? product : {}),
    id,
  }));
}

const server = http.createServer(async (request, response) => {
  const reply = (status, value) => {
    const body = JSON.stringify(value);
    response.writeHead(status, {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
    });
    response.end(body);
  };

  const userId = authenticatedUser(request.headers.authorization);
  if (!userId) return reply(401, { error: 'unauthenticated' });

  if (request.method === 'GET' && request.url === '/catalog') return reply(200, catalog());
  if (request.method === 'GET' && request.url === '/inbox') return reply(200, inboxes.get(userId) || []);
  if (request.method === 'GET' && request.url === '/cart') {
    try {
      return reply(200, cartFor(userId));
    } catch (error) {
      const status = error instanceof ShopError ? error.status : 400;
      const code = error instanceof ShopError ? error.code : 'invalid_cart';
      return reply(status, { error: code });
    }
  }
  if (request.method !== 'POST' || request.url !== '/actions') return reply(404, { error: 'not_found' });

  try {
    let body = '';
    let bytes = 0;
    for await (const chunk of request) {
      bytes += Buffer.byteLength(chunk);
      if (bytes > 65536) throw new ShopError('invalid_request');
      body += chunk.toString();
    }
    const input = JSON.parse(body);
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      throw new ShopError('invalid_request');
    }
    return reply(200, performAction(userId, input));
  } catch (error) {
    const status = error instanceof ShopError ? error.status : 400;
    const code = error instanceof ShopError ? error.code : 'invalid_request';
    return reply(status, { error: code });
  }
});

const wss = new WebSocketServer({ noServer: true });
server.on('upgrade', (request, socket, head) => {
  const userId = authenticatedUser(request.headers.authorization);
  if (!userId || request.url !== '/events') {
    socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
    return;
  }

  wss.handleUpgrade(request, socket, head, ws => {
    const active = sockets.get(userId) || new Set();
    active.add(ws);
    sockets.set(userId, active);
    const remove = () => {
      active.delete(ws);
      if (active.size === 0 && sockets.get(userId) === active) sockets.delete(userId);
    };
    ws.on('close', remove);
    ws.on('error', () => {
      // close normally follows an error; keeping this handler prevents an
      // unhandled ws error from taking down the service.
    });
  });
});

server.listen(Number(process.env.PORT || 0), '127.0.0.1', () => {
  console.log(JSON.stringify({ port: server.address().port }));
});
