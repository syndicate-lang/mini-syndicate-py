import sys
import asyncio
import random
import threading
import syndicate.mini.core as S

Present = S.Record.makeConstructor('Present', 'who')
Says = S.Record.makeConstructor('Says', 'who what')

if len(sys.argv) == 1:
    conn_url = 'ws://localhost:8000/#chat'
elif len(sys.argv) == 2:
    conn_url = sys.argv[1]
else:
    sys.stderr.write(
        'Usage: chat.py [ tcp://HOST[:PORT]#SCOPE | ws://HOST[:PORT]#SCOPE | unix:PATH#SCOPE ]\n')
    sys.exit(1)
conn = S.Connection.from_url(conn_url)

_print = print
def print(*items):
    _print(*items)
    sys.stdout.flush()

## Courtesy of http://listofrandomnames.com/ :-)
names = ['Daria', 'Kendra', 'Danny', 'Rufus', 'Diana', 'Arnetta', 'Dominick', 'Melonie', 'Regan',
         'Glenda', 'Janet', 'Luci', 'Ronnie', 'Vita', 'Amie', 'Stefani', 'Catherine', 'Grady',
         'Terrance', 'Rey', 'Fay', 'Shantae', 'Carlota', 'Judi', 'Crissy', 'Tasha', 'Jordan',
         'Rolande', 'Buster', 'Diamond', 'Dallas', 'Lissa', 'Yang', 'Charlena', 'Brooke', 'Haydee',
         'Griselda', 'Kasie', 'Clara', 'Claudie', 'Darell', 'Emery', 'Barbera', 'Chong', 'Karin',
         'Veronica', 'Karly', 'Shaunda', 'Nigel', 'Cleo']

me = random.choice(names) + '_' + str(random.randint(10, 1000))

with conn.turn() as t:
    S.Endpoint(t, Present(me))
    S.Endpoint(t, S.Observe(Present(S.CAPTURE)),
               on_add=lambda t, who: print(who, 'joined'),
               on_del=lambda t, who: print(who, 'left'))
    S.Endpoint(t, S.Observe(Says(S.CAPTURE, S.CAPTURE)),
               on_msg=lambda t, who, what: print(who, 'said', repr(what)))

async def on_connected():
    print('-'*50, 'Connected')
async def on_disconnected(did_connect):
    if did_connect:
        print('-'*50, 'Disconnected')
    else:
        await asyncio.sleep(2)
    return bool(conn)

def accept_input():
    global conn
    while True:
        line = sys.stdin.readline()
        if not line:
            conn.destroy()
            conn = None
            break
        with conn.turn() as t:
            t.send(Says(me, line.strip()))

loop = asyncio.get_event_loop()
loop.set_debug(True)
threading.Thread(target=accept_input, daemon=True).start()
loop.run_until_complete(conn.reconnecting_main(loop, on_connected, on_disconnected))
loop.stop()
loop.run_forever()
loop.close()
