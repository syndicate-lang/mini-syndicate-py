import asyncio
import secrets
import logging
import websockets
import re
from urllib.parse import urlparse, urlunparse

log = logging.getLogger(__name__)

import syndicate.mini.protocol as protocol
import syndicate.mini.url as url

from syndicate.mini.protocol import Capture, Discard, Observe
CAPTURE = Capture(Discard())

from preserves import *

def _encode(event):
    e = protocol.Encoder()
    e.append(event)
    return e.contents()

_instance_id = secrets.token_urlsafe(8)
_uuid_counter = 0

def uuid(prefix='__@syndicate'):
    global _uuid_counter
    c = _uuid_counter
    _uuid_counter = c + 1
    return prefix + '_' + _instance_id + '_' + str(c)

def _ignore(*args, **kwargs):
    pass

class Turn(object):
    def __init__(self, conn):
        self.conn = conn
        self.items = []

    def _ensure(self, what):
        if self.items is None:
            raise Exception('Attempt to %s a completed Turn' % (what,))

    def _extend(self, item):
        self._ensure('extend')
        self.items.append(item)

    def _reset(self):
        self._ensure('reset')
        self.items.clear()

    def _commit(self):
        self._ensure('commit')
        if self.items: self.conn._send(protocol.Turn(self.items))
        self.items = None

    def send(self, message):
        self._extend(protocol.Message(message))

    def merge_into(self, other):
        self._ensure('merge from')
        other._ensure('merge into')
        if self.items: other.items.extend(self.items)
        self.items.clear()

    def __enter__(self):
        return self

    def __exit__(self, t, v, tb):
        if t is None:
            self._commit()

def _fresh_id(assertion):
    return uuid('sub' if Observe.isClassOf(assertion) else 'pub')

class FacetSetupContext(object):
    def __init__(self, turn, facet):
        self.turn = turn
        self.facet = facet

    def __enter__(self):
        return self.facet

    def __exit__(self, t, v, tb):
        if t is None:
            self.facet.start(self.turn)
        else:
            self.facet.actor.kill(self.turn, (t, v, tb))

_next_actor_number = 0
def _next_actor_name():
    global _next_actor_number
    n = _next_actor_number
    _next_actor_number = n + 1
    return str(n)

class Actor(object):
    def __init__(self, conn, name=None):
        self.conn = conn
        self.name = name or _next_actor_name()
        self.children = set()
        self.alive = True
        self._log = None

    @property
    def log(self):
        if self._log is None:
            self._log = logging.getLogger('syndicate.mini.Actor.%s' % (self.name,))
        return self._log

    def react(self, turn):
        return FacetSetupContext(turn, Facet(self.conn, self, self))

    def _add_child(self, facet):
        if not self.alive:
            raise Exception('Cannot add facet because actor is termianted')
        self.children.add(facet)

    def guard(self, turn):
        return ActorGuard(turn, self)

    def is_inert(self):
        return len(self.children) == 0

    def _stop(self, turn, pending, is_abort):
        for child in list(self.children):
            child._stop(turn, pending, is_abort)
        self.children.clear()

    def stop(self, turn):
        self.alive = False
        pending = []
        self._stop(turn, pending, False)
        for t in pending: t(turn)

    def kill(self, turn, exc_info):
        log.error('%r%s died', self, repr(self.name) if self.name else '', exc_info=exc_info)
        for child in list(self.children):
            child._abort(turn)
        self.children.clear()

class ActorGuard(object):
    def __init__(self, turn, actor):
        self.turn = turn
        self.actor = actor

    def __enter__(self):
        pass

    def __exit__(self, t, v, tb):
        if t is not None:
            self.actor.kill(self.turn, (t, v, tb))
            return True ## suppress exception

