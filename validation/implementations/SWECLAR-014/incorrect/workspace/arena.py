"""Authoritative in-memory grid arena for the local multiplayer service."""

import copy
import json
from pathlib import Path
import re
import secrets
import threading
import time


class Conflict(Exception):
    """An expected HTTP/business error."""

    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def reject(status, code):
    raise Conflict(status, code)


_COMMAND_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_DIRECTIONS = {
    "left": (-1, 0),
    "right": (1, 0),
    "up": (0, -1),
    "down": (0, 1),
}


class Arena:
    """One ephemeral, process-local arena instance.

    All player/session mutations and state snapshots use ``lock``.  The HTTP
    server may dispatch requests on many threads, so the lock is also the
    serialization point for commands and for process-local snapshot sequence
    numbers.
    """

    PROTECTION_MS = 6000
    MAX_HP = 3

    def __init__(self, world, clock_file):
        self.rooms = {room["id"]: copy.deepcopy(room) for room in world["rooms"]}
        self.clock_file = Path(clock_file)
        self.players = {}       # player id -> authoritative player record
        self.sessions = {}      # bearer token -> player id
        # A command is keyed by actor, the generation supplied by the caller,
        # and command id.  Move and respawn consequently share one namespace.
        self.commands = {}
        self.seq = 0
        self.lock = threading.RLock()

    def now(self):
        """Read the manager-owned transaction clock without modifying it."""
        clock = json.loads(self.clock_file.read_text(encoding="utf-8"))
        if clock.get("mode") == "realtime":
            return time.time_ns() // 1_000_000
        value = clock.get("now_ms")
        if type(value) is not int or value < 0:
            raise ValueError("Invalid benchmark clock")
        return value

    def catalog(self):
        # Room definitions are immutable after construction, but copy the
        # externally visible values so a caller cannot mutate the world.
        with self.lock:
            return {
                "rooms": [
                    {key: copy.deepcopy(room[key]) for key in ("id", "label", "cols", "rows")}
                    for room in self.rooms.values()
                ]
            }

    def actor(self, token):
        """Return the session's player or raise the protocol 401 error."""
        player_id = self.sessions.get(token)
        if player_id is None or player_id not in self.players:
            reject(401, "unauthenticated")
        return self.players[player_id]

    def free_spawn(self, room_id):
        """Select the first listed spawn point not occupied by a live player."""
        occupied = {
            (player["x"], player["y"])
            for player in self.players.values()
            if player["room_id"] == room_id and player["alive"]
        }
        for point in self.rooms[room_id]["spawn_points"]:
            x, y = point
            if (x, y) not in occupied:
                return x, y
        reject(409, "conflict")

    def _new_spawn(self, player, now, position, generation):
        player.update(
            x=position[0],
            y=position[1],
            hp=self.MAX_HP,
            alive=True,
            generation=generation,
            spawn_ms=now,
            protected_until_ms=now + self.PROTECTION_MS,
        )

    def snapshot(self, actor, now):
        """Build an immutable-by-convention state while holding ``lock``."""
        self.seq += 1
        room = self.rooms[actor["room_id"]]
        visible_room = {
            key: copy.deepcopy(room[key])
            for key in ("id", "label", "cols", "rows", "walls")
        }
        visible_players = []
        for player in self.players.values():
            if player["room_id"] != actor["room_id"]:
                continue
            visible_players.append(
                {
                    key: copy.deepcopy(player[key])
                    for key in (
                        "id",
                        "label",
                        "x",
                        "y",
                        "hp",
                        "alive",
                        "generation",
                        "spawn_ms",
                        "protected_until_ms",
                    )
                }
            )
        return {
            "room": visible_room,
            "seq": self.seq,
            "server_now_ms": now,
            "players": visible_players,
        }

    def join(self, body):
        room_id = body.get("room_id")
        label = body.get("label")
        if (
            not isinstance(room_id, str)
            or not isinstance(label, str)
            or not 1 <= len(label.strip()) <= 40
        ):
            reject(400, "invalid_request")
        try:
            # JSON can spell an unpaired surrogate even though it is not a
            # UTF-8 Unicode code point and cannot be rendered in a response.
            label.encode("utf-8")
        except UnicodeEncodeError:
            reject(400, "invalid_request")

        with self.lock:
            if room_id not in self.rooms:
                reject(404, "not_found")
            # Spawn selection and insertion are one critical section, so two
            # simultaneous joins cannot receive the same point.
            position = self.free_spawn(room_id)
            now = self.now()
            player_id = "player_" + secrets.token_hex(16)
            player = {
                "id": player_id,
                "room_id": room_id,
                "label": label.strip(),
            }
            self._new_spawn(player, now, position, 1)
            token = secrets.token_hex(32)
            self.players[player_id] = player
            self.sessions[token] = player_id
            return {
                "token": token,
                "player_id": player_id,
                "state": self.snapshot(player, now),
            }

    def state(self, token):
        with self.lock:
            actor = self.actor(token)
            return {"state": self.snapshot(actor, self.now())}

    def leave(self, token):
        with self.lock:
            actor = self.actor(token)
            player_id = actor["id"]
            # Invalidation happens while holding the same lock as command
            # dispatch, making leave and a simultaneous command deterministic.
            del self.sessions[token]
            del self.players[player_id]
            self.commands = {
                key: value for key, value in self.commands.items() if key[0] != player_id
            }
            return {"ok": True}

    @staticmethod
    def protected(player, now):
        """Whether server time is strictly before this live player's deadline."""
        return bool(player["alive"] and now < player["protected_until_ms"])

    def move_player(self, actor, direction, now):
        if not actor["alive"]:
            reject(409, "conflict")

        dx, dy = _DIRECTIONS[direction]
        x, y = actor["x"] + dx, actor["y"] + dy
        room = self.rooms[actor["room_id"]]
        # Outside the rectangle is a wall.  A blocked move is still a valid,
        # committed command, but has no health or position effect.
        if not (0 <= x < room["cols"] and 0 <= y < room["rows"]):
            return
        if [x, y] in room["walls"]:
            return

        for other in self.players.values():
            if (
                other["id"] != actor["id"]
                and other["room_id"] == actor["room_id"]
                and other["alive"]
                and (other["x"], other["y"]) == (x, y)
            ):
                # Protection is evaluated by the transaction clock.  It is
                # enough for either live participant to be protected to allow
                # the move, including temporary overlap.
                if self.protected(actor, now) or self.protected(other, now):
                    continue
                actor["hp"] -= 1
                if actor["hp"] <= 0:
                    actor["hp"] = 0
                    actor["alive"] = False
                return

        actor.update(x=x, y=y)

    @staticmethod
    def _valid_command_fields(operation, body):
        generation = body.get("generation")
        command_id = body.get("command_id")
        if (
            type(generation) is not int
            or generation < 1
            or not isinstance(command_id, str)
            or _COMMAND_ID.fullmatch(command_id) is None
        ):
            reject(400, "invalid_request")
        direction = None
        if operation == "move":
            direction = body.get("direction")
            if direction not in _DIRECTIONS:
                reject(400, "invalid_request")
        return generation, command_id, direction

    def _replay_or_reject(self, actor, operation, generation, command_id, direction):
        """Return True if a committed command was replayed.

        Replay lookup occurs only after all public field types/values have been
        validated.  A replay is a new state snapshot, so it gets a new seq and
        current clock value, but it never repeats its original mutation.
        """
        key = (actor["id"], generation, command_id)
        entry = self.commands.get(key)
        if entry is None:
            return False

        if entry["operation"] != operation or entry.get("direction") != direction:
            reject(409, "conflict")

        # Normal commands can replay while their original generation remains
        # current.  A successful respawn is the one intentional exception:
        # its original generation is replaced by exactly the generation it
        # produced, and the original request remains replayable in that state.
        replayable = actor["generation"] == generation
        if operation == "respawn":
            replayable = replayable or entry["produced_generation"] == actor["generation"]
        if not replayable:
            reject(409, "conflict")
        return True

    def command(self, token, operation, body):
        with self.lock:
            actor = self.actor(token)
            generation, command_id, direction = self._valid_command_fields(operation, body)

            if self._replay_or_reject(actor, operation, generation, command_id, direction):
                return {"state": self.snapshot(actor, self.now())}

            # A new command can only operate on the caller's current
            # generation.  Rejected stale commands do not reserve their id.
            if generation != actor["generation"]:
                reject(409, "conflict")

            now = self.now()
            if operation == "move":
                self.move_player(actor, direction, now)
                produced_generation = actor["generation"]
            elif operation == "respawn":
                if actor["alive"]:
                    reject(409, "conflict")
                position = self.free_spawn(actor["room_id"])
                self._new_spawn(actor, now, position, actor["generation"] + 1)
                produced_generation = actor["generation"]
            else:
                reject(404, "not_found")

            # Store only after the operation has succeeded.  Full spawn areas,
            # live respawns and dead-player moves therefore do not reserve ids.
            self.commands[(actor["id"], generation, command_id)] = {
                "operation": operation,
                "direction": direction,
                "produced_generation": produced_generation,
            }
            return {"state": self.snapshot(actor, now)}
