import sys
import asyncio
import random
import threading
import syndicate.mini.core as S

Present = S.Record.makeConstructor('Present', 'who')
Says = S.Record.makeConstructor('Says', 'who what')

if len(sys.argv) == 4:
    conn = S.TcpConnection(sys.argv[1], int(sys.argv[2]), sys.argv[3])
elif len(sys.argv) == 3:
    if sys.argv[1].startswith('ws:') or sys.argv[1].startswith('wss:'):
        conn = S.WebsocketConnection(sys.argv[1], sys.argv[2])
    else:
        conn = S.UnixSocketConnection(sys.argv[1], sys.argv[2])
elif len(sys.argv) == 1:
    conn = S.WebsocketConnection('ws://localhost:8000/', 'chat')
else:
    sys.stderr.write(
        'Usage: chat.py [ HOST PORT SCOPE | WEBSOCKETURL SCOPE | UNIXSOCKETPATH SCOPE ]\n')
    sys.exit(1)

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

async def reconnect(loop):
    while conn:
        did_connect = await conn.main(loop, on_connected=lambda: print('-'*50, 'Connected'))
        if did_connect:
            print('-'*50, 'Disconnected')
        else:
            await asyncio.sleep(2)

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
loop.run_until_complete(reconnect(loop))
loop.stop()
loop.run_forever()
loop.close()