class Facet(object):
    def __init__(self, conn, actor, parent):
        self.conn = conn
        self.actor = actor
        self.parent = parent
        if parent:
            parent._add_child(self)
        self.children = set()
        self.start_callbacks = []
        self.stop_callbacks = []
        self.endpoints = []
        self.state = 0

    @property
    def log(self):
        return self.actor.log

    def _ensure_state(self, wanted_state, message):
        if self.state != wanted_state:
            raise Exception(message)

    def _add_child(self, facet):
        self._ensure_state(1, 'Cannot add child facet in this state')
        self.children.add(facet)

    def react(self, turn):
        self._ensure_state(1, 'Cannot create subfacet in this state')
        return FacetSetupContext(turn, Facet(self.conn, self.actor, self))

    def add(self, *args, **kwargs):
        self._ensure_state(0, 'Cannot add endpoint to facet in this state')
        endpoint = Endpoint(self, *args, **kwargs)
        self.endpoints.append(endpoint)
        return endpoint

    def on_start(self, callback):
        self._ensure_state(0, 'Cannot add on_start callback to facet in this state')
        self.start_callbacks.append(callback)

    def on_stop(self, callback):
        self._ensure_state(0, 'Cannot add on_stop callback to facet in this state')
        self.stop_callbacks.append(callback)

    def start(self, turn):
        self._ensure_state(0, 'Cannot start facet in this state')
        self.state = 1
        for e in self.endpoints: e._start(turn)
        for t in self.start_callbacks: t(turn)
        self.start_callbacks.clear()

    def is_inert(self):
        return len(self.children) == 0 and len(self.endpoints) == 0

    def _stop(self, turn, pending, is_abort):
        if turn.conn is not self.conn:
            raise Exception('Attempted to stop facet from wrong connection')
        if self.state == 0 and not is_abort:
            raise Exception('Cannot stop facet before starting it')
        if self.state != 1: ## stopping is idempotent
            return
        self.state = 2

        if self.parent:
            self.parent.children.remove(self)

        for child in list(self.children):
            child._stop(turn, pending, is_abort)
        self.children.clear()

        if not is_abort:
            pending.extend(self.stop_callbacks)

        for endpoint in self.endpoints:
            endpoint.clear(turn)
        self.endpoints.clear()

        if not is_abort:
            if self.parent and self.parent.is_inert():
                self.parent._stop(turn, pending, is_abort)

    def stop(self, turn):
        pending = []
        self._stop(turn, pending, False)
        for t in pending: t(turn)

    def _abort(self, turn):
        self._stop(turn, None, True)

class Endpoint(object):
    def __init__(self, facet, assertion, on_add=None, on_del=None, on_msg=None):
        self.facet = facet
        self.assertion = assertion
        self.id = None
        self.on_add = on_add or _ignore
        self.on_del = on_del or _ignore
        self.on_msg = on_msg or _ignore
        self.cache = set()

    @property
    def log(self):
        return self.facet.log

    def _start(self, turn):
        self.set(turn, self.assertion)

    def set(self, turn, new_assertion, on_transition=None):
        if self.id is not None:
            turn.conn._unmap_endpoint(turn, self, on_end=on_transition)
            self.id = None
        self.assertion = new_assertion
        if self.assertion is not None:
            self.id = _fresh_id(self.assertion)
            turn.conn._map_endpoint(turn, self)

    def clear(self, turn, on_cleared=None):
        self.set(turn, None, on_transition=on_cleared)

    def _reset(self, turn):
        for captures in set(self.cache):
            self._del(turn, captures)

    def _add(self, turn, captures):
        if captures in self.cache:
            log.error('Server error: duplicate captures %r added for endpoint %r %r' % (
                captures,
                self.id,
                self.assertion))
        else:
            self.cache.add(captures)
            with self.facet.actor.guard(turn):
                self.on_add(turn, *captures)

    def _del(self, turn, captures):
        if captures in self.cache:
            self.cache.discard(captures)
            with self.facet.actor.guard(turn):
                self.on_del(turn, *captures)
        else:
            log.error('Server error: nonexistent captures %r removed from endpoint %r %r' % (
                captures,
                self.id,
                self.assertion))

    def _msg(self, turn, captures):
        with self.facet.actor.guard(turn):
            self.on_msg(turn, *captures)

