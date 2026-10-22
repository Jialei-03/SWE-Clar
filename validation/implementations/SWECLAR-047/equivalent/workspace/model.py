"""Notebook host and bookmark-domain operations, independent of transport.

The model deliberately keeps the host document and the bookmark workspace in
one JSON value.  Every public operation works on a deep copy and the HTTP
layer commits that copy only after the complete command has validated.  This
makes the error behaviour (including view-only commands) atomic while keeping
the representation easy to inspect in SQLite.
"""
import copy
import re


class Rejected(ValueError):
    """A client command which cannot be applied."""


_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def require(condition, code="invalid_command"):
    if not condition:
        raise Rejected(code)


def identifier(value):
    """Validate and return an item/tab identifier."""
    require(isinstance(value, str) and _ID.fullmatch(value) is not None)
    return value


def label(value):
    """Validate a user-visible label and return its trimmed form."""
    require(isinstance(value, str) and 1 <= len(value.strip()) <= 120)
    return value.strip()


def initial():
    nodes = [
        ("BOOK-A", None, "notebook", "Field journal"),
        ("GROUP-A", "BOOK-A", "group", "Practice"),
        ("SECTION-A", "GROUP-A", "section", "Experiments"),
        ("PAGE-A", "SECTION-A", "page", "Paper bridge"),
        ("PAR-A", "PAGE-A", "paragraph", "Fold a strip into three equal panels."),
        ("PAR-B", "PAGE-A", "paragraph", "Record the load after each trial."),
        ("PAGE-B", "SECTION-A", "page", "Color wheel"),
        ("PAR-C", "PAGE-B", "paragraph", "Mix the three sample colors."),
        ("BOOK-B", None, "notebook", "Reading journal"),
        ("SECTION-B", "BOOK-B", "section", "Ideas"),
        ("PAGE-C", "SECTION-B", "page", "Sketch notes"),
        ("PAR-D", "PAGE-C", "paragraph", "Draw the route using simple shapes."),
    ]
    return {
        "document": [{"id": i, "parent": p, "kind": k, "text": t} for i, p, k, t in nodes],
        "current": "PAR-A",
        "state": {
            "tabs": [{"id": "HOME", "name": "Bookmarks", "items": []}],
            "active_tab": "HOME",
            "expanded": [],
            "width": 280,
            "wrap": False,
        },
    }


def walk(items):
    """Yield every item in display/tree order without a depth limit."""
    stack = list(reversed(items))
    while stack:
        item = stack.pop()
        yield item
        if item.get("kind") == "folder":
            stack.extend(reversed(item["children"]))


def _find(items, key):
    """Find an item and its direct sibling list without recursive descent."""
    stack = [(item, items) for item in reversed(items)]
    while stack:
        item, siblings = stack.pop()
        if item["id"] == key:
            return item, siblings
        if item.get("kind") == "folder":
            stack.extend((child, item["children"]) for child in reversed(item["children"]))
    return None


def locate(state, key):
    """Find an item and its direct sibling list across all tabs."""
    # A malformed identifier is a malformed command; a well-formed unknown
    # identifier is a missing item.  The latter is useful to callers which
    # need to distinguish stale UI state from bad JSON.
    if key is not None:
        require(isinstance(key, str) and _ID.fullmatch(key) is not None)
    for tab in state["tabs"]:
        found = _find(tab["items"], key)
        if found is not None:
            return found
    raise Rejected("missing_item")


def locate_in_tab(state, tab_id, key):
    """Find an item only in one tab, returning ``None`` when absent."""
    tab = tab_by_id(state, tab_id)
    return _find(tab["items"], key)


def tab_by_id(state, key):
    """Return a tab or reject with the public missing-tab error."""
    # A missing field and an unknown well-formed tab have the same useful
    # domain error.  Invalid shaped identifiers remain invalid commands.
    if key is not None:
        require(isinstance(key, str) and _ID.fullmatch(key) is not None)
    for tab in state["tabs"]:
        if tab["id"] == key:
            return tab
    raise Rejected("missing_tab")


