import sys
import asyncio
import random
import threading
import syndicate.mini.core as S

Present = S.Record.makeConstructor('Present', 'who')
Says = S.Record.makeConstructor('Says', 'who what')

if len(sys.argv) == 3:
    conn = S.TcpConnection(sys.argv[1], int(sys.argv[2]))
elif len(sys.argv) == 2:
    if sys.argv[1].startswith('ws:') or sys.argv[1].startswith('wss:'):
        conn = S.WebsocketConnection(sys.argv[1])
    else:
        conn = S.UnixSocketConnection(sys.argv[1])
elif len(sys.argv) == 1:
    conn = S.WebsocketConnection('ws://localhost:8000/broker')
else:
    sys.stderr.write(b'Usage: chat.py [ HOST PORT | WEBSOCKETURL ]\n')
    sys.exit(1)

## Courtesy of http://listofrandomnames.com/ :-)
names = ['Daria', 'Kendra', 'Danny', 'Rufus', 'Diana', 'Arnetta', 'Dominick', 'Melonie', 'Regan',
         'Glenda', 'Janet', 'Luci', 'Ronnie', 'Vita', 'Amie', 'Stefani', 'Catherine', 'Grady',
         'Terrance', 'Rey', 'Fay', 'Shantae', 'Carlota', 'Judi', 'Crissy', 'Tasha', 'Jordan',
         'Rolande', 'Buster', 'Diamond', 'Dallas', 'Lissa', 'Yang', 'Charlena', 'Brooke', 'Haydee',
         'Griselda', 'Kasie', 'Clara', 'Claudie', 'Darell', 'Emery', 'Barbera', 'Chong', 'Karin',
         'Veronica', 'Karly', 'Shaunda', 'Nigel', 'Cleo']

me = random.choice(names) + '_' + str(random.randint(10, 1000))

S.Endpoint(conn, Present(me))

S.Endpoint(conn, S.Observe(Present(S.CAPTURE)),
           on_add=lambda who: print(who, 'joined'),
           on_del=lambda who: print(who, 'left'))

S.Endpoint(conn, S.Observe(Says(S.CAPTURE, S.CAPTURE)),
           on_msg=lambda who, what: print(who, 'said', repr(what)))

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
        conn.send(Says(me, line.strip()))

loop = asyncio.get_event_loop()
loop.set_debug(True)
threading.Thread(target=accept_input, daemon=True).start()
loop.run_until_complete(reconnect(loop))
loop.stop()
loop.run_forever()
loop.close()
