import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';

let token = '';
let generation = 0;
let objectURL = '';
let floor = 0;

// The media element is intentionally a real browser audio element rather than
// a play-state mock.  The server only gives it bytes after authorization.
const audio = new Audio();
audio.dataset.player = 'stream';
audio.controls = true;
audio.preload = 'metadata';
audio.setAttribute('aria-label', 'Streaming player');
document.body.append(audio);

audio.addEventListener('timeupdate', () => {
  if (!audio.seeking && Number.isFinite(audio.currentTime)) {
    floor = Math.max(floor, audio.currentTime);
  }
});
audio.addEventListener('seeking', () => {
  if (!Number.isFinite(audio.currentTime)) return;
  if (audio.currentTime < floor - 0.1) {
    audio.currentTime = floor;
  } else {
    floor = Math.max(floor, audio.currentTime);
  }
});

async function api(path, data) {
  const response = await fetch(path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + token,
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  let result;
  try {
    result = await response.json();
  } catch (_error) {
    throw Error('request_failed');
  }
  if (!response.ok) throw Error(result.error || 'request_failed');
  return result;
}

function clearPlayer() {
  generation += 1;
  audio.pause();
  audio.removeAttribute('src');
  audio.load();
  if (objectURL) URL.revokeObjectURL(objectURL);
  objectURL = '';
  floor = 0;
}

function App() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [user, setUser] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [licenses, setLicenses] = useState([]);
  const [query, setQuery] = useState('');
  const [transaction, setTransaction] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');

  const act = (operation) => async () => {
    setError('');
    try {
      await operation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'request_failed');
    }
  };

  async function refresh() {
    const [account, catalog, owned] = await Promise.all([
      api('/me'),
      api('/catalog?q=' + encodeURIComponent(query)),
      api('/licenses'),
    ]);
    setUser(account);
    setTracks(catalog);
    setLicenses(owned);
  }

  async function login() {
    const result = await api('/login', { email, password });
    token = result.token;
    await refresh();
  }

  async function play(track) {
    clearPlayer();
    const requestGeneration = ++generation;
    setStatus('Loading');
    const response = await fetch('/media/' + encodeURIComponent(track.id), {
      headers: { Authorization: 'Bearer ' + token },
    });
    if (!response.ok) throw Error('not_licensed');
    const blob = await response.blob();
    if (requestGeneration !== generation) return;
    objectURL = URL.createObjectURL(blob);
    audio.src = objectURL;
    await audio.play();
    setStatus('Playing');
  }

  return (
    <main>
      <h1>Listening library</h1>
      {!user ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            act(login)();
          }}
        >
          <label>
            Email
            <input
              aria-label="Email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              aria-label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <button type="submit">Sign in</button>
          <button
            type="button"
            onClick={act(async () => {
              await api('/register', { email, password });
              await login();
            })}
          >
            Register
          </button>
        </form>
      ) : (
        <>
          <p>Account: {user.email}</p>
          <p data-testid="balance">Tokens: {user.balance}</p>
          <button
            onClick={act(async () => {
              await api('/logout', {});
              clearPlayer();
              token = '';
              setUser(null);
              setTracks([]);
              setLicenses([]);
              setStatus('');
            })}
          >
            Sign out
          </button>

          <section>
            <h2>Add tokens</h2>
            <label>
              Local transaction
              <input
                aria-label="Local transaction"
                value={transaction}
                onChange={(event) => setTransaction(event.target.value)}
              />
            </label>
            <button
              onClick={act(async () => {
                await api('/credit', { transaction_id: transaction });
                await refresh();
              })}
            >
              Confirm purchase
            </button>
          </section>

          <section>
            <h2>Catalog</h2>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                act(refresh)();
              }}
            >
              <label>
                Search
                <input
                  aria-label="Search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <button type="submit">Search catalog</button>
            </form>
            <ul>
              {tracks.map((track) => {
                const owned = licenses.includes(track.id);
                return (
                  <li key={track.id}>
                    <h3>{track.title}</h3>
                    <p>{track.artist}</p>
                    <button
                      data-testid={'unlock-' + track.id}
                      onClick={act(async () => {
                        await api('/license', { track: track.id });
                        await refresh();
                      })}
                    >
                      Unlock {track.cost} tokens
                    </button>
                    {owned && <span aria-label="Licensed"> Licensed</span>}
                    <button
                      data-testid={'play-' + track.id}
                      onClick={act(() => play(track))}
                    >
                      Play
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          <section>
            <h2>Player</h2>
            <p role="status">{status}</p>
            <button
              onClick={() => {
                generation += 1;
                if (Number.isFinite(audio.currentTime)) {
                  floor = Math.max(floor, audio.currentTime);
                }
                audio.pause();
                setStatus('Paused');
              }}
            >
              Pause
            </button>
            <button
              onClick={act(async () => {
                await audio.play();
                setStatus('Playing');
              })}
            >
              Resume
            </button>
          </section>
        </>
      )}
      <p role="alert">{error}</p>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