class DummyEndpoint(object):
    def _add(self, turn, captures): pass
    def _del(self, turn, captures): pass
    def _msg(self, turn, captures): pass

_dummy_endpoint = DummyEndpoint()

class Connection(object):
    def __init__(self, scope):
        self.scope = scope
        self.endpoints = {}
        self.end_callbacks = {}
        self._is_connected = False

    def is_connected(self):
        return self._is_connected

    def _each_endpoint(self):
        return list(self.endpoints.values())

    def turn(self):
        return Turn(self)

    def actor(self, name=None):
        return Actor(self, name=name)

    def destroy(self):
        with self.turn() as t:
            for ep in self._each_endpoint():
                ep.clear(t)
            t._reset() ## don't actually Clear the endpoints, we are about to disconnect
        self._disconnect()

    def _unmap_endpoint(self, turn, ep, on_end=None):
        del self.endpoints[ep.id]
        if on_end:
            self.end_callbacks[ep.id] = on_end
        turn._extend(protocol.Clear(ep.id))

    def _on_end(self, turn, id):
        if id in self.end_callbacks:
            self.end_callbacks[id](turn)
            del self.end_callbacks[id]

    def _map_endpoint(self, turn, ep):
        self.endpoints[ep.id] = ep
        turn._extend(protocol.Assert(ep.id, ep.assertion))

    def _on_disconnected(self):
        self._is_connected = False
        with self.turn() as t:
            for ep in self._each_endpoint():
                ep._reset(t)
            t._reset() ## we have been disconnected, no point in keeping the actions
        self._disconnect()

    def _on_connected(self):
        self._send(protocol.Connect(self.scope))
        with self.turn() as t:
            for ep in self._each_endpoint():
                self._map_endpoint(t, ep)
        self._is_connected = True

    def _lookup(self, endpointId):
        return self.endpoints.get(endpointId, _dummy_endpoint)

    def _on_event(self, v):
        with self.turn() as t:
            self._handle_event(t, v)

    def _handle_event(self, turn, v):
        if protocol.Turn.isClassOf(v):
            for item in protocol.Turn._items(v):
                if   protocol.Add.isClassOf(item): self._lookup(item[0])._add(turn, item[1])
                elif protocol.Del.isClassOf(item): self._lookup(item[0])._del(turn, item[1])
                elif protocol.Msg.isClassOf(item): self._lookup(item[0])._msg(turn, item[1])
                elif protocol.End.isClassOf(item): self._on_end(turn, item[0])
                else: log.error('Unhandled server Turn item: %r' % (item,))
            return
        elif protocol.Err.isClassOf(v):
            self._on_error(v[0], v[1])
            return
        elif protocol.Ping.isClassOf(v):
            self._send_bytes(_encode(protocol.Pong()))
            return
        else:
            log.error('Unhandled server message: %r' % (v,))

    def _on_error(self, detail, context):
        log.error('%s: error from server: %r (context: %r)' % (
            self.__class__.__qualname__, detail, context))
        self._disconnect()

    def _send(self, m):
        return self._send_bytes(_encode(m))

    def _send_bytes(self, bs, commitNeeded = False):
        raise Exception('subclassresponsibility')

    def _disconnect(self):
        raise Exception('subclassresponsibility')

    async def reconnecting_main(self, loop, on_connected=None, on_disconnected=None):
        should_run = True
        while should_run:
            did_connect = await self.main(loop, on_connected=(on_connected or _default_on_connected))
            should_run = await (on_disconnected or _default_on_disconnected)(did_connect)

    @classmethod
    def from_url(cls, s):
        return url.connection_from_url(s)

async def _default_on_connected():
    log.info('Connected')

async def _default_on_disconnected(did_connect):
    if did_connect:
        # Reconnect immediately
        log.info('Disconnected')
    else:
        await asyncio.sleep(2)
    return True

