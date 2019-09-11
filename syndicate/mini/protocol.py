import preserves
from preserves import Record

## Enrolment
Connect = Record.makeConstructor('Connect', 'scope')

## Bidirectional
Turn = Record.makeConstructor('Turn', 'items')

## Client -> Server
Assert = Record.makeConstructor('Assert', 'endpointName assertion')
Clear = Record.makeConstructor('Clear', 'endpointName')
Message = Record.makeConstructor('Message', 'body')

## Server -> Client
Add = Record.makeConstructor('Add', 'endpointName captures')
Del = Record.makeConstructor('Del', 'endpointName captures')
Msg = Record.makeConstructor('Msg', 'endpointName captures')
End = Record.makeConstructor('End', 'endpointName')
Err = Record.makeConstructor('Err', 'detail context')

## Bidirectional
Ping = Record.makeConstructor('Ping', '')
Pong = Record.makeConstructor('Pong', '')

## Standard Syndicate constructors
Observe = Record.makeConstructor('observe', 'specification')
Capture = Record.makeConstructor('capture', 'specification')
Discard = Record.makeConstructor('discard', '')

_decode_placeholders = {
    0: Discard.constructorInfo.key,
    1: Capture.constructorInfo.key,
    2: Observe.constructorInfo.key,
}

_encode_placeholders = dict(((v, k) for (k, v) in _decode_placeholders.items()))

class Decoder(preserves.Decoder):
    def __init__(self, *args, **kwargs):
        super(Decoder, self).__init__(*args, placeholders=_decode_placeholders, **kwargs)

class Encoder(preserves.Encoder):
    def __init__(self, *args, **kwargs):
        super(Encoder, self).__init__(*args, placeholders=_encode_placeholders, **kwargs)
