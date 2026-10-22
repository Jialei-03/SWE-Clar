let code = '';
let context = null;

const el = (id) => document.getElementById(id);

async function request(path, body) {
    const options = {
        method: body ? 'POST' : 'GET',
        headers: {
            Authorization: `Bearer ${code}`,
            'Content-Type': 'application/json',
        },
    };
    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(`/api/${path}`, options);
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error?.code || 'request_failed');
    }
    return data;
}

function options(select, values) {
    const children = values.map((value) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        return option;
    });
    select.replaceChildren(...children);
}

function streets() {
    const community = el('community').value;
    options(el('street'), context.communities[community] || []);
}

function renderRecords() {
    const records = el('records');
    const fragment = document.createDocumentFragment();

    for (const record of context.inspections) {
        const row = document.createElement('article');
        row.dataset.id = record.id;

        const text = document.createElement('p');
        text.textContent = [
            record.id,
            record.community,
            record.street,
            record.residence,
            record.status,
        ].join(' · ');
        row.append(text);

        if (context.role === 'admin' && record.status === 'open') {
            const button = document.createElement('button');
            button.textContent = 'Delete';
            button.onclick = () => perform({ type: 'delete', id: record.id });
            row.append(button);
        }
        fragment.append(row);
    }

    records.replaceChildren(fragment);
}

async function refresh() {
    const selected = el('community').value;
    context = await request('context');
    options(el('community'), Object.keys(context.communities));
    if (selected in context.communities) {
        el('community').value = selected;
    }
    streets();
    renderRecords();
    el('workspace').hidden = false;
}

async function perform(action) {
    try {
        const data = await request('command', action);
        el('message').textContent = 'Saved';
        if (action.type === 'report') {
            el('summary').textContent =
                `Total ${data.result.total} · Open ${data.result.by_status.open} · ` +
                `Closed ${data.result.by_status.closed}`;
        } else {
            await refresh();
        }
    } catch (error) {
        el('message').textContent = error.message;
    }
}

el('login').onsubmit = async (event) => {
    event.preventDefault();
    code = el('access-code').value;
    try {
        await refresh();
        el('login').hidden = true;
        el('message').textContent = 'Signed in';
    } catch (error) {
        el('message').textContent = error.message;
    }
};

el('community').onchange = streets;
el('create').onsubmit = (event) => {
    event.preventDefault();
    perform({
        type: 'create',
        id: el('inspection-id').value,
        community: el('community').value,
        street: el('street').value,
        residence: el('residence').value,
    });
};
el('report').onclick = () => perform({
    type: 'report',
    community: el('community').value,
});
