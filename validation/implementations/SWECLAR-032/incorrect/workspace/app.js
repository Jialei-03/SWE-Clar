const h = React.createElement;

function savedAuth() {
  try {
    const value = JSON.parse(window.localStorage.getItem('centre-portal-session') || 'null');
    if (value && value.token && value.user) return value;
  } catch (_) {
    // A malformed browser value is not an authenticated session.
  }
  return null;
}

function App() {
  const [auth, setAuth] = React.useState(savedAuth);
  const [error, setError] = React.useState('');
  const [rows, setRows] = React.useState([]);
  const [module, setModule] = React.useState('daily_chart');
  const [messages, setMessages] = React.useState([]);
  const epoch = React.useRef(0);

  function remember(value) {
    setAuth(value);
    try {
      if (value) window.localStorage.setItem('centre-portal-session', JSON.stringify(value));
      else window.localStorage.removeItem('centre-portal-session');
    } catch (_) {
      // The API session remains authoritative if storage is unavailable.
    }
  }

  async function request(path, body) {
    const options = {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(auth ? { Authorization: 'Bearer ' + auth.token } : {})
      }
    };
    if (body !== undefined) options.body = JSON.stringify(body);
    const response = await fetch(path, options);
    let data;
    try {
      data = await response.json();
    } catch (_) {
      data = { error: 'invalid_response' };
    }
    if (!response.ok) throw Error(data.error || 'request_failed');
    return data;
  }

  async function loadRecords(selectedModule = module) {
    const mark = epoch.current;
    try {
      const result = await request('/api/records?module=' + encodeURIComponent(selectedModule));
      if (mark !== epoch.current) return;
      setRows(Array.isArray(result) ? result : []);
      setError('');
    } catch (caught) {
      if (mark === epoch.current) {
        setRows([]);
        setError(caught.message);
      }
    }
  }

  async function loadMessages() {
    const mark = epoch.current;
    try {
      const result = await request('/api/messages');
      if (mark !== epoch.current) return;
      setMessages(Array.isArray(result) ? result : []);
    } catch (caught) {
      if (mark === epoch.current) setError(caught.message);
    }
  }

  React.useEffect(() => {
    if (!auth) return;
    loadRecords();
    loadMessages();
  }, [auth, module]);

  const field = (label, name, type = 'text') => h(
    'label',
    { key: name },
    label,
    h('input', { name, type, required: true })
  );

  const submitLogin = async event => {
    event.preventDefault();
    const mark = ++epoch.current;
    try {
      const value = await request('/login', Object.fromEntries(new FormData(event.target)));
      if (mark !== epoch.current) return;
      remember(value);
      setError('');
    } catch (caught) {
      if (mark === epoch.current) setError(caught.message);
    }
  };

  const submitRecord = async event => {
    event.preventDefault();
    const mark = epoch.current;
    const value = Object.fromEntries(new FormData(event.target));
    try {
      await request('/api/records', {
        id: value.id,
        module,
        centre_id: auth.user.centre_id,
        child_id: value.child_id || null,
        data: { note: value.note }
      });
      event.target.reset();
      if (mark === epoch.current) await loadRecords();
    } catch (caught) {
      if (mark === epoch.current) setError(caught.message);
    }
  };

  const submitMessage = async event => {
    event.preventDefault();
    const mark = epoch.current;
    try {
      await request('/api/messages', Object.fromEntries(new FormData(event.target)));
      event.target.reset();
      if (mark !== epoch.current) return;
      await loadMessages();
      setError('');
    } catch (caught) {
      if (mark === epoch.current) setError(caught.message);
    }
  };

  if (!auth) {
    return h(
      'main',
      null,
      h('h1', null, 'Centre portal'),
      h('p', null, 'Synthetic operational records'),
      error && h('p', { role: 'alert', id: 'error' }, error),
      h('form', { id: 'login', onSubmit: submitLogin },
        field('User ID', 'user_id'),
        field('Centre ID', 'centre_id'),
        field('PIN', 'pin', 'password'),
        h('button', { type: 'submit' }, 'Sign in')
      )
    );
  }

  return h(
    'main',
    null,
    h('h1', null, 'Centre portal'),
    h('p', null, 'Synthetic operational records'),
    error && h('p', { role: 'alert', id: 'error' }, error),
    h('p', { id: 'identity' }, auth.user.id + ' · ' + auth.user.centre_id + ' · ' + auth.user.role),
    h('button', {
      type: 'button',
      onClick: () => {
        epoch.current++;
        remember(null);
        setRows([]);
        setMessages([]);
        setError('');
      }
    }, 'Sign out'),
    h('nav', null, ['daily_chart', 'curriculum', 'incident', 'attendance'].map(item => h(
      'button',
      {
        key: item,
        type: 'button',
        'data-module': item,
        onClick: () => {
          if (item !== module) {
            epoch.current++;
            setRows([]);
            setError('');
            setModule(item);
          }
        }
      },
      item.replaceAll('_', ' ')
    ))),
    h('h2', null, module.replaceAll('_', ' ')),
    h('section', { id: 'records' }, rows.length ? rows.map(row => h(
      'article',
      { key: row.id, 'data-record': row.id },
      h('h3', null, row.id),
      h('p', null, row.record_type + ' · ' + row.centre_id + (row.child_id ? ' · ' + row.child_id : '')),
      h('pre', null, JSON.stringify(row.data, null, 2))
    )) : h('p', { id: 'no-records' }, 'No records in this module.' )),
    auth.user.role !== 'parent' && h(
      'form',
      { id: 'create', onSubmit: submitRecord },
      field('Record ID', 'id'),
      field('Child ID', 'child_id'),
      field('Note', 'note'),
      h('button', { type: 'submit' }, 'Save record')
    ),
    h('h2', null, 'Messages'),
    h('form', { id: 'chat', onSubmit: submitMessage },
      field('Message ID', 'message_id'),
      field('Recipient ID', 'recipient_id'),
      field('Message', 'text'),
      h('button', { type: 'submit' }, 'Send message')
    ),
    h('section', { id: 'messages' }, messages.map(message => h(
      'p', { key: message.id, 'data-message': message.id },
      message.text
    )))
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(h(App));
