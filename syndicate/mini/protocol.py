import preserves
from preserves import Record, Symbol

## Client -> Broker
Assert = Record.makeConstructor('Assert', 'endpointName assertion')
Clear = Record.makeConstructor('Clear', 'endpointName')
Message = Record.makeConstructor('Message', 'body')

## Broker -> Client
Add = Record.makeConstructor('Add', 'endpointName captures')
Del = Record.makeConstructor('Del', 'endpointName captures')
Msg = Record.makeConstructor('Msg', 'endpointName captures')

## Bidirectional
Ping = Record.makeConstructor('Ping', '')
Pong = Record.makeConstructor('Pong', '')

## Standard Syndicate constructors
Observe = Record.makeConstructor('observe', 'specification')
Capture = Record.makeConstructor('capture', 'specification')
Discard = Record.makeConstructor('discard', '')

class Decoder(preserves.Decoder):
    def __init__(self, *args, **kwargs):
        super(Decoder, self).__init__(*args, **kwargs)
        _init_shortforms(self)

class Encoder(preserves.Encoder):
    def __init__(self, *args, **kwargs):
        super(Encoder, self).__init__(*args, **kwargs)
        _init_shortforms(self)

def _init_shortforms(c):
    c.set_shortform(0, Discard.constructorInfo.key)
    c.set_shortform(1, Capture.constructorInfo.key)
    c.set_shortform(2, Observe.constructorInfo.key)