def _destination_tab(state, command):
    value = command.get("tab_id")
    # Creation/sorting use the active tab when the optional field is absent.
    # Treating explicit null the same way is friendly to JSON clients and is
    # consistent with parent_id's null-as-root convention.
    if value is None:
        value = state["active_tab"]
    return tab_by_id(state, value)


def items_in(state, tab_id, parent_id):
    """Return a direct child list, enforcing the parent/tab boundary."""
    tab = tab_by_id(state, tab_id)
    if parent_id is None:
        return tab["items"]
    # A parent is a tree item, not a host object.  An absent or malformed
    # parent is reported as invalid_parent for creation/sorting commands;
    # move has its own missing-parent distinction below.
    require(isinstance(parent_id, str) and _ID.fullmatch(parent_id) is not None, "invalid_parent")
    found = _find(tab["items"], parent_id)
    require(found is not None, "invalid_parent")
    item, _ = found
    require(item["kind"] == "folder", "invalid_parent")
    return item["children"]


def node_by_id(data, key):
    """Find a real host node; arbitrary/unknown target IDs never get made up."""
    for node in data["document"]:
        if node["id"] == key:
            return node
    raise Rejected("missing_target")


def unique(state, key):
    """Check the global item/tab namespace."""
    identifier(key)
    for tab in state["tabs"]:
        if tab["id"] == key:
            raise Rejected("duplicate_id")
        if any(item["id"] == key for item in walk(tab["items"])):
            raise Rejected("duplicate_id")


def _descendant_ids(item):
    if item.get("kind") != "folder":
        return set()
    return {child["id"] for child in walk(item["children"])}


def _move(state, command):
    """Apply a validated ordered-subtree move to ``state``.

    Validation is intentionally completed before touching any sibling list.
    The references collected here point into the deep-copied candidate state,
    so a failed command cannot leak a partial mutation to the caller.
    """
    ids = command.get("ids")
    require(isinstance(ids, list) and len(ids) > 0)
    # Do shape validation before set()/duplicate checks so non-string JSON
    # values cannot turn into a server exception.
    for key in ids:
        require(isinstance(key, str) and _ID.fullmatch(key) is not None)
    if len(set(ids)) != len(ids):
        raise Rejected("duplicate_selection")

    # A move has an explicit destination tab.  Do not silently activate or
    # infer a different tab for it.
    destination_tab_id = command.get("tab_id")
    destination_tab = tab_by_id(state, destination_tab_id)

    selected = []
    for key in ids:
        selected.append((key, *locate(state, key)))

    selected_ids = set(ids)
    for _, item, _siblings in selected:
        if _descendant_ids(item) & selected_ids:
            raise Rejected("overlapping_selection")

    parent_id = command.get("parent_id")
    if parent_id is None:
        destination = destination_tab["items"]
        destination_parent = None
    else:
        # A stale/missing destination item is a missing item.  An item in a
        # different tab, or an existing non-folder, is an invalid parent.
        require(isinstance(parent_id, str) and _ID.fullmatch(parent_id) is not None, "invalid_parent")
        parent_found = locate(state, parent_id)
        destination_parent, _parent_siblings = parent_found
        require(destination_parent["kind"] == "folder", "invalid_parent")

        # The destination cannot be an item being moved or below a moved
        # folder.  This is checked after proving it is a folder so a bookmark
        # still receives the more useful invalid_parent error.
        if parent_id in selected_ids or any(
            parent_id in _descendant_ids(item) for _, item, _ in selected
        ):
            raise Rejected("cyclic_move")

        in_destination_tab = locate_in_tab(state, destination_tab_id, parent_id)
        require(in_destination_tab is not None, "invalid_parent")
        destination = destination_parent["children"]

    # The insertion index is measured after every selected direct child of
    # the destination has been removed.  This is what makes same-parent
    # reordering predictable.
    direct_removals = sum(1 for _, _item, siblings in selected if siblings is destination)
    remaining_length = len(destination) - direct_removals
    if "index" in command:
        index = command["index"]
        require(type(index) is int and 0 <= index <= remaining_length, "invalid_index")
    else:
        index = remaining_length

    # All validation is complete.  Remove each selected root once, retaining
    # the supplied selection order for insertion rather than source order.
    moving = [item for _, item, _siblings in selected]
    for _key, item, siblings in selected:
        siblings.remove(item)
    destination[index:index] = moving


