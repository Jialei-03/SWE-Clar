"""Notebook host and bookmark-domain operations, independent of transport."""
import copy
import re


class Rejected(ValueError):
    pass


def require(condition, code='invalid_command'):
    if not condition: raise Rejected(code)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value))
    return value


def label(value):
    require(isinstance(value, str) and 1 <= len(value.strip()) <= 120)
    return value.strip()


def initial():
    nodes = [
        ('BOOK-A', None, 'notebook', 'Field journal'),
        ('GROUP-A', 'BOOK-A', 'group', 'Practice'),
        ('SECTION-A', 'GROUP-A', 'section', 'Experiments'),
        ('PAGE-A', 'SECTION-A', 'page', 'Paper bridge'),
        ('PAR-A', 'PAGE-A', 'paragraph', 'Fold a strip into three equal panels.'),
        ('PAR-B', 'PAGE-A', 'paragraph', 'Record the load after each trial.'),
        ('PAGE-B', 'SECTION-A', 'page', 'Color wheel'),
        ('PAR-C', 'PAGE-B', 'paragraph', 'Mix the three sample colors.'),
        ('BOOK-B', None, 'notebook', 'Reading journal'),
        ('SECTION-B', 'BOOK-B', 'section', 'Ideas'),
        ('PAGE-C', 'SECTION-B', 'page', 'Sketch notes'),
        ('PAR-D', 'PAGE-C', 'paragraph', 'Draw the route using simple shapes.'),
    ]
    return {'document': [{'id': i, 'parent': p, 'kind': k, 'text': t} for i, p, k, t in nodes],
            'current': 'PAR-A', 'state': {'tabs': [{'id': 'HOME', 'name': 'Bookmarks', 'items': []}],
            'active_tab': 'HOME', 'expanded': [], 'width': 280, 'wrap': False}}


def walk(items):
    for item in items:
        yield item
        if item['kind'] == 'folder': yield from walk(item['children'])


def locate(state, key):
    def visit(items):
        for item in items:
            if item['id'] == key: return item, items
            if item['kind'] == 'folder':
                found = visit(item['children'])
                if found: return found
    for tab in state['tabs']:
        found = visit(tab['items'])
        if found: return found
    raise Rejected('missing_item')


def tab_by_id(state, key):
    for tab in state['tabs']:
        if tab['id'] == key: return tab
    raise Rejected('missing_tab')


def items_in(state, tab_id, parent_id):
    tab = tab_by_id(state, tab_id)
    if parent_id is None: return tab['items']
    for item in walk(tab['items']):
        if item['id'] == parent_id:
            require(item['kind'] == 'folder', 'invalid_parent')
            return item['children']
    raise Rejected('invalid_parent')


def node_by_id(data, key):
    for node in data['document']:
        if node['id'] == key: return node
    raise Rejected('missing_target')


def unique(state, key):
    identifier(key)
    require(all(tab['id'] != key and all(x['id'] != key for x in walk(tab['items']))
                for tab in state['tabs']), 'duplicate_id')


def move(state, command):
    # Destination and selection policies are awaiting the extension implementation.
    return


def apply(data, command):
    require(isinstance(command, dict))
    data = copy.deepcopy(data)
    state = data['state']; action = command.get('type')
    if action in ('folder', 'bookmark'):
        key = command.get('id'); unique(state, key)
        items = items_in(state, command.get('tab_id', state['active_tab']), command.get('parent_id'))
        if action == 'folder': item = {'id': key, 'kind': 'folder', 'label': label(command.get('label')), 'children': []}
        else:
            target = node_by_id(data, command.get('target_id'))
            item = {'id': key, 'kind': 'bookmark', 'label': label(command.get('label', target['text'].strip()[:120] or 'Untitled')),
                    'target_id': target['id'], 'target_type': target['kind']}
        items.append(item)
    elif action == 'rename':
        item, _ = locate(state, command.get('id')); item['label'] = label(command.get('label'))
    elif action == 'delete':
        item, siblings = locate(state, command.get('id'))
        require(command.get('confirmed') is True, 'confirmation_required')
        descendants = list(walk(item['children'])) if item['kind'] == 'folder' else []
        require(not descendants or command.get('recursive') is True, 'folder_not_empty')
        removed = {item['id']} | {x['id'] for x in descendants}
        siblings.remove(item); state['expanded'] = [x for x in state['expanded'] if x not in removed]
    elif action == 'tab':
        key = command.get('id'); unique(state, key)
        state['tabs'].append({'id': key, 'name': label(command.get('name')), 'items': []})
    elif action == 'activate':
        state['active_tab'] = tab_by_id(state, command.get('id'))['id']
    elif action == 'move': move(state, command)
    elif action == 'sort':
        items = items_in(state, command.get('tab_id', state['active_tab']), command.get('parent_id'))
        folders = sorted((x for x in items if x['kind'] == 'folder'), key=lambda x: x['label'].casefold())
        # Folder-order policy is not yet applied.
    elif action == 'view':
        if 'width' in command:
            require(type(command['width']) is int and 180 <= command['width'] <= 480)
            # Width preference is not yet applied.
        if 'wrap' in command:
            require(type(command['wrap']) is bool); # Wrap preference is not yet applied.
        if 'expanded' in command:
            values = command['expanded']; require(isinstance(values, list) and all(isinstance(x, str) for x in values))
            require(len(values) == len(set(values)))
            for key in values: require(locate(state, key)[0]['kind'] == 'folder', 'invalid_parent')
            state['expanded'] = values[:]
    elif action == 'open':
        item, _ = locate(state, command.get('id')); require(item['kind'] == 'bookmark', 'not_bookmark')
        data['current'] = node_by_id(data, item['target_id'])['id']
    else: raise Rejected('invalid_command')
    return data


def host(data, command):
    require(isinstance(command, dict)); data = copy.deepcopy(data)
    node = node_by_id(data, command.get('id'))
    if command.get('type') == 'navigate': data['current'] = node['id']
    elif command.get('type') == 'edit':
        require(node['kind'] == 'paragraph' and isinstance(command.get('text'), str) and len(command['text']) <= 4000)
        node['text'] = command['text']
    else: raise Rejected('invalid_command')
    return data