class _StreamConnection(Connection, asyncio.Protocol):
    def __init__(self, scope):
        super().__init__(scope)
        self.decoder = None
        self.stop_signal = None
        self.transport = None

    def connection_lost(self, exc):
        self._on_disconnected()

    def connection_made(self, transport):
        self.transport = transport
        self._on_connected()

    def data_received(self, chunk):
        self.decoder.extend(chunk)
        while True:
            v = self.decoder.try_next()
            if v is None: break
            self._on_event(v)

    def _send_bytes(self, bs, commitNeeded = False):
        if self.transport:
            self.transport.write(bs)
            if commitNeeded:
                self.commitNeeded = True

    def _disconnect(self):
        if self.stop_signal:
            self.stop_signal.get_loop().call_soon_threadsafe(
                lambda: self.stop_signal.set_result(True))

    async def _create_connection(self, loop):
        raise Exception('subclassresponsibility')

    async def main(self, loop, on_connected=None):
        if self.transport is not None:
            raise Exception('Cannot run connection twice!')

        self.decoder = protocol.Decoder()
        self.stop_signal = loop.create_future()
        try:
            _transport, _protocol = await self._create_connection(loop)
        except OSError as e:
            log.error('%s: Could not connect to server: %s' % (self.__class__.__qualname__, e))
            return False

        try:
            if on_connected: await on_connected()
            await self.stop_signal
            return True
        finally:
            self.transport.close()
            self.transport = None
            self.stop_signal = None
            self.decoder = None

@url.schema('tcp')
class TcpConnection(_StreamConnection):
    def __init__(self, host, port, scope):
        super().__init__(scope)
        self.host = host
        self.port = port

    async def _create_connection(self, loop):
        return await loop.create_connection(lambda: self, self.host, self.port)

    @classmethod
    def default_port(cls):
        return 21369

    @classmethod
    def from_url(cls, s):
        u = urlparse(s)
        host, port = url._hostport(u.netloc, cls.default_port())
        if not host: return
        scope = u.fragment
        return cls(host, port, scope)

@url.schema('unix')
class UnixSocketConnection(_StreamConnection):
    def __init__(self, path, scope):
        super().__init__(scope)
        self.path = path

    async def _create_connection(self, loop):
        return await loop.create_unix_connection(lambda: self, self.path)

    @classmethod
    def from_url(cls, s):
        u = urlparse(s)
        return cls(u.path, u.fragment)

@url.schema('ws')
@url.schema('wss')
class WebsocketConnection(Connection):
    def __init__(self, url, scope):
        super().__init__(scope)
        self.url = url
        self.loop = None
        self.ws = None

    def _send_bytes(self, bs, commitNeeded = False):
        if self.loop:
            def _do_send():
                if self.ws:
                    self.loop.create_task(self.ws.send(bs))
            self.loop.call_soon_threadsafe(_do_send)
            if commitNeeded:
                self.commitNeeded = True

    def _disconnect(self):
        if self.loop:
            def _do_disconnect():
                if self.ws:
                    self.loop.create_task(self.ws.close())
            self.loop.call_soon_threadsafe(_do_disconnect)

    async def main(self, loop, on_connected=None):
        if self.ws is not None:
            raise Exception('Cannot run connection twice!')

        self.loop = loop

        try:
            async with websockets.connect(self.url) as ws:
                if on_connected: await on_connected()
                self.ws = ws
                self._on_connected()
                try:
                    while True:
                        chunk = await ws.recv()
                        self._on_event(protocol.Decoder(chunk).next())
                except websockets.exceptions.ConnectionClosed:
                    pass
        except OSError as e:
            log.error('%s: Could not connect to server: %s' % (self.__class__.__qualname__, e))
            return False
        finally:
            self._on_disconnected()

        if self.ws:
            await self.ws.close()
        self.loop = None
        self.ws = None
        return True

    @classmethod
    def from_url(cls, s):
        u = urlparse(s)
        return cls(urlunparse(u._replace(fragment='')), u.fragment)
