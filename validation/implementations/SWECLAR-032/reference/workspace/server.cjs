'use strict';

const express = require('express');
const { MongoClient } = require('mongodb');
const fs = require('node:fs/promises');
const path = require('node:path');
const { Portal } = require('./portal.cjs');

(async () => {
  const client = new MongoClient(process.env.MONGODB_URI);
  await client.connect();
  const bootstrap = JSON.parse(await fs.readFile(process.env.PORTAL_BOOTSTRAP, 'utf8'));
  const portal = new Portal(client, client.db(process.env.PORTAL_DATABASE), bootstrap);
  await portal.initialize();

  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '1mb' }));

  // Deliberately enumerate portal assets.  This avoids exposing bootstrap,
  // server source, runtime configuration, or arbitrary database files.
  const assets = {
    '/': 'index.html',
    '/app.js': 'app.js',
    '/style.css': 'style.css',
    '/vendor/react.production.min.js': 'vendor/react.production.min.js',
    '/vendor/react-dom.production.min.js': 'vendor/react-dom.production.min.js'
  };
  for (const [url, file] of Object.entries(assets)) {
    app.get(url, (request, response) => response.sendFile(path.join(__dirname, file)));
  }

  app.post('/login', async (request, response) => {
    response.json(await portal.login(request.body));
  });

  app.use('/api', async (request, response, next) => {
    try {
      const header = request.get('Authorization') || '';
      const token = header.startsWith('Bearer ') ? header.slice(7) : null;
      request.actor = await portal.session(token);
      next();
    } catch (error) {
      next(error);
    }
  });

  app.post('/api/migrate', async (request, response) => {
    // Passing the complete object also permits an optional batch_id without
    // changing the long-standing Portal.migrate(session, rows) array form.
    response.json(await portal.migrate(request.actor, request.body));
  });
  app.post('/api/records', async (request, response) => {
    response.json(await portal.addRecord(request.actor, request.body));
  });
  app.get('/api/records', async (request, response) => {
    response.json(await portal.records(
      request.actor,
      request.query.module,
      request.query.child_id,
      request.query.centre_id
    ));
  });
  app.get('/api/parent-view', async (request, response) => {
    response.json(await portal.parentView(request.actor, request.query.child_id));
  });
  app.post('/api/messages', async (request, response) => {
    response.json(await portal.send(request.actor, request.body));
  });
  app.get('/api/messages', async (request, response) => {
    response.json(await portal.messages(request.actor));
  });

  app.use((request, response) => response.sendStatus(404));
  app.use((error, request, response, next) => {
    if (response.headersSent) return next(error);
    const duplicate = error && error.code === 11000;
    const status = duplicate ? 409 :
      (Number.isInteger(error && error.status) ? error.status : 400);
    const exposed = error && error.status ? error.message : 'invalid_request';
    response.status(status).json({ error: exposed });
  });

  const server = app.listen(Number(process.env.PORT || 0), '127.0.0.1', () => {
    console.log(JSON.stringify({ port: server.address().port }));
  });

  const close = signal => {
    server.close(async () => {
      await client.close();
      process.exit(0);
    });
    // Keep the signal argument intentionally unused; close is graceful.
    void signal;
  };
  process.on('SIGTERM', close);
  process.on('SIGINT', close);
})().catch(error => {
  console.error(error && error.message ? error.message : error);
  process.exit(1);
});
