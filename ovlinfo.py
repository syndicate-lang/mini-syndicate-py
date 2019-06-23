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
    with conn.actor().react(t) as facet:
        facet.add(S.Observe(OverlayLink(S.CAPTURE, S.CAPTURE)),
                  on_add=add_uplink,
                  on_del=del_uplink)

loop = asyncio.get_event_loop()
loop.set_debug(True)
loop.run_until_complete(conn.reconnecting_main(loop))
loop.stop()
loop.run_forever()
loop.close()
