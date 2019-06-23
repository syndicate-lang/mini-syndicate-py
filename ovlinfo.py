import sys
import asyncio
import random
import threading
import syndicate.mini.core as S

OverlayLink = S.Record.makeConstructor('OverlayLink', 'downNode upNode')

conn = S.Connection.from_url(sys.argv[1])

uplinks = {}
def add_uplink(turn, src, tgt):
    uplinks[src] = tgt
    summarise_uplinks()
def del_uplink(turn, src, tgt):
    del uplinks[src]
    summarise_uplinks()
def summarise_uplinks():
    print(repr(uplinks))

with conn.turn() as t:
    S.Endpoint(t, S.Observe(OverlayLink(S.CAPTURE, S.CAPTURE)),
               on_add=add_uplink,
               on_del=del_uplink)

async def reconnect(loop):
    while conn:
        did_connect = await conn.main(loop, on_connected=lambda: print('-'*50, 'Connected'))
        if did_connect:
            print('-'*50, 'Disconnected')
        else:
            await asyncio.sleep(2)

loop = asyncio.get_event_loop()
loop.set_debug(True)
loop.run_until_complete(reconnect(loop))
loop.stop()
loop.run_forever()
loop.close()
