'use strict';

const crypto = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');

const MODULES = Object.freeze(['daily_chart', 'curriculum', 'incident', 'attendance']);
const PARENT_MODULES = new Set(['daily_chart', 'curriculum']);
const ROLES = new Set(['admin', 'staff', 'parent']);
const PRIVATE_USER_FIELDS = ['pin', 'initial_pin', 'initialPin', 'password'];

function isObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasOwn(value, key) {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function nonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function fail(code, status) {
  const error = new Error(code);
  if (status !== undefined) error.status = status;
  throw error;
}

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

function safePinVerifier(pin, salt) {
  return crypto.scryptSync(pin, salt, 32).toString('hex');
}

function hashToken(token) {
  return crypto.createHash('sha256').update(token, 'utf8').digest('hex');
}

function sameVerifier(actual, expected) {
  if (typeof actual !== 'string' || typeof expected !== 'string') return false;
  const left = Buffer.from(actual, 'utf8');
  const right = Buffer.from(expected, 'utf8');
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function publicRecord(document) {
  return {
    id: document._id,
    record_type: document.record_type,
    centre_id: document.centre_id,
    relationship_ids: Array.isArray(document.relationship_ids) ? clone(document.relationship_ids) : [],
    child_id: document.child_id === undefined ? null : document.child_id,
    data: clone(document.data)
  };
}

function publicMessage(document) {
  return {
    id: document._id,
    sender_id: document.sender_id,
    recipient_id: document.recipient_id,
    centre_id: document.centre_id,
    text: document.text
  };
}

class Portal {
  constructor(client, db, bootstrap) {
    this.client = client;
    this.db = db;
    this.bootstrap = bootstrap || {};
    this._initializePromise = null;
  }

  async initialize() {
    if (this._initializePromise) return this._initializePromise;
    this._initializePromise = this._doInitialize();
    try {
      await this._initializePromise;
      return undefined;
    } catch (error) {
      this._initializePromise = null;
      throw error;
    }
  }

  async _doInitialize() {
    const collectionNames = [
      'centres',
      'users',
      'children',
      'records',
      'sessions',
      'messages',
      'migration_batches'
    ];

    for (const name of collectionNames) {
      try {
        await this.db.createCollection(name);
      } catch (error) {
        if (error && error.code !== 48) throw error;
      }
    }

    const centres = isObject(this.bootstrap.centres) ? this.bootstrap.centres : {};
    for (const [id, row] of Object.entries(centres)) {
      if (!nonEmptyString(id) || !isObject(row)) throw new Error('invalid bootstrap');
      const document = clone(row);
      delete document._id;
      await this.db.collection('centres').updateOne(
        { _id: id },
        { $setOnInsert: document },
        { upsert: true }
      );
    }

    const children = isObject(this.bootstrap.children) ? this.bootstrap.children : {};
    for (const [id, row] of Object.entries(children)) {
      if (!nonEmptyString(id) || !isObject(row)) throw new Error('invalid bootstrap');
      const document = clone(row);
      delete document._id;
      await this.db.collection('children').updateOne(
        { _id: id },
        { $setOnInsert: document },
        { upsert: true }
      );
    }

    const users = isObject(this.bootstrap.users) ? this.bootstrap.users : {};
    for (const [id, row] of Object.entries(users)) {
      if (!nonEmptyString(id) || !isObject(row)) throw new Error('invalid bootstrap');
      await this._initializeUser(id, row);
    }

    // These indexes are deliberately limited to the internal collections.  No
    // internal collection is exposed by the HTTP file or record routes.
    await this.db.collection('records').createIndex({ record_type: 1, centre_id: 1, child_id: 1 });
    await this.db.collection('messages').createIndex({ centre_id: 1, sender_id: 1, recipient_id: 1 });
    await this.db.collection('sessions').createIndex({ user_id: 1, centre_id: 1 });
  }

  async _initializeUser(id, source) {
    const users = this.db.collection('users');
    const existing = await users.findOne({ _id: id });
    const sourceCopy = clone(source);
    delete sourceCopy._id;
    for (const field of PRIVATE_USER_FIELDS) delete sourceCopy[field];

    const sourcePin = typeof source.pin === 'string' ? source.pin :
      (typeof source.initial_pin === 'string' ? source.initial_pin :
        (typeof source.initialPin === 'string' ? source.initialPin : null));

    if (!existing) {
      let salt = typeof source.salt === 'string' ? source.salt : null;
      let pinHash = typeof source.pin_hash === 'string' ? source.pin_hash : null;
      if (sourcePin !== null) {
        if (!nonEmptyString(sourcePin)) throw new Error('invalid bootstrap');
        salt = crypto.randomBytes(16).toString('hex');
        pinHash = safePinVerifier(sourcePin, salt);
      }
      if (!nonEmptyString(salt) || !nonEmptyString(pinHash)) throw new Error('invalid bootstrap');
      const document = {
        ...sourceCopy,
        salt,
        pin_hash: pinHash
      };
      delete document.pin;
      await users.insertOne({ _id: id, ...document });
      return;
    }

    // A restart must never leave a bootstrap PIN in an existing user row.  If
    // a legacy row lacks a verifier, repair it from the bootstrap PIN once.
    const update = { $unset: {} };
    for (const field of PRIVATE_USER_FIELDS) update.$unset[field] = '';
    const hasVerifier = nonEmptyString(existing.salt) && nonEmptyString(existing.pin_hash);
    if (!hasVerifier) {
      if (sourcePin === null || !nonEmptyString(sourcePin)) throw new Error('invalid bootstrap');
      const salt = crypto.randomBytes(16).toString('hex');
      update.$set = { salt, pin_hash: safePinVerifier(sourcePin, salt) };
    }
    await users.updateOne({ _id: id }, update);
  }

  async _ensureInitialized() {
    await this.initialize();
  }

  async login(input) {
    await this._ensureInitialized();
    if (!isObject(input) || !nonEmptyString(input.user_id) ||
        !nonEmptyString(input.centre_id) || !nonEmptyString(input.pin)) {
      fail('invalid_login', 403);
    }

    const [user, centre] = await Promise.all([
      this.db.collection('users').findOne({ _id: input.user_id }),
      this.db.collection('centres').findOne({ _id: input.centre_id }, { projection: { _id: 1 } })
    ]);
    if (!user || !centre || !ROLES.has(user.role) || !Array.isArray(user.centre_ids) ||
        !user.centre_ids.includes(input.centre_id) ||
        !nonEmptyString(user.salt) || !nonEmptyString(user.pin_hash)) {
      fail('invalid_login', 403);
    }

    let expected;
    try {
      expected = safePinVerifier(input.pin, user.salt);
    } catch (_) {
      fail('invalid_login', 403);
    }
    if (!sameVerifier(expected, user.pin_hash)) fail('invalid_login', 403);

    const token = crypto.randomBytes(32).toString('hex');
    const session = {
      _id: hashToken(token),
      user_id: user._id,
      role: user.role,
      centre_id: input.centre_id
    };
    await this.db.collection('sessions').insertOne(session);
    return {
      token,
      user: {
        id: user._id,
        role: user.role,
        centre_id: input.centre_id
      }
    };
  }

  async session(token) {
    await this._ensureInitialized();
    if (!nonEmptyString(token)) fail('unauthorized', 403);
    const document = await this.db.collection('sessions').findOne({ _id: hashToken(token) });
    if (!document || !nonEmptyString(document.user_id) || !ROLES.has(document.role) ||
        !nonEmptyString(document.centre_id)) {
      fail('unauthorized', 403);
    }
    const result = {
      user_id: document.user_id,
      role: document.role,
      centre_id: document.centre_id
    };
    // Keep the database session binding private and non-enumerable.  Portal
    // methods use it when an actor came from session(token), while the value
    // can never be serialized as portal identity data.
    Object.defineProperty(result, '_session_id', {
      value: document._id,
      enumerable: false,
      writable: false,
      configurable: false
    });
    return result;
  }

  async _authorize(actor) {
    await this._ensureInitialized();
    if (!isObject(actor) || !nonEmptyString(actor.user_id) || !ROLES.has(actor.role) ||
        !nonEmptyString(actor.centre_id)) fail('unauthorized', 403);

    if (actor._session_id !== undefined) {
      const stored = await this.db.collection('sessions').findOne({ _id: actor._session_id });
      if (!stored || stored.user_id !== actor.user_id || stored.role !== actor.role ||
          stored.centre_id !== actor.centre_id) fail('unauthorized', 403);
    }

    const [user, centre] = await Promise.all([
      this.db.collection('users').findOne({ _id: actor.user_id }),
      this.db.collection('centres').findOne({ _id: actor.centre_id }, { projection: { _id: 1 } })
    ]);
    if (!user || !centre || user.role !== actor.role || !Array.isArray(user.centre_ids) ||
        !user.centre_ids.includes(actor.centre_id)) fail('unauthorized', 403);
    return actor;
  }

  async _referenceData(mongoSession) {
    const options = mongoSession ? { session: mongoSession } : undefined;
    const centreDocuments = await this.db.collection('centres').find({}, options).toArray();
    const childDocuments = await this.db.collection('children').find({}, options).toArray();
    const recordDocuments = await this.db.collection('records').find({}, options).toArray();
    return {
      centres: new Map(centreDocuments.map(document => [document._id, document])),
      children: new Map(childDocuments.map(document => [document._id, document.centre_id])),
      records: new Map(recordDocuments.map(document => [document._id, document]))
    };
  }

  _normalizeRecord(input, references) {
    if (!isObject(input) || !nonEmptyString(input.legacy_id) ||
        !MODULES.includes(input.record_type) || !nonEmptyString(input.centre_id) ||
        !references.centres.has(input.centre_id) || !Array.isArray(input.relationship_ids) ||
        input.relationship_ids.some(id => !nonEmptyString(id)) ||
        !hasOwn(input, 'child_id') || !isObject(input.data)) {
      fail('invalid_record');
    }

    let childId = input.child_id;
    if (childId !== null) {
      if (!nonEmptyString(childId) || !references.children.has(childId) ||
          references.children.get(childId) !== input.centre_id) fail('invalid_child');
    }

    let data;
    try {
      data = clone(input.data);
    } catch (_) {
      fail('invalid_record');
    }

    return {
      _id: input.legacy_id,
      record_type: input.record_type,
      centre_id: input.centre_id,
      relationship_ids: clone(input.relationship_ids),
      child_id: childId,
      data
    };
  }

  _validateRelationships(record, references, sameBatch) {
    for (const relationshipId of record.relationship_ids) {
      if (sameBatch.has(relationshipId)) {
        const related = sameBatch.get(relationshipId);
        if (related.centre_id !== record.centre_id) fail('cross_centre_relationship');
        continue;
      }

      const relatedRecord = references.records.get(relationshipId);
      if (relatedRecord) {
        if (relatedRecord.centre_id !== record.centre_id) fail('cross_centre_relationship');
        continue;
      }

      if (references.children.has(relationshipId)) {
        if (references.children.get(relationshipId) !== record.centre_id) {
          fail('cross_centre_relationship');
        }
        continue;
      }

      fail('unknown_relationship');
    }
  }

  _equivalentRecord(existing, incoming) {
    return existing && existing._id === incoming._id &&
      existing.record_type === incoming.record_type &&
      existing.centre_id === incoming.centre_id &&
      isDeepStrictEqual(existing.relationship_ids, incoming.relationship_ids) &&
      (existing.child_id === undefined ? null : existing.child_id) === incoming.child_id &&
      isDeepStrictEqual(existing.data, incoming.data);
  }

  _migrationInput(input) {
    let rows;
    let batchId;
    let wrapperBatch = false;

    if (Array.isArray(input)) {
      rows = input;
    } else if (isObject(input) && Array.isArray(input.rows)) {
      rows = input.rows;
      if (hasOwn(input, 'batch_id')) {
        batchId = input.batch_id;
        wrapperBatch = true;
      } else if (hasOwn(input, 'batchId')) {
        batchId = input.batchId;
        wrapperBatch = true;
      }
    } else {
      fail('invalid_migration');
    }

    if (wrapperBatch && !nonEmptyString(batchId)) fail('invalid_migration');

    const rowBatchIds = [];
    for (const row of rows) {
      if (!isObject(row) || !hasOwn(row, 'batch_id')) continue;
      if (!nonEmptyString(row.batch_id)) fail('invalid_migration');
      rowBatchIds.push(row.batch_id);
    }
    if (!wrapperBatch && rowBatchIds.length) {
      const first = rowBatchIds[0];
      if (rowBatchIds.some(value => value !== first) || rowBatchIds.length !== rows.length) {
        fail('invalid_migration');
      }
      batchId = first;
    }
    if (wrapperBatch) {
      for (const row of rows) {
        if (isObject(row) && hasOwn(row, 'batch_id') && row.batch_id !== batchId) {
          fail('invalid_migration');
        }
      }
    }

    return { rows, batchId: batchId === undefined ? null : batchId };
  }

  async migrate(actor, input) {
    actor = await this._authorize(actor);
    if (actor.role !== 'admin') fail('write_denied', 403);

    const { rows, batchId } = this._migrationInput(input);
    const normalized = [];
    const ids = new Set();
    for (const row of rows) {
      // References are loaded in the transaction below; validating shape here
      // is safe and ensures caller-owned rows are never modified.
      if (!isObject(row)) fail('invalid_record');
      if (ids.has(row.legacy_id)) fail('duplicate_batch', 409);
      ids.add(row.legacy_id);
    }

    if (actor.role !== 'admin') {
      for (const row of rows) {
        if (!isObject(row) || row.centre_id !== actor.centre_id) fail('centre_denied', 403);
      }
    }

    const mongoSession = this.client.startSession();
    let result = { migrated: 0, skipped: 0 };
    try {
      await mongoSession.withTransaction(async () => {
        // A transaction callback can be retried by the driver after a
        // transient replica-set error.  Keep every attempt's counters and
        // normalized rows local so a retry cannot duplicate either in memory.
        normalized.length = 0;
        const attempt = { migrated: 0, skipped: 0 };
        const references = await this._referenceData(mongoSession);
        for (const row of rows) normalized.push(this._normalizeRecord(row, references));

        const sameBatch = new Map(normalized.map(row => [row._id, row]));
        for (const row of normalized) this._validateRelationships(row, references, sameBatch);

        if (batchId !== null) {
          const previousBatch = await this.db.collection('migration_batches').findOne(
            { _id: batchId },
            { session: mongoSession }
          );
          if (previousBatch) fail('duplicate_batch', 409);
        }

        const existing = new Map();
        if (normalized.length) {
          const existingDocuments = await this.db.collection('records').find(
            { _id: { $in: normalized.map(row => row._id) } },
            { session: mongoSession }
          ).toArray();
          for (const document of existingDocuments) existing.set(document._id, document);
        }

        const toInsert = [];
        for (const row of normalized) {
          const old = existing.get(row._id);
          if (old) {
            if (!this._equivalentRecord(old, row)) fail('record_conflict', 409);
            attempt.skipped += 1;
          } else {
            toInsert.push(row);
          }
        }

        if (batchId !== null) {
          await this.db.collection('migration_batches').insertOne({
            _id: batchId,
            record_ids: normalized.map(row => row._id),
            centre_ids: [...new Set(normalized.map(row => row.centre_id))]
          }, { session: mongoSession });
        }
        if (toInsert.length) {
          await this.db.collection('records').insertMany(toInsert, { session: mongoSession, ordered: true });
          attempt.migrated += toInsert.length;
        }
        result = attempt;
      });
    } finally {
      await mongoSession.endSession();
    }

    if (batchId !== null) result.batch_id = batchId;
    return result;
  }

  async addRecord(actor, input) {
    actor = await this._authorize(actor);
    if (actor.role === 'parent') fail('write_denied', 403);
    if (!isObject(input) || !nonEmptyString(input.id) || !nonEmptyString(input.module) ||
        !nonEmptyString(input.centre_id)) fail('invalid_record');
    if (actor.role !== 'admin' && input.centre_id !== actor.centre_id) {
      fail('centre_denied', 403);
    }

    const references = await this._referenceData();
    const relationshipIds = hasOwn(input, 'relationship_ids') ? input.relationship_ids :
      (input.child_id === undefined || input.child_id === null ? [] : [input.child_id]);
    const childId = input.child_id === undefined ? null : input.child_id;
    const normalized = this._normalizeRecord({
      legacy_id: input.id,
      record_type: input.module,
      centre_id: input.centre_id,
      relationship_ids: relationshipIds,
      child_id: childId,
      data: input.data
    }, references);
    this._validateRelationships(normalized, references, new Map());

    const records = this.db.collection('records');
    if (await records.findOne({ _id: normalized._id })) fail('record_conflict', 409);
    try {
      await records.insertOne(normalized);
    } catch (error) {
      if (error && error.code === 11000) fail('record_conflict', 409);
      throw error;
    }
    return { id: normalized._id };
  }

  async childAllowed(actor, childId) {
    if (!nonEmptyString(childId)) return false;
    const child = await this.db.collection('children').findOne({ _id: childId });
    if (!child) return false;
    if (actor.role === 'admin') return true;
    if (child.centre_id !== actor.centre_id) return false;
    if (actor.role === 'parent') {
      const user = await this.db.collection('users').findOne({ _id: actor.user_id });
      return !!(user && Array.isArray(user.child_ids) && user.child_ids.includes(childId));
    }
    return actor.role === 'staff';
  }

  async records(actor, module, childId, centreId) {
    actor = await this._authorize(actor);
    if (!MODULES.includes(module)) fail('unknown_module');
    if (actor.role === 'parent' && !PARENT_MODULES.has(module)) fail('module_denied', 403);

    const query = { record_type: module };
    if (actor.role === 'parent') {
      query.centre_id = actor.centre_id;
      const user = await this.db.collection('users').findOne({ _id: actor.user_id });
      const linkedIds = user && Array.isArray(user.child_ids) ? user.child_ids : [];
      const linkedChildren = linkedIds.length ? await this.db.collection('children').find(
        { _id: { $in: linkedIds }, centre_id: actor.centre_id },
        { projection: { _id: 1 } }
      ).toArray() : [];
      if (childId !== undefined) {
        if (!await this.childAllowed(actor, childId)) fail('child_denied', 403);
        query.child_id = childId;
      } else {
        query.child_id = { $in: linkedChildren.map(child => child._id) };
      }
    } else {
      if (actor.role !== 'admin') query.centre_id = actor.centre_id;
      if (centreId !== undefined) {
        if (!nonEmptyString(centreId) || !await this._centreExists(centreId)) fail('invalid_centre');
        if (actor.role !== 'admin' && centreId !== actor.centre_id) fail('centre_denied', 403);
        query.centre_id = centreId;
      }
      if (childId !== undefined) {
        if (!await this.childAllowed(actor, childId)) fail('child_denied', 403);
        query.child_id = childId;
      }
    }

    const documents = await this.db.collection('records').find(query).sort({ _id: 1 }).toArray();
    return documents.map(publicRecord);
  }

  async _centreExists(centreId) {
    return !!(await this.db.collection('centres').findOne({ _id: centreId }, { projection: { _id: 1 } }));
  }

  async parentView(actor, childId) {
    actor = await this._authorize(actor);
    if (actor.role !== 'parent') fail('view_denied', 403);
    if (!nonEmptyString(childId) || !await this.childAllowed(actor, childId)) {
      fail('child_denied', 403);
    }
    return {
      daily_chart: await this.records(actor, 'daily_chart', childId),
      curriculum: await this.records(actor, 'curriculum', childId)
    };
  }

  async send(actor, input) {
    actor = await this._authorize(actor);
    if (!isObject(input) || !nonEmptyString(input.message_id) ||
        !nonEmptyString(input.recipient_id) || !nonEmptyString(input.text) ||
        input.recipient_id === actor.user_id) fail('invalid_message');

    const recipient = await this.db.collection('users').findOne({ _id: input.recipient_id });
    if (!recipient || !Array.isArray(recipient.centre_ids) ||
        !recipient.centre_ids.includes(actor.centre_id)) fail('recipient_denied', 403);

    const incoming = {
      _id: input.message_id,
      sender_id: actor.user_id,
      recipient_id: input.recipient_id,
      centre_id: actor.centre_id,
      text: input.text
    };
    const messages = this.db.collection('messages');
    const sameMessage = document => document &&
      document._id === incoming._id &&
      document.sender_id === incoming.sender_id &&
      document.recipient_id === incoming.recipient_id &&
      document.centre_id === incoming.centre_id &&
      document.text === incoming.text;

    const existing = await messages.findOne({ _id: incoming._id });
    if (existing) {
      if (!sameMessage(existing)) fail('message_conflict', 409);
      return { duplicate: true };
    }

    try {
      await messages.insertOne(incoming);
    } catch (error) {
      if (error && error.code === 11000) {
        const raced = await messages.findOne({ _id: incoming._id });
        if (sameMessage(raced)) return { duplicate: true };
        fail('message_conflict', 409);
      }
      throw error;
    }
    return { duplicate: false };
  }

  async messages(actor) {
    actor = await this._authorize(actor);
    const documents = await this.db.collection('messages').find({
      centre_id: actor.centre_id,
      $or: [{ sender_id: actor.user_id }, { recipient_id: actor.user_id }]
    }).sort({ _id: 1 }).toArray();
    return documents.map(publicMessage);
  }
}

module.exports = { Portal, MODULES };