def move(state, command):
    """Compatibility entry point for applying a move to a candidate state."""
    return _move(state, command)


def apply(data, command):
    """Return the result of one bookmark/view command or raise ``Rejected``."""
    require(isinstance(command, dict))
    candidate = copy.deepcopy(data)
    state = candidate["state"]
    action = command.get("type")

    if action in ("folder", "bookmark"):
        key = command.get("id")
        unique(state, key)
        tab = _destination_tab(state, command)
        items = items_in(state, tab["id"], command.get("parent_id"))
        if action == "folder":
            item = {
                "id": key,
                "kind": "folder",
                "label": label(command.get("label")),
                "children": [],
            }
        else:
            target = node_by_id(candidate, command.get("target_id"))
            if "label" in command:
                shown = label(command["label"])
            else:
                shown = target["text"].strip()[:120] or "Untitled"
            item = {
                "id": key,
                "kind": "bookmark",
                "label": shown,
                "target_id": target["id"],
                "target_type": target["kind"],
            }
        items.append(item)

    elif action == "rename":
        item, _siblings = locate(state, command.get("id"))
        item["label"] = label(command.get("label"))

    elif action == "delete":
        item, siblings = locate(state, command.get("id"))
        require(command.get("confirmed") is True, "confirmation_required")
        descendants = list(walk(item["children"])) if item["kind"] == "folder" else []
        require(not descendants or command.get("recursive") is True, "folder_not_empty")
        removed = {item["id"]} | {child["id"] for child in descendants}
        siblings.remove(item)
        state["expanded"] = [key for key in state["expanded"] if key not in removed]

    elif action == "tab":
        key = command.get("id")
        unique(state, key)
        state["tabs"].append({"id": key, "name": label(command.get("name")), "items": []})

    elif action == "activate":
        state["active_tab"] = tab_by_id(state, command.get("id"))["id"]

    elif action == "move":
        move(state, command)

    elif action == "sort":
        tab = _destination_tab(state, command)
        items = items_in(state, tab["id"], command.get("parent_id"))
        folders = sorted(
            (item for item in items if item["kind"] == "folder"),
            key=lambda item: item["label"].casefold(),
        )
        # Bookmark order is intentionally untouched.  Python's sorted is
        # stable, so equal-folded folder labels retain their prior order.
        bookmarks = [item for item in items if item["kind"] == "bookmark"]
        items[:] = folders + bookmarks

    elif action == "view":
        # Validate every supplied preference before assigning any of them.
        if "width" in command:
            width = command["width"]
            require(type(width) is int and 180 <= width <= 480)
        if "wrap" in command:
            wrap = command["wrap"]
            require(type(wrap) is bool)
        if "expanded" in command:
            values = command["expanded"]
            require(isinstance(values, list))
            require(all(isinstance(key, str) for key in values))
            require(len(values) == len(set(values)))
            for key in values:
                item, _siblings = locate(state, key)
                require(item["kind"] == "folder", "invalid_parent")
            expanded = values[:]
        if "width" in command:
            state["width"] = width
        if "wrap" in command:
            state["wrap"] = wrap
        if "expanded" in command:
            state["expanded"] = expanded

    elif action == "open":
        item, _siblings = locate(state, command.get("id"))
        require(item["kind"] == "bookmark", "not_bookmark")
        candidate["current"] = node_by_id(candidate, item["target_id"])["id"]

    else:
        raise Rejected("invalid_command")

    return candidate


def host(data, command):
    """Return the result of one host navigation/edit command."""
    require(isinstance(command, dict))
    candidate = copy.deepcopy(data)
    node = node_by_id(candidate, command.get("id"))
    if command.get("type") == "navigate":
        candidate["current"] = node["id"]
    elif command.get("type") == "edit":
        text = command.get("text")
        require(node["kind"] == "paragraph" and isinstance(text, str) and len(text) <= 4000)
        node["text"] = text
    else:
        raise Rejected("invalid_command")
    return candidate
