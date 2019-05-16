import asyncio
import secrets
import logging
import websockets

log = logging.getLogger(__name__)

import syndicate.mini.protocol as protocol

from syndicate.mini.protocol import Capture, Discard, Observe
CAPTURE = Capture(Discard())

from preserves import *

_instance_id = secrets.token_urlsafe(8)
_uuid_counter = 0

def uuid(prefix='__@syndicate'):
    global _uuid_counter
    c = _uuid_counter
    _uuid_counter = c + 1
    return prefix + '_' + _instance_id + '_' + str(c)

def _ignore(*args, **kwargs):
    pass

class Endpoint(object):
    def __init__(self, conn, assertion, id=None, on_add=None, on_del=None, on_msg=None):
        self.conn = conn
        self.assertion = assertion
        self.id = id or uuid('sub' if Observe.isClassOf(assertion) else 'pub')
        self.on_add = on_add or _ignore
        self.on_del = on_del or _ignore
        self.on_msg = on_msg or _ignore
        self.cache = set()
        self.conn._update_endpoint(self)

    def set(self, new_assertion):
        self.assertion = new_assertion
        if self.conn:
            self.conn._update_endpoint(self)

    def send(self, message):
        '''Shortcut to Connection.send.'''
        if self.conn:
            self.conn.send(message)

    def destroy(self):
        if self.conn:
            self.conn._clear_endpoint(self)
            self.conn = None

    def _reset(self):
        for captures in set(self.cache):
            self._del(captures)

    def _add(self, captures):
        if captures in self.cache:
            log.error('Server error: duplicate captures %r added for endpoint %r %r' % (
                captures,
                self.id,
                self.assertion))
        else:
            self.cache.add(captures)
            self.on_add(*captures)

    def _del(self, captures):
        if captures in self.cache:
            self.cache.discard(captures)
            self.on_del(*captures)
        else:
            log.error('Server error: nonexistent captures %r removed from endpoint %r %r' % (
                captures,
                self.id,
                self.assertion))

    def _msg(self, captures):
        self.on_msg(*captures)

class DummyEndpoint(object):
    def _add(self, captures): pass
    def _del(self, captures): pass
    def _msg(self, captures): pass

_dummy_endpoint = DummyEndpoint()

class Connection(object):
    def __init__(self, scope):
        self.endpoints = {}
        self.scope = scope

    def _each_endpoint(self):
        return list(self.endpoints.values())

    def destroy(self):
        for ep in self._each_endpoint():
            ep.destroy()
        self._disconnect()

    def _encode(self, event):
        e = protocol.Encoder()
        e.append(event)
        return e.contents()

    def _update_endpoint(self, ep):
        self.endpoints[ep.id] = ep
        self._send(self._encode(protocol.Assert(ep.id, ep.assertion)))

    def _clear_endpoint(self, ep):
        if ep.id in self.endpoints:
            del self.endpoints[ep.id]
            self._send(self._encode(protocol.Clear(ep.id)))

    def send(self, message):
        self._send(self._encode(protocol.Message(message)))

    def _on_disconnected(self):
        for ep in self._each_endpoint():
            ep._reset()
        self._disconnect()

    def _on_connected(self):
        self._send(self._encode(protocol.Connect(self.scope)))
        for ep in self._each_endpoint():
            self._update_endpoint(ep)

    def _lookup(self, endpointId):
        return self.endpoints.get(endpointId, _dummy_endpoint)

    def _on_event(self, v):
        if protocol.Add.isClassOf(v): return self._lookup(v[0])._add(v[1])
        if protocol.Del.isClassOf(v): return self._lookup(v[0])._del(v[1])
        if protocol.Msg.isClassOf(v): return self._lookup(v[0])._msg(v[1])
        if protocol.Err.isClassOf(v): return self._on_error(v[0])
        if protocol.Ping.isClassOf(v): self._send(self._encode(protocol.Pong()))

    def _on_error(self, detail):
        log.error('%s: error from server: %r' % (self.__class__.__qualname__, detail))
        self._disconnect()

    def _send(self, bs):
        raise Exception('subclassresponsibility')

    def _disconnect(self):
        raise Exception('subclassresponsibility')

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

    def _send(self, bs):
        if self.transport:
            self.transport.write(bs)

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

class TcpConnection(_StreamConnection):
    def __init__(self, host, port, scope):
        super().__init__(scope)
        self.host = host
        self.port = port

    async def _create_connection(self, loop):
        return await loop.create_connection(lambda: self, self.host, self.port)

class UnixSocketConnection(_StreamConnection):
    def __init__(self, path, scope):
        super().__init__(scope)
        self.path = path

    async def _create_connection(self, loop):
        return await loop.create_unix_connection(lambda: self, self.path)

class WebsocketConnection(Connection):
    def __init__(self, url, scope):
        super().__init__(scope)
        self.url = url
        self.loop = None
        self.ws = None

    def _send(self, bs):
        if self.loop:
            def _do_send():
                if self.ws:
                    self.loop.create_task(self.ws.send(bs))
            self.loop.call_soon_threadsafe(_do_send)

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
