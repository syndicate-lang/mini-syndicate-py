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

    def _extend(self, item):
        self.items.append(item)

    def _reset(self):
        self.items.clear()

    def _commit(self):
        if self.items:
            self.conn._send(protocol.Turn(self.items))
            self._reset()

    def send(self, message):
        self._extend(protocol.Message(message))

    def __enter__(self):
        if self.items:
            raise Exception('Cannot reenter with statement for Turn')
        return self

    def __exit__(self, t, v, tb):
        if t is None:
            self._commit()

def _fresh_id(assertion):
    return uuid('sub' if Observe.isClassOf(assertion) else 'pub')

class Endpoint(object):
    def __init__(self, turn, assertion,
                 on_add=None, on_del=None, on_msg=None):
        self.assertion = None
        self.id = None
        self.on_add = on_add or _ignore
        self.on_del = on_del or _ignore
        self.on_msg = on_msg or _ignore
        self.cache = set()
        self.set(turn, assertion)

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
            self.on_add(turn, *captures)

    def _del(self, turn, captures):
        if captures in self.cache:
            self.cache.discard(captures)
            self.on_del(turn, *captures)
        else:
            log.error('Server error: nonexistent captures %r removed from endpoint %r %r' % (
                captures,
                self.id,
                self.assertion))

    def _msg(self, turn, captures):
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

    def _each_endpoint(self):
        return list(self.endpoints.values())

    def turn(self):
        return Turn(self)

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

    @classmethod
    def from_url(cls, s):
        return url.connection_from_url(s)

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
            if on_connected: on_connected()
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
                if on_connected: on_connected()
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
